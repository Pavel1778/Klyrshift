"""The guided-tour overlay: dimmed background, highlighted target, step card.

The overlay is a plain :class:`Gtk.Overlay` placed above the whole window, so the
scrim covers the header bar too. It renders the scenario from
:mod:`klyrshift.onboarding`; it holds no step text of its own, which is what keeps
the help and the UI from drifting apart.

Design notes that are not obvious from the code:

* The scrim is a semi-transparent layer with a bright ring around the target, not
  a blur. The target stays readable under it, so the highlight never depends on a
  single visual cue, and the widget works on compositors without blur support.
* A step whose target cannot be resolved is skipped instead of pointing at
  nothing; if no step can be shown the tour closes rather than trapping the user
  behind a dimmed window.
* The scrim accepts pointer input, so the tour is modal. Every step is
  informational (no step asks the user to change a setting mid-tour), so blocking
  clicks is the least surprising behaviour.
"""

from __future__ import annotations

import logging
from collections.abc import Callable

import gi

gi.require_version("Gtk", "4.0")
gi.require_version("Adw", "1")
from gi.repository import Gdk, GLib, Gtk  # noqa: E402

from ...onboarding import TOUR_STEPS, TourStep  # noqa: E402

logger = logging.getLogger(__name__)

SCRIM_ALPHA = 0.45
RING_WIDTH = 3.0
RING_PADDING = 4.0
CARD_MAX_WIDTH = 380
CARD_GAP = 12
EDGE_MARGIN = 12


def bounds_rect(
    result: object,
) -> tuple[float, float, float, float] | None:
    """Convert a ``Gtk.Widget.compute_bounds`` result into a plain rectangle.

    GTK returns ``(success, Graphene.Rect)``; PyGObject does not model the tuple,
    so the success flag and the rectangle are unpacked explicitly and anything
    unexpected yields ``None`` instead of raising into the tour.
    """
    if not isinstance(result, tuple) or len(result) != 2:
        return None
    ok, rect = result
    if not ok or rect is None:
        return None
    return (rect.origin.x, rect.origin.y, rect.size.width, rect.size.height)


class TourOverlay(Gtk.Overlay):
    """A modal, step-by-step tour drawn over the application window.

    Args:
        resolve_target: Maps a step's ``page.widget`` name to a live widget, or
            ``None`` when it is not in the current window.
        measure_target: Returns the target's rectangle in this widget's coordinate
            space, or ``None`` when it cannot be measured. The window supplies it
            because only the window owns an ancestor of the target widgets; the
            overlay itself is a sibling of them, not an ancestor, so it cannot
            call ``compute_bounds`` itself.
        on_finished: Called with the last step index when the user reaches the end.
        on_skipped: Called with the current step index when the user skips.
        on_closed: Called after the overlay is hidden, whatever the reason.
    """

    def __init__(
        self,
        resolve_target: Callable[[str], Gtk.Widget | None],
        *,
        measure_target: (
            Callable[[Gtk.Widget], tuple[float, float, float, float] | None] | None
        ) = None,
        on_finished: Callable[[int], None] | None = None,
        on_skipped: Callable[[int], None] | None = None,
        on_closed: Callable[[], None] | None = None,
        show_step: Callable[[TourStep], None] | None = None,
        steps: tuple[TourStep, ...] = TOUR_STEPS,
    ) -> None:
        super().__init__()
        self._resolve = resolve_target
        self._measure = measure_target or self._measure_with_bounds
        self._on_finished = on_finished
        self._on_skipped = on_skipped
        self._on_closed = on_closed
        self._show_step = show_step
        self._steps = steps
        self._index = 0
        self._highlight: tuple[float, float, float, float] | None = None
        self._previous_focus: Gtk.Widget | None = None

        self.set_hexpand(True)
        self.set_vexpand(True)
        self.set_can_focus(True)
        self.add_css_class("tour-overlay")
        # This widget is added as an overlay child of the window's content, so it
        # never owns the window content and starting hidden cannot blank the app.
        self.set_visible(False)

        self._scrim = Gtk.DrawingArea()
        self._scrim.set_hexpand(True)
        self._scrim.set_vexpand(True)
        # Picking up pointer events here is what makes the tour modal.
        self._scrim.set_can_target(True)
        self._scrim.set_draw_func(self._draw_scrim)
        self.set_child(self._scrim)

        self._card = self._build_card()
        self.add_overlay(self._card)

        keys = Gtk.EventControllerKey()
        keys.connect("key-pressed", self._on_key_pressed)
        self.add_controller(keys)
        self.add_tick_callback(self._on_tick)

    def _measure_with_bounds(self, target: Gtk.Widget) -> tuple[float, float, float, float] | None:
        """Fallback measurement for when the overlay *is* an ancestor of the target."""
        # ``target.compute_bounds(reference)`` returns the target's rectangle in
        # the reference widget's coordinates; the arguments are the other way
        # round from what the GTK name suggests.
        return bounds_rect(target.compute_bounds(self))

    # --- construction ---------------------------------------------------------
    def _build_card(self) -> Gtk.Box:
        card = Gtk.Box(orientation=Gtk.Orientation.VERTICAL, spacing=10)
        card.add_css_class("tour-card")
        card.set_halign(Gtk.Align.CENTER)
        card.set_valign(Gtk.Align.START)

        self._progress = Gtk.Label(xalign=0.0)
        self._progress.add_css_class("dim-label")
        self._progress.add_css_class("caption")
        card.append(self._progress)

        self._title = Gtk.Label(xalign=0.0)
        self._title.add_css_class("title-3")
        self._title.set_wrap(True)
        card.append(self._title)

        self._short = Gtk.Label(xalign=0.0)
        self._short.set_wrap(True)
        self._short.set_justify(Gtk.Justification.LEFT)
        card.append(self._short)

        self._details_toggle = Gtk.ToggleButton(label="Подробнее")
        self._details_toggle.add_css_class("flat")
        self._details_toggle.set_halign(Gtk.Align.START)
        self._details_toggle.connect("toggled", self._on_details_toggled)
        card.append(self._details_toggle)

        self._details = Gtk.Label(xalign=0.0)
        self._details.set_wrap(True)
        self._details.set_justify(Gtk.Justification.LEFT)
        self._details.add_css_class("dim-label")
        self._details.set_visible(False)
        card.append(self._details)

        buttons = Gtk.Box(orientation=Gtk.Orientation.HORIZONTAL, spacing=8)
        buttons.set_halign(Gtk.Align.END)
        self._skip_button = Gtk.Button(label="Пропустить")
        self._skip_button.add_css_class("flat")
        self._skip_button.connect("clicked", lambda _b: self.skip())
        self._back_button = Gtk.Button(label="Назад")
        self._back_button.connect("clicked", lambda _b: self.previous_step())
        self._next_button = Gtk.Button(label="Далее")
        self._next_button.add_css_class("suggested-action")
        self._next_button.connect("clicked", lambda _b: self.next_step())
        for button in (self._skip_button, self._back_button, self._next_button):
            buttons.append(button)
        card.append(buttons)
        return card

    # --- lifecycle ------------------------------------------------------------
    def open(self) -> bool:
        """Show the tour at the first displayable step.

        Returns:
            ``True`` when the tour is showing, ``False`` when no step could be
            displayed (the caller then leaves the window untouched).
        """
        root = self.get_root()
        if isinstance(root, Gtk.Window):
            self._previous_focus = root.get_focus()
        self.set_visible(True)
        self.grab_focus()
        self._index = -1
        if not self._advance(1):
            self.close()
            return False
        return True

    def close(self) -> None:
        """Hide the tour, restore focus and notify the window."""
        self.set_visible(False)
        self._highlight = None
        if self._previous_focus is not None and self._previous_focus.get_visible():
            self._previous_focus.grab_focus()
        if self._on_closed is not None:
            self._on_closed()

    # --- navigation -----------------------------------------------------------
    def next_step(self) -> None:
        """Go forward; finishing on the last step."""
        if not self._advance(1):
            self._finish()

    def previous_step(self) -> None:
        """Go back one step; a no-op on the first step."""
        if self._index <= 0:
            return
        self._advance(-1)

    def skip(self) -> None:
        """End the tour early, recording it as skipped."""
        if self._on_skipped is not None:
            self._on_skipped(self._index)
        self.close()

    def _is_displayable(self, step: TourStep) -> bool:
        """Return whether a step can be shown.

        A step with no target is the closing card and is always displayable; a
        step with a target is displayable only when that widget is in the window.
        """
        if not step.target:
            return True
        return self._resolve(step.target) is not None

    def _advance(self, direction: int) -> bool:
        """Move to the next displayable step; return whether one was found."""
        index = self._index
        while True:
            index += direction
            if not 0 <= index < len(self._steps):
                return False
            if self._is_displayable(self._steps[index]):
                break
        self._index = index
        self._apply_step()
        return True

    def _finish(self) -> None:
        if self._on_finished is not None:
            self._on_finished(self._index)
        self.close()

    def _step_widget(self, step: TourStep) -> Gtk.Widget | None:
        """Return the widget a step points at, or ``None`` when it has none."""
        if not step.target:
            return None
        return self._resolve(step.target)

    def _apply_step(self) -> None:
        step = self._steps[self._index]
        if self._show_step is not None:
            self._show_step(step)
        self._progress.set_label(f"Шаг {self._index + 1} из {len(self._steps)}")
        self._title.set_label(step.title)
        self._short.set_label(step.short)
        self._details.set_label(step.details)
        self._details.set_visible(False)
        self._details_toggle.set_active(False)
        self._back_button.set_sensitive(self._index > 0)
        # The closing card has no target, so it is displayable wherever it sits.
        is_last = not any(self._is_displayable(s) for s in self._steps[self._index + 1 :])
        self._next_button.set_label("Завершить" if is_last else "Далее")
        self._reposition()

    def _on_details_toggled(self, button: Gtk.ToggleButton) -> None:
        self._details.set_visible(button.get_active())
        self._reposition()

    # --- keyboard -------------------------------------------------------------
    def _on_key_pressed(
        self, _controller: Gtk.EventControllerKey, keyval: int, _code: int, _state: Gdk.ModifierType
    ) -> bool:
        if keyval == Gdk.KEY_Escape:
            self.skip()
            return True
        if keyval in (Gdk.KEY_Right, Gdk.KEY_Down, Gdk.KEY_Return, Gdk.KEY_KP_Enter):
            self.next_step()
            return True
        if keyval in (Gdk.KEY_Left, Gdk.KEY_Up):
            self.previous_step()
            return True
        return False

    # --- layout ---------------------------------------------------------------
    def _on_tick(self, _widget: Gtk.Widget, _clock: Gdk.FrameClock) -> bool:
        # A resize (or a page change) moves the target; recompute so the ring and
        # the card never lag behind the widget they describe.
        if self.get_visible():
            self._reposition()
        return bool(GLib.SOURCE_CONTINUE)

    def _reposition(self) -> None:
        overlay_w = self.get_width()
        overlay_h = self.get_height()
        if overlay_w <= 0 or overlay_h <= 0:
            return
        target = self._step_widget(self._steps[self._index]) if self._index >= 0 else None
        rect: tuple[float, float, float, float] | None = None
        if target is not None:
            rect = self._measure(target)
        self._highlight = rect
        self._scrim.queue_draw()

        card_width = min(CARD_MAX_WIDTH, max(200, overlay_w - 2 * EDGE_MARGIN))
        self._card.set_size_request(card_width, -1)
        card_height = self._measure_card_height(card_width)
        if rect is None:
            # Nothing to point at: centre the card so the closing step reads as a
            # plain dialog rather than a misplaced tooltip.
            self._card.set_valign(Gtk.Align.CENTER)
            self._card.set_margin_top(0)
            self._card.set_margin_bottom(0)
            return

        self._card.set_valign(Gtk.Align.START)
        target_center = rect[1] + rect[3] / 2
        if target_center > overlay_h / 2:
            top = rect[1] - card_height - CARD_GAP
        else:
            top = rect[1] + rect[3] + CARD_GAP
        top = max(EDGE_MARGIN, min(top, max(EDGE_MARGIN, overlay_h - card_height - EDGE_MARGIN)))
        self._card.set_margin_top(int(top))
        self._card.set_margin_bottom(0)

    def _measure_card_height(self, width: int) -> int:
        minimum, natural = self._card.measure(Gtk.Orientation.VERTICAL, width)[:2]
        return int(max(minimum, natural))

    def _draw_scrim(self, _area: Gtk.DrawingArea, cr: object, width: int, height: int) -> None:
        red, green, blue, alpha = 0.0, 0.0, 0.0, SCRIM_ALPHA
        color = self.get_color()
        if color is not None:
            # Follow the theme: a light theme dims with its own foreground colour
            # instead of always painting black.
            red, green, blue = color.red, color.green, color.blue
        cr.set_source_rgba(red, green, blue, alpha)  # type: ignore[attr-defined]
        cr.rectangle(0, 0, width, height)  # type: ignore[attr-defined]
        cr.fill()  # type: ignore[attr-defined]

        if self._highlight is None:
            return
        x, y, w, h = self._highlight
        pad = RING_PADDING
        cr.set_line_width(RING_WIDTH)  # type: ignore[attr-defined]
        cr.set_source_rgba(red, green, blue, 0.95)  # type: ignore[attr-defined]
        cr.rectangle(x - pad, y - pad, w + 2 * pad, h + 2 * pad)  # type: ignore[attr-defined]
        cr.stroke()  # type: ignore[attr-defined]

    # --- introspection (used by the window and the tests) ---------------------
    @property
    def index(self) -> int:
        """Return the current step index."""
        return self._index

    @property
    def current_step(self) -> TourStep | None:
        """Return the step being shown, or ``None`` before :meth:`open`."""
        if 0 <= self._index < len(self._steps):
            return self._steps[self._index]
        return None

    @property
    def card(self) -> Gtk.Box:
        """Expose the step card for tests."""
        return self._card

    @property
    def details_visible(self) -> bool:
        """Return whether the detailed explanation is expanded."""
        return bool(self._details.get_visible())

    @property
    def highlight(self) -> tuple[float, float, float, float] | None:
        """Return the highlighted rectangle in overlay coordinates."""
        return self._highlight

    @property
    def progress_text(self) -> str:
        """Return the progress label, e.g. ``Шаг 2 из 6``."""
        return str(self._progress.get_label())

    @property
    def next_label(self) -> str:
        """Return the primary button's label."""
        return str(self._next_button.get_label())


__all__ = ["TourOverlay", "bounds_rect"]
