"""Always-on, privacy-preserving learning from the user's typing.

Klyrshift can adapt to the person using it: it remembers which corrections were
rejected (``Ctrl+Z``, or the undo hotkey) and stops repeating them, and it picks
up the words a user types often enough that they should stop being "corrected".

The one hard rule of this project is that the typed characters never reach the
disk (see ``tests/test_privacy_audit.py``). Learning therefore keeps the words in
memory only, for the lifetime of the daemon, and persists *counters alone* to
``state_dir()/learning.json``. A profile that stored the learned words would be a
plaintext record of everything the user types; a salted hash of them would still
be a dictionary-attackable vocabulary record. Neither is written, so a profile
file can never be read back as the user's typing.

The consequence is deliberate: the vocabulary that changes behaviour lasts one
session, while the durable part is metadata (how many words were observed, kept,
corrected, rejected and promoted). See ``AGENTS.md`` for the trade-off.
"""

from __future__ import annotations

import json
import logging
import os
import threading
import time
from dataclasses import dataclass
from pathlib import Path
from typing import Final

from .config import state_dir

logger = logging.getLogger(__name__)

PROFILE_FILE_NAME: Final[str] = "learning.json"
# A word must be kept this many times before it joins the detector's vocabulary
# for the rest of the session. Below it a single deliberate mistype (or a name
# typed once) would silently become "correct" and never be fixed again.
DEFAULT_PROMOTE_THRESHOLD: Final[int] = 3
# Upper bound on the in-memory learned vocabulary, so a session that types a huge
# corpus cannot grow the set without bound.
DEFAULT_MAX_LEARNED_WORDS: Final[int] = 2000
# A word the user rejected stays suppressed for the whole session; the map is
# capped so a pathological session cannot grow it without bound.
_MAX_SUPPRESSED_WORDS: Final[int] = 1000
# Words longer than the user-dictionary cap are not learned (they are almost
# certainly a pasted token, not a word the user types).
_MAX_WORD_LENGTH: Final[int] = 64


def profile_path() -> Path:
    """Return the path of the metadata-only learning profile."""
    return state_dir() / PROFILE_FILE_NAME


@dataclass
class LearningStats:
    """Aggregate counters for the learning feature (never a typed word)."""

    observed: int = 0
    kept: int = 0
    corrected: int = 0
    rejected: int = 0
    promoted: int = 0

    def to_dict(self) -> dict[str, int]:
        """Return a plain mapping suitable for JSON."""
        return {
            "observed": self.observed,
            "kept": self.kept,
            "corrected": self.corrected,
            "rejected": self.rejected,
            "promoted": self.promoted,
        }

    @classmethod
    def from_dict(cls, data: object) -> LearningStats:
        """Build stats from an untrusted mapping, ignoring bad values."""
        if not isinstance(data, dict):
            return cls()
        fields = ("observed", "kept", "corrected", "rejected", "promoted")
        values: dict[str, int] = {}
        for name in fields:
            raw = data.get(name)
            if isinstance(raw, bool) or not isinstance(raw, int) or raw < 0:
                continue
            values[name] = raw
        return cls(**values)


class LearningStore:
    """Persist the aggregate learning counters (never a word).

    The file is written atomically and a corrupt or unreadable one is ignored, so
    a bad profile can never stop the daemon from starting.
    """

    def __init__(self, path: Path | None = None) -> None:
        self.path = path or profile_path()

    def load(self) -> LearningStats:
        """Return the stored stats, or empty stats when the file is absent."""
        try:
            raw = self.path.read_text(encoding="utf-8")
        except FileNotFoundError:
            return LearningStats()
        except OSError:
            logger.debug("Could not read the learning profile", exc_info=True)
            return LearningStats()
        try:
            data: object = json.loads(raw)
        except json.JSONDecodeError:
            logger.warning("Learning profile %s is corrupt; ignoring it", self.path)
            return LearningStats()
        return LearningStats.from_dict(data)

    def save(self, stats: LearningStats) -> None:
        """Write ``stats`` atomically, best-effort."""
        try:
            self.path.parent.mkdir(parents=True, exist_ok=True)
            payload = json.dumps(stats.to_dict(), sort_keys=True)
            tmp = self.path.with_suffix(f".tmp-{os.getpid()}")
            tmp.write_text(payload, encoding="utf-8")
            os.replace(tmp, self.path)
        except OSError:
            logger.debug("Could not write the learning profile", exc_info=True)

    def reset(self) -> None:
        """Delete the profile, returning the counters to zero."""
        try:
            self.path.unlink()
        except FileNotFoundError:
            return
        except OSError:
            logger.debug("Could not remove the learning profile", exc_info=True)


class LearningEngine:
    """Observe flushed words and adapt to what the user actually keeps.

    The engine holds the learned vocabulary and the set of rejected words in
    memory; it never writes a word anywhere. All state is guarded by a lock
    because the daemon's event loop and the tray/GUI threads may both touch it.

    Args:
        enabled: When ``False`` every ``observe_*`` call is a no-op and nothing
            is ever suppressed or learned.
        promote_threshold: Times a word must be kept before it is promoted.
        max_words: Cap on the in-memory learned vocabulary.
        store: Optional persistent counter store (mainly for tests).
    """

    def __init__(
        self,
        *,
        enabled: bool = True,
        promote_threshold: int = DEFAULT_PROMOTE_THRESHOLD,
        max_words: int = DEFAULT_MAX_LEARNED_WORDS,
        store: LearningStore | None = None,
    ) -> None:
        self.enabled = enabled
        self.promote_threshold = max(1, promote_threshold)
        self.max_words = max(1, max_words)
        self._store = store if store is not None else LearningStore()
        self._counts: dict[str, int] = {}
        self._promoted: list[str] = []
        self._suppressed: dict[str, float] = {}
        self._stats = self._store.load()
        self._lock = threading.Lock()
        # A background write is skipped while one is already pending; the daemon
        # flushes on its own cadence (see ``persist``).
        self._dirty = False

    # --- observation ------------------------------------------------------
    def observe_kept(self, word: str) -> bool:
        """Record that the user kept ``word`` unchanged.

        Returns:
            ``True`` when the word crossed the promotion threshold on this call
            (so the caller can refresh the detector's vocabulary).
        """
        if not self.enabled:
            return False
        normalised = self._normalise(word)
        if normalised is None:
            return False
        with self._lock:
            self._stats.observed += 1
            self._stats.kept += 1
            self._dirty = True
            count = self._counts.get(normalised, 0) + 1
            self._counts[normalised] = count
            if count < self.promote_threshold or normalised in self._promoted:
                return False
            if len(self._promoted) >= self.max_words:
                # The vocabulary is full: evict the least-typed word so a heavy
                # session keeps adapting instead of freezing its first N words.
                oldest = min(self._promoted, key=lambda w: self._counts.get(w, 0))
                self._promoted.remove(oldest)
            self._promoted.append(normalised)
            self._stats.promoted += 1
        return True

    def observe_corrected(self, word: str) -> None:
        """Record that a correction was applied to ``word``."""
        if not self.enabled:
            return
        if self._normalise(word) is None:
            return
        with self._lock:
            self._stats.observed += 1
            self._stats.corrected += 1
            self._dirty = True

    def observe_rejected(self, word: str) -> None:
        """Record that the user rejected a correction for ``word``.

        The word is suppressed for the rest of the session, so the daemon stops
        offering the correction the user just undid.
        """
        if not self.enabled:
            return
        normalised = self._normalise(word)
        if normalised is None:
            return
        with self._lock:
            self._stats.rejected += 1
            self._dirty = True
            # A rejected word is never "learned as correct" either: the user is
            # saying they want their own text, not the daemon's guess.
            self._counts.pop(normalised, None)
            if normalised in self._promoted:
                self._promoted.remove(normalised)
            self._suppressed[normalised] = time.monotonic()
            if len(self._suppressed) > _MAX_SUPPRESSED_WORDS:
                oldest = min(self._suppressed, key=lambda w: self._suppressed[w])
                self._suppressed.pop(oldest, None)

    # --- queries ----------------------------------------------------------
    def is_suppressed(self, word: str) -> bool:
        """Return ``True`` when the user rejected a fix for ``word``."""
        if not self.enabled:
            return False
        normalised = self._normalise(word)
        if normalised is None:
            return False
        with self._lock:
            return normalised in self._suppressed

    def suppressed_count(self) -> int:
        """Return how many words the user rejected this session."""
        with self._lock:
            return len(self._suppressed)

    def learned_words(self) -> list[str]:
        """Return the promoted words (in promotion order)."""
        with self._lock:
            return list(self._promoted)

    def is_promoted(self, word: str) -> bool:
        """Return ``True`` when ``word`` is in the session vocabulary."""
        normalised = self._normalise(word)
        if normalised is None:
            return False
        with self._lock:
            return normalised in self._promoted

    def promote(self, word: str) -> bool:
        """Force ``word`` into the session vocabulary now.

        This is the manual counterpart of the automatic promotion: the user
        tells Klyrshift "leave this word alone" without waiting for it to be
        kept ``promote_threshold`` times. The word still lives in memory only.

        Returns:
            ``True`` when the word was added (``False`` when it was already
            promoted, empty, or not a plain word).
        """
        normalised = self._normalise(word)
        if normalised is None:
            return False
        with self._lock:
            if normalised in self._promoted:
                return False
            if len(self._promoted) >= self.max_words:
                oldest = min(self._promoted, key=lambda w: self._counts.get(w, 0))
                self._promoted.remove(oldest)
            self._promoted.append(normalised)
            # A word the user explicitly promotes is no longer "rejected".
            self._suppressed.pop(normalised, None)
            self._stats.promoted += 1
            self._dirty = True
        return True

    def forget(self, word: str) -> bool:
        """Drop ``word`` from the session vocabulary and the suppressed set.

        The manual counterpart of a reset, per word: the user removes a word
        they promoted (or a word that was suppressed) without clearing the whole
        session. Nothing is written anywhere, because the word was never on disk.

        Returns:
            ``True`` when the word was present and has been removed.
        """
        normalised = self._normalise(word)
        if normalised is None:
            return False
        with self._lock:
            present = normalised in self._promoted or normalised in self._suppressed
            if normalised in self._promoted:
                self._promoted.remove(normalised)
            self._suppressed.pop(normalised, None)
            self._counts.pop(normalised, None)
            if present:
                self._dirty = True
        return present

    @property
    def stats(self) -> LearningStats:
        """Return a copy of the aggregate counters."""
        with self._lock:
            return LearningStats(**self._stats.to_dict())

    # --- persistence ------------------------------------------------------
    def persist(self, *, force: bool = False) -> None:
        """Write the counters when they changed (best-effort)."""
        with self._lock:
            if not self._dirty and not force:
                return
            self._dirty = False
            snapshot = LearningStats(**self._stats.to_dict())
        self._store.save(snapshot)

    def reset(self) -> None:
        """Forget everything learned and clear the stored counters."""
        with self._lock:
            self._counts.clear()
            self._promoted.clear()
            self._suppressed.clear()
            self._stats = LearningStats()
            self._dirty = False
        self._store.reset()

    # --- helpers ----------------------------------------------------------
    @staticmethod
    def _normalise(word: str) -> str | None:
        """Return the lower-cased word to learn, or ``None`` when it is not one.

        Only a plain letter word is eligible: a token with a digit, a separator
        or a mixed script is not something the user "keeps as a word", and
        learning it would pollute the vocabulary.
        """
        stripped = word.strip()
        if not stripped or len(stripped) > _MAX_WORD_LENGTH or not stripped.isalpha():
            return None
        return stripped.lower()
