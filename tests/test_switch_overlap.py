"""The daemon overlaps the layout switch with the deletion.

Deleting the mistyped word does not depend on the layout, so the daemon starts
the switch before the Backspaces and only waits for it to finish before typing
the replacement (:meth:`LayoutSwitcher.start_switch` and the ``before_typing``
hook of :meth:`TextInjector.replace_text`).
"""

from __future__ import annotations

from collections.abc import Callable

from klyrshift.config import Config
from klyrshift.daemon import KlyrshiftDaemon
from klyrshift.injector import TextInjector
from klyrshift.switcher import LayoutSwitcher


class RecordingSwitcher(LayoutSwitcher):
    def __init__(self, events: list[str]) -> None:
        super().__init__(["us", "ru"], "none")
        self.events = events

    def start_switch(self, layout: str) -> Callable[[], bool]:
        self.events.append(f"start {layout}")

        def finish() -> bool:
            self.events.append(f"finish {layout}")
            return True

        return finish

    def switch_to(self, layout: str) -> bool:  # pragma: no cover - must not be used
        raise AssertionError("the overlapped path must not switch synchronously")


class RecordingInjector(TextInjector):
    def __init__(self, events: list[str]) -> None:
        super().__init__(backend="none")
        self.events = events

    def replace_text(
        self,
        backspace_count: int,
        new: str,
        layout: str,
        before_typing: Callable[[], bool] | None = None,
    ) -> bool:
        self.events.append(f"delete {backspace_count}")
        if before_typing is not None:
            before_typing()
        self.events.append(f"type {len(new)} in {layout}")
        return True


def test_switch_starts_before_and_finishes_after_the_deletion() -> None:
    events: list[str] = []
    daemon = KlyrshiftDaemon(
        Config(stop_words=[]),
        switcher=RecordingSwitcher(events),
        injector=RecordingInjector(events),
    )
    assert daemon._switch_and_replace(6, "привет", "ru") is True
    assert events == ["start ru", "delete 6", "finish ru", "type 6 in ru"]
