"""Basic settings page (always visible)."""

from __future__ import annotations

from collections.abc import Callable

import gi

gi.require_version("Gtk", "4.0")
gi.require_version("Adw", "1")
from gi.repository import Adw, Gtk  # noqa: E402

from ..langstore import (  # noqa: E402
    LANGUAGE_LABELS,
    all_language_status,
    install_language,
    remove_language,
)
from .async_utils import run_in_background  # noqa: E402
from .prefs_base import BoundPreferencesPage  # noqa: E402
from .state import MODE_LABELS, GuiState  # noqa: E402
from .theme import apply_theme  # noqa: E402
from .widgets.hotkey_row import HotkeyRow  # noqa: E402
from .widgets.languages_group import LanguagesGroup  # noqa: E402

MODE_ORDER = ("auto", "manual", "hybrid")

# The colour-scheme choices offered in the settings window, in display order.
THEME_ORDER = ("system", "light", "dark")
THEME_LABELS = {"system": "Как в системе", "light": "Светлая", "dark": "Тёмная"}


class SettingsPage(BoundPreferencesPage):
    """The default settings tab: mode, hotkeys, languages and notifications."""

    def __init__(self, state: GuiState, on_saved: Callable[[str], None] | None = None) -> None:
        super().__init__(state, on_saved)
        self._build_mode_group()
        self._build_appearance_group()
        self._build_hotkeys_group()
        self._build_languages_group()
        self._build_notifications_group()

    # --- groups -----------------------------------------------------------
    def _build_mode_group(self) -> None:
        group = self.attach_help(Adw.PreferencesGroup(title="Основные"), "mode")
        self._mode_row = self.add_combo(
            group,
            "Режим работы",
            list(MODE_ORDER),
            [MODE_LABELS[m] for m in MODE_ORDER],
            self._config.mode,
            self._on_mode_selected,
            # The layout switch is what ``manual`` gates. The opt-in passes
            # (T9, punctuation) are layout-neutral and still run unless their
            # own switches are off, so a "fully quiet" manual needs those off.
            subtitle=(
                "Авто исправляет сразу, ручной — только по хоткею "
                "(опечатки и пунктуация — по своим переключателям)"
            ),
        )
        self.add(group)

    def _on_mode_selected(self, mode: str) -> None:
        self._config.mode = mode
        self._save(f"Режим изменён на {MODE_LABELS.get(mode, mode)}")

    def _build_appearance_group(self) -> None:
        group = self.attach_help(Adw.PreferencesGroup(title="Оформление"), "theme")
        self._theme_row = self.add_combo(
            group,
            "Тема окна",
            list(THEME_ORDER),
            [THEME_LABELS[t] for t in THEME_ORDER],
            self._config.theme,
            self._on_theme_selected,
            subtitle="Только окно настроек; на исправление текста не влияет",
        )
        self.add(group)

    @property
    def theme_row(self) -> Adw.ComboRow:
        """Expose the theme combo (also a tour target)."""
        return self._theme_row

    def _on_theme_selected(self, theme: str) -> None:
        self._config.theme = theme
        apply_theme(theme)
        self._save(f"Тема: {THEME_LABELS.get(theme, theme)}")

    def reload(self) -> None:
        """Re-read the config into the rows without emitting change signals.

        The first-run wizard writes the same config fields the rows bind to; a
        row that is not re-synced would show the old value until the window is
        rebuilt. Signals are blocked so a reload never writes the config back.
        """
        self._mode_row.handler_block_by_func(self._on_combo)
        self._mode_row.set_selected(MODE_ORDER.index(self._config.mode))
        self._mode_row.handler_unblock_by_func(self._on_combo)
        self._languages.refresh(all_language_status(self._config))

    def _build_hotkeys_group(self) -> None:
        group = self.attach_help(
            Adw.PreferencesGroup(
                title="Хоткеи",
                description="Нажмите «Изменить», затем нужную комбинацию. Esc — отмена.",
            ),
            "hotkeys",
        )
        self.add_switch(group, "Хоткеи включены", "hotkeys_enabled")
        self._hotkey_fix = HotkeyRow(
            "Исправить последнее слово",
            "Двойной Shift по умолчанию. Нажмите «Изменить» и дважды нажмите "
            "нужный модификатор (Shift/Ctrl/Alt) или задайте комбинацию.",
            self._config.hotkey_fix_last_word,
            on_change=self._make_hotkey_handler("hotkey_fix_last_word"),
        )
        group.add(self._hotkey_fix)
        self._hotkey_undo = HotkeyRow(
            "Отменить последнее исправление",
            "Работает только в режиме «Гибрид»",
            self._config.hotkey_undo_last_fix,
            on_change=self._make_hotkey_handler("hotkey_undo_last_fix"),
        )
        group.add(self._hotkey_undo)
        self._hotkey_toggle_layout = HotkeyRow(
            "Сменить раскладку последнего слова",
            "Разворачивает последнее слово в другую раскладку (привет → ghbdtn), "
            "даже если слово выглядит правильным. Пустое значение — выключено.",
            self._config.hotkey_toggle_layout_last_word,
            on_change=self._make_hotkey_handler("hotkey_toggle_layout_last_word"),
        )
        group.add(self._hotkey_toggle_layout)
        self.add(group)

    def _make_hotkey_handler(self, field: str) -> Callable[[str], None]:
        def handler(value: str) -> None:
            setattr(self._config, field, value)
            self._save("Хоткей сохранён")

        return handler

    def _build_languages_group(self) -> None:
        self._languages = LanguagesGroup(
            all_language_status(self._config),
            on_toggle=self._on_language_toggled,
            on_install=self._on_language_install,
            on_remove=self._on_language_remove,
        )
        self.attach_help(self._languages, "languages")
        self.add(self._languages)

    @property
    def language_rows(self) -> dict[str, Gtk.Switch]:
        """Expose the language enable switches by code, for the tour and tests."""
        return {code: row.switch for code, row in self._languages.rows.items()}

    @property
    def languages_group(self) -> LanguagesGroup:
        """Expose the languages group for tests."""
        return self._languages

    def _on_language_toggled(self, lang: str, active: bool) -> None:
        languages = [lang_ for lang_ in self._config.languages if lang_ != lang]
        if active:
            languages.append(lang)
        self._config.languages = languages
        try:
            self._config.validate()
        except ValueError:
            # Never leave the user with zero languages enabled; put the switch
            # back where it was rather than persist an invalid configuration.
            self._languages.refresh(all_language_status(self._config))
            return
        self._state.save()
        if self._on_saved is not None:
            self._on_saved("Языки сохранены")

    def _on_language_install(self, lang: str) -> None:
        """Download a language dictionary off the main thread, then refresh."""
        self._languages.set_busy(lang, True)

        def done(_result: object) -> None:
            self._languages.set_busy(lang, False)
            self._languages.refresh(all_language_status(self._config))
            if self._on_saved is not None:
                self._on_saved(f"Словарь {LANGUAGE_LABELS.get(lang, lang)} установлен")

        run_in_background(install_language, done, self._config, lang)

    def _on_language_remove(self, lang: str) -> None:
        """Delete a language dictionary, unless it is the last enabled one."""
        try:
            remove_language(self._config, lang)
        except ValueError:
            if self._on_saved is not None:
                self._on_saved("Нельзя удалить единственный включённый язык")
            return
        except OSError:
            if self._on_saved is not None:
                self._on_saved("Не удалось удалить словарь")
            return
        self._languages.refresh(all_language_status(self._config))
        if self._on_saved is not None:
            self._on_saved(f"Словарь {LANGUAGE_LABELS.get(lang, lang)} удалён")

    def _build_notifications_group(self) -> None:
        group = self.attach_help(Adw.PreferencesGroup(title="Уведомления и тайминги"), "timing")
        self.add_switch(group, "Уведомления при исправлении", "notify_on_fix")
        self.add_spin(
            group,
            "Таймаут анализа, с",
            "analysis_timeout",
            lower=0.3,
            upper=3.0,
            step=0.1,
            digits=1,
        )
        self.add(group)

    @property
    def hotkey_fix_row(self) -> HotkeyRow:
        """Expose the fix hotkey row (also a tour target)."""
        return self._hotkey_fix
