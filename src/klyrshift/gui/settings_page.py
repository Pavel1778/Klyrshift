"""Basic settings page (always visible)."""

from __future__ import annotations

from collections.abc import Callable

import gi

from .. import i18n
from ..i18n import LazyLabels, _, set_locale

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
THEME_LABELS = LazyLabels({"system": "Как в системе", "light": "Светлая", "dark": "Тёмная"})

# Interface language. ``auto`` follows the environment; the rest are explicit.
# The explicit list comes from the catalogue registry, so a new catalogue shows
# up in the combo without editing this module.
UI_LOCALE_ORDER = ("auto", *i18n.SUPPORTED_LOCALES)


def ui_locale_labels() -> list[str]:
    """Translated labels for the interface-language combo, in display order.

    ``auto`` is translated because it is an instruction ("follow the desktop");
    every other entry is the language's own name, which must stay readable to a
    speaker who cannot yet read the current interface language.
    """
    labels = [i18n.tr("Как в системе")]
    labels.extend(i18n.locale_name(locale) for locale in UI_LOCALE_ORDER[1:])
    return labels


class SettingsPage(BoundPreferencesPage):
    """The default settings tab: mode, hotkeys, languages and notifications."""

    def __init__(
        self,
        state: GuiState,
        on_saved: Callable[[str], None] | None = None,
        on_locale_changed: Callable[[], None] | None = None,
    ) -> None:
        self._on_locale_changed = on_locale_changed
        super().__init__(state, on_saved)
        self._build_mode_group()
        self._build_appearance_group()
        self._build_hotkeys_group()
        self._build_languages_group()
        self._build_notifications_group()

    # --- groups -----------------------------------------------------------
    def _build_mode_group(self) -> None:
        group = self.attach_help(Adw.PreferencesGroup(title=_("Основные")), "mode")
        self._mode_row = self.add_combo(
            group,
            _("Режим работы"),
            list(MODE_ORDER),
            [MODE_LABELS[m] for m in MODE_ORDER],
            self._config.mode,
            self._on_mode_selected,
            # The layout switch is what ``manual`` gates. The opt-in passes
            # (T9, punctuation) are layout-neutral and still run unless their
            # own switches are off, so a "fully quiet" manual needs those off.
            subtitle=(
                _(
                    "Авто исправляет сразу, ручной — только по хоткею "
                    "(опечатки и пунктуация — по своим переключателям)"
                )
            ),
        )
        self.add(group)

    def _on_mode_selected(self, mode: str) -> None:
        self._config.mode = mode
        self._save(_("Режим изменён на {0}").format(MODE_LABELS.get(mode, mode)))

    def _build_appearance_group(self) -> None:
        group = self.attach_help(Adw.PreferencesGroup(title=_("Оформление")), "theme")
        self._theme_row = self.add_combo(
            group,
            _("Тема окна"),
            list(THEME_ORDER),
            [THEME_LABELS[t] for t in THEME_ORDER],
            self._config.theme,
            self._on_theme_selected,
            subtitle=_("Только окно настроек; на исправление текста не влияет"),
        )
        self._locale_row = self.add_combo(
            group,
            _("Язык интерфейса"),
            list(UI_LOCALE_ORDER),
            ui_locale_labels(),
            self._config.ui_locale,
            self._on_locale_selected,
            subtitle=_("Применяется сразу; «Как в системе» — по языку окружения"),
        )
        self.add(group)

    @property
    def theme_row(self) -> Adw.ComboRow:
        """Expose the theme combo (also a tour target)."""
        return self._theme_row

    @property
    def locale_row(self) -> Adw.ComboRow:
        """Expose the interface-language combo."""
        return self._locale_row

    def _on_theme_selected(self, theme: str) -> None:
        self._config.theme = theme
        apply_theme(theme)
        self._save(_("Тема: {0}").format(THEME_LABELS.get(theme, theme)))

    def _on_locale_selected(self, locale: str) -> None:
        self._config.ui_locale = locale
        set_locale(locale)
        self._save(_("Язык интерфейса сохранён"))
        if self._on_locale_changed is not None:
            self._on_locale_changed()

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
                title=_("Хоткеи"),
                description=_("Нажмите «Изменить», затем нужную комбинацию. Esc — отмена."),
            ),
            "hotkeys",
        )
        self.add_switch(group, _("Хоткеи включены"), "hotkeys_enabled")
        self._hotkey_fix = HotkeyRow(
            _("Исправить последнее слово"),
            _(
                "Двойной Shift по умолчанию. Нажмите «Изменить» и дважды нажмите "
                "нужный модификатор (Shift/Ctrl/Alt) или задайте комбинацию."
            ),
            self._config.hotkey_fix_last_word,
            on_change=self._make_hotkey_handler("hotkey_fix_last_word"),
        )
        group.add(self._hotkey_fix)
        self._hotkey_undo = HotkeyRow(
            _("Отменить последнее исправление"),
            _("Работает только в режиме «Гибрид»"),
            self._config.hotkey_undo_last_fix,
            on_change=self._make_hotkey_handler("hotkey_undo_last_fix"),
        )
        group.add(self._hotkey_undo)
        self._hotkey_toggle_layout = HotkeyRow(
            _("Сменить раскладку последнего слова"),
            _(
                "Разворачивает последнее слово в другую раскладку (привет → ghbdtn), "
                "даже если слово выглядит правильным. Пустое значение — выключено."
            ),
            self._config.hotkey_toggle_layout_last_word,
            on_change=self._make_hotkey_handler("hotkey_toggle_layout_last_word"),
        )
        group.add(self._hotkey_toggle_layout)
        self.add(group)

    def _make_hotkey_handler(self, field: str) -> Callable[[str], None]:
        def handler(value: str) -> None:
            setattr(self._config, field, value)
            self._save(_("Хоткей сохранён"))

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
            self._on_saved(_("Языки сохранены"))

    def _on_language_install(self, lang: str) -> None:
        """Download a language dictionary off the main thread, then refresh."""
        self._languages.set_busy(lang, True)

        def done(_result: object) -> None:
            self._languages.set_busy(lang, False)
            self._languages.refresh(all_language_status(self._config))
            if self._on_saved is not None:
                self._on_saved(_("Словарь {0} установлен").format(LANGUAGE_LABELS.get(lang, lang)))

        run_in_background(install_language, done, self._config, lang)

    def _on_language_remove(self, lang: str) -> None:
        """Delete a language dictionary, unless it is the last enabled one."""
        try:
            remove_language(self._config, lang)
        except ValueError:
            if self._on_saved is not None:
                self._on_saved(_("Нельзя удалить единственный включённый язык"))
            return
        except OSError:
            if self._on_saved is not None:
                self._on_saved(_("Не удалось удалить словарь"))
            return
        self._languages.refresh(all_language_status(self._config))
        if self._on_saved is not None:
            self._on_saved(_("Словарь {0} удалён").format(LANGUAGE_LABELS.get(lang, lang)))

    def _build_notifications_group(self) -> None:
        group = self.attach_help(Adw.PreferencesGroup(title=_("Уведомления и тайминги")), "timing")
        self.add_switch(group, _("Уведомления при исправлении"), "notify_on_fix")
        self.add_spin(
            group,
            _("Таймаут анализа, с"),
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
