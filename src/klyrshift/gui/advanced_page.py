"""Advanced settings page, hidden behind a button on the main window."""

from __future__ import annotations

import re
from collections.abc import Callable
from pathlib import Path

import gi

from ..i18n import _

gi.require_version("Gtk", "4.0")
gi.require_version("Adw", "1")
from gi.repository import Adw, Gtk  # noqa: E402

from ..config import (  # noqa: E402
    DEFAULT_ACCEPT_SUGGESTION_HOTKEY,
    DEFAULT_FIX_HOTKEY,
    DEFAULT_TOGGLE_LAYOUT_HOTKEY,
    DEFAULT_UNDO_HOTKEY,
    config_path,
)
from .prefs_base import BoundPreferencesPage  # noqa: E402
from .state import GuiState  # noqa: E402
from .widgets.app_exceptions_list import AppExceptionsList  # noqa: E402
from .widgets.app_layout_map import AppLayoutMap  # noqa: E402
from .widgets.backup_group import BackupGroup  # noqa: E402
from .widgets.hotkey_row import HotkeyRow  # noqa: E402

DICTIONARY_OPTIONS = ("1000", "5000", "10000")
LOG_LEVELS = ("DEBUG", "INFO", "WARNING", "ERROR")


class AdvancedPage(BoundPreferencesPage):
    """Detector, trigger, injection, exception, dictionary and log settings."""

    def __init__(self, state: GuiState, on_saved: Callable[[str], None] | None = None) -> None:
        super().__init__(state, on_saved)
        self._build_detector_group()
        self._build_triggers_group()
        self._build_injection_group()
        self._build_quiet_hours_group()
        self._build_exceptions_group()
        self._build_dictionary_group()
        self._build_typo_group()
        self._build_expander_group()
        self._build_learning_group()
        self._build_hotkeys_group()
        self._build_notifications_group()
        self._build_backup_group()
        self._build_logs_group()

    # --- detector ---------------------------------------------------------
    def _build_detector_group(self) -> None:
        group = self.attach_help(Adw.PreferencesGroup(title=_("Детектор")), "guards")
        self.add_spin(
            group, _("Минимальная длина слова"), "min_word_length", lower=1, upper=10, step=1
        )
        self.add_spin(
            group,
            _("Порог уверенности"),
            "confidence_threshold",
            lower=0.5,
            upper=0.95,
            step=0.05,
            digits=2,
        )
        self.add_spin(
            group,
            _("Гибрид: порог автозамены"),
            "hybrid_confidence",
            lower=0.0,
            upper=20.0,
            step=0.5,
            digits=1,
            subtitle=_("Ниже порога исправление остаётся на горячую клавишу"),
        )
        self.add_switch(group, _("Контекстный анализ"), "context_analysis")
        self.add_spin(
            group,
            _("Вес контекста"),
            "context_weight",
            lower=0.0,
            upper=1.0,
            step=0.05,
            digits=2,
        )
        self.add_switch(group, _("Не трогать СЛОВА_КАПСОМ"), "ignore_all_caps")
        self.add_switch(group, _("Не трогать слова с цифрами"), "ignore_with_digits")
        self.add_switch(group, _("Не трогать email и URL"), "ignore_emails_urls")
        self.add_switch(
            group,
            _("Не трогать поля пароля"),
            "password_guard",
            subtitle=_("Через AT-SPI (доступность); при недоступности — обычное поведение"),
        )
        self._regex_entry = self.add_entry(
            group,
            _("Свой regex-пропуск"),
            "custom_skip_regex",
            on_changed=self._validate_regex,
        )
        self.add(group)

    def _validate_regex(self, value: str) -> bool:
        if not value:
            return True
        try:
            re.compile(value)
        except re.error:
            self._regex_entry.add_css_class("error")
            if self._on_saved is not None:
                self._on_saved(_("Некорректное регулярное выражение"))
            return False
        self._regex_entry.remove_css_class("error")
        return True

    # --- triggers ---------------------------------------------------------
    def _build_triggers_group(self) -> None:
        group = self.attach_help(Adw.PreferencesGroup(title=_("Триггеры")), "triggers")
        self.add_switch(group, _("По пробелу"), "on_space")
        self.add_switch(group, _("По Enter"), "on_enter")
        self.add_switch(group, _("По Tab"), "on_tab")
        self.add_switch(group, _("По знакам препинания"), "on_punctuation")
        self.add_entry(group, _("Символы-разделители"), "punctuation_chars")
        self.add_spin(
            group,
            _("Таймаут анализа, с"),
            "analysis_timeout",
            lower=0.3,
            upper=3.0,
            step=0.1,
            digits=1,
        )
        self.add_spin(
            group,
            _("Пауза после Backspace, мс"),
            "backspace_settle_ms",
            lower=0,
            upper=200,
            step=5,
        )
        self.add_spin(
            group,
            _("Пауза после триггера (пробел/Enter), мс"),
            "trigger_settle_ms",
            lower=0,
            upper=200,
            step=5,
        )
        self.add(group)

    # --- injection --------------------------------------------------------
    def _build_injection_group(self) -> None:
        group = self.attach_help(Adw.PreferencesGroup(title=_("Инъекция")), "timing")
        self.add_spin(
            group, _("Максимальный размер буфера"), "max_buffer_size", lower=50, upper=1000, step=10
        )
        self.add_spin(
            group, _("Глубина истории отмены"), "undo_history_depth", lower=1, upper=10, step=1
        )
        self.add_spin(group, _("Окно отмены, с"), "undo_window_seconds", lower=3, upper=60, step=1)
        self.add_spin(group, _("Записей в истории"), "history_size", lower=5, upper=50, step=5)
        self.add(group)

    # --- quiet hours ------------------------------------------------------
    def _build_quiet_hours_group(self) -> None:
        group = self.attach_help(
            Adw.PreferencesGroup(
                title=_("Тихие часы"),
                description=_(
                    "В это время автоматическая коррекция приостановлена; "
                    "ручной fix (двойной Shift) продолжает работать."
                ),
            ),
            "quiet_hours",
        )
        self.add_switch(group, _("Включить тихие часы"), "quiet_hours_enabled")
        self.add_entry(group, _("Начало (ЧЧ:ММ)"), "quiet_hours_start")
        self.add_entry(group, _("Конец (ЧЧ:ММ)"), "quiet_hours_end")
        self.add(group)

    # --- exceptions -------------------------------------------------------
    def _build_exceptions_group(self) -> None:
        self._exceptions = self.attach_help(
            AppExceptionsList(
                _("Исключения приложений"),
                _("В этих приложениях автокоррекция отключена"),
                self._config.exceptions_apps,
                on_change=self._on_exceptions_changed,
                on_detect=self._detect_current_app,
            ),
            "exceptions",
        )
        self.add(self._exceptions)
        self._force_manual = self.attach_help(
            AppExceptionsList(
                _("Исправлять даже в ручном режиме"),
                _("Эти приложения исправляются автоматически в режиме «Ручной»"),
                self._config.exceptions_force_in_manual,
                on_change=self._on_force_manual_changed,
            ),
            "exceptions",
        )
        self.add(self._force_manual)
        self._app_layouts = self.attach_help(
            AppLayoutMap(
                _("Раскладка по приложениям"),
                _("При переключении на приложение включать эту раскладку"),
                self._config.app_layouts,
                on_change=self._on_app_layouts_changed,
                on_detect=self._detect_current_app,
            ),
            "app_layouts",
        )
        self.add(self._app_layouts)
        self.add_switch(
            self._app_layouts, _("Переключать раскладку по приложению"), "app_layout_switch"
        )

    def _on_app_layouts_changed(self, mapping: dict[str, str]) -> None:
        self._config.app_layouts = mapping
        self._save(_("Раскладка по приложениям сохранена"))

    def _on_exceptions_changed(self, apps: list[str]) -> None:
        self._config.exceptions_apps = apps
        self._save(_("Исключения сохранены"))

    def _on_force_manual_changed(self, apps: list[str]) -> None:
        self._config.exceptions_force_in_manual = apps
        self._save(_("Исключения сохранены"))

    @staticmethod
    def _detect_current_app() -> str | None:
        """Best-effort active-window process name via GNOME Shell's D-Bus."""
        try:
            from ..app_focus import get_active_app
        except ImportError:  # pragma: no cover - defensive
            return None
        return get_active_app()

    # --- dictionaries -----------------------------------------------------
    def _build_dictionary_group(self) -> None:
        group = self.attach_help(Adw.PreferencesGroup(title=_("Словари")), "dictionary")
        self.add_combo(
            group,
            _("Размер словаря"),
            list(DICTIONARY_OPTIONS),
            [_("{0} слов").format(size) for size in DICTIONARY_OPTIONS],
            str(self._config.dictionary_size),
            self._on_dictionary_size,
        )
        self.add_entry(group, _("Свой словарь (путь)"), "dictionary_custom_path")
        self.add(group)

    def _on_dictionary_size(self, value: str) -> None:
        self._config.dictionary_size = int(value)
        self._save(_("Словарь сохранён"))

    # --- typo correction (T9) ---------------------------------------------
    def _build_typo_group(self) -> None:
        group = self.attach_help(
            Adw.PreferencesGroup(
                title=_("Исправление опечаток (T9)"),
                description=_(
                    "Меняет слово на ближайшее из словаря, только если "
                    "вариант однозначен: одну опечатку в коротком слове, до двух — "
                    "в слове длиной от 6 символов. Выключено по умолчанию."
                ),
            ),
            "typo",
        )
        self._typo_switch = self.add_switch(group, _("Исправлять опечатки"), "typo_correction")
        self.add_spin(
            group,
            _("Максимум опечаток (короткие слова)"),
            "typo_max_distance",
            lower=1,
            upper=2,
            step=1,
        )
        self.add_spin(
            group,
            _("Максимум опечаток (слова от 6 символов)"),
            "typo_max_distance_long",
            lower=1,
            upper=2,
            step=1,
        )
        self.add_spin(
            group,
            _("Минимальная длина слова"),
            "typo_min_word_length",
            lower=3,
            upper=12,
            step=1,
        )
        self.add(group)

    # --- text expansion (snippets) ----------------------------------------
    def _build_expander_group(self) -> None:
        group = self.attach_help(
            Adw.PreferencesGroup(
                title=_("Текстовые сокращения"),
                description=_(
                    "Короткий триггер превращается в длинный текст, "
                    "например !!email → адрес. Выключено по умолчанию."
                ),
            ),
            "snippets",
        )
        self.add_switch(group, _("Включить сокращения"), "text_expander_enabled")
        self.add_entry(group, _("Файл сокращений"), "text_expander_snippets_path")
        self.add(group)

    # --- learning ---------------------------------------------------------
    def _build_learning_group(self) -> None:
        group = self.attach_help(
            Adw.PreferencesGroup(
                title=_("Обучение"),
                description=_(
                    "Приложение наблюдает за тем, что вы оставляете, "
                    "исправляете и отменяете (Ctrl+Z), и подстраивается. Сами слова "
                    "держатся только в памяти и никогда не пишутся на диск."
                ),
            ),
            "learning",
        )
        self._learning_switch = self.add_switch(group, _("Включить обучение"), "learning_enabled")
        self.add_spin(
            group,
            _("Сколько раз оставить слово, чтобы запомнить"),
            "learning_promote_threshold",
            lower=1,
            upper=20,
            step=1,
        )
        self.add(group)

    # --- hotkeys ----------------------------------------------------------
    def _build_hotkeys_group(self) -> None:
        group = self.attach_help(Adw.PreferencesGroup(title=_("Хоткеи")), "hotkeys")
        self._toggle_row = HotkeyRow(
            _("Переключить режим"),
            "",
            self._config.hotkey_toggle_mode,
            on_change=self._make_hotkey_handler("hotkey_toggle_mode"),
        )
        group.add(self._toggle_row)
        self._reload_row = HotkeyRow(
            _("Перечитать конфигурацию"),
            "",
            self._config.hotkey_reload_config,
            on_change=self._make_hotkey_handler("hotkey_reload_config"),
        )
        group.add(self._reload_row)
        self._selection_row = HotkeyRow(
            _("Исправить выделенный текст"),
            "CTRL+SHIFT+L",
            self._config.selection_fix_hotkey,
            on_change=self._make_hotkey_handler("selection_fix_hotkey"),
        )
        group.add(self._selection_row)
        self._accept_row = HotkeyRow(
            _("Применить предложение"),
            "",
            self._config.hotkey_accept_suggestion,
            on_change=self._make_hotkey_handler("hotkey_accept_suggestion"),
        )
        group.add(self._accept_row)
        self.add_switch(group, _("Не передавать хоткей в приложение"), "hotkey_swallow")
        self.add_switch(group, _("Исправлять выделенный текст"), "selection_fix_enabled")
        reset = Gtk.Button(label=_("Сбросить к дефолтным"))
        reset.connect("clicked", self._on_reset_hotkeys)
        reset.set_halign(Gtk.Align.START)
        reset.add_css_class("flat")
        group.add(reset)
        self.add(group)

    def _make_hotkey_handler(self, field: str) -> Callable[[str], None]:
        def handler(value: str) -> None:
            setattr(self._config, field, value)
            self._save(_("Хоткей сохранён"))

        return handler

    def _on_reset_hotkeys(self, _button: Gtk.Button) -> None:
        # The fix/undo rows live on the Settings page, so only the two rows on
        # this page are redrawn here; the config fields are all reset.
        self._config.hotkey_fix_last_word = DEFAULT_FIX_HOTKEY
        self._config.hotkey_undo_last_fix = DEFAULT_UNDO_HOTKEY
        self._config.hotkey_toggle_layout_last_word = DEFAULT_TOGGLE_LAYOUT_HOTKEY
        self._config.hotkey_accept_suggestion = DEFAULT_ACCEPT_SUGGESTION_HOTKEY
        self._config.hotkey_toggle_mode = ""
        self._config.hotkey_reload_config = "CTRL+SHIFT+R"
        self._config.hotkey = DEFAULT_FIX_HOTKEY
        self._config.selection_fix_hotkey = "CTRL+SHIFT+L"
        self._toggle_row.set_value("")
        self._reload_row.set_value("CTRL+SHIFT+R")
        self._selection_row.set_value("CTRL+SHIFT+L")
        self._accept_row.set_value("")
        self._save(_("Хоткеи сброшены"))

    # --- notifications ----------------------------------------------------
    def _build_notifications_group(self) -> None:
        group = self.attach_help(Adw.PreferencesGroup(title=_("Уведомления")), "notifications")
        self.add_switch(group, _("Уведомлять об исправлении"), "notify_on_fix")
        self.add_switch(group, _("Уведомлять об ошибке"), "notify_on_error")
        self.add_switch(
            group,
            _("Уведомлять о предложении"),
            "suggest_on_withhold",
            subtitle=_("В гибридном режиме, когда исправление отложено"),
        )
        self.add_switch(group, _("Звук при исправлении"), "sound_on_fix")
        self.add_switch(group, _("Иконка в трее"), "tray_enabled")
        self.add_switch(
            group,
            _("Проверять обновления"),
            "update_check_enabled",
            subtitle=_("Раз в сутки запрашивает номер последней версии на GitHub"),
        )
        self.add(group)

    # --- backup -----------------------------------------------------------
    def _build_backup_group(self) -> None:
        self._backup_group = BackupGroup(
            on_export=self._export_settings,
            on_import=self._import_settings,
            on_notify=self._on_saved,
        )
        self.add(self._backup_group)

    @staticmethod
    def _export_settings(path: str) -> bool:
        from ..backup import write_backup

        try:
            write_backup(Path(path))
        except OSError:
            return False
        return True

    def _import_settings(self, path: str) -> bool:
        from ..backup import apply_backup, read_backup

        try:
            data = read_backup(Path(path))
        except (OSError, ValueError):
            return False
        apply_backup(data)
        self._state.reload()
        self._config = self._state.config
        return True

    def _build_logs_group(self) -> None:
        group = self.attach_help(Adw.PreferencesGroup(title=_("Логи")), "logs")
        self.add_combo(
            group,
            _("Уровень логирования"),
            list(LOG_LEVELS),
            list(LOG_LEVELS),
            self._config.log_level,
            self._on_log_level,
        )
        self.add_spin(group, _("Ротация, МБ"), "log_rotation_mb", lower=1, upper=50, step=1)
        open_button = Gtk.Button(label=_("Открыть config.toml"))
        open_button.connect("clicked", self._on_open_config)
        open_button.set_halign(Gtk.Align.START)
        open_button.add_css_class("flat")
        group.add(open_button)
        self.add(group)

    def _on_log_level(self, value: str) -> None:
        self._config.log_level = value
        self._save(_("Уровень логирования сохранён"))

    @staticmethod
    def _on_open_config(_button: Gtk.Button) -> None:
        path = config_path()
        try:
            import subprocess

            subprocess.run(["xdg-open", str(path)], check=False, timeout=5)
        except (OSError, subprocess.SubprocessError):  # pragma: no cover - desktop only
            pass
