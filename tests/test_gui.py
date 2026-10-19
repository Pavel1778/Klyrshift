"""Tests for the GTK4 GUI.

GTK cannot be initialised without a display (it aborts the process), so these
tests are skipped unless one is available. In CI the suite runs under
``xvfb-run``, which provides a virtual display; on a developer machine with a
desktop session they run against the real display.
"""

from __future__ import annotations

import os
import sys
from pathlib import Path
from typing import Any

import pytest

import klyrshift.app_focus as app_focus
from klyrshift.config import Config

_DIST_PACKAGES = "/usr/lib/python3/dist-packages"
if os.path.isdir(_DIST_PACKAGES) and _DIST_PACKAGES not in sys.path:
    sys.path.append(_DIST_PACKAGES)


def _gtk_usable() -> bool:
    """GTK aborts without a display, so only run when one is reachable."""
    if not (os.environ.get("DISPLAY") or os.environ.get("WAYLAND_DISPLAY")):
        return False
    try:
        import gi

        gi.require_version("Gtk", "4.0")
        gi.require_version("Adw", "1")
        from gi.repository import Adw, Gtk  # noqa: F401
    except (ImportError, ValueError):
        return False
    return True


pytestmark = pytest.mark.skipif(not _gtk_usable(), reason="GTK4/libadwaita or display unavailable")


@pytest.fixture
def gui_state(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> Any:
    """Return a :class:`GuiState` isolated to ``tmp_path`` and a fake backend."""
    from klyrshift.gui import state as state_module
    from klyrshift.gui.state import GuiState

    config = Config()
    monkeypatch.setattr(state_module, "load_config", lambda: config)
    monkeypatch.setattr(state_module, "save_config", lambda _cfg, _path=None: tmp_path)
    return GuiState(config=config)


def test_window_creates_with_expected_pages(gui_state: Any) -> None:
    import gi

    gi.require_version("Adw", "1")
    from gi.repository import Adw

    from klyrshift.gui.window import KlyrshiftWindow

    app = Adw.Application(application_id="io.github.pavel1778.KlyrshiftTest")
    window = KlyrshiftWindow(gui_state, app)
    names = {page.get_name() for page in window.stack.get_pages()}
    assert names == {
        "home",
        "settings",
        "dictionary",
        "typo",
        "history",
        "advanced",
        "help",
    }
    # The advanced page exists but is hidden from the switcher until revealed.
    assert window.advanced_page.get_visible() is False
    assert window.help_page.get_visible() is False
    assert window.home.toggle.state == "off"
    window._on_show_advanced(None, None)
    assert window.advanced_page.get_visible() is True
    assert len(window.stack.get_pages()) == 7


def test_big_toggle_start_and_stop(gui_state: Any, monkeypatch: pytest.MonkeyPatch) -> None:
    from klyrshift.gui import state as state_module

    active = {"value": False}
    calls: list[str] = []

    monkeypatch.setattr(state_module, "daemon_is_running", lambda: active["value"])
    monkeypatch.setattr(state_module, "daemon_start", lambda: calls.append("start") or True)
    monkeypatch.setattr(state_module, "daemon_stop", lambda: calls.append("stop") or True)
    monkeypatch.setattr(state_module, "daemon_autostart_enabled", lambda: False)
    monkeypatch.setattr(state_module, "subprocess", _NoLayout())

    import gi

    from klyrshift.gui.home_page import HomePage
    from klyrshift.gui.widgets.big_toggle import STATE_BUSY, STATE_OFF, STATE_ON

    gi.require_version("Adw", "1")
    from gi.repository import Adw

    monkeypatch.setattr(app_focus, "get_active_app", lambda: None)

    page = HomePage(gui_state, Adw.ToastOverlay())
    assert page.toggle.state == STATE_OFF

    # Turn on: the service is not active, so a click starts it. The click must
    # return at once (the start runs on a worker thread), leaving the button busy.
    page._on_toggle_clicked()
    assert calls == ["start"]
    assert page.toggle.state == STATE_BUSY
    page._on_toggle_done(True)

    # The service is now active; a synchronous status apply flips the button ON.
    active["value"] = True
    page._apply_status(page._collect_status())
    assert page.toggle.state == STATE_ON

    page._on_toggle_clicked()
    assert calls == ["start", "stop"]
    assert page.toggle.state == STATE_BUSY


def test_undo_button_asks_daemon(gui_state: Any, monkeypatch: pytest.MonkeyPatch) -> None:
    from klyrshift.gui import state as state_module

    calls: list[str] = []
    monkeypatch.setattr(state_module, "daemon_is_running", lambda: True)
    monkeypatch.setattr(state_module, "daemon_undo_last_fix", lambda: calls.append("undo") or True)
    monkeypatch.setattr(state_module, "subprocess", _NoLayout())

    import gi

    gi.require_version("Adw", "1")
    from gi.repository import Adw

    from klyrshift.gui.home_page import HomePage

    page = HomePage(gui_state, Adw.ToastOverlay())
    page._on_undo_clicked(None)
    assert calls == ["undo"]


def test_mode_switcher_persists(gui_state: Any, monkeypatch: pytest.MonkeyPatch) -> None:
    saved: list[str] = []
    monkeypatch.setattr(gui_state, "save", lambda: saved.append(gui_state.config.mode))

    from klyrshift.gui.widgets.mode_switcher import ModeSwitcher

    switcher = ModeSwitcher(on_change=gui_state.set_mode)
    switcher.set_mode("hybrid", notify=True)
    assert gui_state.config.mode == "hybrid"
    assert saved == ["hybrid"]


def test_set_mode_signals_running_daemon(gui_state: Any, monkeypatch: pytest.MonkeyPatch) -> None:
    """Switching mode in the GUI must reach a running daemon, not just the file."""
    from klyrshift.gui import state as state_module

    reloads: list[bool] = []
    monkeypatch.setattr(state_module, "daemon_is_running", lambda: True)
    monkeypatch.setattr(state_module, "daemon_reload_config", lambda: reloads.append(True) or True)

    gui_state.set_mode("hybrid")
    assert gui_state.config.mode == "hybrid"
    assert reloads == [True]


def test_set_mode_does_not_signal_when_daemon_stopped(
    gui_state: Any, monkeypatch: pytest.MonkeyPatch
) -> None:
    from klyrshift.gui import state as state_module

    reloads: list[bool] = []
    monkeypatch.setattr(state_module, "daemon_is_running", lambda: False)
    monkeypatch.setattr(state_module, "daemon_reload_config", lambda: reloads.append(True) or True)

    gui_state.set_mode("manual")
    assert gui_state.config.mode == "manual"
    assert reloads == []


def test_autostart_switch_enables_and_disables(
    gui_state: Any, monkeypatch: pytest.MonkeyPatch
) -> None:
    from klyrshift.gui import state as state_module

    enabled = {"value": False}
    calls: list[bool] = []
    monkeypatch.setattr(state_module, "daemon_autostart_enabled", lambda: enabled["value"])
    monkeypatch.setattr(
        state_module,
        "daemon_enable_autostart",
        lambda: calls.append(True) or True,
    )
    monkeypatch.setattr(
        state_module,
        "daemon_disable_autostart",
        lambda: calls.append(False) or True,
    )
    monkeypatch.setattr(state_module, "subprocess", _NoLayout())

    import gi

    gi.require_version("Adw", "1")
    from gi.repository import Adw

    from klyrshift.gui.home_page import HomePage

    page = HomePage(gui_state, Adw.ToastOverlay())
    page.autostart_row.set_active(True)
    assert calls == [True]
    enabled["value"] = True
    page.autostart_row.set_active(False)
    assert calls == [True, False]


def test_hotkey_row_validation(gui_state: Any) -> None:
    from klyrshift.gui.widgets.hotkey_row import HotkeyRow

    changes: list[str] = []
    row = HotkeyRow("Исправить", value="PAUSE", on_change=changes.append)
    row._start_recording(None)
    # ENTER must be rejected (forbidden key): nothing is recorded.
    assert row._on_key_pressed(None, 0xFF0D, 0, 0) is True
    assert row.value == "PAUSE"
    assert changes == []


def test_hotkey_row_records_and_clears(gui_state: Any) -> None:
    import gi

    gi.require_version("Gdk", "4.0")
    from gi.repository import Gdk

    from klyrshift.gui.widgets.hotkey_row import HotkeyRow

    changes: list[str] = []
    row = HotkeyRow("Исправить", value="PAUSE", on_change=changes.append)

    row._start_recording(None)
    keyval = Gdk.unicode_to_keyval(ord("r"))
    state = int(Gdk.ModifierType.CONTROL_MASK) | int(Gdk.ModifierType.SHIFT_MASK)
    assert row._on_key_pressed(None, keyval, 0, state) is True
    assert row.value == "CTRL+SHIFT+R"
    assert changes == ["CTRL+SHIFT+R"]

    # Backspace clears the binding.
    row._start_recording(None)
    backspace = Gdk.KEY_BackSpace
    assert row._on_key_pressed(None, backspace, 0, 0) is True
    assert row.value == ""
    assert changes == ["CTRL+SHIFT+R", ""]


def test_keyval_to_hotkey_rejects_modifier_only() -> None:
    import gi

    gi.require_version("Gdk", "4.0")
    from gi.repository import Gdk

    from klyrshift.gui.widgets.hotkey_row import keyval_to_hotkey

    assert keyval_to_hotkey(Gdk.KEY_Control_L, 0) is None


def test_app_exceptions_list_add_remove(gui_state: Any) -> None:
    from klyrshift.gui.widgets.app_exceptions_list import AppExceptionsList

    changes: list[list[str]] = []
    widget = AppExceptionsList("Исключения", apps=["code"], on_change=changes.append)
    assert widget.apps == ["code"]

    class _Entry:
        def __init__(self, text: str) -> None:
            self._text = text

        def get_text(self) -> str:
            return self._text

        def set_text(self, text: str) -> None:
            self._text = text

    widget._on_add(None, _Entry("gnome-terminal"))
    assert widget.apps == ["code", "gnome-terminal"]
    assert changes[-1] == ["code", "gnome-terminal"]

    # Duplicates are ignored.
    widget._on_add(None, _Entry("code"))
    assert widget.apps == ["code", "gnome-terminal"]

    widget._on_remove(None, "code")
    assert widget.apps == ["gnome-terminal"]


def test_dictionary_list_add_remove_search(gui_state: Any) -> None:
    from klyrshift.gui.widgets.dictionary_list import DictionaryList

    changes: list[list[str]] = []
    widget = DictionaryList("Словарь", words=["vercel"], on_change=changes.append)
    assert widget.words == ["vercel"]

    class _Entry:
        def __init__(self, text: str) -> None:
            self._text = text

        def get_text(self) -> str:
            return self._text

        def set_text(self, text: str) -> None:
            self._text = text

    widget._on_add(None, _Entry("муксуд"))
    assert widget.words == ["vercel", "муксуд"]
    assert changes[-1] == ["vercel", "муксуд"]

    # Duplicates (case-insensitive) are ignored.
    widget._on_add(None, _Entry("Vercel"))
    assert widget.words == ["vercel", "муксуд"]

    widget._on_remove(None, "vercel")
    assert widget.words == ["муксуд"]


def test_dictionary_list_import_export(tmp_path: Path, gui_state: Any) -> None:
    from klyrshift.gui.widgets.dictionary_list import DictionaryList

    widget = DictionaryList("Словарь", words=["vercel"])
    source = tmp_path / "in.txt"
    source.write_text("# comment\nghbdtn\n\nvercel\n", encoding="utf-8")
    assert widget.import_words(str(source)) == 1
    assert widget.words == ["vercel", "ghbdtn"]

    target = tmp_path / "out.txt"
    assert widget.export_words(str(target)) is True
    assert target.read_text(encoding="utf-8") == "vercel\nghbdtn\n"


def test_dictionary_page_persists_words(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    import gi

    gi.require_version("Adw", "1")

    from klyrshift.config import Config
    from klyrshift.gui.dictionary_page import DictionaryPage
    from klyrshift.gui.state import GuiState

    config = Config(dictionary_custom_path=str(tmp_path / "dictionary.txt"))
    state = GuiState(config=config)
    saved: list[str] = []
    page = DictionaryPage(state, on_saved=saved.append)

    assert page.dictionary.add_word("vercel") is True
    assert (tmp_path / "dictionary.txt").read_text(encoding="utf-8") == "vercel\n"

    # The apply button asks the daemon to reload its configuration.
    monkeypatch.setattr(state, "reload_config", lambda: True)
    page._on_apply(None)
    assert saved == ["Словарь применён"]


def test_hotkey_row_records_double_tap_modifier(gui_state: Any) -> None:
    import gi

    gi.require_version("Gdk", "4.0")
    from gi.repository import Gdk

    from klyrshift.gui.widgets.hotkey_row import HotkeyRow

    changes: list[str] = []
    row = HotkeyRow("Исправить", value="", on_change=changes.append)
    row._start_recording(None)
    # First Shift press waits for a second tap.
    assert row._on_key_pressed(None, Gdk.KEY_Shift_L, 0, 0) is True
    assert row.value == ""
    assert changes == []
    # Second Shift within the window records SHIFT+SHIFT.
    assert row._on_key_pressed(None, Gdk.KEY_Shift_L, 0, 0) is True
    assert row.value == "SHIFT+SHIFT"
    assert changes == ["SHIFT+SHIFT"]


def test_status_summary_uses_metadata_only(gui_state: Any, monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(gui_state, "current_layout", lambda: "us")
    gui_state.config.mode = "manual"
    assert gui_state.status_summary() == "Раскладка: us · Режим: Ручной"


def test_seconds_since_last_fix(gui_state: Any) -> None:
    assert gui_state.seconds_since_last_fix() is None
    gui_state.last_fix_at = 0.0
    assert isinstance(gui_state.seconds_since_last_fix(), int)


class _NoLayout:
    """Stand-in for ``subprocess`` so layout probes never touch the system."""

    class CompletedProcess:  # pragma: no cover - trivial
        returncode = 1
        stdout = ""

    @staticmethod
    def run(*_args: Any, **_kwargs: Any) -> Any:
        return _NoLayout.CompletedProcess()


def test_status_row_renders_all_branches() -> None:
    from klyrshift.gui.widgets.status_row import StatusRow

    row = StatusRow()
    row.update(layout="us", backend="uinput", mode="Авто", seconds_since_fix=None)
    row.update(layout="ru", backend="", mode="", seconds_since_fix=3)
    assert True


def test_mode_switcher_click_notifies(gui_state: Any) -> None:
    from klyrshift.gui.widgets.mode_switcher import ModeSwitcher

    seen: list[str] = []
    switcher = ModeSwitcher(on_change=seen.append)
    switcher._buttons["manual"].set_active(True)
    assert seen == ["manual"]
    switcher._buttons["manual"].set_active(True)
    assert seen == ["manual"]
    switcher.set_mode("nonsense", notify=True)
    assert switcher.mode == "manual"


def test_big_toggle_states_and_poller() -> None:
    from klyrshift.gui.widgets.big_toggle import (
        STATE_BUSY,
        STATE_OFF,
        STATE_ON,
        BigToggle,
        BusyPoller,
    )

    clicks: list[int] = []
    toggle = BigToggle(on_toggle=lambda: clicks.append(1))
    toggle.set_state(STATE_ON, "ru")
    toggle.set_state(STATE_BUSY)
    toggle.set_state(STATE_OFF)
    toggle._on_clicked(None)
    assert clicks == [1]
    toggle.set_busy()
    assert toggle.state == STATE_BUSY
    toggle._on_clicked(None)
    assert clicks == [1]

    ready: list[bool] = []
    poller = BusyPoller(lambda: True, lambda: ready.append(True), attempts=1)
    assert poller._tick() is False
    assert ready == [True]
    ready2: list[bool] = []
    poller2 = BusyPoller(lambda: False, lambda: ready2.append(True), attempts=0)
    assert poller2._tick() is False
    assert ready2 == [True]


def test_app_exceptions_set_apps_and_detect(gui_state: Any) -> None:
    from klyrshift.gui.widgets.app_exceptions_list import AppExceptionsList

    widget = AppExceptionsList("Исключения", apps=["code"], on_detect=lambda: "firefox")
    widget.set_apps(["vim", "nano"])
    assert widget.apps == ["vim", "nano"]

    class _Entry:
        def __init__(self) -> None:
            self.text = ""

        def get_text(self) -> str:
            return self.text

        def set_text(self, value: str) -> None:
            self.text = value

    entry = _Entry()
    widget._on_detect_clicked(None, entry)
    assert entry.get_text() == "firefox"


def test_app_exceptions_add_empty_is_ignored(gui_state: Any) -> None:
    from klyrshift.gui.widgets.app_exceptions_list import AppExceptionsList

    widget = AppExceptionsList("Исключения")

    class _Entry:
        def get_text(self) -> str:
            return "   "

        def set_text(self, _value: str) -> None:
            pass

    widget._on_add(None, _Entry())
    assert widget.apps == []


def test_settings_page_bindings(gui_state: Any, monkeypatch: pytest.MonkeyPatch) -> None:
    saved: list[str] = []
    monkeypatch.setattr(gui_state, "save", lambda: saved.append("save"))

    from klyrshift.gui.settings_page import SettingsPage

    page = SettingsPage(gui_state, on_saved=saved.append)
    page._on_mode_selected("hybrid")
    assert gui_state.config.mode == "hybrid"
    page._make_hotkey_handler("hotkey_fix_last_word")("CTRL+Q")
    assert gui_state.config.hotkey_fix_last_word == "CTRL+Q"
    # The toggle-layout row is wired to its own config field.
    assert page._hotkey_toggle_layout is not None
    page._make_hotkey_handler("hotkey_toggle_layout_last_word")("CTRL+ALT+T")
    assert gui_state.config.hotkey_toggle_layout_last_word == "CTRL+ALT+T"


def test_settings_page_language_toggle(gui_state: Any, monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(gui_state, "save", lambda: None)

    from klyrshift.gui.settings_page import SettingsPage

    page = SettingsPage(gui_state, on_saved=lambda _m: None)
    row = page.language_rows["ru"]
    row.set_active(not row.get_active())
    gui_state.config.validate()
    assert isinstance(gui_state.config.languages, list)


def test_advanced_page_handlers(gui_state: Any, monkeypatch: pytest.MonkeyPatch) -> None:
    saved: list[str] = []
    monkeypatch.setattr(gui_state, "save", lambda: saved.append("save"))

    from klyrshift.gui.advanced_page import AdvancedPage

    page = AdvancedPage(gui_state, on_saved=saved.append)
    page._on_exceptions_changed(["code", "gnome-terminal"])
    assert gui_state.config.exceptions_apps == ["code", "gnome-terminal"]
    page._on_force_manual_changed(["kitty"])
    assert gui_state.config.exceptions_force_in_manual == ["kitty"]
    page._on_dictionary_size("10000")
    assert gui_state.config.dictionary_size == 10000
    page._on_log_level("DEBUG")
    assert gui_state.config.log_level == "DEBUG"
    page._make_hotkey_handler("hotkey_toggle_mode")("CTRL+M")
    assert gui_state.config.hotkey_toggle_mode == "CTRL+M"
    page._on_reset_hotkeys(None)
    assert gui_state.config.hotkey_reload_config == "CTRL+SHIFT+R"
    assert gui_state.config.hotkey_toggle_layout_last_word == "CTRL+SHIFT+T"


def test_advanced_page_typo_group_reflects_config(
    gui_state: Any, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setattr(gui_state, "save", lambda: None)
    from klyrshift.gui.advanced_page import AdvancedPage

    gui_state.config.typo_correction = True
    gui_state.config.typo_max_distance = 2
    page = AdvancedPage(gui_state)

    assert page._typo_switch.get_active() is True
    # Toggling the row writes through to the config and saves.
    page._typo_switch.set_active(False)
    assert gui_state.config.typo_correction is False


def test_advanced_page_expander_group_reflects_config(
    gui_state: Any, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setattr(gui_state, "save", lambda: None)
    from klyrshift.gui.advanced_page import AdvancedPage

    gui_state.config.text_expander_enabled = True
    gui_state.config.selection_fix_enabled = False
    gui_state.config.selection_fix_hotkey = "CTRL+ALT+L"
    page = AdvancedPage(gui_state)

    # The selection-fix hotkey row reflects the configured binding.
    page._make_hotkey_handler("selection_fix_hotkey")("CTRL+SHIFT+L")
    assert gui_state.config.selection_fix_hotkey == "CTRL+SHIFT+L"


def test_advanced_page_learning_group_reflects_config(
    gui_state: Any, monkeypatch: pytest.MonkeyPatch
) -> None:
    """The learning group is on by default and toggles write through."""
    monkeypatch.setattr(gui_state, "save", lambda: None)
    from klyrshift.gui.advanced_page import AdvancedPage

    page = AdvancedPage(gui_state)
    assert gui_state.config.learning_enabled is True
    assert page._learning_switch.get_active() is True
    page._learning_switch.set_active(False)
    assert gui_state.config.learning_enabled is False


def test_app_layout_map_add_remove(gui_state: Any) -> None:
    from klyrshift.gui.widgets.app_layout_map import AppLayoutMap

    changes: list[dict[str, str]] = []
    widget = AppLayoutMap("Раскладка", mapping={"code": "us"}, on_change=changes.append)
    assert widget.mapping == {"code": "us"}

    class _Entry:
        def __init__(self, text: str) -> None:
            self._text = text

        def get_text(self) -> str:
            return self._text

        def set_text(self, text: str) -> None:
            self._text = text

    widget._app_entry = _Entry("kitty")
    widget._layout_entry = _Entry("RU")
    widget._on_add(None)
    assert widget.mapping == {"code": "us", "kitty": "ru"}
    assert changes[-1] == {"code": "us", "kitty": "ru"}

    # Missing app or layout is ignored.
    widget._app_entry = _Entry("")
    widget._layout_entry = _Entry("de")
    widget._on_add(None)
    assert widget.mapping == {"code": "us", "kitty": "ru"}

    widget._on_remove(None, "code")
    assert widget.mapping == {"kitty": "ru"}


def test_app_layout_map_detect(gui_state: Any) -> None:
    from klyrshift.gui.widgets.app_layout_map import AppLayoutMap

    widget = AppLayoutMap("Раскладка", on_detect=lambda: "firefox")
    widget._on_detect_clicked(None)
    assert widget._app_entry.get_text() == "firefox"

    no_detect = AppLayoutMap("Раскладка")
    no_detect._on_detect_clicked(None)  # no crash without a probe


def test_advanced_page_app_layouts_changed(gui_state: Any, monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(gui_state, "save", lambda: None)
    from klyrshift.gui.advanced_page import AdvancedPage

    page = AdvancedPage(gui_state)
    page._on_app_layouts_changed({"kitty": "ru"})
    assert gui_state.config.app_layouts == {"kitty": "ru"}


def test_backup_group_export_import(gui_state: Any) -> None:
    from klyrshift.gui.widgets.backup_group import BackupGroup

    exported: list[str] = []
    imported: list[str] = []
    notes: list[str] = []
    widget = BackupGroup(
        on_export=lambda p: exported.append(p) or True,
        on_import=lambda p: imported.append(p) or True,
        on_notify=notes.append,
    )

    class _File:
        def get_path(self) -> str:
            return "/tmp/x.json"

    class _Dialog:
        def save_finish(self, _result: object) -> _File:
            return _File()

        def open_finish(self, _result: object) -> _File:
            return _File()

    widget._on_export_done(_Dialog(), None)
    assert exported == ["/tmp/x.json"]
    assert notes[-1] == "Настройки сохранены"

    widget._on_import_done(_Dialog(), None)
    assert imported == ["/tmp/x.json"]
    assert notes[-1] == "Настройки восстановлены"


def test_backup_group_cancel_is_silent(gui_state: Any) -> None:
    from klyrshift.gui.widgets.backup_group import BackupGroup

    notes: list[str] = []
    widget = BackupGroup(
        on_export=lambda _p: True,
        on_import=lambda _p: True,
        on_notify=notes.append,
    )

    class _Dialog:
        def save_finish(self, _result: object) -> None:
            raise RuntimeError("cancelled")

    widget._on_export_done(_Dialog(), None)
    assert notes == []


def test_advanced_page_settings_roundtrip(
    gui_state: Any, tmp_path: Any, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setattr(gui_state, "save", lambda: None)
    from klyrshift.gui.advanced_page import AdvancedPage

    page = AdvancedPage(gui_state)
    out = tmp_path / "backup.json"
    assert page._export_settings(str(out)) is True
    assert page._import_settings(str(out)) is True
    assert page._import_settings(str(tmp_path / "missing.json")) is False


def test_advanced_page_regex_validation(gui_state: Any, monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(gui_state, "save", lambda: None)
    from klyrshift.gui.advanced_page import AdvancedPage

    page = AdvancedPage(gui_state)
    assert page._validate_regex("") is True
    assert page._validate_regex("^[a-z]+$") is True
    assert page._validate_regex("(") is False


def test_window_menu_actions(gui_state: Any) -> None:
    import gi

    gi.require_version("Adw", "1")
    from gi.repository import Adw

    from klyrshift.gui.window import KlyrshiftWindow

    app = Adw.Application(application_id="io.github.pavel1778.KlyrshiftTest2")
    window = KlyrshiftWindow(gui_state, app)
    window._on_open_config(None, None)
    window._on_saved("ok")
    window._on_show_advanced(None, None)
    window._on_show_advanced(None, None)
    names = {page.get_name() for page in window.stack.get_pages()}
    assert names == {
        "home",
        "settings",
        "dictionary",
        "typo",
        "history",
        "advanced",
        "help",
    }
    assert window.stack.get_visible_child_name() == "advanced"
    # The help page is reachable from the menu and from the tour's action.
    window._on_show_help(None, None)
    assert window.help_page.get_visible() is True
    assert window.stack.get_visible_child_name() == "help"


def test_window_resizes_without_breaking(gui_state: Any) -> None:
    """The window must survive resize and tab switches at several widths."""
    import gi

    gi.require_version("Adw", "1")
    from gi.repository import Adw

    from klyrshift.gui.window import KlyrshiftWindow

    app = Adw.Application(application_id="io.github.pavel1778.KlyrshiftTestResize")
    window = KlyrshiftWindow(gui_state, app)
    # Width is homogeneous; height follows the visible page so the window can
    # shrink instead of being pinned to the tallest page.
    assert window.stack.get_hhomogeneous() is True
    assert window.stack.get_vhomogeneous() is False
    for width, height in ((600, 720), (800, 760), (1200, 900)):
        window.set_default_size(width, height)
        for page in window.stack.get_pages():
            window.stack.set_visible_child_name(page.get_name())
    # The loop leaves the last page in the stack visible; every page survived the
    # resizes, including the help page added for onboarding.
    assert window.stack.get_visible_child_name() == "help"
    window.stack.set_visible_child_name("advanced")
    assert window.stack.get_visible_child_name() == "advanced"


def test_about_window_builds() -> None:
    import gi

    gi.require_version("Adw", "1")
    from gi.repository import Adw

    from klyrshift.gui.about_page import build_about_window

    Adw.Application(application_id="io.github.pavel1778.KlyrshiftTest3")
    dialog = build_about_window()
    assert dialog.get_application_name() == "Klyrshift"


def test_gui_module_availability() -> None:
    from klyrshift.gui import cairo_available, gtk_available

    assert gtk_available() is True
    assert cairo_available() is True


def test_gui_main_runs_and_quits(monkeypatch: pytest.MonkeyPatch) -> None:
    from klyrshift.gui import app as app_module, main

    class _App:
        def run(self, _argv: list[str]) -> int:
            return 0

    monkeypatch.setattr(app_module, "KlyrshiftApplication", _App)
    assert main([]) == 0


def test_gui_main_refuses_to_start_without_cairo(
    monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
) -> None:
    """A missing Cairo override must name the fix instead of opening a blank window.

    Without ``_gi_cairo`` the window opens but every ``set_draw_func`` callback
    raises, so the tour never dims and the toggle shows no glyph; the user gets no
    hint at all. ``main`` must stop with the exact ``apt`` command.
    """
    from klyrshift import gui as gui_module

    monkeypatch.setattr(gui_module, "gtk_available", lambda: True)
    monkeypatch.setattr(gui_module, "cairo_available", lambda: False)
    assert gui_module.main([]) == 1
    assert "python3-gi-cairo" in capsys.readouterr().out


# --- history page -----------------------------------------------------------


def test_history_page_formats_metadata_rows(
    gui_state: Any, monkeypatch: pytest.MonkeyPatch
) -> None:
    import time

    monkeypatch.setattr(
        gui_state,
        "read_history",
        lambda: [
            {
                "id": 2,
                "at": time.time() - 5,
                "length": 6,
                "source": "us",
                "target": "ru",
                "undone": False,
            },
            {
                "id": 1,
                "at": time.time() - 90,
                "length": 9,
                "source": "ru",
                "target": "us",
                "undone": True,
            },
        ],
    )
    from klyrshift.gui.history_page import HistoryPage

    class _Toasts:
        def add_toast(self, _t: object) -> None:
            pass

    page = HistoryPage(gui_state, _Toasts())
    assert page is not None


def test_history_page_undo_asks_daemon(gui_state: Any, monkeypatch: pytest.MonkeyPatch) -> None:
    import time

    calls: list[str] = []
    monkeypatch.setattr(
        gui_state, "undo_last_fix", lambda entry_id=None: calls.append("undo") or True
    )
    monkeypatch.setattr(
        gui_state,
        "read_history",
        lambda: [
            {
                "id": 7,
                "at": time.time(),
                "length": 6,
                "source": "us",
                "target": "ru",
                "undone": False,
            }
        ],
    )
    from klyrshift.gui.history_page import HistoryPage

    class _Toasts:
        def add_toast(self, _t: object) -> None:
            pass

    page = HistoryPage(gui_state, _Toasts())
    page._on_undo_clicked(None, 7)
    assert calls == ["undo"]


def test_history_page_does_not_poll_while_hidden(
    gui_state: Any, monkeypatch: pytest.MonkeyPatch
) -> None:
    """A hidden History tab must not signal the daemon every tick.

    ``read_history`` sends ``SIGUSR2`` to the daemon; an unattended 2 s poll from
    a background tab spammed the daemon's log, so the poll is paused unless the
    page is mapped.
    """
    calls: list[int] = []
    monkeypatch.setattr(gui_state, "read_history", lambda: calls.append(1) or [])
    from klyrshift.gui.history_page import HistoryPage

    class _Toasts:
        def add_toast(self, _t: object) -> None:
            pass

    page = HistoryPage(gui_state, _Toasts())
    baseline = len(calls)
    page._tick()
    assert len(calls) == baseline


def test_home_page_quiet_hours_indicator(gui_state: Any, monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(gui_state, "in_quiet_hours", lambda: True)
    from klyrshift.gui.home_page import HomePage

    class _Toasts:
        def add_toast(self, _t: object) -> None:
            pass

    monkeypatch.setattr(app_focus, "get_active_app", lambda: None)
    page = HomePage(gui_state, _Toasts())
    page._apply_status(page._collect_status())
    assert page._pause.get_visible() is True
    assert "тихие часы" in page._pause.get_label()


def test_home_page_pause_indicator_only_for_excepted_app(
    gui_state: Any, monkeypatch: pytest.MonkeyPatch
) -> None:
    """The banner names an app only when that app is on the never-touch list.

    A focused app that is *not* excepted still gets corrected by the daemon, so
    reporting it as "paused" would be a false alarm the user cannot act on.
    """
    from klyrshift.gui.home_page import HomePage

    class _Toasts:
        def add_toast(self, _t: object) -> None:
            pass

    monkeypatch.setattr(gui_state, "in_quiet_hours", lambda: False)
    monkeypatch.setattr(app_focus, "get_active_app", lambda: "some-editor")
    page = HomePage(gui_state, _Toasts())
    page._apply_status(page._collect_status())
    assert page._pause.get_visible() is False
    assert page._pause.get_label() == ""

    monkeypatch.setattr(gui_state, "is_app_excepted", lambda app: app == "some-editor")
    page._apply_status(page._collect_status())
    assert page._pause.get_visible() is True
    assert "some-editor" in page._pause.get_label()


def test_gui_state_in_quiet_hours() -> None:
    from klyrshift.config import Config
    from klyrshift.gui.state import GuiState

    config = Config(quiet_hours_enabled=True, quiet_hours_start="00:00", quiet_hours_end="23:59")
    state = GuiState(config=config)
    assert state.in_quiet_hours() is True


def test_typo_page_master_toggle(gui_state: Any, monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(gui_state, "save", lambda: None)
    monkeypatch.setattr(gui_state, "reload_config", lambda: True)
    from klyrshift.gui.typo_page import TypoPage
    from klyrshift.gui.widgets.big_toggle import STATE_OFF, STATE_ON

    class _Toasts:
        def add_toast(self, _t: object) -> None:
            pass

    page = TypoPage(gui_state, _Toasts())
    assert page.toggle.state == STATE_OFF
    page._on_toggle_clicked()
    assert gui_state.config.typo_correction is True
    assert gui_state.config.punctuation_correction is True
    assert page.toggle.state == STATE_ON
    page._on_toggle_clicked()
    assert gui_state.config.typo_correction is False
    assert gui_state.config.punctuation_correction is False
    assert page.toggle.state == STATE_OFF


def test_typo_page_reset_restores_defaults(gui_state: Any, monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(gui_state, "save", lambda: None)
    from klyrshift.gui.typo_page import TypoPage

    class _Toasts:
        def add_toast(self, _t: object) -> None:
            pass

    gui_state.config.typo_correction = True
    gui_state.config.typo_max_distance = 2
    gui_state.config.punctuation_smart_quotes = True
    page = TypoPage(gui_state, _Toasts())
    page._on_reset(None)
    assert gui_state.config.typo_correction is False
    assert gui_state.config.typo_max_distance == 1
    assert gui_state.config.punctuation_smart_quotes is False
    assert gui_state.config.punctuation_dashes is True


def test_typo_page_punctuation_switch_persists(
    gui_state: Any, monkeypatch: pytest.MonkeyPatch
) -> None:
    saved: list[str] = []
    monkeypatch.setattr(gui_state, "save", lambda: saved.append("save"))
    from klyrshift.gui.typo_page import TypoPage

    class _Toasts:
        def add_toast(self, _t: object) -> None:
            pass

    page = TypoPage(gui_state, _Toasts())
    page._dashes_switch.set_active(not page._dashes_switch.get_active())
    assert gui_state.config.punctuation_dashes is False
    assert saved == ["save"]


def test_typo_page_mode_combo_sets_independent_mode(
    gui_state: Any, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setattr(gui_state, "save", lambda: None)
    from klyrshift.gui.typo_page import TypoPage

    class _Toasts:
        def add_toast(self, _t: object) -> None:
            pass

    page = TypoPage(gui_state, _Toasts())
    page.typo_mode_combo.set_selected(2)  # auto
    assert gui_state.config.typo_mode == "auto"
    assert gui_state.config.typo_correction is True
    # The punctuation mode is untouched by the T9 combo.
    assert gui_state.config.punctuation_mode == "off"
    page.typo_mode_combo.set_selected(0)  # off
    assert gui_state.config.typo_mode == "off"
    assert gui_state.config.typo_correction is False


def test_typo_page_switch_enables_auto_mode(
    gui_state: Any, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setattr(gui_state, "save", lambda: None)
    from klyrshift.gui.typo_page import TypoPage

    class _Toasts:
        def add_toast(self, _t: object) -> None:
            pass

    page = TypoPage(gui_state, _Toasts())
    assert gui_state.config.typo_mode == "off"
    page._typo_switch.set_active(True)
    assert gui_state.config.typo_correction is True
    assert gui_state.config.typo_mode == "auto"
    page._typo_switch.set_active(False)
    assert gui_state.config.typo_mode == "off"


def test_typo_page_hotkey_rows_persist(gui_state: Any, monkeypatch: pytest.MonkeyPatch) -> None:
    """The T9 and punctuation hotkey rows write their fields and save."""
    saved: list[str] = []
    monkeypatch.setattr(gui_state, "save", lambda: saved.append("save"))
    from klyrshift.gui.typo_page import TypoPage

    class _Toasts:
        def add_toast(self, _t: object) -> None:
            pass

    page = TypoPage(gui_state, _Toasts())
    assert page.typo_hotkey_row.value == gui_state.config.typo_hotkey
    page.typo_hotkey_row._apply("CTRL+SHIFT+9")
    assert gui_state.config.typo_hotkey == "CTRL+SHIFT+9"
    page.punctuation_hotkey_row._apply("")
    assert gui_state.config.punctuation_hotkey == ""
    assert saved == ["save", "save"]


def test_typo_page_reset_restores_hotkeys(gui_state: Any, monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(gui_state, "save", lambda: None)
    from klyrshift.config import DEFAULT_PUNCTUATION_HOTKEY, DEFAULT_TYPO_HOTKEY
    from klyrshift.gui.typo_page import TypoPage

    class _Toasts:
        def add_toast(self, _t: object) -> None:
            pass

    gui_state.config.typo_hotkey = ""
    gui_state.config.punctuation_hotkey = ""
    page = TypoPage(gui_state, _Toasts())
    page._on_reset(None)
    assert gui_state.config.typo_hotkey == DEFAULT_TYPO_HOTKEY
    assert gui_state.config.punctuation_hotkey == DEFAULT_PUNCTUATION_HOTKEY
    assert page.typo_hotkey_row.value == DEFAULT_TYPO_HOTKEY


def test_desktop_entry_matches_app_id() -> None:
    """The launcher must declare the same app-id the GUI runs under.

    GNOME matches a running window to its launcher by ``StartupWMClass``; if it
    does not equal the ``Gtk.Application`` id, the window shows a generic icon
    and cannot be pinned or grouped with the installed entry.
    """
    from pathlib import Path

    from klyrshift.gui.app import APP_ID

    root = Path(__file__).resolve().parents[1]
    entry = (root / "data" / "klyrshift.desktop").read_text(encoding="utf-8")
    assert f"StartupWMClass={APP_ID}\n" in entry


def test_toggle_failure_shows_reason(gui_state: Any, monkeypatch: pytest.MonkeyPatch) -> None:
    """A failed start must surface the real reason, not a bare "не удалось"."""
    toasts: list[str] = []

    class _Toasts:
        def add_toast(self, toast: object) -> None:
            toasts.append(toast.get_title())

    monkeypatch.setattr(app_focus, "get_active_app", lambda: None)
    monkeypatch.setattr(gui_state, "is_active", lambda: False)
    monkeypatch.setattr(gui_state, "current_layout", lambda: "")
    monkeypatch.setattr(gui_state, "is_autostart_enabled", lambda: False)
    monkeypatch.setattr(gui_state, "start", lambda: False)
    monkeypatch.setattr(
        gui_state, "last_error", lambda: "сервис не стал активным (проверьте journalctl)"
    )

    from klyrshift.gui.home_page import HomePage

    page = HomePage(gui_state, _Toasts())
    page._on_toggle_done(False)
    assert toasts
    assert "journalctl" in toasts[-1]


def test_toggle_reconcile_window_outlasts_start_timeout() -> None:
    """The reconcile loop must run longer than a worst-case ``start()``."""
    from klyrshift.daemon_control import START_TIMEOUT
    from klyrshift.gui import home_page

    window = (home_page.RECONCILE_MS / 1000.0) * home_page.RECONCILE_ATTEMPTS
    # start() can spend START_TIMEOUT on systemd plus START_TIMEOUT on the
    # detached fallback before giving up; the button must stay busy until then.
    assert window >= 2 * START_TIMEOUT


def test_service_unit_has_no_user_hostile_scheduling() -> None:
    """A user unit must not request nice/RT scheduling it cannot obtain.

    systemd treats a failed ``Nice=``/``CPUSchedulingPolicy=`` as fatal for a
    user service (no CAP_SYS_NICE), so the unit never starts and the daemon
    loops on restart -- exactly the "button flips back to OFF" bug.
    """
    from pathlib import Path

    root = Path(__file__).resolve().parents[1]
    unit = (root / "data" / "klyrshift.service").read_text(encoding="utf-8")
    active = [line for line in unit.splitlines() if not line.lstrip().startswith("#")]
    joined = "\n".join(active)
    assert "Nice=" not in joined
    assert "CPUSchedulingPolicy=" not in joined
    assert "CPUSchedulingPriority=" not in joined


def test_languages_group_reflects_status(gui_state: Any) -> None:
    from klyrshift.gui.widgets.languages_group import LanguagesGroup
    from klyrshift.langstore import LanguageStatus

    toggles: list[tuple[str, bool]] = []
    installs: list[str] = []
    removes: list[str] = []
    group = LanguagesGroup(
        [
            LanguageStatus("ru", "Русский", enabled=True, installed=True, word_count=42),
            LanguageStatus("de", "Deutsch", enabled=False, installed=False, word_count=0),
        ],
        on_toggle=lambda lang, active: toggles.append((lang, active)),
        on_install=installs.append,
        on_remove=removes.append,
    )

    ru = group.rows["ru"]
    assert ru.get_subtitle() == "Включён · Установлен · слов: 42"
    # An installed language offers removal, not installation.
    assert ru.remove_button.get_visible() is True
    assert ru.install_button.get_visible() is False

    de = group.rows["de"]
    assert de.get_subtitle() == "Выключен · Не установлен"
    assert de.install_button.get_visible() is True
    assert de.remove_button.get_visible() is False

    de.install_button.emit("clicked")
    ru.remove_button.emit("clicked")
    assert installs == ["de"]
    assert removes == ["ru"]

    de.switch.set_active(True)
    assert ("de", True) in toggles


def test_languages_group_busy_state(gui_state: Any) -> None:
    from klyrshift.gui.widgets.languages_group import LanguagesGroup
    from klyrshift.langstore import LanguageStatus

    group = LanguagesGroup(
        [LanguageStatus("de", "Deutsch", enabled=False, installed=False, word_count=0)],
        on_toggle=lambda _l, _a: None,
        on_install=lambda _l: None,
        on_remove=lambda _l: None,
    )
    row = group.rows["de"]
    group.set_busy("de", True)
    assert row.install_button.get_sensitive() is False
    group.set_busy("de", False)
    assert row.install_button.get_sensitive() is True


def test_settings_page_language_install_runs_in_background(
    gui_state: Any, monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    """Install hands the download to a worker and refreshes when it returns."""
    from klyrshift.gui import settings_page as settings_module
    from klyrshift.gui.settings_page import SettingsPage
    from klyrshift.langstore import LanguageStatus

    gui_state.config.extended_dictionary_dir = str(tmp_path / "dicts")
    monkeypatch.setattr(gui_state, "save", lambda: None)

    captured: dict[str, Any] = {}

    def fake_background(fn: Any, on_done: Any, *args: Any, **kwargs: Any) -> None:
        captured["fn"] = fn
        captured["args"] = args
        on_done("ok")

    monkeypatch.setattr(settings_module, "run_in_background", fake_background)

    def fake_install(config: Any, language: str) -> LanguageStatus:
        return LanguageStatus(language, language, True, True, 7)

    monkeypatch.setattr(settings_module, "install_language", fake_install)

    saved: list[str] = []
    page = SettingsPage(gui_state, on_saved=saved.append)
    page.languages_group.rows["de"].install_button.emit("clicked")

    assert captured["fn"] is fake_install
    assert captured["args"][1] == "de"
    assert any("Deutsch" in message for message in saved)


def test_settings_page_language_remove_refuses_last(
    gui_state: Any, monkeypatch: pytest.MonkeyPatch
) -> None:
    from klyrshift.gui import settings_page as settings_module
    from klyrshift.gui.settings_page import SettingsPage

    monkeypatch.setattr(gui_state, "save", lambda: None)
    gui_state.config.languages = ["ru"]

    def fake_remove(_config: Any, _language: str) -> None:
        raise ValueError("cannot remove the only enabled language")

    monkeypatch.setattr(settings_module, "remove_language", fake_remove)

    saved: list[str] = []
    page = SettingsPage(gui_state, on_saved=saved.append)
    page.languages_group.rows["ru"].remove_button.emit("clicked")
    assert any("единственный" in message for message in saved)


def test_settings_page_language_remove_ok(
    gui_state: Any, monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    from klyrshift.gui import settings_page as settings_module
    from klyrshift.gui.settings_page import SettingsPage

    monkeypatch.setattr(gui_state, "save", lambda: None)
    gui_state.config.languages = ["en", "de"]
    gui_state.config.extended_dictionary_dir = str(tmp_path / "dicts")

    removed: list[str] = []

    def fake_remove(_config: Any, language: str) -> None:
        removed.append(language)

    monkeypatch.setattr(settings_module, "remove_language", fake_remove)

    saved: list[str] = []
    page = SettingsPage(gui_state, on_saved=saved.append)
    page.languages_group.rows["de"].remove_button.emit("clicked")
    assert removed == ["de"]
    assert any("Deutsch" in message for message in saved)


def test_apply_theme_maps_values(gui_state: Any) -> None:
    """``apply_theme`` maps every valid value and falls back on garbage."""
    import gi

    gi.require_version("Adw", "1")
    from gi.repository import Adw

    from klyrshift.gui.theme import apply_theme

    manager = Adw.StyleManager.get_default()
    assert apply_theme("dark") == "dark"
    assert manager.get_color_scheme() == Adw.ColorScheme.FORCE_DARK
    assert apply_theme("light") == "light"
    assert manager.get_color_scheme() == Adw.ColorScheme.FORCE_LIGHT
    assert apply_theme("system") == "system"
    assert manager.get_color_scheme() == Adw.ColorScheme.DEFAULT

    # A hand-edited config must not crash the window.
    assert apply_theme("neon") == "system"
    assert manager.get_color_scheme() == Adw.ColorScheme.DEFAULT


def test_settings_page_theme_combo(gui_state: Any, monkeypatch: pytest.MonkeyPatch) -> None:
    """Selecting a theme updates the config, applies it and saves."""
    from klyrshift.gui import settings_page as settings_module
    from klyrshift.gui.settings_page import THEME_ORDER, SettingsPage

    applied: list[str] = []
    monkeypatch.setattr(settings_module, "apply_theme", applied.append)

    saved: list[str] = []
    page = SettingsPage(gui_state, on_saved=saved.append)
    assert page.theme_row.get_selected() == THEME_ORDER.index("system")

    page.theme_row.set_selected(THEME_ORDER.index("dark"))
    assert gui_state.config.theme == "dark"
    assert applied == ["dark"]
    assert any("Тёмная" in message for message in saved)
