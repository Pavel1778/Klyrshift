"""About dialog."""

from __future__ import annotations

import gi

from ..i18n import _

gi.require_version("Gtk", "4.0")
gi.require_version("Adw", "1")
from gi.repository import Adw, Gtk  # noqa: E402

from .. import __version__, repo  # noqa: E402

REPOSITORY = repo.REPO_URL


def build_about_window(parent: Gtk.Window | None = None) -> Adw.AboutDialog:
    """Create the About dialog with version, links and credits."""
    dialog = Adw.AboutDialog(
        application_name="Klyrshift",
        application_icon="klyrshift",
        version=__version__,
        developer_name="Pavel1778",
        license_type=Gtk.License.MIT_X11,
        website=REPOSITORY,
        issue_url=f"{REPOSITORY}/issues",
        comments=(
            _(
                "Автоматическое исправление текста, набранного не в той раскладке.\n"
                "Текст не покидает машину: демон не делает сетевых запросов."
            )
        ),
    )
    dialog.set_developers(["Pavel1778"])
    dialog.add_credit_section(
        _("Идеи и вдохновение"),
        ["g3kb-switch", "gswitch", "evdev", "niri-punto", "PolterType"],
    )
    # CC-BY-SA-4.0 requires attribution, and the base frequency lists that ship
    # in the .deb are FrequencyWords content under that licence (the code above
    # them stays MIT). Without this credit the dialog names only the code
    # licence and hides where the word data comes from.
    dialog.add_credit_section(
        _("Данные словарей"),
        [_("FrequencyWords (hermitdave/FrequencyWords) — CC-BY-SA-4.0")],
    )
    return dialog
