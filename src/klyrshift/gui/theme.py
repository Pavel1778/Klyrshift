"""Apply the configured colour scheme to the GUI.

Lives in its own module so both the application (at startup) and the settings
page (when the user changes the value) can call it without a circular import:
``app`` imports ``window``, which imports ``settings_page``.
"""

from __future__ import annotations

import logging

import gi

gi.require_version("Gtk", "4.0")
gi.require_version("Adw", "1")
from gi.repository import Adw  # noqa: E402

from ..config import VALID_THEMES  # noqa: E402

logger = logging.getLogger(__name__)

# ``Adw.ColorScheme`` values for each supported ``Config.theme``.
_THEME_TO_SCHEME = {
    "system": Adw.ColorScheme.DEFAULT,
    "light": Adw.ColorScheme.FORCE_LIGHT,
    "dark": Adw.ColorScheme.FORCE_DARK,
}


def apply_theme(theme: str) -> str:
    """Set the application colour scheme from ``theme``.

    ``system`` follows the desktop; ``light``/``dark`` force one scheme. The
    value is validated first, so a hand-edited config cannot crash startup: an
    unknown value falls back to ``system``.

    Returns:
        The theme actually applied (``system`` when the value was unknown).
    """
    normalized = str(theme).lower()
    if normalized not in VALID_THEMES:
        logger.warning("unknown theme %r; using system", theme)
        normalized = "system"
    try:
        Adw.StyleManager.get_default().set_color_scheme(_THEME_TO_SCHEME[normalized])
    except Exception:  # pragma: no cover - only without a display
        logger.debug("could not set colour scheme", exc_info=True)
    return normalized
