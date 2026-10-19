"""A keyboard reference: the app's shortcuts and the effective text hotkeys.

The window is fully operable from the keyboard, but nothing told the user which
keys do what -- the only discoverable shortcut was the tour's arrow-key
navigation. This dialog lists the window accelerators next to the daemon
hotkeys read from the live config, so the reference cannot drift from what is
actually bound.
"""

from __future__ import annotations

from typing import Final

import gi

from ...i18n import _

gi.require_version("Gtk", "4.0")
gi.require_version("Adw", "1")
from gi.repository import Adw, Gtk  # noqa: E402

# Window accelerators, as ``(keys, what it does)``. ``keys`` uses the GTK
# accelerator syntax so the label and the binding share one spelling.
WINDOW_SHORTCUTS: Final[tuple[tuple[str, str], ...]] = (
    ("Ctrl+?", "Эта справка по клавишам"),
    ("Ctrl+Page_Down", "Следующая вкладка"),
    ("Ctrl+Page_Up", "Предыдущая вкладка"),
    ("Escape", "Закрыть диалог"),
)

# Daemon hotkeys shown in the dialog, as ``(config field, what it does)``.
# Read from ``Config`` at build time so a rebind is reflected immediately.
HOTKEY_FIELDS: Final[tuple[tuple[str, str], ...]] = (
    ("hotkey_fix_last_word", "Исправить последнее слово"),
    ("hotkey_undo_last_fix", "Отменить последнее исправление"),
    ("hotkey_toggle_layout_last_word", "Сменить раскладку последнего слова"),
    ("hotkey_accept_suggestion", "Принять отложенное предложение"),
    ("hotkey_toggle_mode", "Переключить режим"),
    ("hotkey_reload_config", "Перезагрузить конфигурацию"),
)


def _shortcut_row(keys: str, description: str) -> Adw.ActionRow:
    """One row: the keys on the right, the description on the left."""
    row = Adw.ActionRow(title=_(description))
    label = Gtk.Label(label=keys)
    label.add_css_class("dim-label")
    label.add_css_class("monospace")
    row.add_suffix(label)
    return row


def build_shortcuts_dialog(config: object) -> Adw.Dialog:
    """Return the keyboard reference dialog for ``config``.

    The daemon hotkeys come from ``config`` so the list matches what is bound;
    an unset hotkey is shown as "not assigned" rather than an empty row.
    """
    dialog = Adw.Dialog()
    dialog.set_title(_("Клавиши"))
    dialog.set_content_width(460)

    toolbar = Adw.ToolbarView()
    header = Adw.HeaderBar()
    header.set_show_end_title_buttons(False)
    close = Gtk.Button(label=_("Понятно"))
    close.add_css_class("suggested-action")
    close.connect("clicked", lambda _b: dialog.close())
    header.pack_end(close)
    toolbar.add_top_bar(header)

    page = Adw.PreferencesPage()
    window_group = Adw.PreferencesGroup(
        title=_("Окно"),
        description=_("Работают, когда окно настроек в фокусе."),
    )
    for keys, description in WINDOW_SHORTCUTS:
        window_group.add(_shortcut_row(keys, description))
    page.add(window_group)

    hotkey_group = Adw.PreferencesGroup(
        title=_("Исправление текста"),
        description=_("Действуют во всей системе, а не только в окне Klyrshift."),
    )
    for field, description in HOTKEY_FIELDS:
        value = getattr(config, field, "")
        hotkey_group.add(_shortcut_row(value or _("не назначено"), description))
    page.add(hotkey_group)

    scrolled = Gtk.ScrolledWindow()
    scrolled.set_policy(Gtk.PolicyType.NEVER, Gtk.PolicyType.AUTOMATIC)
    scrolled.set_child(page)
    toolbar.set_content(scrolled)
    dialog.set_child(toolbar)
    return dialog
