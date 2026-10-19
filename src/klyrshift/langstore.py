"""Install and remove language dictionaries, for the GUI.

The CLI already downloads an extended dictionary for a language
(``klyrshift dict download ru``) and a thematic category
(``klyrshift dict install <slug>``). The GUI had only the enable/disable switch:
turning a language on made the daemon *use* it, but nothing put the word list on
disk. This module is the missing piece — a small, testable layer the GUI calls,
so the download/remove logic is not duplicated inside a GTK callback.

Everything here is a thin, explicit wrapper over the modules that already own
the formats: :mod:`klyrshift.dictionary` for the extended (frequency) list and
:mod:`klyrshift.thematic` for the thematic categories. No network call happens
at import time; the caller decides when to install, and the GUI runs the call on
a worker thread.
"""

from __future__ import annotations

import logging
from dataclasses import dataclass
from pathlib import Path
from typing import Final

from .config import SUPPORTED_LANGUAGES, Config, save_config
from .dictionary import (
    BUNDLED_DICTIONARY_LANGUAGES,
    default_extended_dictionary_dir,
    download_extended_dictionary,
    extended_dictionary_path,
)
from .i18n import _
from .thematic import (
    CATEGORIES,
    disable_category,
    download_category,
    enable_category,
    thematic_path,
)

logger = logging.getLogger(__name__)

# Human names for the supported languages, shared with the GUI.
LANGUAGE_LABELS: Final[dict[str, str]] = {
    "en": "English",
    "ru": "Русский",
    "uk": "Українська",
    "de": "Deutsch",
    "fr": "Français",
}


@dataclass(frozen=True)
class LanguageStatus:
    """What is on disk for one language, and whether the daemon uses it."""

    language: str
    label: str
    enabled: bool
    installed: bool
    word_count: int

    @property
    def can_install(self) -> bool:
        """Whether a dictionary for this language can be downloaded."""
        return self.language in BUNDLED_DICTIONARY_LANGUAGES

    @property
    def state_text(self) -> str:
        """A short status for a GTK row subtitle, translated for the locale."""
        base = (
            _("Установлен · слов: {0}").format(self.word_count)
            if self.installed
            else _("Не установлен")
        )
        return _("Включён · {0}").format(base) if self.enabled else _("Выключен · {0}").format(base)


@dataclass(frozen=True)
class CategoryStatus:
    """What is on disk for one thematic category, and whether it is enabled."""

    slug: str
    title: str
    enabled: bool
    installed: bool
    word_count: int

    @property
    def state_text(self) -> str:
        """A short status for a GTK row subtitle, translated for the locale."""
        base = (
            _("Установлена · слов: {0}").format(self.word_count)
            if self.installed
            else _("Не установлена")
        )
        return (
            _("Включена · {0}").format(base) if self.enabled else _("Выключена · {0}").format(base)
        )


def extended_dir(config: Config) -> Path:
    """Return the directory that holds the extended language dictionaries."""
    if config.extended_dictionary_dir.strip():
        return Path(config.extended_dictionary_dir).expanduser()
    return default_extended_dictionary_dir()


def _count_words(path: Path) -> int:
    """Count usable word lines in ``path`` (0 when the file is absent)."""
    try:
        text = path.read_text(encoding="utf-8")
    except (FileNotFoundError, OSError):
        return 0
    return sum(
        1 for raw in text.splitlines() if raw.strip() and not raw.lstrip().startswith(("#", "//"))
    )


def language_status(config: Config, language: str) -> LanguageStatus:
    """Return the install/enable state of one language."""
    lang = language.strip().lower()
    path = extended_dictionary_path(lang, str(extended_dir(config)))
    count = _count_words(path)
    return LanguageStatus(
        language=lang,
        label=LANGUAGE_LABELS.get(lang, lang),
        enabled=lang in config.languages,
        installed=count > 0,
        word_count=count,
    )


def all_language_status(config: Config) -> list[LanguageStatus]:
    """Return the status of every language Klyrshift ships dictionaries for."""
    return [language_status(config, lang) for lang in SUPPORTED_LANGUAGES]


def install_language(config: Config, language: str) -> LanguageStatus:
    """Download the extended dictionary for ``language`` and enable it.

    On success the language joins ``config.languages`` and the extended
    directory is remembered, so the daemon loads the new list on its next
    reload. The network call is the caller's to schedule off the GTK thread.

    Raises:
        ValueError: The language has no downloadable dictionary.
        OSError: Every source failed and no local copy exists.
    """
    lang = language.strip().lower()
    directory = extended_dir(config)
    download_extended_dictionary(lang, str(directory))
    config.extended_dictionary_dir = str(directory)
    if lang not in config.languages:
        config.languages = [*config.languages, lang]
    config.validate()
    save_config(config)
    logger.info("Installed the %s dictionary into %s", lang, directory)
    return language_status(config, lang)


def remove_language(config: Config, language: str) -> LanguageStatus:
    """Delete the downloaded dictionary for ``language`` and disable it.

    The last enabled language is never removed: the daemon must keep at least
    one layout, so removing it would only produce a config that fails
    validation. Removing a language that is not enabled is fine — its file
    still goes.

    Raises:
        ValueError: This is the only enabled language.
        OSError: The file exists but could not be deleted.
    """
    lang = language.strip().lower()
    if lang in config.languages and len(config.languages) == 1:
        raise ValueError("cannot remove the only enabled language")
    path = extended_dictionary_path(lang, str(extended_dir(config)))
    try:
        path.unlink()
    except FileNotFoundError:
        pass
    except OSError:
        logger.warning("Could not delete %s", path, exc_info=True)
        raise
    config.languages = [lang_ for lang_ in config.languages if lang_ != lang]
    save_config(config)
    logger.info("Removed the %s dictionary (%s)", lang, path)
    return language_status(config, lang)


def category_status(config: Config, slug: str, language: str = "ru") -> CategoryStatus:
    """Return the install/enable state of one thematic category."""
    cat = next((c for c in CATEGORIES if c.slug == slug), None)
    title = cat.title() if cat is not None else slug
    count = _count_words(thematic_path(slug, language, str(extended_dir(config))))
    return CategoryStatus(
        slug=slug,
        title=title,
        enabled=slug in config.installed_dict_categories,
        installed=count > 0,
        word_count=count,
    )


def all_category_status(config: Config, language: str = "ru") -> list[CategoryStatus]:
    """Return the status of every thematic category."""
    return [category_status(config, cat.slug, language) for cat in CATEGORIES]


def install_category(config: Config, slug: str, language: str = "ru") -> CategoryStatus:
    """Download a thematic category and enable it."""
    directory = extended_dir(config)
    download_category(slug, language, str(directory))
    config.extended_dictionary_dir = str(directory)
    config.installed_dict_categories = enable_category(config.installed_dict_categories, slug)
    save_config(config)
    logger.info("Installed the %s/%s category into %s", slug, language, directory)
    return category_status(config, slug, language)


def remove_category(config: Config, slug: str, language: str = "ru") -> CategoryStatus:
    """Disable a thematic category and delete its downloaded file.

    ``base`` is never removed: :func:`~klyrshift.thematic.disable_category` keeps
    it, and its file is not touched here.
    """
    if slug == "base":
        raise ValueError("the base category cannot be removed")
    path = thematic_path(slug, language, str(extended_dir(config)))
    try:
        path.unlink()
    except FileNotFoundError:
        pass
    except OSError:
        logger.warning("Could not delete %s", path, exc_info=True)
        raise
    config.installed_dict_categories = disable_category(config.installed_dict_categories, slug)
    save_config(config)
    logger.info("Removed the %s/%s category (%s)", slug, language, path)
    return category_status(config, slug, language)
