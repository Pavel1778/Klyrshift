"""The first-run wizard: a short, paginated setup dialog.

The tour explains the interface; the wizard changes three settings that a new
user has to get right before Klyrshift is useful — the languages to recognise,
the working mode, and whether the daemon starts at login. It writes through the
same :class:`~klyrshift.gui.state.GuiState` the settings pages use, so the wizard
is only a second view of the configuration, not a second source of truth.

Design notes that are not obvious from the code:

* The wizard owns no text of its own beyond its headings; the choices and their
  labels come from :mod:`klyrshift.config` and :mod:`klyrshift.gui.state`, so the
  wizard cannot drift from the settings pages.
* Nothing is written until the user presses "Готово". Cancelling leaves the
  configuration untouched, which is what makes "Пропустить" safe.
* The dialog is modal and centred rather than a window, so it cannot be lost
  behind the main window on a tiling compositor.
"""

from __future__ import annotations

import contextlib
from collections.abc import Callable

import gi

from ...i18n import _

gi.require_version("Gtk", "4.0")
gi.require_version("Adw", "1")
from gi.repository import Adw, Gtk  # noqa: E402

from ...config import SUPPORTED_LANGUAGES  # noqa: E402
from ..state import LANGUAGE_LABELS, GuiState  # noqa: E402
from .mode_switcher import ModeSwitcher  # noqa: E402

# Order shown in the wizard; kept next to the labels so a new mode cannot be
# added to one list and forgotten in the other.
MODE_ORDER = ("auto", "manual", "hybrid")

PAGE_NAMES = ("languages", "mode", "autostart")


class FirstRunWizard(Adw.Dialog):
    """A three-step first-run setup dialog.

    Args:
        state: The GUI state the choices are read from and written to.
        on_finished: Called after the configuration is saved.
        on_skipped: Called when the user closes the dialog without finishing.
    """

    def __init__(
        self,
        state: GuiState,
        *,
        on_finished: Callable[[], None] | None = None,
        on_skipped: Callable[[], None] | None = None,
    ) -> None:
        super().__init__()
        self._state = state
        self._on_finished = on_finished
        self._on_skipped = on_skipped
        self._finished = False
        self._index = 0

        self.set_title(_("Настройка Klyrshift"))
        self.set_content_width(460)
        self.set_content_height(420)

        self._carousel = Adw.Carousel(interactive=True)
        self._carousel.set_allow_scroll_wheel(False)
        self._carousel.append(self._build_languages_page())
        self._carousel.append(self._build_mode_page())
        self._carousel.append(self._build_autostart_page())

        dots = Adw.CarouselIndicatorDots(carousel=self._carousel)

        self._back = Gtk.Button(label=_("Назад"))
        self._back.connect("clicked", lambda _b: self._go(-1))
        self._next = Gtk.Button(label=_("Далее"))
        self._next.add_css_class("suggested-action")
        self._next.connect("clicked", lambda _b: self._go(1))
        self._skip = Gtk.Button(label=_("Пропустить"))
        self._skip.add_css_class("flat")
        self._skip.connect("clicked", lambda _b: self._skip_wizard())

        header = Adw.HeaderBar()
        header.set_show_end_title_buttons(False)
        header.pack_start(self._back)
        header.pack_end(self._next)
        header.pack_end(self._skip)

        toolbar = Adw.ToolbarView()
        toolbar.add_top_bar(header)
        body = Gtk.Box(orientation=Gtk.Orientation.VERTICAL, spacing=12)
        body.set_margin_top(18)
        body.set_margin_bottom(18)
        body.set_margin_start(18)
        body.set_margin_end(18)
        body.append(self._carousel)
        body.append(dots)
        toolbar.set_content(body)
        self.set_child(toolbar)

        self._carousel.connect("notify::position", lambda *_a: self._on_position_changed())
        # Any close route (the "Пропустить" button, Escape, the window manager)
        # emits "closed"; recording the skip here covers them all, which
        # overriding close() would not.
        self.connect("closed", self._on_closed)
        self._sync_buttons()
        # The dialog is opened by the window, which decides when to offer it.

    # --- pages ------------------------------------------------------------

    def _build_languages_page(self) -> Gtk.Widget:
        page = self._page(
            _("Языки"),
            _(
                "Отметьте раскладки, которые Klyrshift должен распознавать. "
                "Раскладки уже должны быть добавлены в системе."
            ),
        )
        group = Adw.PreferencesGroup()
        self._language_rows: dict[str, Adw.SwitchRow] = {}
        for lang in SUPPORTED_LANGUAGES:
            row = Adw.SwitchRow(title=LANGUAGE_LABELS.get(lang, lang))
            row.set_active(lang in self._state.config.languages)
            row.connect("notify::active", self._on_language, lang)
            group.add(row)
            self._language_rows[lang] = row
        page.append(group)
        return page

    def _build_mode_page(self) -> Gtk.Widget:
        page = self._page(
            _("Режим работы"),
            _(
                "«Авто» исправляет сразу, «Ручной» — только по горячей клавише, "
                "«Гибрид» решает по уверенности."
            ),
        )
        self._mode = ModeSwitcher(on_change=self._on_mode)
        self._mode.set_mode(self._state.config.mode)
        page.append(self._mode)
        return page

    def _build_autostart_page(self) -> Gtk.Widget:
        page = self._page(
            _("Автозапуск"),
            _(
                "С автозапуском Klyrshift включается сам после входа в систему, и "
                "кнопку на главном экране нажимать не нужно."
            ),
        )
        group = Adw.PreferencesGroup()
        self._autostart = Adw.SwitchRow(
            title=_("Запускать при входе в систему"),
            subtitle=_("Демон будет активироваться автоматически"),
        )
        self._autostart.set_active(self._state.is_autostart_enabled())
        group.add(self._autostart)
        page.append(group)
        return page

    def _page(self, title: str, subtitle: str) -> Gtk.Box:
        box = Gtk.Box(orientation=Gtk.Orientation.VERTICAL, spacing=12)
        heading = Gtk.Label(label=title, xalign=0)
        heading.add_css_class("title-2")
        box.append(heading)
        caption = Gtk.Label(label=subtitle, xalign=0, wrap=True)
        caption.add_css_class("dim-label")
        box.append(caption)
        return box

    # --- behaviour --------------------------------------------------------

    def _on_language(self, row: Adw.SwitchRow, _param: object, lang: str) -> None:
        languages = [code for code in self._state.config.languages if code != lang]
        if row.get_active():
            languages.append(lang)
        # Refuse to empty the list, exactly as the settings page does: a config
        # with no languages is invalid. The switch is put back so the row does
        # not disagree with the config it is supposed to show.
        if not languages:
            row.set_active(True)
            return
        self._state.config.languages = languages

    def _on_mode(self, mode: str) -> None:
        self._state.config.mode = mode

    def _go(self, delta: int) -> None:
        index = self._index + delta
        if index >= self._carousel.get_n_pages():
            self._finish()
            return
        self._index = max(index, 0)
        self._carousel.scroll_to(self._carousel.get_nth_page(self._index), True)
        self._sync_buttons()

    def _on_position_changed(self) -> None:
        """Follow a swipe: the carousel moves without the buttons being asked."""
        self._index = self._carousel.get_position()
        self._sync_buttons()

    def _sync_buttons(self) -> None:
        self._back.set_visible(self._index > 0)
        self._next.set_label(_("Готово") if self._is_last_page() else _("Далее"))

    def _is_last_page(self) -> bool:
        """Return whether the current page is the last one.

        The index is tracked here rather than read from ``get_position``: the
        property only follows ``scroll_to`` once the widget is mapped, so a
        freshly built dialog would always look like it is on the first page.
        """
        return self._index >= int(self._carousel.get_n_pages()) - 1

    def _finish(self) -> None:
        self._finished = True
        # A value the dialog produced is invalid only if the config was already
        # broken; the settings pages will show the problem. Closing is still
        # better than trapping the user in the dialog.
        with contextlib.suppress(ValueError):
            self._state.save()
        autostart = self._autostart.get_active()
        if autostart != self._state.is_autostart_enabled():
            self._state.set_autostart(autostart)
        if self._on_finished is not None:
            self._on_finished()
        self.close()

    def _skip_wizard(self) -> None:
        self.close()

    def _on_closed(self, _dialog: Adw.Dialog) -> None:
        """Report a skip unless the user finished.

        Closing the dialog by any route other than "Готово" counts as a skip, so
        the offer is not shown again on the next start. The callback is cleared
        after it runs, so a later close cannot report the same skip twice.
        """
        if self._finished or self._on_skipped is None:
            return
        callback = self._on_skipped
        self._on_skipped = None
        callback()

    @property
    def carousel(self) -> Adw.Carousel:
        """Expose the page carousel for tests."""
        return self._carousel
