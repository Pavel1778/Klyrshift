"""GTK4 + libadwaita graphical interface for Klyrshift.

The GUI is a separate process: it talks to the daemon through ``systemctl
--user`` and the :mod:`klyrshift.cli` helpers, never through in-process state.
If the GUI crashes the daemon keeps running, and if GTK is not installed the
rest of the application is unaffected.

:func:`main` is the ``klyrshift gui`` entry point. It prints a friendly message
and returns 1 when the GTK stack is missing instead of raising.
"""

from __future__ import annotations

import logging

from ..i18n import _

logger = logging.getLogger(__name__)

MISSING_STACK_MESSAGE = (
    "Для графического интерфейса нужны GTK4 и libadwaita.\n"
    "Установите их командой:\n"
    "  sudo apt install python3-gi gir1.2-gtk-4.0 gir1.2-adw-1\n"
    "Демон и CLI работают без них."
)

MISSING_CAIRO_MESSAGE = (
    "Для графического интерфейса нужен модуль cairo для PyGObject.\n"
    "Без него не рисуются затемнение тура и значок кнопки включения.\n"
    "Установите его командой:\n"
    "  sudo apt install python3-gi-cairo\n"
    "Демон и CLI работают без него."
)


def gtk_available() -> bool:
    """Return ``True`` when GTK4 and libadwaita can be imported."""
    try:
        import gi

        gi.require_version("Gtk", "4.0")
        gi.require_version("Adw", "1")
        from gi.repository import Adw, Gtk  # noqa: F401
    except (ImportError, ValueError):
        return False
    return True


def cairo_available() -> bool:
    """Return ``True`` when PyGObject can convert to ``cairo.Context``.

    The tour's scrim and the fallback power glyph paint with Cairo through
    ``Gtk.DrawingArea.set_draw_func``. That conversion lives in the ``_gi_cairo``
    override module, shipped by ``python3-gi-cairo``; without it every draw raises
    ``TypeError: Couldn't find foreign struct converter for 'cairo.Context'`` and
    the widgets stay blank. ``from gi.repository import cairo`` still succeeds
    without the override, so only importing ``_gi_cairo`` detects the gap.
    """
    try:
        from gi import _gi_cairo  # noqa: F401
    except (ImportError, ValueError):
        return False
    return True


def main(argv: list[str] | None = None) -> int:
    """Run the GTK application.

    Args:
        argv: Optional argument vector passed through to GTK.

    Returns:
        The process exit code. ``1`` when the GTK stack is unavailable.
    """
    if not gtk_available():
        print(_(MISSING_STACK_MESSAGE))
        return 1
    if not cairo_available():
        print(_(MISSING_CAIRO_MESSAGE))
        return 1

    # The GUI is its own process: give it a logger (a dedicated gui.log) so a
    # failed start/stop or a missing daemon leaves a trace instead of vanishing.
    from ..logging_setup import GUI_LOG_FILE_NAME, setup_logging

    setup_logging(file_name=GUI_LOG_FILE_NAME)
    logger.debug("Starting Klyrshift GUI")

    from .app import KlyrshiftApplication

    app = KlyrshiftApplication()
    return int(app.run(argv or []))
