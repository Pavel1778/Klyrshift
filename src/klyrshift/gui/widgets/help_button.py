"""Context help: a "?" button and the dialog it opens.

The texts come from :mod:`klyrshift.onboarding`, so a settings row and its help
share one source. The dialog shows the short answer first and the detailed one
behind a disclosure, matching the two levels the tour uses.
"""

from __future__ import annotations

import gi

from ...i18n import _

gi.require_version("Gtk", "4.0")
gi.require_version("Adw", "1")
from gi.repository import Adw, Gtk  # noqa: E402

from ...onboarding import HelpTopic  # noqa: E402


def build_help_content(topic: HelpTopic) -> Gtk.Box:
    """Build the body of a help dialog: short text, then the details."""
    box = Gtk.Box(orientation=Gtk.Orientation.VERTICAL, spacing=10)

    short = Gtk.Label(label=_(topic.short), xalign=0.0, wrap=True)
    short.set_justify(Gtk.Justification.LEFT)
    box.append(short)

    expander = Gtk.Expander(label=_("Подробнее"))
    details = Gtk.Label(label=_(topic.details), xalign=0.0, wrap=True)
    details.set_justify(Gtk.Justification.LEFT)
    details.add_css_class("dim-label")
    details.set_margin_top(6)
    expander.set_child(details)
    box.append(expander)
    return box


def show_help_dialog(topic: HelpTopic, parent: Gtk.Widget | None = None) -> Adw.Dialog:
    """Present a help dialog for ``topic``.

    Returns the dialog so tests can inspect it without a running main loop.
    """
    dialog = Adw.Dialog()
    dialog.set_title(_(topic.title))
    dialog.set_content_width(420)

    toolbar = Adw.ToolbarView()
    header = Adw.HeaderBar()
    header.set_show_end_title_buttons(False)
    close = Gtk.Button(label=_("Понятно"))
    close.add_css_class("suggested-action")
    close.connect("clicked", lambda _b: dialog.close())
    header.pack_end(close)
    toolbar.add_top_bar(header)

    scrolled = Gtk.ScrolledWindow()
    scrolled.set_policy(Gtk.PolicyType.NEVER, Gtk.PolicyType.AUTOMATIC)
    scrolled.set_child(build_help_content(topic))
    toolbar.set_content(scrolled)
    dialog.set_child(toolbar)

    root = parent.get_root() if parent is not None else None
    if isinstance(root, Gtk.Window):
        dialog.present(root)
    return dialog


class HelpButton(Gtk.Button):
    """A compact "?" button that opens the context help for one topic."""

    def __init__(self, topic: HelpTopic) -> None:
        super().__init__(icon_name="help-about-symbolic")
        self._topic = topic
        self.add_css_class("flat")
        self.add_css_class("help-button")
        self.set_valign(Gtk.Align.CENTER)
        self.set_tooltip_text(_("Справка: {0}").format(_(topic.title)))
        self.update_property(
            [Gtk.AccessibleProperty.LABEL], [_("Справка: {0}").format(_(topic.title))]
        )
        self.connect("clicked", self._on_clicked)

    def _on_clicked(self, _button: Gtk.Button) -> None:
        show_help_dialog(self._topic, self)

    @property
    def topic(self) -> HelpTopic:
        """Expose the topic for tests."""
        return self._topic


__all__ = ["HelpButton", "build_help_content", "show_help_dialog"]
