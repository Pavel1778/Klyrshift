"""Languages group: enable a language and install/remove its dictionary.

The settings page already had an enable/disable switch per language, but nothing
put a word list on disk — so switching a language on only made the daemon look
for a dictionary that was not there. This widget pairs the switch with the two
actions that were missing: **Установить** (download the extended dictionary) and
**Удалить** (delete it and disable the language).

The widget owns no I/O. It reports intent through ``on_toggle``, ``on_install``
and ``on_remove``; the page runs the download on a worker thread and calls
:meth:`set_busy` / :meth:`refresh` around it. That keeps the GTK code free of
network calls and the behaviour testable without a display.
"""

from __future__ import annotations

from collections.abc import Callable

import gi

from ...i18n import _

gi.require_version("Gtk", "4.0")
gi.require_version("Adw", "1")
from gi.repository import Adw, Gtk  # noqa: E402

from ...langstore import LanguageStatus  # noqa: E402


class LanguageRow(Adw.ActionRow):
    """One language: an enable switch, a status line, and install/remove buttons."""

    def __init__(
        self,
        status: LanguageStatus,
        on_toggle: Callable[[str, bool], None],
        on_install: Callable[[str], None],
        on_remove: Callable[[str], None],
    ) -> None:
        super().__init__(title=status.label)
        self._language = status.language
        self._on_toggle = on_toggle
        self._on_install = on_install
        self._on_remove = on_remove

        self._switch = Gtk.Switch()
        self._switch.set_valign(Gtk.Align.CENTER)
        self._switch.set_active(status.enabled)
        self._toggle_handler = self._switch.connect("notify::active", self._on_switch_changed)
        self.add_prefix(self._switch)

        self._install_button = Gtk.Button(label=_("Установить"))
        self._install_button.add_css_class("flat")
        self._install_button.connect("clicked", self._on_install_clicked)
        self.add_suffix(self._install_button)

        self._remove_button = Gtk.Button(icon_name="user-trash-symbolic")
        self._remove_button.add_css_class("flat")
        self._remove_button.set_tooltip_text(_("Удалить словарь с диска"))
        self._remove_button.connect("clicked", self._on_remove_clicked)
        self.add_suffix(self._remove_button)

        self._spinner = Gtk.Spinner()
        self.add_suffix(self._spinner)

        self.refresh(status)

    @property
    def language(self) -> str:
        """The language code this row controls."""
        return self._language

    @property
    def switch(self) -> Gtk.Switch:
        """Expose the enable switch for tests."""
        return self._switch

    @property
    def install_button(self) -> Gtk.Button:
        """Expose the install button for tests."""
        return self._install_button

    @property
    def remove_button(self) -> Gtk.Button:
        """Expose the remove button for tests."""
        return self._remove_button

    def refresh(self, status: LanguageStatus) -> None:
        """Re-render the row from ``status`` (called after install/remove)."""
        self.set_subtitle(status.state_text)
        self._switch.handler_block(self._toggle_handler)
        self._switch.set_active(status.enabled)
        self._switch.handler_unblock(self._toggle_handler)
        self._install_button.set_visible(status.can_install and not status.installed)
        self._remove_button.set_visible(status.installed)

    def set_busy(self, busy: bool) -> None:
        """Show a spinner and block the buttons while a download runs."""
        self._spinner.set_visible(busy)
        if busy:
            self._spinner.start()
        else:
            self._spinner.stop()
        self._install_button.set_sensitive(not busy)
        self._remove_button.set_sensitive(not busy)

    def _on_switch_changed(self, switch: Gtk.Switch, _param: object) -> None:
        self._on_toggle(self._language, switch.get_active())

    def _on_install_clicked(self, _button: Gtk.Button) -> None:
        self._on_install(self._language)

    def _on_remove_clicked(self, _button: Gtk.Button) -> None:
        self._on_remove(self._language)


class LanguagesGroup(Adw.PreferencesGroup):
    """A group of :class:`LanguageRow` widgets, one per supported language."""

    def __init__(
        self,
        statuses: list[LanguageStatus],
        on_toggle: Callable[[str, bool], None],
        on_install: Callable[[str], None],
        on_remove: Callable[[str], None],
        title: str = _("Языки"),
        description: str = _("Какие раскладки Klyrshift должен распознавать"),
    ) -> None:
        super().__init__(title=title, description=description)
        self._rows: dict[str, LanguageRow] = {}
        for status in statuses:
            row = LanguageRow(status, on_toggle, on_install, on_remove)
            self.add(row)
            self._rows[status.language] = row

    @property
    def rows(self) -> dict[str, LanguageRow]:
        """Expose the rows by language code for tests."""
        return self._rows

    def refresh(self, statuses: list[LanguageStatus]) -> None:
        """Re-render every row from a fresh list of statuses."""
        for status in statuses:
            row = self._rows.get(status.language)
            if row is not None:
                row.refresh(status)

    def set_busy(self, language: str, busy: bool) -> None:
        """Toggle the busy state of one row."""
        row = self._rows.get(language)
        if row is not None:
            row.set_busy(busy)
