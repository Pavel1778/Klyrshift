"""Language dictionaries: install/remove for the GUI (``klyrshift.langstore``).

The download itself is a network boundary, so these tests stub the two
downloaders and exercise the real store logic around them: status reporting,
config updates, the "last language" guard, and file removal.
"""

from __future__ import annotations

from pathlib import Path

import pytest

from klyrshift import langstore
from klyrshift.config import Config
from klyrshift.dictionary import extended_dictionary_path
from klyrshift.thematic import thematic_path


@pytest.fixture
def config(tmp_path: Path) -> Config:
    """A config whose extended dictionaries live in ``tmp_path``."""
    cfg = Config()
    cfg.extended_dictionary_dir = str(tmp_path / "dicts")
    return cfg


def _write_dictionary(config: Config, language: str, words: int) -> Path:
    path = extended_dictionary_path(language, str(langstore.extended_dir(config)))
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text("\n".join(f"w{i}" for i in range(words)) + "\n", encoding="utf-8")
    return path


def test_status_reports_missing_dictionary(config: Config) -> None:
    status = langstore.language_status(config, "de")
    assert status.installed is False
    assert status.word_count == 0
    assert status.can_install is True
    assert "Не установлен" in status.state_text


def test_status_counts_words_and_comments(config: Config) -> None:
    path = extended_dictionary_path("de", str(langstore.extended_dir(config)))
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text("# comment\n// another\nслово\n\nвторое\n", encoding="utf-8")
    status = langstore.language_status(config, "de")
    assert status.installed is True
    assert status.word_count == 2


def test_all_status_covers_every_supported_language(config: Config) -> None:
    statuses = langstore.all_language_status(config)
    assert {s.language for s in statuses} == set(langstore.SUPPORTED_LANGUAGES)


def test_install_downloads_and_enables(config: Config, monkeypatch: pytest.MonkeyPatch) -> None:
    calls: list[tuple[str, str]] = []

    def fake_download(language: str, directory: str = "") -> tuple[Path, int]:
        calls.append((language, directory))
        path = _write_dictionary(config, language, 3)
        return path, 3

    monkeypatch.setattr(langstore, "download_extended_dictionary", fake_download)
    monkeypatch.setattr(langstore, "save_config", lambda _cfg: Path("/dev/null"))

    status = langstore.install_language(config, "de")
    assert calls == [("de", str(langstore.extended_dir(config)))]
    assert status.installed is True
    assert status.enabled is True
    assert status.word_count == 3
    assert "de" in config.languages
    assert config.extended_dictionary_dir == str(langstore.extended_dir(config))


def test_install_is_idempotent_for_enabled_language(
    config: Config, monkeypatch: pytest.MonkeyPatch
) -> None:
    config.languages = ["en", "ru"]
    monkeypatch.setattr(
        langstore,
        "download_extended_dictionary",
        lambda language, directory="": (_write_dictionary(config, language, 1), 1),
    )
    monkeypatch.setattr(langstore, "save_config", lambda _cfg: Path("/dev/null"))

    langstore.install_language(config, "ru")
    assert config.languages == ["en", "ru"]


def test_remove_deletes_file_and_disables(config: Config, monkeypatch: pytest.MonkeyPatch) -> None:
    config.languages = ["en", "de"]
    path = _write_dictionary(config, "de", 2)
    monkeypatch.setattr(langstore, "save_config", lambda _cfg: Path("/dev/null"))

    status = langstore.remove_language(config, "de")
    assert not path.exists()
    assert status.installed is False
    assert status.enabled is False
    assert config.languages == ["en"]


def test_remove_refuses_the_last_language(config: Config, monkeypatch: pytest.MonkeyPatch) -> None:
    config.languages = ["ru"]
    _write_dictionary(config, "ru", 2)
    monkeypatch.setattr(langstore, "save_config", lambda _cfg: Path("/dev/null"))

    with pytest.raises(ValueError):
        langstore.remove_language(config, "ru")
    assert config.languages == ["ru"]


def test_remove_missing_file_is_ok(config: Config, monkeypatch: pytest.MonkeyPatch) -> None:
    config.languages = ["en", "fr"]
    monkeypatch.setattr(langstore, "save_config", lambda _cfg: Path("/dev/null"))
    status = langstore.remove_language(config, "fr")
    assert status.installed is False
    assert config.languages == ["en"]


def test_category_status_and_install(config: Config, monkeypatch: pytest.MonkeyPatch) -> None:
    calls: list[tuple[str, str, str]] = []

    def fake_download(slug: str, language: str = "ru", directory: str = "") -> tuple[Path, int]:
        calls.append((slug, language, directory))
        path = thematic_path(slug, language, str(langstore.extended_dir(config)))
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text("термин\n", encoding="utf-8")
        return path, 1

    monkeypatch.setattr(langstore, "download_category", fake_download)
    monkeypatch.setattr(langstore, "save_config", lambda _cfg: Path("/dev/null"))

    status = langstore.install_category(config, "medical", "ru")
    assert calls == [("medical", "ru", str(langstore.extended_dir(config)))]
    assert status.installed is True
    assert status.enabled is True
    assert "medical" in config.installed_dict_categories


def test_remove_category_deletes_file_and_disables(
    config: Config, monkeypatch: pytest.MonkeyPatch
) -> None:
    path = thematic_path("medical", "ru", str(langstore.extended_dir(config)))
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text("термин\n", encoding="utf-8")
    config.installed_dict_categories = ["base", "medical"]
    monkeypatch.setattr(langstore, "save_config", lambda _cfg: Path("/dev/null"))

    status = langstore.remove_category(config, "medical")
    assert not path.exists()
    assert status.installed is False
    assert "medical" not in config.installed_dict_categories
    assert "base" in config.installed_dict_categories


def test_remove_base_category_is_refused(config: Config, monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(langstore, "save_config", lambda _cfg: Path("/dev/null"))
    with pytest.raises(ValueError):
        langstore.remove_category(config, "base")
