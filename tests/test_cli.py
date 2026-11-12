"""Tests for :mod:`klyrshift.cli`."""

from __future__ import annotations

import argparse
import signal
from pathlib import Path

import pytest

from klyrshift import cli
from klyrshift.config import config_path


@pytest.fixture
def isolated_env(monkeypatch: pytest.MonkeyPatch, tmp_path: Path) -> Path:
    """Redirect XDG directories into a temporary tree."""
    monkeypatch.setenv("XDG_CONFIG_HOME", str(tmp_path / "config"))
    monkeypatch.setenv("XDG_STATE_HOME", str(tmp_path / "state"))
    monkeypatch.setenv("XDG_CACHE_HOME", str(tmp_path / "cache"))
    return tmp_path


def test_build_parser_has_all_commands() -> None:
    parser = cli.build_parser()
    actions = [
        choice for action in parser._actions for choice in getattr(action, "choices", []) or []
    ]
    for command in (
        "start",
        "stop",
        "kill",
        "status",
        "mode",
        "app-mode",
        "undo",
        "learn",
        "hotkeys",
        "dict",
        "config",
        "fix",
        "doctor",
        "collect-logs",
        "install-autostart",
        "uninstall-autostart",
        "version",
        "export",
        "import",
        "restart",
        "verify",
    ):
        assert command in actions


def test_learn_command(isolated_env: Path, capsys: pytest.CaptureFixture[str]) -> None:
    """``klyrshift learn`` reports the setting and the counters, never a word."""
    assert cli.main(["learn"]) == 0
    out = capsys.readouterr().out
    assert "Обучение: включено" in out
    assert "Слов увидено: 0" in out

    assert cli.main(["learn", "--off"]) == 0
    out = capsys.readouterr().out
    assert "Обучение: выключено" in out
    from klyrshift.config import load_config

    assert load_config().learning_enabled is False

    assert cli.main(["learn", "--reset"]) == 0
    assert "Счётчики обучения сброшены" in capsys.readouterr().out


def test_hotkeys_command(isolated_env: Path, capsys: pytest.CaptureFixture[str]) -> None:
    """``klyrshift hotkeys`` prints the effective bindings for a default config."""
    assert cli.main(["hotkeys"]) == 0
    out = capsys.readouterr().out
    assert "SHIFT+SHIFT" in out
    assert "SHIFT+BACKSPACE" in out
    assert "CTRL+SHIFT+T" in out
    assert "CTRL+SHIFT+R" in out
    assert "CTRL+SHIFT+F" in out
    assert "CTRL+SHIFT+P" in out
    assert "2000" in out


def test_version_command(capsys: pytest.CaptureFixture[str]) -> None:
    assert cli.main(["version"]) == 0
    assert "Klyrshift" in capsys.readouterr().out


def test_doctor_command(
    isolated_env: Path, capsys: pytest.CaptureFixture[str], monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setattr(cli, "run_doctor", lambda: 0)
    assert cli.main(["doctor"]) == 0


def test_verify_command(
    isolated_env: Path, capsys: pytest.CaptureFixture[str], monkeypatch: pytest.MonkeyPatch
) -> None:
    """``klyrshift verify`` delegates to the integrity check and passes its code."""
    monkeypatch.setattr("klyrshift.integrity.run_verify", lambda: 0)
    assert cli.main(["verify"]) == 0


def test_verify_command_reports_damage(
    isolated_env: Path, capsys: pytest.CaptureFixture[str], monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setattr("klyrshift.integrity.run_verify", lambda: 1)
    assert cli.main(["verify"]) == 1


def test_collect_logs_command(
    isolated_env: Path, tmp_path: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    assert cli.main(["collect-logs", "--output", str(tmp_path)]) == 0
    out = capsys.readouterr().out
    assert "архив создан" in out
    assert list(tmp_path.glob("klyrshift-logs-*.tar.gz"))


def test_collect_logs_command_failure(
    isolated_env: Path, capsys: pytest.CaptureFixture[str], monkeypatch: pytest.MonkeyPatch
) -> None:
    def boom(*_args: object, **_kwargs: object) -> None:
        raise OSError("disk full")

    monkeypatch.setattr(cli, "collect_logs", boom)
    assert cli.main(["collect-logs"]) == 1
    assert "Не удалось создать архив" in capsys.readouterr().out


def test_status_when_not_running(
    isolated_env: Path, capsys: pytest.CaptureFixture[str], monkeypatch: pytest.MonkeyPatch
) -> None:
    from klyrshift import daemon_control

    monkeypatch.setattr(daemon_control, "is_running", lambda: False)
    monkeypatch.setattr(cli, "_read_pid", lambda: None)
    assert cli.main(["status"]) == 0
    assert "не запущен" in capsys.readouterr().out


def test_status_when_running(
    isolated_env: Path, capsys: pytest.CaptureFixture[str], monkeypatch: pytest.MonkeyPatch
) -> None:
    from klyrshift import daemon_control

    monkeypatch.setattr(daemon_control, "is_running", lambda: True)
    monkeypatch.setattr(cli, "_read_pid", lambda: 4242)
    assert cli.main(["status"]) == 0
    assert "4242" in capsys.readouterr().out


def test_status_agrees_with_is_running_for_a_service_daemon(
    isolated_env: Path, capsys: pytest.CaptureFixture[str], monkeypatch: pytest.MonkeyPatch
) -> None:
    """A service daemon without a lock file is still "running" (systemd active).

    ``status`` must use the same definition as ``stop``; reading only the lock
    file made the two disagree.
    """
    from klyrshift import daemon_control

    monkeypatch.setattr(daemon_control, "is_running", lambda: True)
    monkeypatch.setattr(cli, "_read_pid", lambda: None)
    assert cli.main(["status"]) == 0
    assert "запущен" in capsys.readouterr().out


def test_stop_when_not_running(
    isolated_env: Path, capsys: pytest.CaptureFixture[str], monkeypatch: pytest.MonkeyPatch
) -> None:
    from klyrshift import daemon_control

    monkeypatch.setattr(daemon_control, "is_running", lambda: False)
    assert cli.main(["stop"]) == 0
    assert "уже остановлен" in capsys.readouterr().out


def test_stop_delegates_to_daemon_control(
    isolated_env: Path, capsys: pytest.CaptureFixture[str], monkeypatch: pytest.MonkeyPatch
) -> None:
    """``stop`` must go through ``daemon_control.stop`` (stops the systemd unit)."""
    from klyrshift import daemon_control

    stopped: list[bool] = []
    monkeypatch.setattr(daemon_control, "is_running", lambda: True)
    monkeypatch.setattr(daemon_control, "stop", lambda: stopped.append(True) or True)
    assert cli.main(["stop"]) == 0
    assert stopped == [True]
    assert "остановлен" in capsys.readouterr().out


def test_stop_reports_failure(
    isolated_env: Path, capsys: pytest.CaptureFixture[str], monkeypatch: pytest.MonkeyPatch
) -> None:
    from klyrshift import daemon_control

    monkeypatch.setattr(daemon_control, "is_running", lambda: True)
    monkeypatch.setattr(daemon_control, "stop", lambda: False)
    assert cli.main(["stop"]) == 1
    assert "Не удалось остановить" in capsys.readouterr().out


def test_kill_delegates_to_daemon_control(
    isolated_env: Path, capsys: pytest.CaptureFixture[str], monkeypatch: pytest.MonkeyPatch
) -> None:
    from klyrshift import daemon_control

    killed: list[bool] = []
    monkeypatch.setattr(daemon_control, "is_running", lambda: True)
    monkeypatch.setattr(daemon_control, "kill", lambda: killed.append(True) or True)
    assert cli.main(["kill"]) == 0
    assert killed == [True]
    assert "SIGKILL" in capsys.readouterr().out


def test_kill_when_not_running(
    isolated_env: Path, capsys: pytest.CaptureFixture[str], monkeypatch: pytest.MonkeyPatch
) -> None:
    from klyrshift import daemon_control

    monkeypatch.setattr(daemon_control, "is_running", lambda: False)
    assert cli.main(["kill"]) == 0
    assert "уже остановлен" in capsys.readouterr().out


def test_config_show(isolated_env: Path, capsys: pytest.CaptureFixture[str]) -> None:
    assert cli.main(["config", "show"]) == 0
    output = capsys.readouterr().out
    assert "analysis_timeout" in output


def test_config_reset(isolated_env: Path, capsys: pytest.CaptureFixture[str]) -> None:
    assert cli.main(["config", "reset"]) == 0
    assert "сброшена" in capsys.readouterr().out


def test_config_migrate_dry_run_shows_pending(
    isolated_env: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    path = config_path()
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(
        'hotkey_undo_last_fix = "CTRL+CTRL"\nhotkey_double_tap_ms = 300\n', encoding="utf-8"
    )
    assert cli.main(["config", "migrate", "--dry-run"]) == 0
    out = capsys.readouterr().out
    assert "hotkey_undo_last_fix" in out
    assert "CTRL+CTRL" in out
    # Nothing written by a dry run.
    assert "CTRL+CTRL" in path.read_text(encoding="utf-8")


def test_config_migrate_writes_and_show_reflects(
    isolated_env: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    path = config_path()
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(
        'hotkey_undo_last_fix = "CTRL+CTRL"\nhotkey_double_tap_ms = 300\n', encoding="utf-8"
    )
    assert cli.main(["config", "migrate"]) == 0
    capsys.readouterr()
    assert "CTRL+CTRL" not in path.read_text(encoding="utf-8")
    # show reads the file, so it now shows the migrated value.
    assert cli.main(["config", "show"]) == 0
    assert "SHIFT+BACKSPACE" in capsys.readouterr().out


def test_config_migrate_reports_nothing_to_do(
    isolated_env: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    cli.main(["config", "reset"])
    capsys.readouterr()
    assert cli.main(["config", "migrate"]) == 0
    assert "не требуются" in capsys.readouterr().out


def test_fix_reports_no_change(
    isolated_env: Path, capsys: pytest.CaptureFixture[str], monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setattr(cli.LayoutSwitcher, "get_current_layout", lambda self, force=False: "us")
    assert cli.main(["fix", "--text", "hello"]) == 0
    assert "не требуется" in capsys.readouterr().out


def test_fix_shows_conversion(
    isolated_env: Path, capsys: pytest.CaptureFixture[str], monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setattr(cli.LayoutSwitcher, "get_current_layout", lambda self, force=False: "us")
    assert cli.main(["fix", "--text", "ghbdtn"]) == 0
    assert "привет" in capsys.readouterr().out


def test_fix_apply(
    isolated_env: Path, capsys: pytest.CaptureFixture[str], monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setattr(cli.LayoutSwitcher, "get_current_layout", lambda self, force=False: "us")
    monkeypatch.setattr(cli.LayoutSwitcher, "switch_to", lambda self, layout: True)
    applied: list[tuple[int, str, str]] = []
    monkeypatch.setattr(
        cli.TextInjector,
        "replace_text",
        lambda self, count, new, layout: applied.append((count, new, layout)) or True,
    )
    assert cli.main(["fix", "--text", "ghbdtn", "--apply"]) == 0
    assert applied == [(6, "привет", "ru")]


def test_fix_apply_failure(
    isolated_env: Path, capsys: pytest.CaptureFixture[str], monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setattr(cli.LayoutSwitcher, "get_current_layout", lambda self, force=False: "us")
    monkeypatch.setattr(cli.LayoutSwitcher, "switch_to", lambda self, layout: True)
    monkeypatch.setattr(cli.TextInjector, "replace_text", lambda self, o, n, layout: False)
    assert cli.main(["fix", "--text", "ghbdtn", "--apply"]) == 1


def test_fix_empty_text(
    isolated_env: Path, capsys: pytest.CaptureFixture[str], monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setattr("sys.stdin", type("S", (), {"read": staticmethod(lambda: "")})())
    assert cli.main(["fix"]) == 2
    assert "Нет текста" in capsys.readouterr().out


def test_fix_honours_user_dictionary(
    isolated_env: Path, capsys: pytest.CaptureFixture[str], monkeypatch: pytest.MonkeyPatch
) -> None:
    # A taught brand is not in the frequency corpora; the CLI must load the
    # user dictionary so ``fix`` agrees with the daemon on ``муксуд``.
    monkeypatch.setenv("XDG_DATA_HOME", str(isolated_env / "data"))
    monkeypatch.setattr(cli.LayoutSwitcher, "get_current_layout", lambda self, force=False: "ru")
    assert cli.main(["dict", "add", "vercel"]) == 0
    capsys.readouterr()
    assert cli.main(["fix", "--text", "муксуд"]) == 0
    assert "vercel" in capsys.readouterr().out


def test_fix_dry_run_does_not_apply(
    isolated_env: Path, capsys: pytest.CaptureFixture[str], monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setattr(cli.LayoutSwitcher, "get_current_layout", lambda self, force=False: "us")
    applied: list[tuple[int, str, str]] = []
    monkeypatch.setattr(
        cli.TextInjector,
        "replace_text",
        lambda self, count, new, layout: applied.append((count, new, layout)) or True,
    )
    assert cli.main(["fix", "--text", "ghbdtn", "--apply", "--dry-run"]) == 0
    out = capsys.readouterr().out
    assert "привет" in out
    assert "dry-run" in out
    assert applied == []


def test_start_dry_run_flag_is_parsed() -> None:
    args = cli.build_parser().parse_args(["start", "--foreground", "--dry-run"])
    assert args.dry_run is True


def test_install_autostart(
    isolated_env: Path, capsys: pytest.CaptureFixture[str], monkeypatch: pytest.MonkeyPatch
) -> None:
    desktop = isolated_env / "src" / "klyrshift.desktop"
    desktop.parent.mkdir(parents=True, exist_ok=True)
    desktop.write_text("[Desktop Entry]\nName=Klyrshift\n", encoding="utf-8")
    monkeypatch.setattr(
        cli, "_bundled_data_file", lambda name: desktop if name.endswith("desktop") else None
    )
    monkeypatch.setattr(cli.subprocess, "run", lambda *a, **k: None)
    assert cli.main(["install-autostart"]) == 0
    assert cli._autostart_path().exists()
    assert "Автозапуск установлен" in capsys.readouterr().out


def test_install_autostart_missing_source(
    isolated_env: Path, capsys: pytest.CaptureFixture[str], monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setattr(cli, "_bundled_data_file", lambda name: None)
    assert cli.main(["install-autostart"]) == 1


def test_install_autostart_renders_bin_placeholder(
    isolated_env: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    desktop = isolated_env / "src" / "klyrshift.desktop"
    desktop.parent.mkdir(parents=True, exist_ok=True)
    desktop.write_text("[Desktop Entry]\nExec=@BIN@ start --foreground\n", encoding="utf-8")
    monkeypatch.setattr(
        cli, "_bundled_data_file", lambda name: desktop if name.endswith("desktop") else None
    )
    monkeypatch.setattr(cli.subprocess, "run", lambda *a, **k: None)
    monkeypatch.setattr(cli, "_launcher_path", lambda: "/usr/bin/klyrshift")
    assert cli.main(["install-autostart"]) == 0
    written = cli._autostart_path().read_text(encoding="utf-8")
    assert "@BIN@" not in written
    assert "Exec=/usr/bin/klyrshift start --foreground" in written


def test_bundled_unit_and_desktop_are_templates() -> None:
    """The shipped files must keep the placeholder for installers to render."""
    from importlib import resources

    base = resources.files("klyrshift") / "data"
    assert "@BIN@" in (base / "klyrshift.service").read_text(encoding="utf-8")
    assert "@BIN@" in (base / "klyrshift.desktop").read_text(encoding="utf-8")


def test_udev_rule_uses_uaccess() -> None:
    """The shipped udev rule must grant access via uaccess, not the input group."""
    rule = Path(__file__).resolve().parent.parent / "data" / "71-klyrshift.rules"
    text = rule.read_text(encoding="utf-8")
    active = [line for line in text.splitlines() if line.strip() and not line.startswith("#")]
    assert any('TAG+="uaccess"' in line for line in active)
    assert not any("GROUP=" in line for line in active)
    # Every active rule needs ACTION!="remove": on systemd 257+ (Debian 13) the
    # uaccess ACL is applied by 73-seat-late.rules, which only processes rules
    # that guard against the "remove" event.
    assert all('ACTION!="remove"' in line for line in active)


def test_udev_rule_opens_keyboards_only() -> None:
    """Event devices are opened only when they are keyboards or our own.

    The daemon reads keyboards only, so a blanket ``KERNEL=="event*"`` rule
    would also hand the session the mouse, touchpad and joysticks. The second
    rule covers the daemon's own virtual keyboards, which udev may not classify
    as keyboards (python-evdev waits ~2 s for each one it cannot read).
    """
    rule = Path(__file__).resolve().parent.parent / "data" / "71-klyrshift.rules"
    text = rule.read_text(encoding="utf-8")
    active = [line for line in text.splitlines() if line.strip() and not line.startswith("#")]
    event_rules = [line for line in active if 'KERNEL=="event*"' in line]
    assert event_rules
    for line in event_rules:
        assert 'ENV{ID_INPUT_KEYBOARD}=="1"' in line or 'ATTRS{name}=="klyrshift*"' in line
    assert any('ATTRS{name}=="klyrshift*"' in line for line in event_rules)


def test_repo_and_packaged_data_files_match() -> None:
    """``data/`` and ``src/klyrshift/data/`` must not drift apart."""
    from importlib import resources

    packaged = Path(str(resources.files("klyrshift") / "data"))
    repo_data = Path(__file__).resolve().parent.parent / "data"
    for name in ("klyrshift.service", "klyrshift.desktop", "klyrshift.svg"):
        assert (repo_data / name).read_bytes() == (packaged / name).read_bytes(), name


def test_uninstall_autostart(
    isolated_env: Path, capsys: pytest.CaptureFixture[str], monkeypatch: pytest.MonkeyPatch
) -> None:
    target = cli._autostart_path()
    target.parent.mkdir(parents=True, exist_ok=True)
    target.write_text("x", encoding="utf-8")
    monkeypatch.setattr(cli, "_run_quiet", lambda *a, **k: 0)
    assert cli.main(["uninstall-autostart"]) == 0
    assert not target.exists()
    assert "Автозапуск удалён" in capsys.readouterr().out


def test_run_quiet_survives_missing_binary() -> None:
    assert cli._run_quiet(["definitely-not-a-real-binary-xyz"]) == 127


def test_install_autostart_survives_missing_systemctl(
    isolated_env: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    desktop = isolated_env / "src" / "klyrshift.desktop"
    desktop.parent.mkdir(parents=True, exist_ok=True)
    desktop.write_text("Exec=@BIN@ start\n", encoding="utf-8")
    unit = isolated_env / "src" / "klyrshift.service"
    unit.write_text("ExecStart=@BIN@ start\n", encoding="utf-8")

    def fake(name: str) -> Path:
        return unit if name.endswith("service") else desktop

    monkeypatch.setattr(cli, "_bundled_data_file", fake)
    assert cli.main(["install-autostart"]) == 0


def test_pid_alive_for_current_process() -> None:
    import os

    assert cli._pid_alive(os.getpid()) is True


def test_pid_alive_for_missing_process() -> None:
    assert cli._pid_alive(999_999_999) is False


def test_read_pid_invalid_file(isolated_env: Path) -> None:
    path = cli._lock_path()
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text("not-a-pid", encoding="utf-8")
    assert cli._read_pid() is None


def test_read_pid_missing_file(isolated_env: Path) -> None:
    assert cli._read_pid() is None


def test_start_when_already_running(
    isolated_env: Path, capsys: pytest.CaptureFixture[str], monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setattr(cli, "_read_pid", lambda: 1234)
    args = argparse.Namespace(foreground=False)
    assert cli.cmd_start(args) == 0
    assert "запущен" in capsys.readouterr().out


def test_cmd_gui_delegates(monkeypatch: pytest.MonkeyPatch) -> None:
    import klyrshift.gui as gui

    monkeypatch.setattr(gui, "main", lambda: 0)
    assert cli.cmd_gui(argparse.Namespace()) == 0


def test_start_detached_delegates_to_daemon_control(
    isolated_env: Path, capsys: pytest.CaptureFixture[str], monkeypatch: pytest.MonkeyPatch
) -> None:
    """``start`` must use the shared control module, not its own spawn/poll."""
    from klyrshift import daemon_control

    started: list[bool] = []
    monkeypatch.setattr(daemon_control, "start", lambda dry_run=False: started.append(True) or True)
    assert cli.cmd_start(argparse.Namespace(foreground=False, dry_run=False)) == 0
    assert started == [True]
    assert "запущен" in capsys.readouterr().out


def test_start_detached_reports_failure_when_daemon_dies(
    isolated_env: Path, capsys: pytest.CaptureFixture[str], monkeypatch: pytest.MonkeyPatch
) -> None:
    """A daemon that never comes up must not print success, and must say why."""
    from klyrshift import daemon_control

    monkeypatch.setattr(daemon_control, "start", lambda dry_run=False: False)
    monkeypatch.setattr(daemon_control, "last_error", lambda: "демон завершился сразу")
    assert cli.cmd_start(argparse.Namespace(foreground=False, dry_run=False)) == 1
    out = capsys.readouterr().out
    assert "Не удалось запустить" in out
    assert "демон завершился сразу" in out


def test_mode_show_and_set(isolated_env: Path, capsys: pytest.CaptureFixture[str]) -> None:
    assert cli.main(["mode"]) == 0
    assert capsys.readouterr().out.strip() == "auto"

    assert cli.main(["mode", "manual"]) == 0
    assert "manual" in capsys.readouterr().out
    assert cli.main(["mode"]) == 0
    assert capsys.readouterr().out.strip() == "manual"


def test_mode_signals_running_daemon(isolated_env: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    """Changing the mode must reach a running daemon, not only the file."""
    from klyrshift import daemon_control

    reloads: list[bool] = []
    monkeypatch.setattr(daemon_control, "is_running", lambda: True)
    monkeypatch.setattr(daemon_control, "reload_config", lambda: reloads.append(True) or True)

    assert cli.main(["mode", "manual"]) == 0
    assert reloads == [True]


def test_mode_does_not_signal_when_daemon_stopped(
    isolated_env: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    from klyrshift import daemon_control

    reloads: list[bool] = []
    monkeypatch.setattr(daemon_control, "is_running", lambda: False)
    monkeypatch.setattr(daemon_control, "reload_config", lambda: reloads.append(True) or True)

    assert cli.main(["mode", "manual"]) == 0
    assert reloads == []


def test_app_mode_show_set_and_clear(
    isolated_env: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    """``klyrshift app-mode`` manages per-application overrides."""
    assert cli.main(["app-mode"]) == 0
    assert "не заданы" in capsys.readouterr().out

    assert cli.main(["app-mode", "code", "manual"]) == 0
    assert "code" in capsys.readouterr().out
    assert cli.main(["app-mode", "code"]) == 0
    assert capsys.readouterr().out.strip() == "manual"

    # An application without an override reports the global mode.
    assert cli.main(["app-mode", "firefox"]) == 0
    assert capsys.readouterr().out.strip() == "auto"

    assert cli.main(["app-mode"]) == 0
    assert "code: manual" in capsys.readouterr().out

    assert cli.main(["app-mode", "code", "--clear"]) == 0
    assert cli.main(["app-mode"]) == 0
    assert "не заданы" in capsys.readouterr().out


def test_app_mode_rejects_an_unknown_mode(isolated_env: Path) -> None:
    with pytest.raises(SystemExit):
        cli.main(["app-mode", "code", "sometimes"])


def test_app_mode_signals_running_daemon(
    isolated_env: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    from klyrshift import daemon_control

    reloads: list[bool] = []
    monkeypatch.setattr(daemon_control, "is_running", lambda: True)
    monkeypatch.setattr(daemon_control, "reload_config", lambda: reloads.append(True) or True)

    assert cli.main(["app-mode", "code", "manual"]) == 0
    assert reloads == [True]


def test_undo_requires_running_daemon(
    isolated_env: Path, capsys: pytest.CaptureFixture[str], monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setattr(cli, "_read_pid", lambda: None)
    assert cli.main(["undo"]) == 1
    assert "не запущен" in capsys.readouterr().out


def test_undo_signals_daemon(
    isolated_env: Path, capsys: pytest.CaptureFixture[str], monkeypatch: pytest.MonkeyPatch
) -> None:
    signals: list[tuple[int, int]] = []
    monkeypatch.setattr(cli, "_read_pid", lambda: 4242)
    monkeypatch.setattr(cli.os, "kill", lambda pid, sig: signals.append((pid, sig)))
    assert cli.main(["undo"]) == 0
    assert signals == [(4242, signal.SIGUSR1)]


def test_dict_add_list_remove(
    isolated_env: Path,
    capsys: pytest.CaptureFixture[str],
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setenv("XDG_DATA_HOME", str(isolated_env / "data"))
    assert cli.main(["dict", "list"]) == 0
    assert "пуст" in capsys.readouterr().out

    assert cli.main(["dict", "add", "котопёс"]) == 0
    assert cli.main(["dict", "add", "гайдлайн"]) == 0
    assert cli.main(["dict", "list"]) == 0
    listed = capsys.readouterr().out
    assert "котопёс" in listed and "гайдлайн" in listed

    assert cli.main(["dict", "remove", "котопёс"]) == 0
    assert cli.main(["dict", "list"]) == 0
    assert "котопёс" not in capsys.readouterr().out


def test_dict_remove_missing_word(
    isolated_env: Path,
    capsys: pytest.CaptureFixture[str],
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setenv("XDG_DATA_HOME", str(isolated_env / "data"))
    assert cli.main(["dict", "remove", "нетакого"]) == 1
    assert "не найдено" in capsys.readouterr().out


def test_dict_add_without_word(
    isolated_env: Path,
    capsys: pytest.CaptureFixture[str],
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setenv("XDG_DATA_HOME", str(isolated_env / "data"))
    assert cli.main(["dict", "add"]) == 2
    assert "Укажите слово" in capsys.readouterr().out


def test_install_autostart_uses_dedicated_autostart_file(
    isolated_env: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """The menu entry and the autostart entry are distinct desktop files."""
    requested: list[str] = []

    def fake(name: str) -> Path | None:
        requested.append(name)
        desktop = isolated_env / "src" / name
        desktop.parent.mkdir(parents=True, exist_ok=True)
        desktop.write_text("Exec=@BIN@ start\n", encoding="utf-8")
        return desktop

    monkeypatch.setattr(cli, "_bundled_data_file", fake)
    assert cli.main(["install-autostart"]) == 0
    assert "klyrshift-autostart.desktop" in requested


def test_dict_pack_verify_install_roundtrip(
    isolated_env: Path,
    capsys: pytest.CaptureFixture[str],
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
) -> None:
    """``dict pack`` -> ``verify`` -> ``install-file`` round-trips a package."""
    monkeypatch.setenv("XDG_DATA_HOME", str(isolated_env / "data"))
    monkeypatch.setenv("XDG_CONFIG_HOME", str(isolated_env / "config"))
    source = tmp_path / "ru-50k.txt"
    source.write_text("привет\nмир\n", encoding="utf-8")
    archive = tmp_path / "ru-50k.tar.gz"

    assert (
        cli.main(
            [
                "dict",
                "pack",
                str(source),
                "--name",
                "ru-50k",
                "--lang",
                "ru",
                "--output",
                str(archive),
                "--license",
                "MIT",
            ]
        )
        == 0
    )
    assert "Собран пакет" in capsys.readouterr().out
    assert archive.is_file()

    assert cli.main(["dict", "verify", str(archive)]) == 0
    assert "в порядке" in capsys.readouterr().out

    assert cli.main(["dict", "install-file", str(archive)]) == 0
    assert "Установлен пакет" in capsys.readouterr().out
    installed = isolated_env / "data" / "klyrshift" / "dictionaries" / "ru-50k.txt"
    assert installed.is_file()

    assert cli.main(["dict", "uninstall-file", str(archive)]) == 0
    assert not installed.exists()


def test_dict_verify_rejects_a_tampered_package(
    isolated_env: Path,
    capsys: pytest.CaptureFixture[str],
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
) -> None:
    """``dict verify`` exits non-zero on a package whose bytes changed."""
    import io
    import tarfile

    monkeypatch.setenv("XDG_DATA_HOME", str(isolated_env / "data"))
    source = tmp_path / "ru-50k.txt"
    source.write_text("привет\n", encoding="utf-8")
    archive = tmp_path / "ru-50k.tar.gz"
    assert (
        cli.main(
            [
                "dict",
                "pack",
                str(source),
                "--name",
                "ru-50k",
                "--lang",
                "ru",
                "--output",
                str(archive),
            ]
        )
        == 0
    )
    capsys.readouterr()

    tampered = tmp_path / "tampered.tar.gz"
    with tarfile.open(archive, "r:gz") as src, tarfile.open(tampered, "w:gz") as dst:
        for member in src.getmembers():
            stream = src.extractfile(member) if member.isfile() else None
            payload = stream.read() if stream is not None else b""
            if member.name == "ru-50k.txt":
                payload = b"evil\n"
            info = tarfile.TarInfo(member.name)
            info.size = len(payload)
            info.mtime = 0
            dst.addfile(info, io.BytesIO(payload))

    assert cli.main(["dict", "verify", str(tampered)]) == 1
    assert "не прошёл проверку" in capsys.readouterr().out


def test_dict_pack_without_files(isolated_env: Path, capsys: pytest.CaptureFixture[str]) -> None:
    assert cli.main(["dict", "pack"]) == 2
    assert "Укажите файлы" in capsys.readouterr().out


def test_learn_list_without_a_daemon(
    isolated_env: Path,
    capsys: pytest.CaptureFixture[str],
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """``learn list`` says the daemon is not running instead of printing nothing."""
    monkeypatch.setenv("XDG_RUNTIME_DIR", str(isolated_env / "runtime"))
    assert cli.main(["learn", "list"]) == 1
    assert "Демон не запущен" in capsys.readouterr().out


def test_learn_promote_without_a_daemon(
    isolated_env: Path,
    capsys: pytest.CaptureFixture[str],
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setenv("XDG_RUNTIME_DIR", str(isolated_env / "runtime"))
    assert cli.main(["learn", "promote", "vercel"]) == 1
    assert "Демон не запущен" in capsys.readouterr().out


def test_learn_promote_requires_a_word(
    isolated_env: Path,
    capsys: pytest.CaptureFixture[str],
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setenv("XDG_RUNTIME_DIR", str(isolated_env / "runtime"))
    assert cli.main(["learn", "promote"]) == 2
    assert "Укажите слово" in capsys.readouterr().out


def test_learn_list_and_promote_against_a_live_socket(
    isolated_env: Path,
    capsys: pytest.CaptureFixture[str],
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """The CLI drives the control socket end to end."""
    import selectors
    import threading

    from klyrshift import control

    monkeypatch.setenv("XDG_RUNTIME_DIR", str(isolated_env / "runtime"))
    words: list[str] = []

    def handler(request: dict[str, object]) -> dict[str, object]:
        command = request.get("cmd")
        if command == "learn.list":
            return {"words": list(words)}
        word = request.get("word")
        assert isinstance(word, str)
        if command == "learn.promote":
            words.append(word)
            return {"ok": True}
        if command == "learn.forget":
            words.remove(word)
            return {"ok": True}
        return {"error": "unknown"}

    server = control.ControlServer(handler)
    assert server.start()
    selector = selectors.DefaultSelector()
    selector.register(server.fileno, selectors.EVENT_READ, server)
    stop = threading.Event()

    def serve() -> None:
        while not stop.is_set():
            for key, _mask in selector.select(0.05):
                key.data.handle()

    thread = threading.Thread(target=serve, daemon=True)
    thread.start()
    try:
        assert cli.main(["learn", "list"]) == 0
        assert "Выученных слов пока нет" in capsys.readouterr().out

        assert cli.main(["learn", "promote", "vercel"]) == 0
        assert "закреплено" in capsys.readouterr().out

        assert cli.main(["learn", "list"]) == 0
        assert "vercel" in capsys.readouterr().out

        assert cli.main(["learn", "forget", "vercel"]) == 0
        assert "забыто" in capsys.readouterr().out
    finally:
        stop.set()
        thread.join(timeout=5)
        selector.close()
        server.stop()
