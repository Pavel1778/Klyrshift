"""The "Помощь и обучение" page: tour replay, settings help and diagnostics.

Everything the user needs after the first run lives here: re-run the tour, look
up a setting, run the environment check, and read the list of supported languages
and known limitations. The page never shows on its own; it is opened from the
header menu, so nothing is forced on the user.
"""

from __future__ import annotations

from collections.abc import Callable

import gi

gi.require_version("Gtk", "4.0")
gi.require_version("Adw", "1")
from gi.repository import Adw, Gtk  # noqa: E402

from ..config import SUPPORTED_LANGUAGES  # noqa: E402
from ..doctor import FAIL, OK, WARN, CheckResult, collect_checks  # noqa: E402
from ..onboarding import HELP_TOPICS  # noqa: E402
from .async_utils import run_in_background  # noqa: E402
from .state import LANGUAGE_LABELS  # noqa: E402
from .widgets.help_button import show_help_dialog  # noqa: E402

# The diagnostics table maps the doctor's statuses to symbols. Kept in step with
# :mod:`klyrshift.doctor`, which owns the vocabulary.
_STATUS_ICON = {
    OK: "object-select-symbolic",
    WARN: "dialog-warning-symbolic",
    FAIL: "dialog-error-symbolic",
}

# Known limitations, stated plainly. Every line here is a real constraint of the
# current code, not a roadmap item: the app must not promise more than it does.
LIMITATIONS = (
    "Только Linux (Debian и производные). Windows и macOS не поддерживаются.",
    "Переключение раскладки опирается на раскладки, уже настроенные в системе.",
    "Защита полей пароля зависит от AT-SPI (доступность) и не срабатывает, "
    "если окружение его не предоставляет.",
    "Определение активного приложения работает через D-Bus GNOME Shell; "
    "в других окружениях функция «раскладка по приложениям» недоступна.",
    "Пользовательские языковые пакеты пока не подключены: доступны только " "встроенные раскладки.",
    "Проверка обновлений — единственная сетевая функция и выключена по умолчанию.",
)


class HelpPage(Adw.PreferencesPage):
    """Help and learning page: repeat the tour, browse topics, run diagnostics."""

    def __init__(self, on_start_tour: Callable[[], object] | None = None) -> None:
        super().__init__()
        self._on_start_tour = on_start_tour
        self._topic_rows: list[Gtk.Widget] = []

        self._build_tour_group()
        self._build_topics_group()
        self._build_diagnostics_group()
        self._build_languages_group()
        self._build_limitations_group()

    # --- tour -----------------------------------------------------------------
    def _build_tour_group(self) -> None:
        group = Adw.PreferencesGroup(
            title="Помощь и обучение",
            description="Повторите обучение, найдите объяснение настройки или "
            "проверьте готовность окружения. Ничего из этого не показывается "
            "автоматически.",
        )
        row = Adw.ActionRow(
            title="Повторить вводный тур",
            subtitle="Пошаговое знакомство с главным экраном и основными настройками",
        )
        button = Gtk.Button(label="Начать тур")
        button.add_css_class("pill")
        button.set_valign(Gtk.Align.CENTER)
        button.connect("clicked", self._on_tour_clicked)
        row.add_suffix(button)
        group.add(row)
        self.add(group)

    def _on_tour_clicked(self, _button: Gtk.Button) -> None:
        if self._on_start_tour is not None:
            self._on_start_tour()

    # --- topics ---------------------------------------------------------------
    def _build_topics_group(self) -> None:
        group = Adw.PreferencesGroup(
            title="Объяснения настроек",
            description="Кратко — что делает настройка; подробнее — как она работает.",
        )
        for topic in HELP_TOPICS.values():
            row = Adw.ActionRow(title=topic.title, subtitle=topic.short)
            button = Gtk.Button(icon_name="help-about-symbolic")
            button.add_css_class("flat")
            button.add_css_class("help-button")
            button.set_valign(Gtk.Align.CENTER)
            button.set_tooltip_text(f"Справка: {topic.title}")
            button.connect("clicked", lambda _b, t=topic: show_help_dialog(t, _b))
            row.add_suffix(button)
            group.add(row)
            self._topic_rows.append(row)
        self.add(group)

    # --- diagnostics ----------------------------------------------------------
    def _build_diagnostics_group(self) -> None:
        group = Adw.PreferencesGroup(title="Диагностика")
        row = Adw.ActionRow(
            title="Проверить окружение",
            subtitle="Права на устройства ввода, раскладки и инструменты переключения",
        )
        self._diagnostics_button = Gtk.Button(label="Проверить")
        self._diagnostics_button.add_css_class("pill")
        self._diagnostics_button.set_valign(Gtk.Align.CENTER)
        self._diagnostics_button.connect("clicked", self._on_diagnostics_clicked)
        row.add_suffix(self._diagnostics_button)
        group.add(row)

        self._diagnostics_output = Gtk.Label(xalign=0.0)
        self._diagnostics_output.set_wrap(True)
        self._diagnostics_output.set_justify(Gtk.Justification.LEFT)
        self._diagnostics_output.add_css_class("monospace")
        self._diagnostics_output.set_visible(False)
        self._diagnostics_output.set_selectable(True)
        group.add(self._diagnostics_output)
        self.add(group)

    def _on_diagnostics_clicked(self, _button: Gtk.Button) -> None:
        self._diagnostics_button.set_sensitive(False)
        self._diagnostics_output.set_label("Проверка…")
        self._diagnostics_output.set_visible(True)
        run_in_background(collect_checks, self._apply_diagnostics)

    def _apply_diagnostics(self, results: object) -> None:
        self._diagnostics_button.set_sensitive(True)
        if not isinstance(results, list) or not results:
            self._diagnostics_output.set_label("Не удалось выполнить проверку.")
            return
        self._diagnostics_output.set_label(format_diagnostics(results))

    # --- languages ------------------------------------------------------------
    def _build_languages_group(self) -> None:
        group = Adw.PreferencesGroup(
            title="Поддерживаемые языки",
            description="Встроенные раскладки, доступные для распознавания",
        )
        names = ", ".join(LANGUAGE_LABELS.get(lang, lang) for lang in SUPPORTED_LANGUAGES)
        row = Adw.ActionRow(title="Раскладки", subtitle=names)
        group.add(row)
        self.add(group)

    # --- limitations ----------------------------------------------------------
    def _build_limitations_group(self) -> None:
        group = Adw.PreferencesGroup(title="Известные ограничения")
        for text in LIMITATIONS:
            row = Adw.ActionRow(title=text)
            row.add_css_class("property")
            group.add(row)
        self.add(group)

    @property
    def topic_rows(self) -> list[Gtk.Widget]:
        """Expose the help-topic rows for tests."""
        return self._topic_rows

    @property
    def diagnostics_button(self) -> Gtk.Button:
        """Expose the diagnostics button (also a tour target)."""
        return self._diagnostics_button

    @property
    def diagnostics_output(self) -> Gtk.Label:
        """Expose the diagnostics label for tests."""
        return self._diagnostics_output


def format_diagnostics(results: list[CheckResult]) -> str:
    """Render ``results`` as a plain-text block for the help page."""
    name_width = max((len(r.name) for r in results), default=0)
    lines: list[str] = []
    for result in results:
        marker = {"OK": "✓", "WARN": "!", "FAIL": "✗"}.get(result.status, "?")
        lines.append(f"{marker} {result.name.ljust(name_width)}  {result.detail}")
        if result.hint and result.status != OK:
            lines.append(f"  {' ' * name_width}  ↳ {result.hint}")
    return "\n".join(lines)


__all__ = ["LIMITATIONS", "HelpPage", "format_diagnostics"]
