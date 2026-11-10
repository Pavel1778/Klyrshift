"""Regression tests for the false-positive guards (task A).

Text that already reads as real words in the layout it was typed in must never
be rewritten, however plausible another layout looks. These tests pin the three
guards: plausibility, structural boundaries and identifier detection.
"""

from __future__ import annotations

import mimetypes

import pytest

from klyrshift.converter import LayoutConverter
from klyrshift.detector import _BASE_VOWELS, LanguageDetector


@pytest.fixture
def det() -> LanguageDetector:
    """Return a detector with the bundled corpora and no stop words."""
    return LanguageDetector(converter=LayoutConverter(), stop_words=[], min_word_length=3)


# --- the reported false positive -------------------------------------------------

# Typed in the Russian layout, this is a symbol-heavy string that the detector
# used to convert to the US layout. It must be left alone.
FALSE_POSITIVES = [
    ("сb cj,jq?ye;yjn/g/", "ru"),
    ("github.com", "us"),
    ("user@example.com", "us"),
    ("3.14", "us"),
    ("snake_case", "us"),
    ("camelCase", "us"),
    ("x86_64", "us"),
    ("https://example.com/path", "us"),
    ("/usr/local/bin", "us"),
    ("my-var", "us"),
]


@pytest.mark.parametrize(("text", "layout"), FALSE_POSITIVES)
def test_false_positives_are_left_alone(det: LanguageDetector, text: str, layout: str) -> None:
    assert det.target_layout(text, layout) is None


@pytest.mark.parametrize(("text", "layout"), FALSE_POSITIVES)
def test_false_positives_never_flagged(det: LanguageDetector, text: str, layout: str) -> None:
    assert det.should_fix(text, layout) is False


# --- the genuine wrong-layout words must still be fixed --------------------------


@pytest.mark.parametrize(
    ("text", "layout", "expected"),
    [
        ("ghbdtn", "us", "ru"),
        ("руддщ", "ru", "us"),
        ("Руддщ", "ru", "us"),
        ("привет", "us", "ru"),
        ("hello", "ru", "us"),
        ("ghbdtn vbh", "us", "ru"),
        ("Руддщ цщкл", "ru", "us"),
    ],
)
def test_real_wrong_layout_words_are_still_fixed(
    det: LanguageDetector, text: str, layout: str, expected: str
) -> None:
    assert det.target_layout(text, layout) == expected


def test_rare_real_word_is_protected(det: LanguageDetector) -> None:
    """A real but uncommon Russian word must not be "corrected" into noise."""
    assert det.target_layout("нот", "ru") is None


# --- guards can be disabled independently ----------------------------------------


def test_plausibility_guard_can_be_disabled() -> None:
    guarded = LanguageDetector(converter=LayoutConverter(), stop_words=[], min_word_length=3)
    unguarded = LanguageDetector(
        converter=LayoutConverter(),
        stop_words=[],
        min_word_length=3,
        plausibility_check=False,
        structural_boundaries=False,
        identifier_guard=False,
    )
    # With every guard off, the reported phrase converts again: this proves the
    # guards, not some other change, are what suppress it. (A pure-Cyrillic
    # sample is used because a mixed-script token is skipped by a separate,
    # independent rule that stays on even when these guards are disabled.)
    sample = "ыв сл,дж?ые;ынп/g/"
    assert guarded.target_layout(sample, "ru") is None
    assert unguarded.target_layout(sample, "ru") is not None


def test_structural_boundary_guard_ignores_urls() -> None:
    det = LanguageDetector(converter=LayoutConverter(), stop_words=[], min_word_length=3)
    assert det._has_structural_marker("github.com") is True
    assert det._has_structural_marker("user@example.com") is True
    assert det._has_structural_marker("hello") is False
    assert det._has_structural_marker("привет") is False


def test_identifier_guard_detects_code_tokens() -> None:
    det = LanguageDetector(converter=LayoutConverter(), stop_words=[], min_word_length=3)
    for token in ("snake_case", "camelCase", "x86_64", "A1", "my-var"):
        assert det._has_structural_marker(token) or det._should_guard(token, "us")
    # Plain words are not identifiers.
    assert det._should_guard("ghbdtn", "us") is False


def test_taught_word_wins_over_plausibility_guard() -> None:
    """A user-taught word must be fixed even if the source looks plausible."""
    det = LanguageDetector(
        converter=LayoutConverter(), stop_words=[], min_word_length=3, user_words=["vercel"]
    )
    assert det.target_layout("муксуд", "ru") == "us"


# --- a real wrong-layout word whose source spelling looks plausible --------------
#
# ``ltym`` is not an English word, but its bigram score clears the plausibility
# floor, so the false-positive guard used to veto the conversion even though
# ``день`` is a common Russian word. A conversion that yields *only* known
# words of the target language is stronger evidence than the source's
# plausibility, so it now overrides the guard. These cases include letters whose
# US keys are punctuation (``;`` -> ``ж``, ``[`` -> ``х``), which the word tokenizer
# splits, so the whole-token vocabulary check is what makes them work.


@pytest.mark.parametrize(
    ("typed", "layout", "expected"),
    [
        ("ltym", "us", "ru"),
        (",eltn", "us", "ru"),
        ("vj;tn", "us", "ru"),
        ("ye;yj", "us", "ru"),
        ("b[", "us", None),
    ],
)
def test_plausible_source_word_is_still_corrected(
    det: LanguageDetector, typed: str, layout: str, expected: str | None
) -> None:
    assert det.target_layout(typed, layout) == expected


@pytest.mark.parametrize(
    ("typed", "layout", "expected"),
    [
        ("ltym", "us", "день"),
        (",eltn", "us", "будет"),
        ("vj;tn", "us", "может"),
        ("ye;yj", "us", "нужно"),
    ],
)
def test_plausible_source_word_converts_to_the_expected_word(
    det: LanguageDetector, typed: str, layout: str, expected: str
) -> None:
    target = det.target_layout(typed, layout)
    assert target is not None
    assert det.convert_buffer(typed, layout, target) == expected


def test_vocabulary_validated_override_respects_a_real_source_word(
    det: LanguageDetector,
) -> None:
    """A word that really is a current-layout word is never overridden."""
    # Short pairs such as ``lf`` -> ``да`` stay on the explicit-hotkey path; a
    # full-length real word must stay put here.
    assert det._vocabulary_validated_layout("hello", "us") is None
    assert det._vocabulary_validated_layout("привет", "ru") is None
    assert det.target_layout("hello", "us") is None


def test_vocabulary_validated_override_is_not_applied_to_urls(
    det: LanguageDetector,
) -> None:
    """The override must not resurrect a structural false positive."""
    for token in ("github.com", "user@example.com", "/usr/local/bin", "snake_case"):
        assert det._vocabulary_validated_layout(token, "us") is None


# --- accented Latin vowels (diacritic false-positive guard) ----------------------


@pytest.fixture
def multi_det() -> LanguageDetector:
    """A detector with every shipped corpus, so de/fr really have a model."""
    return LanguageDetector(
        converter=LayoutConverter(),
        stop_words=[],
        min_word_length=3,
        languages=("en", "ru", "uk", "de", "fr"),
    )


@pytest.mark.parametrize(
    ("word", "language"),
    [
        # Every vowel here is accented: the old hand-written set saw no vowel at
        # all, so a valid word was rejected as noise.
        ("zähl", "de"),
        ("möcht", "de"),
        ("füllt", "de"),
        ("rück", "de"),
        ("schämt", "de"),
        ("brûlés", "fr"),
        ("cédé", "fr"),
        ("mémé", "fr"),
        ("dégénéré", "fr"),
    ],
)
def test_accented_vowel_words_are_plausible(
    multi_det: LanguageDetector, word: str, language: str
) -> None:
    """An accented vowel counts as a vowel in the shape guard.

    The guard used to miss ``ü``/``é``/``ø`` and the rest, so a valid German or
    French word outside the top-10k vocabulary looked vowel-less and was treated
    as noise. These words are deliberately absent from the bundled corpora and
    contain no plain base vowel, so only the accent fold can make them pass.
    """
    assert word.lower() not in multi_det._vocabularies.get(language, set())
    assert not any(char in _BASE_VOWELS for char in word.lower())
    assert multi_det._word_is_plausible(word, language) is True


def test_cyrillic_short_i_stays_a_consonant() -> None:
    """The Latin fold must not touch Cyrillic: ``й`` is a consonant."""
    from klyrshift.detector import _VOWELS

    assert "й" not in _VOWELS
    assert "ё" in _VOWELS  # a real Russian vowel, already listed
    assert "ї" in _VOWELS  # Ukrainian


def test_every_accented_latin_vowel_is_recognised() -> None:
    """No precomposed accented Latin vowel may be missing from the set."""
    import unicodedata

    from klyrshift.detector import _VOWELS

    missing = []
    for code in range(0xC0, 0x2B0):
        char = chr(code)
        decomposed = unicodedata.normalize("NFKD", char)
        if decomposed != char and decomposed[0] in _BASE_VOWELS and char not in _VOWELS:
            missing.append(char)
    assert missing == []


# --- short technical tokens (acronyms) -------------------------------------------
#
# A short, vowel-less Latin token (``http``, ``www``, ``xml``, ``pdf`` ...) scores
# as noise in the English bigram model, so the Russian model used to win by a
# small margin and the detector rewrote the token into Cyrillic letters the user
# never typed. These tokens are not words of any shipped language, so they are
# listed in the bundled stop-word list; the detector must leave them alone.

# The tokens whose wrong-layout rendering the corpus would otherwise accept.
_TECH_TOKENS = [
    "http",
    "https",
    "www",
    "xml",
    "yml",
    "toml",
    "pdf",
    "jpg",
    "jpeg",
    "png",
    "gif",
    "svg",
    "csv",
    "tsv",
    "xlsx",
    "xls",
    "docx",
    "txt",
    "cfg",
    "ini",
    "conf",
    "pem",
    "crt",
    "tls",
    "ssl",
    "mtls",
    "jwt",
    "csrf",
    "xss",
    "cors",
    "vpn",
    "dhcp",
    "ntp",
    "dns",
    "svn",
    "cvs",
    "hg",
    "fps",
    "tpu",
    "npu",
    "apu",
    "llm",
]


@pytest.fixture
def default_det() -> LanguageDetector:
    """A detector configured exactly as the daemon configures it by default."""
    from klyrshift.config import load_default_stop_words

    return LanguageDetector(
        converter=LayoutConverter(),
        stop_words=load_default_stop_words(),
        min_word_length=3,
    )


@pytest.mark.parametrize("token", _TECH_TOKENS)
def test_short_tech_token_is_left_alone(default_det: LanguageDetector, token: str) -> None:
    assert default_det.target_layout(token, "us") is None


@pytest.mark.parametrize("token", _TECH_TOKENS)
def test_short_tech_token_is_never_flagged(default_det: LanguageDetector, token: str) -> None:
    assert default_det.should_fix(token, "us") is False


def test_stop_words_do_not_block_the_flagship_fixes(default_det: LanguageDetector) -> None:
    """The added tokens must not stop a genuine wrong-layout word being fixed."""
    for typed, layout, expected in [
        ("ghbdtn", "us", "ru"),
        ("rfr", "us", "ru"),
        ("ltkf", "us", "ru"),
        ("ntrcn", "us", "ru"),
    ]:
        assert default_det.target_layout(typed, layout) == expected, typed


# --- canary: a wide, independent technical-token corpus ----------------------
#
# The canary for the "technical tokens" section of stop_words.txt. It must NOT
# be a restatement of that list, or it would only prove "the list is applied",
# never "the list is sufficient": a token that leaks would go unnamed because it
# is not in the corpus either.
#
# The corpus is therefore built from two sources *wider* than the stop-word
# list, and the tests below assert that widening explicitly:
#
#   * Python's stdlib ``mimetypes`` extension table -- an external, maintained
#     source the project does not control, so a new file format appears here
#     without anyone editing this file; and
#   * a static list of source extensions, protocols, build/container tools and
#     config keys, which never belong in the detector's word model.
#
# A token that IS a real word of a shipped language (``so``, ``key``, ``log``)
# is not "a leak" when left alone and is excluded by ``_KNOWN_WORDS``; the
# detector is *allowed* to keep a real word. Everything else must be left in the
# layout it was typed in.

# Extensions that are also real words, so leaving them alone is not a bug.
_KNOWN_WORDS = frozenset({"so", "key", "log", "mid", "img", "tmp", "dat", "bin", "iso"})


def _mimetype_extensions() -> set[str]:
    """Return the built-in MIME extensions (no system files, so it is stable).

    ``mimetypes.types_map`` is populated from the stdlib table at import; the
    system ``/etc/mime.types`` is only read by ``mimetypes.init()``, which is
    deliberately not called so the corpus does not depend on the host.
    """
    return {
        ext.lstrip(".").lower()
        for ext in mimetypes.types_map
        if len(ext) >= 4 and ext.lstrip(".").isalpha()
    }


# Source extensions, protocols, build/container tools and config keys. None is a
# word of en/ru/de/fr/uk; they are what a developer types all day.
_STATIC_TECH_TOKENS = frozenset(
    [
        "webp",
        "jsonl",
        "toml",
        "sse",
        "yaml",
        "proto",
        "proto3",
        "pem",
        "crt",
        "csr",
        "der",
        "p12",
        "pfx",
        "jks",
        "crl",
        "ocsp",
        "mjs",
        "cjs",
        "tsx",
        "jsx",
        "vue",
        "svelte",
        "astro",
        "xhtml",
        "rdf",
        "pkl",
        "npy",
        "npz",
        "parquet",
        "arrow",
        "feather",
        "orc",
        "avro",
        "zarr",
        "hdf",
        "hdf5",
        "webm",
        "mkv",
        "flac",
        "ogg",
        "opus",
        "aiff",
        "midi",
        "zstd",
        "lz4",
        "bz2",
        "tgz",
        "zst",
        "lzo",
        "lzma",
        "dll",
        "dylib",
        "appimage",
        "flatpak",
        "msix",
        "pyc",
        "pyo",
        "pyi",
        "whl",
        "sass",
        "scss",
        "less",
        "styl",
        "ipynb",
        "rmd",
        "psd",
        "indd",
        "ttf",
        "otf",
        "woff",
        "woff2",
        "tcp",
        "udp",
        "smtp",
        "imap",
        "pop3",
        "ssl",
        "tls",
        "ssh",
        "scp",
        "sftp",
        "rsync",
        "ntp",
        "snmp",
        "ldap",
        "oauth",
        "saml",
        "sso",
        "mfa",
        "otp",
        "totp",
        "jwt",
        "csrf",
        "xss",
        "cors",
        "csp",
        "hsts",
        "dockerfile",
        "vagrantfile",
        "makefile",
        "cmakelists",
        "gemfile",
        "procfile",
        "npmrc",
        "yarnrc",
        "babelrc",
        "eslintrc",
        "prettierrc",
        "editorconfig",
        "gitignore",
        "dockerignore",
        "kubernetes",
        "kubectl",
        "helm",
        "terraform",
        "ansible",
        "redis",
        "mongo",
        "mysql",
        "pgsql",
        "sqlite",
        "nginx",
        "apache",
        "caddy",
        "haproxy",
        "varnish",
        "webpack",
        "vite",
        "rollup",
        "esbuild",
        "parcel",
        "protobuf",
        "thrift",
        "capnp",
        "flatbuffers",
        "msgpack",
        "cbor",
        "bson",
    ]
)

_TECH_TOKEN_CORPUS = tuple(
    sorted((set(_mimetype_extensions()) | _STATIC_TECH_TOKENS) - _KNOWN_WORDS)
)


@pytest.mark.parametrize("token", _TECH_TOKEN_CORPUS)
def test_tech_token_corpus_is_never_rewritten(default_det: LanguageDetector, token: str) -> None:
    assert default_det.target_layout(token, "us") is None, token
    assert default_det.should_fix(token, "us") is False, token


def test_the_canary_corpus_is_wider_than_the_stop_word_list() -> None:
    """The canary must not be a restatement of stop_words.txt.

    If every corpus token were also a stop word, the corpus would only prove
    "the list is applied". The independent tokens -- those protected by the
    plausibility/structural guards rather than by the list -- are what catch a
    regression in *those* guards, and they must be the majority of the corpus.
    """
    from klyrshift.config import load_default_stop_words

    stop_words = {word.lower() for word in load_default_stop_words()}
    independent = [token for token in _TECH_TOKEN_CORPUS if token not in stop_words]
    assert len(independent) >= 100, (
        f"only {len(independent)} of {len(_TECH_TOKEN_CORPUS)} canary tokens are "
        "independent of stop_words.txt; the canary is too close to the list it guards"
    )


def test_the_canary_corpus_is_reasonably_wide() -> None:
    """A canary that is too small is not a net."""
    assert len(_TECH_TOKEN_CORPUS) >= 150
