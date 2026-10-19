"""Onboarding scenario, guided tour and context help for Klyrshift.

This module holds no GTK import on purpose. The tour scenario, the help texts and
the persisted onboarding state are plain data, so they can be validated by the
test-suite without a display and reused by the CLI. The GUI only renders them.

The texts live here as the single source of truth: every help topic names the
``Config`` fields it explains, and ``tests/test_onboarding.py`` fails when a field
is renamed, so the help cannot drift away from the settings it describes.
"""

from __future__ import annotations

import json
import logging
import os
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Final

from .config import state_dir

logger = logging.getLogger(__name__)

# Bump when the scenario changes enough that a user who finished the old tour
# should be offered the new one. Finishing or skipping records this number, so a
# routine start never re-opens the tour.
TOUR_VERSION: Final[int] = 1

# The wizard is versioned separately from the tour: the two are independent
# offers, and changing one must not re-open the other.
WIZARD_VERSION: Final[int] = 1

ONBOARDING_FILE_NAME: Final[str] = "onboarding.json"


@dataclass(frozen=True)
class TourStep:
    """One step of the guided tour, bound to a real widget.

    Attributes:
        key: Stable identifier, also used by tests.
        page: Name of the view-stack page the step belongs to; the window
            switches to it before highlighting ``target``.
        target: Widget name looked up in the window; an empty string centres the
            card with no highlight (the closing step).
        title: Short heading shown in the card.
        short: One-paragraph explanation.
        details: Longer explanation, revealed only when the user asks for it.
        position: Preferred card side, one of ``auto``/``top``/``bottom``.
    """

    key: str
    page: str
    target: str
    title: str
    short: str
    details: str
    position: str = "auto"


# The scenario follows the order in which a new user needs the features. Every
# target below exists in the current GUI, so no step can highlight a widget that
# is not there; a target that goes missing at runtime is skipped, not faked.
TOUR_STEPS: Final[tuple[TourStep, ...]] = (
    TourStep(
        key="home",
        page="home",
        target="home.toggle",
        title="Главный экран",
        short=(
            "Большая кнопка включает и выключает Klyrshift. Под ней — текущая "
            "раскладка, режим и время с последнего исправления."
        ),
        details=(
            "Выключенная кнопка означает, что демон остановлен и текст не "
            "анализируется. Включённая — что демон читает нажатия и исправляет "
            "слова. Ниже кнопки есть переключатель «Запускать при входе в "
            "систему»: с ним Klyrshift включается сам после входа в сеанс, и "
            "нажимать кнопку каждый раз не нужно."
        ),
    ),
    TourStep(
        key="languages",
        page="settings",
        target="settings.languages",
        title="Языки",
        short=(
            "Отметьте раскладки, которые Klyrshift должен распознавать. "
            "По умолчанию включены английская и русская."
        ),
        details=(
            "Каждая включённая раскладка должна быть настроена в системе: "
            "Klyrshift переключает уже существующие раскладки и не создаёт новые. "
            "Если раскладка не добавлена в настройках системы, переключение на "
            "неё не сработает. Список доступных языков показывает встроенные "
            "раскладки; пользовательские языковые пакеты подключаются отдельно и "
            "сейчас находятся в разработке."
        ),
    ),
    TourStep(
        key="mode",
        page="home",
        target="home.mode",
        title="Режим работы",
        short=(
            "«Авто» исправляет сразу, «Ручной» — только по горячей клавише, "
            "«Гибрид» — сам решает по уверенности."
        ),
        details=(
            "В режиме «Авто» уверенное исправление применяется без спроса. "
            "В «Ручном» ничего не меняется, пока вы не нажмёте горячую клавишу: "
            "это безопасный выбор, если не хочется неожиданных правок. "
            "«Гибрид» исправляет автоматически только однозначные случаи, а "
            "остальные оставляет на клавишу. Режим применяется сразу, "
            "перезапуск демона не нужен."
        ),
    ),
    TourStep(
        key="hotkey",
        page="settings",
        target="settings.hotkey_fix",
        title="Горячая клавиша исправления",
        short=(
            "По умолчанию — двойной Shift. Нажмите её, чтобы исправить последнее " "слово вручную."
        ),
        details=(
            "Двойной Shift работает даже в «Ручном» режиме и не мешает обычному "
            "набору. Изменить сочетание можно кнопкой «Изменить»: нажмите её, "
            "затем дважды нужный модификатор (Shift, Ctrl или Alt) либо задайте "
            "комбинацию. Esc отменяет изменение. Рядом настраивается клавиша "
            "отмены последнего исправления."
        ),
    ),
    TourStep(
        key="diagnostics",
        page="help",
        target="help.diagnostics",
        title="Проверка окружения",
        short=(
            "Кнопка «Проверить окружение» показывает, всё ли готово для работы: "
            "права на устройства, раскладки, инструменты переключения."
        ),
        details=(
            "Диагностика проверяет доступ к /dev/input, наличие uinput, "
            "установленные утилиты переключения раскладки и настройки "
            "конфигурации. Если что-то не готово, в отчёте будет указано, что "
            "именно и как исправить. Запускать её стоит после установки и при "
            "любой проблеме с исправлением."
        ),
    ),
    TourStep(
        key="finish",
        page="help",
        target="",
        title="Готово",
        short=(
            "Это всё. Тур можно повторить в любой момент на странице «Помощь», "
            "а рядом с настройками есть кнопки «?» с пояснениями."
        ),
        details=(
            "Раздел «Помощь и обучение» собирает повторный запуск тура, "
            "объяснения настроек, диагностику, список поддерживаемых языков и "
            "известные ограничения. Ничего из этого не показывается "
            "принудительно после первого запуска."
        ),
    ),
)


@dataclass(frozen=True)
class HelpTopic:
    """Context help for one setting or group of settings.

    Attributes:
        key: Stable identifier used by the GUI and tests.
        title: Human-readable name of the setting.
        short: What the setting does and when to use it.
        details: How it works, side effects, platform requirements, limits.
        fields: ``Config`` fields the topic documents. Validated against the
            dataclass by the test-suite so a rename cannot silently orphan it.
    """

    key: str
    title: str
    short: str
    details: str
    fields: tuple[str, ...] = ()


HELP_TOPICS: Final[dict[str, HelpTopic]] = {
    "mode": HelpTopic(
        key="mode",
        title="Режим работы",
        short="Когда Klyrshift исправляет текст: сразу, только по клавише или по уверенности.",
        details=(
            "«Авто» применяет уверенные исправления сразу. «Ручной» не меняет "
            "текст без горячей клавиши. «Гибрид» исправляет автоматически только "
            "однозначные случаи, остальные оставляет на клавишу. Опции T9 и "
            "пунктуации управляются своими переключателями и в «Ручном» режиме "
            "продолжают работать, если включены отдельно."
        ),
        fields=("mode",),
    ),
    "languages": HelpTopic(
        key="languages",
        title="Языки",
        short="Какие раскладки распознавать при проверке слова.",
        details=(
            "Включайте только те раскладки, которые реально добавлены в системе: "
            "Klyrshift переключает существующие раскладки, а не создаёт новые. "
            "Нужен минимум один язык. Отключение языка исключает его из проверок "
            "и из списка кандидатов при исправлении."
        ),
        fields=("languages", "layouts"),
    ),
    "hotkeys": HelpTopic(
        key="hotkeys",
        title="Горячие клавиши",
        short="Клавиши для ручного исправления, отмены и смены раскладки слова.",
        details=(
            "«Исправить последнее слово» по умолчанию — двойной Shift; работает "
            "и в ручном режиме. «Отменить последнее исправление» возвращает "
            "предыдущий текст, пока не истекло окно отмены. «Сменить раскладку "
            "последнего слова» разворачивает слово в другую раскладку, даже если "
            "оно выглядит правильным. «Не передавать хоткей в приложение» "
            "поглощает нажатие, чтобы оно не дошло до активного окна."
        ),
        fields=(
            "hotkeys_enabled",
            "hotkey_fix_last_word",
            "hotkey_undo_last_fix",
            "hotkey_toggle_layout_last_word",
            "hotkey_swallow",
            "hotkey_double_tap_ms",
        ),
    ),
    "triggers": HelpTopic(
        key="triggers",
        title="Триггеры",
        short="По каким клавишам слово считается законченным и проверяется.",
        details=(
            "Пробел и Enter включены по умолчанию. Tab и знаки препинания "
            "добавляются по желанию: в редакторах кода точка и скобки часто "
            "заканчивают слово раньше, чем нужно. Таймаут анализа — запасной "
            "вариант для слова без разделителя (длинный URL или составное слово)."
        ),
        fields=("on_space", "on_enter", "on_tab", "on_punctuation", "punctuation_chars"),
    ),
    "timing": HelpTopic(
        key="timing",
        title="Тайминги",
        short="Паузы, которые делают вставку текста надёжной в медленных приложениях.",
        details=(
            "«Пауза после Backspace» нужна для Chromium и Electron: они "
            "обрабатывают Backspace асинхронно, и без паузы первый символ "
            "остаётся от старого слова. «Пауза после триггера» даёт приложению "
            "обработать пробел или Enter до удаления. Слишком большие значения "
            "заметны как задержка, поэтому увеличивайте их только при проблемах."
        ),
        fields=("analysis_timeout", "backspace_settle_ms", "trigger_settle_ms"),
    ),
    "confidence": HelpTopic(
        key="confidence",
        title="Порог уверенности",
        short="Насколько однозначным должно быть исправление, чтобы примениться автоматически.",
        details=(
            "Выше порог — меньше ложных срабатываний, но больше случаев, "
            "оставленных на горячую клавишу. Ниже порог — больше автоматики, но "
            "выше риск неверной правки. В «Гибриде» отдельный порог "
            "«Гибрид: порог автозамены» решает, что делать автоматически, а что "
            "показать как подсказку."
        ),
        fields=("confidence_threshold", "hybrid_confidence", "min_word_length"),
    ),
    "context": HelpTopic(
        key="context",
        title="Контекстный анализ",
        short="Учитывать соседние слова при выборе исправления.",
        details=(
            "Контекст помогает, когда само слово правдоподобно в обеих "
            "раскладках. Вес контекста задаёт, насколько сильно соседние слова "
            "влияют на решение. Отключение контекста ускоряет работу и делает "
            "решение предсказуемым: слово оценивается отдельно от окружения."
        ),
        fields=("context_analysis", "context_weight"),
    ),
    "guards": HelpTopic(
        key="guards",
        title="Защита от лишних правок",
        short="Что Klyrshift никогда не трогает: капс, цифры, адреса, пароли.",
        details=(
            "Слова капсом и слова с цифрами часто являются кодами и "
            "идентификаторами, поэтому их можно исключить. Email и URL "
            "пропускаются по умолчанию. «Не трогать поля пароля» опирается на "
            "AT-SPI (средства доступности): если окружение его не предоставляет, "
            "защита не сработает, и это известное ограничение, а не гарантия. "
            "Свой regex-пропуск добавляет личные правила; неверное выражение "
            "подсвечивается и не сохраняется."
        ),
        fields=(
            "ignore_all_caps",
            "ignore_with_digits",
            "ignore_emails_urls",
            "password_guard",
            "identifier_guard",
            "custom_skip_regex",
        ),
    ),
    "quiet_hours": HelpTopic(
        key="quiet_hours",
        title="Тихие часы",
        short="Промежуток, в котором автоматическая коррекция приостановлена.",
        details=(
            "В тихие часы автопереключение не срабатывает, но ручное исправление "
            "по горячей клавише продолжает работать. Удобно, когда за одной "
            "машиной работают с разными языками или ночью не нужны правки."
        ),
        fields=("quiet_hours_enabled", "quiet_hours_start", "quiet_hours_end"),
    ),
    "exceptions": HelpTopic(
        key="exceptions",
        title="Исключения приложений",
        short="В каких программах не исправлять текст автоматически.",
        details=(
            "Исключение отключает автокоррекцию в указанном приложении: полезно "
            "для терминалов, IDE и игр, где важны точные символы. Отдельный "
            "список «Исправлять даже в ручном режиме» возвращает автоматику для "
            "выбранных программ, когда включён ручной режим."
        ),
        fields=("exceptions_apps", "exceptions_force_in_manual"),
    ),
    "app_layouts": HelpTopic(
        key="app_layouts",
        title="Раскладка по приложениям",
        short="Включать нужную раскладку при переключении на приложение.",
        details=(
            "Например, для терминала можно закрепить английскую раскладку. "
            "Определение активного приложения опирается на D-Bus GNOME Shell; в "
            "других окружениях оно может быть недоступно, тогда функция не "
            "срабатывает. Переключатель «Переключать раскладку по приложению» "
            "включает поведение целиком."
        ),
        fields=("app_layouts", "app_layout_switch"),
    ),
    "dictionary": HelpTopic(
        key="dictionary",
        title="Словарь",
        short="Размер встроенного словаря и путь к своему списку слов.",
        details=(
            "Больший словарь распознаёт больше слов, но занимает больше памяти и "
            "чуть медленнее проверяет редкие слова. Свой словарь — текстовый файл "
            "со словами по одному в строке; он дополняет встроенный. Слова из "
            "словаря не исправляются автоматически."
        ),
        fields=("dictionary_size", "dictionary_custom_path"),
    ),
    "typo": HelpTopic(
        key="typo",
        title="Исправление опечаток (T9)",
        short="Менять слово на ближайшее из словаря, если вариант однозначен.",
        details=(
            "Механизм отдельный от исправления раскладки и выключен по "
            "умолчанию. Он срабатывает только при однозначном варианте: одна "
            "опечатка в коротком слове, до двух — в слове от шести символов. "
            "Пороги можно ужесточить, если правки кажутся слишком смелыми."
        ),
        fields=(
            "typo_mode",
            "typo_correction",
            "typo_max_distance",
            "typo_max_distance_long",
            "typo_min_word_length",
            "typo_debounce_seconds",
        ),
    ),
    "punctuation": HelpTopic(
        key="punctuation",
        title="Пунктуация",
        short="Заменять дефисы, многоточия и кавычки на типографские.",
        details=(
            "Три независимых правила: дефисы, многоточие, типографские кавычки, "
            "плюс исправление лишних пробелов. Выключено по умолчанию, потому "
            "что в коде и командных строках обычные символы важнее красивых."
        ),
        fields=(
            "punctuation_mode",
            "punctuation_correction",
            "punctuation_dashes",
            "punctuation_ellipsis",
            "punctuation_smart_quotes",
            "punctuation_fix_spacing",
        ),
    ),
    "snippets": HelpTopic(
        key="snippets",
        title="Текстовые сокращения",
        short="Превращать короткий триггер в длинный текст.",
        details=(
            "Файл сокращений связывает триггер с текстом, например !!email → "
            "адрес. Выключено по умолчанию. Убедитесь, что триггеры не "
            "встречаются в обычном тексте, иначе подстановка сработает неожиданно."
        ),
        fields=("text_expander_enabled", "text_expander_snippets_path"),
    ),
    "learning": HelpTopic(
        key="learning",
        title="Обучение",
        short="Приложение наблюдает за вами и подстраивается под то, что вы правите.",
        details=(
            "Обучение включено всегда и работает незаметно. Оно замечает, какие "
            "слова вы оставляете без изменений, какие исправляете сами и какие "
            "правки отменяете (Ctrl+Z или горячая клавиша отмены). Если вы "
            "отменили исправление, это слово больше не трогается до конца "
            "сессии. Слово, которое вы оставляете неизменным достаточно часто, "
            "попадает в словарь как «правильное» и перестаёт исправляться. "
            "Сами слова держатся только в памяти демона и никогда не "
            "записываются на диск; сохраняются лишь счётчики (сколько слов "
            "увидено, исправлено, отклонено)."
        ),
        fields=(
            "learning_enabled",
            "learning_promote_threshold",
            "learning_max_words",
        ),
    ),
    "selection": HelpTopic(
        key="selection",
        title="Исправление выделенного текста",
        short="Исправить раскладку у выделенного фрагмента по горячей клавише.",
        details=(
            "Выделите текст и нажмите сочетание (по умолчанию Ctrl+Shift+L). "
            "Работает и для фрагмента внутри строки. Требует доступа к буферу "
            "обмена и инъекции ввода; в приложениях с защищённым вводом может не "
            "сработать."
        ),
        fields=("selection_fix_enabled", "selection_fix_hotkey"),
    ),
    "notifications": HelpTopic(
        key="notifications",
        title="Уведомления и звук",
        short="Показывать уведомление или звук при исправлении и ошибке.",
        details=(
            "По умолчанию выключено, чтобы не отвлекать. Уведомление содержит "
            "только факт исправления и раскладки, без самого текста."
        ),
        fields=("notify_on_fix", "notify_on_error", "sound_on_fix"),
    ),
    "tray": HelpTopic(
        key="tray",
        title="Иконка в трее",
        short="Показывать значок в системном трее для быстрого доступа.",
        details=(
            "Требует поддержки AppIndicator в окружении. Если трей недоступен, "
            "иконка не появится, и это не мешает работе демона."
        ),
        fields=("tray_enabled",),
    ),
    "backend": HelpTopic(
        key="backend",
        title="Способ вставки текста",
        short="Каким механизмом заменять текст в активном приложении.",
        details=(
            "«auto» выбирает рабочий способ сам. uinput эмулирует клавиатуру на "
            "уровне ядра и работает в большинстве приложений. Выбор другого "
            "бэкенда имеет смысл только при проблемах с вставкой в конкретной "
            "программе."
        ),
        fields=("backend", "switch_method"),
    ),
    "undo": HelpTopic(
        key="undo",
        title="Отмена исправлений",
        short="Сколько исправлений можно вернуть и как долго они доступны.",
        details=(
            "Глубина истории задаёт, сколько последних исправлений хранится в "
            "памяти. Окно отмены ограничивает время, в течение которого отмена "
            "ещё возможна. Отмена не изменяет историю исправлений и не трогает "
            "текст в других приложениях."
        ),
        fields=("undo_history_depth", "undo_window_seconds", "history_size"),
    ),
    "update_check": HelpTopic(
        key="update_check",
        title="Проверка обновлений",
        short="Раз в сутки запрашивать номер последней версии на GitHub.",
        details=(
            "Единственная функция, использующая сеть, и она выключена по "
            "умолчанию. Запрос передаёт только факт проверки; текст, набранный "
            "пользователем, никогда не отправляется. При выключенной опции "
            "Klyrshift не делает сетевых запросов вообще."
        ),
        fields=("update_check_enabled",),
    ),
    "logs": HelpTopic(
        key="logs",
        title="Логи",
        short="Подробность журнала и размер файла до ротации.",
        details=(
            "Уровень DEBUG полезен при разборе проблемы, но пишет больше строк. "
            "Содержимое набранного текста в журнал не попадает: записываются "
            "только метаданные (длина слова, раскладки, время)."
        ),
        fields=("log_level", "log_rotation_mb"),
    ),
    "autostart": HelpTopic(
        key="autostart",
        title="Запуск при входе в систему",
        short="Включать Klyrshift автоматически после входа в сеанс.",
        details=(
            "Настройка меняет состояние автозапуска для текущего пользователя и "
            "не требует прав root. Отключение останавливает автозапуск, но не "
            "удаляет программу."
        ),
        fields=(),
    ),
}

# ``Config`` field -> topic key, so a settings row can ask for its own help.
FIELD_HELP: Final[dict[str, str]] = {
    field_name: topic.key for topic in HELP_TOPICS.values() for field_name in topic.fields
}


def help_for_field(field_name: str) -> HelpTopic | None:
    """Return the help topic documenting ``field_name``, if any."""
    key = FIELD_HELP.get(field_name)
    return HELP_TOPICS.get(key) if key else None


@dataclass
class OnboardingState:
    """Persisted record of what the user has already seen.

    Attributes:
        completed_version: ``TOUR_VERSION`` the user finished, or ``0``.
        skipped_version: ``TOUR_VERSION`` the user skipped, or ``0``.
        last_step: Index of the last step shown, so an interrupted tour can be
            resumed instead of restarted.
        wizard_completed_version: ``WIZARD_VERSION`` the user finished, or ``0``.
        wizard_skipped_version: ``WIZARD_VERSION`` the user skipped, or ``0``.
    """

    completed_version: int = 0
    skipped_version: int = 0
    last_step: int = 0
    wizard_completed_version: int = 0
    wizard_skipped_version: int = 0

    def to_dict(self) -> dict[str, Any]:
        """Return a plain ``dict`` for JSON serialisation."""
        return {
            "completed_version": self.completed_version,
            "skipped_version": self.skipped_version,
            "last_step": self.last_step,
            "wizard_completed_version": self.wizard_completed_version,
            "wizard_skipped_version": self.wizard_skipped_version,
        }


def onboarding_path() -> Path:
    """Return the path of the onboarding state file."""
    return state_dir() / ONBOARDING_FILE_NAME


def load_onboarding_state(path: Path | None = None) -> OnboardingState:
    """Load the onboarding state, falling back to defaults.

    A missing or unreadable file is not an error: the user simply sees the tour
    offer once more. Nothing here can raise into the GUI startup path.
    """
    target = path or onboarding_path()
    try:
        raw = json.loads(target.read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return OnboardingState()
    if not isinstance(raw, dict):
        return OnboardingState()
    return OnboardingState(
        completed_version=_as_int(raw.get("completed_version")),
        skipped_version=_as_int(raw.get("skipped_version")),
        last_step=_as_int(raw.get("last_step")),
        wizard_completed_version=_as_int(raw.get("wizard_completed_version")),
        wizard_skipped_version=_as_int(raw.get("wizard_skipped_version")),
    )


def save_onboarding_state(state: OnboardingState, path: Path | None = None) -> bool:
    """Persist ``state`` atomically; return whether it was written.

    The write goes to a temporary file in the same directory and is then moved
    over the target, so an interrupted write cannot leave a half-written file.
    """
    target = path or onboarding_path()
    tmp = target.with_name(f".{target.name}.tmp-{os.getpid()}")
    try:
        target.parent.mkdir(parents=True, exist_ok=True)
        tmp.write_text(json.dumps(state.to_dict(), ensure_ascii=False), encoding="utf-8")
        os.replace(tmp, target)
    except OSError:
        tmp.unlink(missing_ok=True)
        logger.warning("Could not save the onboarding state to %s", target, exc_info=True)
        return False
    return True


def should_offer_tour(state: OnboardingState) -> bool:
    """Return whether the first-run tour offer should be shown.

    Only a user who has neither finished nor skipped the current scenario sees
    the offer, so the tour is never forced on someone who already declined it.
    """
    return TOUR_VERSION not in (state.completed_version, state.skipped_version)


def should_offer_wizard(state: OnboardingState) -> bool:
    """Return whether the first-run wizard should be shown.

    Like the tour offer, but tracked with its own version so the two do not
    re-open each other.
    """
    return WIZARD_VERSION not in (
        state.wizard_completed_version,
        state.wizard_skipped_version,
    )


def _as_int(value: object) -> int:
    """Coerce ``value`` to ``int``, defaulting to ``0`` for anything else."""
    if isinstance(value, bool):
        return 0
    if isinstance(value, int):
        return value
    return 0


__all__ = [
    "FIELD_HELP",
    "HELP_TOPICS",
    "ONBOARDING_FILE_NAME",
    "TOUR_STEPS",
    "TOUR_VERSION",
    "WIZARD_VERSION",
    "HelpTopic",
    "OnboardingState",
    "TourStep",
    "help_for_field",
    "load_onboarding_state",
    "onboarding_path",
    "save_onboarding_state",
    "should_offer_tour",
    "should_offer_wizard",
]
