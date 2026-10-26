"""Environment self-diagnosis for Klyrshift.

The ``klyrshift doctor`` command runs a series of read-only checks against the
running system (permissions, devices, external tools, session type, GNOME
version and the resolved backends) and prints a table with a status marker and a
hint for every failed or degraded check.

The module is deliberately free of side effects: it never changes the layout,
never writes text and never modifies the configuration.
"""

from __future__ import annotations

import grp
import logging
import os
import shutil
import subprocess
from dataclasses import dataclass
from pathlib import Path

from .config import Config, config_path, load_config
from .i18n import _
from .injector import TextInjector
from .switcher import LayoutSwitcher, key_sender_for

logger = logging.getLogger(__name__)

OK = "OK"
WARN = "WARN"
FAIL = "FAIL"

_MARKER = {OK: "✅", WARN: "⚠️", FAIL: "❌"}

# Range of GNOME Shell versions for which g3kb-switch is known to work.
GNOME_MIN = 42
GNOME_MAX = 45

COMMAND_TIMEOUT = 5.0


@dataclass
class CheckResult:
    """The outcome of a single diagnostic check.

    Args:
        name: Human-readable check name.
        status: One of :data:`OK`, :data:`WARN` or :data:`FAIL`.
        detail: Short description of what was found.
        hint: Optional suggestion shown when the check did not pass.
    """

    name: str
    status: str
    detail: str
    hint: str = ""


def _session_type() -> str:
    """Return the current session type (``wayland``, ``x11`` or ``unknown``)."""
    return os.environ.get("XDG_SESSION_TYPE", "").lower() or "unknown"


def _gnome_major_version() -> int | None:
    """Return the major GNOME Shell version, or ``None`` if undetectable."""
    executable = shutil.which("gnome-shell")
    if executable is None:
        return None
    try:
        result = subprocess.run(
            [executable, "--version"],
            check=False,
            capture_output=True,
            text=True,
            timeout=COMMAND_TIMEOUT,
        )
    except (OSError, subprocess.SubprocessError):
        return None
    for token in result.stdout.split():
        if token[:1].isdigit():
            try:
                return int(token.split(".")[0])
            except ValueError:
                return None
    return None


def _input_group_membership() -> bool:
    """Return ``True`` when the current user belongs to the ``input`` group."""
    try:
        names = {grp.getgrgid(gid).gr_name for gid in os.getgroups()}
    except (KeyError, OSError):  # pragma: no cover - defensive
        return False
    return "input" in names


# Directories where a distribution installs udev rules, in lookup order.
_UDEV_RULE_DIRS = (
    Path("/usr/lib/udev/rules.d"),
    Path("/etc/udev/rules.d"),
    Path("/run/udev/rules.d"),
)


def _uaccess_rule_present() -> bool:
    """Return ``True`` when an installed Klyrshift rule grants ``uaccess``.

    The packaged udev rule gives device access to the active session user with
    ``TAG+="uaccess"`` instead of adding the user to the ``input`` group, so a
    correct install can have read access without any group membership.
    """
    for directory in _UDEV_RULE_DIRS:
        try:
            rules = list(directory.glob("*klyrshift*.rules"))
        except OSError:  # pragma: no cover - defensive
            continue
        for rule in rules:
            try:
                text = rule.read_text(encoding="utf-8", errors="replace")
            except OSError:  # pragma: no cover - defensive
                continue
            if 'TAG+="uaccess"' in text or "TAG+='uaccess'" in text:
                return True
    return False


def _readable_event_devices() -> tuple[int, int]:
    """Return ``(readable, total)`` counts for ``/dev/input/event*`` nodes."""
    total = 0
    readable = 0
    for path in sorted(Path("/dev/input").glob("event*")):
        total += 1
        if os.access(path, os.R_OK):
            readable += 1
    return readable, total


def check_device_access() -> CheckResult:
    """Check how access to the input devices is granted.

    A correct install grants it either through the packaged udev rule
    (``TAG+="uaccess"``, the .deb path) or, on the developer path, through
    membership of the ``input`` group. Either is accepted.
    """
    uaccess = _uaccess_rule_present()
    in_group = _input_group_membership()
    if uaccess:
        return CheckResult(
            _("Правило доступа"),
            OK,
            _("udev-правило с uaccess установлено"),
        )
    if in_group:
        return CheckResult(
            _("Правило доступа"),
            OK,
            _("пользователь в группе input (dev-путь)"),
        )
    return CheckResult(
        _("Правило доступа"),
        FAIL,
        _("нет udev-правила с uaccess и нет группы input"),
        _(
            "установите пакет .deb (udev-правило ставится автоматически) "
            "или на dev-пути скопируйте data/71-klyrshift.rules в "
            "/etc/udev/rules.d/ и перелогиньтесь; подробнее — docs/TROUBLESHOOTING.md"
        ),
    )


def check_event_devices() -> CheckResult:
    """Check read access to ``/dev/input/event*``."""
    readable, total = _readable_event_devices()
    if total == 0:
        return CheckResult(
            _("Устройства /dev/input/event*"),
            WARN,
            _("устройства не найдены"),
            _("проверьте, что вы в графической сессии и есть клавиатура"),
        )
    if readable == 0:
        return CheckResult(
            _("Устройства /dev/input/event*"),
            FAIL,
            _("0 из {0} доступны для чтения").format(total),
            _(
                "перезагрузите udev-правило: sudo udevadm control --reload-rules && "
                "sudo udevadm trigger; проверьте getfacl (см. docs/TROUBLESHOOTING.md)"
            ),
        )
    return CheckResult(
        _("Устройства /dev/input/event*"),
        OK,
        _("{0} из {1} доступны для чтения").format(readable, total),
    )


def check_uinput() -> CheckResult:
    """Check that ``/dev/uinput`` exists and is writable."""
    path = Path("/dev/uinput")
    if not path.exists():
        return CheckResult(
            _("Устройство /dev/uinput"),
            WARN,
            _("не найдено"),
            _("sudo modprobe uinput; бэкенд uinput будет недоступен"),
        )
    if os.access(path, os.W_OK):
        return CheckResult(_("Устройство /dev/uinput"), OK, _("доступно для записи"))
    return CheckResult(
        _("Устройство /dev/uinput"),
        FAIL,
        _("нет прав на запись"),
        _(
            "перезагрузите udev-правило: sudo udevadm control --reload-rules && "
            "sudo udevadm trigger; проверьте getfacl (см. docs/TROUBLESHOOTING.md)"
        ),
    )


def check_tools() -> CheckResult:
    """Check availability of the external layout/injection tools."""
    found: list[str] = []
    missing: list[str] = []
    for tool in ("g3kb-switch", "gsettings", "wtype", "xdotool", "setxkbmap"):
        if shutil.which(tool) is not None:
            found.append(tool)
        else:
            missing.append(tool)
    detail = _("найдены: ") + (", ".join(found) if found else _("нет"))
    if missing:
        detail += _("; нет: ") + ", ".join(missing)
    # gsettings drives the built-in ``gnome-shortcut`` switcher, which needs
    # nothing else on GNOME (it presses the input-source shortcut via uinput).
    if not {"g3kb-switch", "gsettings", "setxkbmap"} & set(found):
        return CheckResult(
            _("Внешние утилиты"),
            FAIL,
            detail,
            _("установите g3kb-switch (Wayland) или setxkbmap (X11)"),
        )
    if "wtype" not in found and "xdotool" not in found:
        return CheckResult(
            _("Внешние утилиты"),
            WARN,
            detail,
            _("нет wtype/xdotool; замена текста возможна только через uinput"),
        )
    return CheckResult(_("Внешние утилиты"), OK, detail)


def check_gui_libraries() -> CheckResult:
    """Check whether the GTK4/libadwaita GUI stack is present.

    The GUI binary depends on the system PyGObject stack, which is only an
    optional ``Recommends`` of the ``.deb`` (a headless server install never
    needs it). A user who downloads the package and types ``klyrshift gui``
    would otherwise only see the bare "install GTK4" message; this check names
    the exact packages up front.
    """
    from .gui import cairo_available, gtk_available

    if gtk_available() and cairo_available():
        return CheckResult(_("Графический интерфейс"), OK, _("GTK4, libadwaita и cairo доступны"))
    if gtk_available():
        return CheckResult(
            _("Графический интерфейс"),
            WARN,
            _("нет cairo для PyGObject (тур и значок кнопки не отрисуются)"),
            "sudo apt install python3-gi-cairo",
        )
    return CheckResult(
        _("Графический интерфейс"),
        WARN,
        _("нет GTK4/libadwaita (GUI недоступен)"),
        "sudo apt install python3-gi gir1.2-gtk-4.0 gir1.2-adw-1",
    )


def check_gnome_version() -> CheckResult:
    """Check the GNOME Shell version against the supported range."""
    version = _gnome_major_version()
    if version is None:
        return CheckResult(
            _("Версия GNOME"),
            WARN,
            _("не удалось определить (gnome-shell не найден)"),
            _("переключение раскладки через g3kb-switch может не работать"),
        )
    if GNOME_MIN <= version <= GNOME_MAX:
        return CheckResult(
            _("Версия GNOME"),
            OK,
            _("{0} (поддерживается {1}–{2})").format(version, GNOME_MIN, GNOME_MAX),
        )
    return CheckResult(
        _("Версия GNOME"),
        WARN,
        _("{0} вне диапазона {1}–{2}").format(version, GNOME_MIN, GNOME_MAX),
        _("g3kb-switch может не работать; проверьте документацию расширения"),
    )


def check_backends(config: Config) -> list[CheckResult]:
    """Resolve the switcher and injector backends and report them."""
    session = _session_type()
    injector = TextInjector(backend=config.backend)
    switcher = LayoutSwitcher(
        layouts=config.layouts,
        switch_method=config.switch_method,
        key_sender=key_sender_for(injector),
    )

    switcher_result = CheckResult(
        _("Переключение раскладки"),
        OK if switcher.backend != "none" else FAIL,
        switcher.describe(),
        _("установите g3kb-switch или setxkbmap"),
    )
    injector_result = CheckResult(
        _("Замена текста"),
        OK if injector.backend != "none" else FAIL,
        injector.describe(),
        _("установите wtype (Wayland), xdotool (X11) или python3-evdev"),
    )
    if session == "unknown":
        session_result = CheckResult(
            _("Тип сессии"),
            WARN,
            _("unknown (XDG_SESSION_TYPE не задан)"),
            _(
                "запустите doctor из графической сессии GNOME; из TTY/ssh "
                "переключение раскладки и замена текста недоступны"
            ),
        )
    else:
        session_result = CheckResult(_("Тип сессии"), OK, session)
    return [session_result, switcher_result, injector_result]


def check_config(config: Config) -> CheckResult:
    """Report the configuration file location and layout list."""
    return CheckResult(
        _("Конфигурация"),
        OK,
        _("{0} (раскладки: {1})").format(config_path(), ", ".join(config.layouts)),
    )


def check_package_integrity() -> CheckResult:
    """Check the installed files against the package's md5sums manifest.

    A source checkout, a venv install and a container have no manifest, so the
    check reports OK with an explicit "not installed from a .deb" detail rather
    than a pass it cannot support. A real ``.deb`` install ships the manifest
    (``scripts/build_deb.sh`` writes it), and any file that no longer matches is
    a FAIL: the package was corrupted after installation.
    """
    from .integrity import verify_package

    report = verify_package()
    if report.manifest is None:
        return CheckResult(
            _("Целостность пакета"),
            OK,
            _("не установлен из .deb — проверка не требуется"),
        )
    if report.ok:
        detail = _("{0} файлов совпадают с манифестом").format(report.matched)
        if report.excluded:
            detail = _("{0} ({1} пропущено политикой dpkg)").format(detail, len(report.excluded))
        return CheckResult(_("Целостность пакета"), OK, detail)
    return CheckResult(
        _("Целостность пакета"),
        FAIL,
        _("{0} отсутствуют, {1} изменены").format(len(report.missing), len(report.modified)),
        _(
            "переустановите пакет: sudo apt install --reinstall klyrshift; "
            "подробности — klyrshift verify"
        ),
    )


def check_detector_model(config: Config) -> CheckResult:
    """Report the detector's loaded corpora and calibrated confidence model.

    Makes the Stage 3 confidence model visible: the user can see which languages
    have a model and how a known word is scored, without guessing.
    """
    from .converter import LayoutConverter
    from .detector import LanguageDetector

    try:
        detector = LanguageDetector(
            converter=LayoutConverter(),
            stop_words=config.stop_words,
            min_word_length=config.min_word_length,
            languages=tuple(config.languages),
            extended_dictionary_dir=config.extended_dictionary_dir,
            thematic_categories=config.installed_dict_categories,
        )
    except Exception as exc:  # pragma: no cover - defensive
        return CheckResult(_("Модель детектора"), WARN, _("не загрузилась: {0}").format(exc))

    loaded = sorted(detector.loaded_languages)
    if not loaded:
        return CheckResult(
            _("Модель детектора"),
            FAIL,
            _("ни один язык не загружен"),
            _("проверьте config.languages и установленные словари"),
        )
    # A known wrong-layout word is the sanity probe: the model must both decide
    # to convert it and report a high calibrated confidence.
    confidence = detector.analyze("ghbdtn", "us")
    return CheckResult(
        _("Модель детектора"),
        OK,
        _("языки: {0}; уверенность модели: {1:.0%}").format(", ".join(loaded), confidence.value),
    )


def collect_checks(config: Config | None = None) -> list[CheckResult]:
    """Run all checks and return their results in display order.

    Args:
        config: Optional configuration; loaded from disk when omitted.

    Returns:
        The list of check results.
    """
    cfg = config or load_config()
    results = [
        check_device_access(),
        check_event_devices(),
        check_uinput(),
        check_tools(),
        check_gui_libraries(),
        check_gnome_version(),
        check_package_integrity(),
        check_detector_model(cfg),
    ]
    results.extend(check_backends(cfg))
    results.append(check_config(cfg))
    return results


def render(results: list[CheckResult]) -> str:
    """Render the check results as a fixed-width table with markers.

    Args:
        results: Results produced by :func:`collect_checks`.

    Returns:
        The formatted table as a single string.
    """
    name_width = max((len(r.name) for r in results), default=0)
    lines: list[str] = []
    for result in results:
        marker = _MARKER.get(result.status, "?")
        line = f"{marker}  {result.name.ljust(name_width)}  {result.detail}"
        lines.append(line)
        if result.hint and result.status != OK:
            lines.append(f"   {' ' * name_width}  ↳ {result.hint}")
    return "\n".join(lines)


def has_failures(results: list[CheckResult]) -> bool:
    """Return ``True`` when any check has the :data:`FAIL` status."""
    return any(result.status == FAIL for result in results)


def run_doctor(config: Config | None = None) -> int:
    """Run the diagnostics, print the table and return an exit code.

    Args:
        config: Optional configuration override.

    Returns:
        ``0`` when no check failed, ``1`` otherwise.
    """
    results = collect_checks(config)
    print("Klyrshift doctor")
    print("=" * 40)
    print(render(results))
    print()
    if has_failures(results):
        print(_("Итог: есть проблемы, см. подсказки выше."))
        return 1
    print(_("Итог: критических проблем не найдено."))
    return 0
