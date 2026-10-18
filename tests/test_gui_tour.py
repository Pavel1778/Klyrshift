"""GUI tests for the onboarding tour and the context help.

Like the rest of the GUI suite these need a display: GTK aborts without one, so
the module is skipped unless ``DISPLAY``/``WAYLAND_DISPLAY`` is set (CI runs the
suite under ``xvfb-run``). The tour is driven through its real widget tree, so a
renamed target widget fails here instead of degrading silently to centred cards.
"""

from __future__ import annotations

import os
import sys
import time
from pathlib import Path
from typing import Any

import pytest

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


def _pump(seconds: float = 0.4) -> None:
    """Run the main loop until it has had a chance to lay the window out."""
    import gi

    gi.require_version("GLib", "2.0")
    from gi.repository import GLib

    context = GLib.MainContext.default()
    deadline = time.monotonic() + seconds
    while time.monotonic() < deadline:
        while context.pending():
            context.iteration(False)
        time.sleep(0.01)


@pytest.fixture
def gui_state(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> Any:
    """Return a :class:`GuiState` isolated to ``tmp_path`` and a fake backend."""
    from klyrshift.gui import state as state_module
    from klyrshift.gui.state import GuiState

    config = Config()
    monkeypatch.setattr(state_module, "load_config", lambda: config)
    monkeypatch.setattr(state_module, "save_config", lambda _cfg, _path=None: tmp_path)
    return GuiState(config=config)


@pytest.fixture
def window(gui_state: Any, tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> Any:
    """Build a real window whose onboarding state stays inside ``tmp_path``.

    The state file path comes from ``state_dir()``, which honours
    ``XDG_STATE_HOME``; pointing that at ``tmp_path`` keeps the test from
    touching the developer's real onboarding file.
    """
    import gi

    gi.require_version("Adw", "1")
    from gi.repository import Adw

    from klyrshift.gui.window import KlyrshiftWindow

    monkeypatch.setenv("XDG_STATE_HOME", str(tmp_path))
    app = Adw.Application(application_id="io.github.pavel1778.KlyrshiftTourTest")
    return KlyrshiftWindow(gui_state, app)


def test_every_tour_step_target_resolves(window: Any) -> None:
    """No step points at a widget that is missing from the window."""
    from klyrshift.onboarding import TOUR_STEPS

    missing = [
        step.target
        for step in TOUR_STEPS
        if step.target and window._resolve_tour_target(step.target) is None
    ]
    assert missing == []


def test_every_tour_step_page_exists(window: Any) -> None:
    """Every step names a view-stack page, so the window can switch to it."""
    from klyrshift.onboarding import TOUR_STEPS

    for step in TOUR_STEPS:
        assert window.stack.get_child_by_name(step.page) is not None, step.key


def test_tour_stays_hidden_until_started(window: Any) -> None:
    assert window.tour.get_visible() is False
    assert window.start_tour() is True
    assert window.tour.get_visible() is True


def test_tour_walks_every_step_and_switches_page(window: Any) -> None:
    """Advancing shows each step on its own page; the last step ends the tour."""
    window.start_tour()
    seen = [window.tour.current_step.key]
    for _ in range(len(window.tour._steps) - 1):
        assert window.stack.get_visible_child_name() == window.tour.current_step.page
        window.tour.next_step()
        seen.append(window.tour.current_step.key)
    assert seen == [step.key for step in window.tour._steps]
    window.tour.next_step()
    assert window.tour.get_visible() is False


def test_tour_highlight_tracks_the_target(window: Any) -> None:
    """The highlight rectangle is the target's bounds inside the window content."""
    from klyrshift.gui.widgets.tour_overlay import bounds_rect

    window.present()
    _pump()
    window.start_tour()
    _pump()

    target = window._resolve_tour_target(window.tour.current_step.target)
    expected = bounds_rect(target.compute_bounds(window._root_overlay))
    assert expected is not None
    assert window.tour.highlight == pytest.approx(expected)


def test_tour_finish_records_the_version(window: Any) -> None:
    """Reaching the end persists the version so the offer never returns."""
    from klyrshift.onboarding import TOUR_VERSION, load_onboarding_state

    window.start_tour()
    for _ in range(len(window.tour._steps)):
        window.tour.next_step()
    assert window.tour.get_visible() is False
    assert load_onboarding_state().completed_version == TOUR_VERSION


def test_tour_skip_records_the_version(window: Any) -> None:
    """Skipping also persists the version, so a routine start stays quiet."""
    from klyrshift.onboarding import TOUR_VERSION, load_onboarding_state

    window.start_tour()
    window.tour.skip()
    assert window.tour.get_visible() is False
    assert load_onboarding_state().skipped_version == TOUR_VERSION


def test_settings_groups_offer_context_help(window: Any) -> None:
    """Every "?" button on a settings group points at a real help topic."""
    import gi

    gi.require_version("Adw", "1")
    from gi.repository import Adw

    from klyrshift.gui.widgets.help_button import HelpButton
    from klyrshift.onboarding import HELP_TOPICS

    def collect(widget: Any, found: list[Any]) -> None:
        if isinstance(widget, Adw.PreferencesGroup):
            suffix = widget.get_header_suffix()
            if suffix is not None:
                found.append(suffix)
        child = widget.get_first_child()
        while child is not None:
            collect(child, found)
            child = child.get_next_sibling()

    found: list[Any] = []
    collect(window.settings_page, found)

    assert found, "no settings group offers context help"
    for button in found:
        assert isinstance(button, HelpButton)
        assert button.topic.key in HELP_TOPICS
        assert button.topic.fields, f"topic {button.topic.key} explains no config field"


def test_help_dialog_shows_the_topic() -> None:
    """Opening a topic's help builds a dialog titled after it."""
    from klyrshift.gui.widgets.help_button import show_help_dialog
    from klyrshift.onboarding import HELP_TOPICS

    topic = HELP_TOPICS["mode"]
    dialog = show_help_dialog(topic)
    assert dialog.get_title() == topic.title


def test_tour_persists_the_step_being_shown(window: Any) -> None:
    """Each displayed step is written to the onboarding state."""
    from klyrshift.onboarding import load_onboarding_state

    window.start_tour()
    assert load_onboarding_state().last_step == 0
    window.tour.next_step()
    assert load_onboarding_state().last_step == 1


def test_an_interrupted_tour_resumes_at_the_saved_step(window: Any) -> None:
    """A tour that was never finished or skipped picks up where it stopped."""
    window.start_tour()
    window.tour.next_step()
    window.tour.next_step()
    expected = window.tour.current_step.key
    window.tour.close()

    assert window.start_tour() is True
    assert window.tour.current_step.key == expected


def test_finishing_the_tour_clears_the_saved_step(window: Any) -> None:
    """A completed tour starts over next time instead of resuming."""
    from klyrshift.onboarding import load_onboarding_state

    window.start_tour()
    for _ in range(len(window.tour._steps)):
        window.tour.next_step()
    assert load_onboarding_state().last_step == 0

    assert window.start_tour() is True
    assert window.tour.index == 0


def test_skipping_the_tour_clears_the_saved_step(window: Any) -> None:
    """A skipped tour also forgets the position, so a replay starts at the top."""
    from klyrshift.onboarding import load_onboarding_state

    window.start_tour()
    window.tour.next_step()
    window.tour.skip()
    assert load_onboarding_state().last_step == 0

    assert window.start_tour() is True
    assert window.tour.index == 0
