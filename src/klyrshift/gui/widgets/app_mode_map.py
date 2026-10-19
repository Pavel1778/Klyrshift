"""Editable mapping of application name to a correction mode.

The global ``mode`` is a single setting, but the right mode depends on what the
user is doing: an editor with code should never be rewritten automatically,
while a chat window benefits from it. This group lets the user pin a mode per
application; an application absent from the map keeps the global mode.

The mode is chosen from a combo, not typed, so an invalid value cannot be
entered (the config would reject it anyway, but the UI should not offer it).
"""

from __future__ import annotations

from collections.abc import Callable

import gi

from ...config import VALID_MODES
from ...i18n import _

gi.require_version("Gtk", "4.0")
gi.require_version("Adw", "1")
from gi.repository import Adw, Gtk  # noqa: E402

# Display order of the modes in the combo; the values are the config values.
MODE_LABELS: dict[str, str] = {
    "auto": "Автоматически",
    "hybrid": "Гибрид",
    "manual": "Вручную",
}


class AppModeMap(Adw.PreferencesGroup):
    """A preferences group mapping an application to a correction mode.

    The caller owns persistence: changes are reported through ``on_change`` as
    a fresh ``{app: mode}`` mapping.
    """

    def __init__(
        self,
        title: str,
        description: str = "",
        mapping: dict[str, str] | None = None,
        on_change: Callable[[dict[str, str]], None] | None = None,
        on_detect: Callable[[], str | None] | None = None,
    ) -> None:
        super().__init__(title=title, description=description)
        self._on_change = on_change
        self._mapping: dict[str, str] = dict(mapping or {})
        self._on_detect = on_detect
        self._rows: list[Adw.ActionRow] = []

        self._app_entry = Adw.EntryRow(title=_("Имя процесса"))
        if on_detect is not None:
            detect_button = Gtk.Button(label=_("Определить"))
            detect_button.add_css_class("flat")
            detect_button.connect("clicked", self._on_detect_clicked)
            self._app_entry.add_suffix(detect_button)
        self.add(self._app_entry)

        self._mode_row = Adw.ComboRow(
            title=_("Режим"),
            model=Gtk.StringList.new([_(MODE_LABELS[mode]) for mode in VALID_MODES]),
        )
        self._mode_row.set_selected(0)
        add_button = Gtk.Button(icon_name="list-add-symbolic")
        add_button.add_css_class("flat")
        add_button.set_tooltip_text(_("Добавить"))
        add_button.connect("clicked", self._on_add)
        self._mode_row.add_suffix(add_button)
        self.add(self._mode_row)

        self._render()

    def _render(self) -> None:
        for row in self._rows:
            self.remove(row)
        self._rows = []
        for app, mode in sorted(self._mapping.items()):
            row = Adw.ActionRow(title=app, subtitle=_(MODE_LABELS.get(mode, mode)))
            remove = Gtk.Button(icon_name="user-trash-symbolic")
            remove.add_css_class("flat")
            remove.connect("clicked", self._on_remove, app)
            row.add_suffix(remove)
            self.add(row)
            self._rows.append(row)

    def _on_add(self, _button: Gtk.Button | None) -> None:
        app = self._app_entry.get_text().strip().lower()
        index = self._mode_row.get_selected()
        if not app or not 0 <= index < len(VALID_MODES):
            return
        self._mapping[app] = VALID_MODES[index]
        self._app_entry.set_text("")
        self._render()
        self._emit()

    def _on_remove(self, _button: Gtk.Button, app: str) -> None:
        if app in self._mapping:
            del self._mapping[app]
            self._render()
            self._emit()

    def _on_detect_clicked(self, _button: Gtk.Button) -> None:
        if self._on_detect is None:
            return
        name = self._on_detect()
        if name:
            self._app_entry.set_text(name)

    def _emit(self) -> None:
        if self._on_change is not None:
            self._on_change(dict(self._mapping))

    @property
    def mapping(self) -> dict[str, str]:
        """Return the current application-to-mode mapping."""
        return dict(self._mapping)
