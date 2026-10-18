"""Render real Klyrshift GUI screenshots to PNG.

Builds the actual ``KlyrshiftWindow`` (the same widget tree the app shows), lets
GTK lay it out under the current display, and renders the widget tree into a
PNG through ``Gtk.WidgetPaintable`` + a ``Gsk`` renderer. This is a real render
of the real UI, not a hand-drawn mock.

Usage (needs a display; use ``xvfb-run`` without one):
    PYTHONPATH=/usr/lib/python3/dist-packages xvfb-run -a \
        python3 scripts/make_screenshots.py docs/screenshots
"""

from __future__ import annotations

import os
import shutil
import sys
import tempfile
import time
from pathlib import Path
from typing import Any

_DIST_PACKAGES = "/usr/lib/python3/dist-packages"
if _DIST_PACKAGES not in sys.path:
    sys.path.append(_DIST_PACKAGES)

import gi  # noqa: E402

gi.require_version("Gtk", "4.0")
gi.require_version("Adw", "1")
gi.require_version("Gsk", "4.0")
from gi.repository import Adw, Gdk, GLib, Gsk, Gtk  # noqa: E402

REPO_ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(REPO_ROOT / "src"))

WIDTH = 980
HEIGHT = 720

# Wall-clock window a page is left to settle before it is rendered. Covers the
# ``Adw.ViewSwitcher`` underline animation, which is timeline-driven and so is
# not reported by ``Adw.ViewStack``'s ``transition-running`` flag.
_SETTLE_SECONDS = 0.6


def _make_renderer() -> Gsk.Renderer:
    """Realize one Cairo renderer for the process; reuse it for every shot.

    Creating (and dropping) a renderer per shot trips ``gsk_renderer_dispose``
    ("assertion failed: !priv->is_realized"), which aborts the process.
    """
    renderer = Gsk.CairoRenderer.new()
    display = Gdk.Display.get_default()
    if display is None or not renderer.realize_for_display(display):
        raise RuntimeError("could not realize the GSK renderer")
    return renderer


def _render(widget: Gtk.Widget, path: Path, renderer: Gsk.Renderer) -> None:
    """Render ``widget`` into ``path`` as PNG at its allocated size."""
    width = widget.get_width() or WIDTH
    height = widget.get_height() or HEIGHT
    paintable = Gtk.WidgetPaintable.new(widget)
    snapshot = Gtk.Snapshot.new()
    paintable.snapshot(snapshot, width, height)
    node = snapshot.to_node()
    if node is None:
        raise RuntimeError(f"nothing rendered for {path.name}")
    texture = renderer.render_texture(node, None)
    if texture is None:
        raise RuntimeError(f"renderer returned no texture for {path.name}")
    texture.save_to_png(str(path))
    print(f"wrote {path} ({path.stat().st_size} bytes)")


def main() -> int:
    out_dir = Path(sys.argv[1]) if len(sys.argv) > 1 else REPO_ROOT / "docs" / "screenshots"
    out_dir.mkdir(parents=True, exist_ok=True)

    # Keep the render hermetic: a first-run tour offer would otherwise cover the
    # home page, so the shot would depend on the machine's onboarding state
    # instead of on the code. ``HOME`` is a fixed placeholder (so the dictionary
    # path shown on the page reads like a real user's) while every directory the
    # run writes to is redirected into a throwaway tree.
    temp_root = Path(tempfile.gettempdir()) / "klyrshift-shots"
    shutil.rmtree(temp_root, ignore_errors=True)
    temp_root.mkdir(parents=True)
    os.environ["HOME"] = "/home/user"
    os.environ["XDG_STATE_HOME"] = str(temp_root / "state")
    os.environ["XDG_CONFIG_HOME"] = str(temp_root / "config")
    os.environ.pop("XDG_DATA_HOME", None)

    from klyrshift.config import Config
    from klyrshift.gui.state import GuiState
    from klyrshift.gui.window import KlyrshiftWindow
    from klyrshift.onboarding import TOUR_VERSION, OnboardingState, save_onboarding_state

    # Mark the tour as already seen so the first-run offer cannot cover the home
    # page; the screenshots must show the window itself, not the onboarding card.
    save_onboarding_state(
        OnboardingState(completed_version=TOUR_VERSION, skipped_version=TOUR_VERSION)
    )

    shots: list[str] = []

    app = Adw.Application(application_id="io.github.pavel1778.KlyrshiftShots")
    # GTK ships no type stubs, so every widget is ``Any``; keep the holders
    # ``Any`` too rather than sprinkling ``type: ignore`` on each access.
    holder: dict[str, Any] = {}

    def on_activate(application: Adw.Application) -> None:
        # A blinking text caret would land in or out of the frame depending on
        # where the blink happens to be, so turn it off for the capture.
        Gtk.Settings.get_default().set_property("gtk-cursor-blink", False)
        state = GuiState(config=Config())
        window = KlyrshiftWindow(state, application)
        holder["window"] = window
        holder["renderer"] = _make_renderer()
        window.set_default_size(WIDTH, HEIGHT)
        window.present()
        # Wait until the window is mapped and allocated before rendering.
        GLib.timeout_add(500, _grab)

    def _settle() -> None:
        """Let every page transition finish before the frame is captured.

        ``Adw.ViewStack`` cross-fades ``set_visible_child_name`` and the
        ``Adw.ViewSwitcher`` underline keeps ticking for a moment after that;
        the tick is driven by a wall-clock timeline, so ``transition-running``
        alone returns too early and the render catches an arbitrary frame of the
        animation. Transitions are disabled and the loop is pumped for a fixed
        settle window, which makes the PNGs byte-stable from run to run instead
        of drifting by a few antialiasing levels.
        """
        context = GLib.MainContext.default()
        deadline = time.monotonic() + _SETTLE_SECONDS
        while time.monotonic() < deadline:
            while context.pending():
                context.iteration(False)
            time.sleep(0.01)
        while context.pending():
            context.iteration(False)

    def _grab() -> bool:
        window = holder.get("window")
        renderer = holder.get("renderer")
        if window is None or renderer is None:
            return False
        # No cross-fade: every shot must be a settled frame, not a fade midpoint.
        window.stack.set_enable_transitions(False)
        for page_name, filename in (
            ("home", "main-window.png"),
            ("settings", "advanced-settings.png"),
            ("dictionary", "dictionary.png"),
        ):
            window.stack.set_visible_child_name(page_name)
            _settle()
            _render(window, out_dir / filename, renderer)
            shots.append(filename)
        app.quit()
        return False

    app.connect("activate", on_activate)
    app.run([])

    expected = {"main-window.png", "advanced-settings.png", "dictionary.png"}
    produced = set(shots)
    if not expected <= produced:
        print(f"missing screenshots: {expected - produced}", file=sys.stderr)
        return 1
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
