"""The ``Adw.Application`` for the Lingvix GUI."""

from __future__ import annotations

import logging

import gi

gi.require_version("Gtk", "4.0")
gi.require_version("Adw", "1")
from gi.repository import Adw, Gio  # noqa: E402

from .state import GuiState  # noqa: E402
from .style import load_stylesheet  # noqa: E402
from .window import LingvixWindow  # noqa: E402

logger = logging.getLogger(__name__)

APP_ID = "io.github.pavel1778.Lingvix"


class LingvixApplication(Adw.Application):
    """GTK application hosting :class:`~lingvix.gui.window.LingvixWindow`."""

    def __init__(self, state: GuiState | None = None) -> None:
        super().__init__(application_id=APP_ID, flags=Gio.ApplicationFlags.FLAGS_NONE)
        self._state = state or GuiState()
        self._window: LingvixWindow | None = None

    def do_activate(self) -> None:
        """Present the window, creating it on first activation."""
        if self._window is None:
            load_stylesheet()
            self._window = LingvixWindow(self._state, self)
        self._window.present()

    @property
    def window(self) -> LingvixWindow | None:
        """Return the main window, if it was created."""
        return self._window

    @property
    def state(self) -> GuiState:
        """Return the shared GUI state."""
        return self._state
