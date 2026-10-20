"""The ``Adw.Application`` for the Klyrshift GUI."""

from __future__ import annotations

import logging

import gi

gi.require_version("Gtk", "4.0")
gi.require_version("Adw", "1")
from gi.repository import Adw, Gio, GLib  # noqa: E402

from ..i18n import SUPPORTED_LOCALES, set_locale  # noqa: E402
from .state import GuiState  # noqa: E402
from .style import load_stylesheet  # noqa: E402
from .theme import apply_theme  # noqa: E402
from .window import KlyrshiftWindow  # noqa: E402

logger = logging.getLogger(__name__)

APP_ID = "io.github.pavel1778.Klyrshift"


class KlyrshiftApplication(Adw.Application):
    """GTK application hosting :class:`~klyrshift.gui.window.KlyrshiftWindow`."""

    def __init__(self, state: GuiState | None = None) -> None:
        super().__init__(application_id=APP_ID, flags=Gio.ApplicationFlags.FLAGS_NONE)
        self._state = state or GuiState()
        self._window: KlyrshiftWindow | None = None
        # ``--lang`` overrides the stored preference for this run only.
        self.add_main_option(
            "lang",
            ord("l"),
            GLib.OptionFlags.NONE,
            GLib.OptionArg.STRING,
            f"Interface language (auto, {', '.join(SUPPORTED_LOCALES)})",
            "LOCALE",
        )
        set_locale(self._state.config.ui_locale)

    def do_handle_local_options(self, options: GLib.VariantDict) -> int:
        """Apply ``--lang`` before the window is built, if it was given."""
        lang = options.lookup_value("lang", GLib.VariantType.new("s"))
        if lang is not None:
            set_locale(lang.get_string())
        return -1

    def do_activate(self) -> None:
        """Present the window, creating it on first activation."""
        if self._window is None:
            load_stylesheet()
            apply_theme(self._state.config.theme)
            self._window = KlyrshiftWindow(self._state, self)
        self._window.present()

    def reload_ui(self) -> None:
        """Rebuild the window so a new interface language takes effect.

        GTK labels are set once, at construction; there is no rebind pass, so
        the honest way to re-render a translated UI is to build the window
        again. The shared state (and the config) survives, so nothing is lost.
        """
        if self._window is None:
            return
        was_visible = self._window.get_visible()
        self._window.destroy()
        self._window = KlyrshiftWindow(self._state, self)
        if was_visible:
            self._window.present()

    @property
    def window(self) -> KlyrshiftWindow | None:
        """Return the main window, if it was created."""
        return self._window

    @property
    def state(self) -> GuiState:
        """Return the shared GUI state."""
        return self._state
