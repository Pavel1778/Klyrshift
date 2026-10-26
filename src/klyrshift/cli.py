"""Command line interface for Klyrshift.

The CLI is intentionally thin: it starts and stops the daemon, inspects status,
manages the configuration file and can trigger a manual correction.
"""

from __future__ import annotations

import argparse
import logging
import os
import shutil
import signal
import subprocess
import sys
import time
from collections.abc import Callable
from pathlib import Path

from . import __version__
from .collect_logs import collect_logs
from .config import (
    Config,
    cache_dir,
    config_path,
    load_config,
    preview_migrations,
    save_config,
)
from .converter import LayoutConverter
from .detector import LanguageDetector
from .dictionary import load_user_dictionary
from .doctor import run_doctor
from .i18n import SUPPORTED_LOCALES, _, set_locale
from .injector import TextInjector
from .switcher import LayoutSwitcher, key_sender_for

logger = logging.getLogger(__name__)

LOCK_FILE_NAME = "daemon.lock"

# Russian source strings, translated where they are printed: this module is
# imported before ``--lang`` is parsed, so translating at import time would
# freeze whichever locale happened to be active first.
MSG_NOT_RUNNING = "Klyrshift не запущен."
MSG_STOPPED = "Klyrshift остановлен."
MSG_STOPPED_FORCED = "Klyrshift не ответил на SIGTERM; отправлен SIGKILL."
MSG_KILLED = "Klyrshift принудительно завершён (SIGKILL)."
MSG_ALREADY_STOPPED = "Klyrshift уже остановлен."
MSG_STARTED = "Klyrshift запущен."
MSG_AUTOSTART_INSTALLED = "Автозапуск установлен."
MSG_AUTOSTART_REMOVED = "Автозапуск удалён."
MSG_CONFIG_RESET = "Конфигурация сброшена к значениям по умолчанию."


def _lock_path() -> Path:
    """Return the path of the daemon lock file."""
    return cache_dir() / LOCK_FILE_NAME


def _read_pid() -> int | None:
    """Return the PID stored in the lock file, if any and alive.

    Delegates to :func:`klyrshift.daemon_control.read_pid` so the CLI and the
    GUI share one implementation, including the cleanup of a stale lock file.
    """
    from .daemon_control import read_pid

    return read_pid()


def _pid_alive(pid: int) -> bool:
    """Return ``True`` when a process with ``pid`` exists and has not exited.

    Delegates to :func:`klyrshift.daemon_control.pid_alive` so the CLI and the
    GUI agree on what "alive" means (a zombie is not alive).
    """
    from .daemon_control import pid_alive

    return pid_alive(pid)


def _autostart_path() -> Path:
    """Return the XDG autostart desktop file path.

    Delegates to :func:`klyrshift.daemon_control.autostart_path` so the CLI and
    the GUI can never disagree about which file they manage.
    """
    from .daemon_control import autostart_path

    return autostart_path()


def _config_home() -> Path:
    """Return ``XDG_CONFIG_HOME`` (or ``~/.config``)."""
    return Path(os.environ.get("XDG_CONFIG_HOME", Path.home() / ".config"))


def cmd_start(args: argparse.Namespace) -> int:
    """Start the daemon, either in the foreground or detached."""
    if _read_pid() is not None:
        print(_(MSG_STARTED))
        return 0
    if args.foreground:
        from .daemon import KlyrshiftDaemon
        from .logging_setup import setup_logging

        config = load_config()
        setup_logging(config.log_level, console=True)
        daemon = KlyrshiftDaemon(config, dry_run=args.dry_run)
        return daemon.run()

    # Delegate to the shared control module so ``start``, ``status`` and the GUI
    # toggle agree on one definition of "running" (the lock file, or the systemd
    # unit). The previous hand-rolled spawn/poll could report a start that the
    # very next ``status`` denied; one implementation cannot disagree with itself.
    from .daemon_control import last_error, start

    if start(dry_run=args.dry_run):
        print(_(MSG_STARTED))
        return 0
    reason = last_error()
    print(_("Не удалось запустить Klyrshift.") + (f" {reason}" if reason else ""))
    print(_("Смотрите логи: ~/.local/state/klyrshift/"))
    return 1


def cmd_stop(_args: argparse.Namespace) -> int:
    """Stop the daemon, however it was started.

    Delegates to :func:`klyrshift.daemon_control.stop` so the CLI agrees with
    the GUI: the systemd user unit is stopped first (it carries
    ``Restart=always`` and would otherwise respawn the daemon a few seconds
    later), then the lock-file PID is signalled, escalating to SIGKILL.
    """
    from .daemon_control import is_running, stop

    if not is_running():
        print(_(MSG_ALREADY_STOPPED))
        return 0
    if stop():
        print(_(MSG_STOPPED))
        return 0
    print(_("Не удалось остановить Klyrshift. Смотрите логи: ~/.local/state/klyrshift/"))
    return 1


def cmd_kill(_args: argparse.Namespace) -> int:
    """Force-stop a running daemon with SIGKILL, without a graceful attempt."""
    from .daemon_control import is_running, kill

    if not is_running():
        print(_(MSG_ALREADY_STOPPED))
        return 0
    if kill():
        print(_(MSG_KILLED))
        return 0
    print(_("Не удалось принудительно завершить Klyrshift."))
    return 1


def cmd_restart(_args: argparse.Namespace) -> int:
    """Restart the daemon, preserving whether it runs as a user service."""
    from .daemon_control import restart

    if restart():
        print(_(MSG_STARTED))
        return 0
    print(_("Не удалось перезапустить Klyrshift."))
    return 1


def cmd_status(_args: argparse.Namespace) -> int:
    """Print the daemon status and runtime environment."""
    from .daemon_control import is_running

    config = load_config()
    pid = _read_pid()
    # Use the same "running" definition as ``stop`` and the GUI toggle (the lock
    # file, or an active systemd user unit). Reading only the lock file would
    # report "not running" for a service daemon whose lock was not written yet,
    # disagreeing with the very next ``stop``.
    if is_running():
        print(
            _("Klyrshift запущен (PID {0}).").format(pid)
            if pid
            else _("Klyrshift запущен (systemd).")
        )
    else:
        print(_(MSG_NOT_RUNNING))

    injector = TextInjector(backend=config.backend)
    switcher = LayoutSwitcher(
        layouts=config.layouts,
        switch_method=config.switch_method,
        key_sender=key_sender_for(injector),
    )
    print(_("Раскладки: {0}").format(", ".join(config.layouts)))
    print(_("Текущая раскладка: {0}").format(switcher.get_current_layout(force=True)))
    print(_("Режим: {0}").format(config.mode))
    print(_("Переключение: {0}").format(switcher.describe()))
    print(_("Ввод текста: {0}").format(injector.describe()))
    print(_("Конфигурация: {0}").format(config_path()))
    return 0


def cmd_mode(args: argparse.Namespace) -> int:
    """Show or change the working mode (auto/manual/hybrid)."""
    config = load_config()
    if args.mode is None:
        print(config.mode)
        return 0
    config.mode = args.mode
    try:
        config.validate()
    except ValueError as exc:
        print(_("Недопустимый режим: {0}").format(exc))
        return 2
    save_config(config)
    # A running daemon holds its own config copy; ask it to reload so the new
    # mode takes effect immediately instead of at the next restart.
    from .daemon_control import is_running, reload_config

    if is_running():
        reload_config()
    print(_("Режим: {0}").format(config.mode))
    return 0


def cmd_app_mode(args: argparse.Namespace) -> int:
    """Show, set or clear the per-application correction mode."""
    config = load_config()
    if args.app is None:
        if not config.app_modes:
            print(_("Режимы по приложениям не заданы"))
            return 0
        for app, mode in sorted(config.app_modes.items()):
            print(f"{app}: {mode}")
        return 0
    app = args.app.strip().lower()
    if args.clear:
        config.app_modes.pop(app, None)
    else:
        if args.mode is None:
            print(config.app_modes.get(app, config.mode))
            return 0
        config.app_modes[app] = args.mode
    try:
        config.validate()
    except ValueError as exc:
        print(_("Недопустимый режим: {0}").format(exc))
        return 2
    save_config(config)
    # The daemon keeps its own config copy; reload so the override applies now.
    from .daemon_control import is_running, reload_config

    if is_running():
        reload_config()
    if args.clear:
        print(_("Режим по приложению удалён: {0}").format(app))
    else:
        print(_("Режим для {0}: {1}").format(app, config.app_modes[app]))
    return 0


def cmd_hotkeys(_args: argparse.Namespace) -> int:
    """Print the effective hotkeys, so the user can check what is bound.

    The daemon logs its bindings once at startup; this prints the same values
    on demand, which is what makes a stuck config value (``CTRL+CTRL``) visible
    without reading the journal.
    """
    config = load_config()

    def show(label: str, value: str, enabled: bool = True) -> None:
        print(_("{0}: {1}").format(label, value if value and enabled else _("(выключено)")))

    show(_("Исправление последнего слова"), config.hotkey_fix_last_word)
    show(_("Отмена последнего исправления"), config.hotkey_undo_last_fix)
    show(_("Смена раскладки последнего слова"), config.hotkey_toggle_layout_last_word)
    show(_("Переключение режима"), config.hotkey_toggle_mode)
    show(_("Перезагрузка конфигурации"), config.hotkey_reload_config)
    show(_("Правка выделенного"), config.selection_fix_hotkey, config.selection_fix_enabled)
    # The per-feature hotkeys stay visible even when the feature is off: the
    # binding is what the user configures, and the mode is reported next to it.
    show(_("Т9 (опечатки)"), config.typo_hotkey)
    show(_("Пунктуация"), config.punctuation_hotkey)
    print(_("Режим Т9: {0}").format(config.typo_mode))
    print(_("Режим пунктуации: {0}").format(config.punctuation_mode))
    print(_("Хоткеи: {0}").format(_("включены") if config.hotkeys_enabled else _("выключены")))
    print(_("Окно двойного тапа: {0} мс").format(config.hotkey_double_tap_ms))
    return 0


def cmd_undo(_args: argparse.Namespace) -> int:
    """Ask a running daemon to undo its most recent correction."""
    pid = _read_pid()
    if pid is None:
        print(_(MSG_NOT_RUNNING))
        return 1
    try:
        os.kill(pid, signal.SIGUSR1)
    except OSError as exc:
        print(_("Не удалось отменить исправление: {0}").format(exc))
        return 1
    print(_("Запрошена отмена последнего исправления."))
    return 0


def _cmd_learn_words(action: str, args: argparse.Namespace) -> int:
    """Handle ``learn list`` / ``promote`` / ``forget`` over the control socket.

    These words are the ones the daemon promoted from watching the user's typing;
    they live in memory only, so a one-shot CLI cannot read them from a file. It
    asks the daemon instead. When no daemon is running there is nothing to list
    or edit, and the command says so rather than silently doing nothing.
    """
    from . import control

    if action == "list":
        words = control.learn_list()
        if words is None:
            print(
                _("Демон не запущен: список выученных слов доступен только у работающего демона.")
            )
            return 1
        if not words:
            print(_("Выученных слов пока нет."))
            return 0
        print(_("Выученные слова ({0}):").format(len(words)))
        for word in words:
            print(f"  {word}")
        return 0

    word = (args.word or "").strip()
    if not word:
        print(_("Укажите слово: klyrshift learn {0} <слово>").format(action))
        return 2
    if action == "promote":
        result = control.learn_promote(word)
        if result is None:
            print(_("Демон не запущен: закрепить слово можно только у работающего демона."))
            return 1
        print(_("Слово «{0}» закреплено: оно больше не исправляется в этой сессии.").format(word))
        return 0
    result = control.learn_forget(word)
    if result is None:
        print(_("Демон не запущен: забыть слово можно только у работающего демона."))
        return 1
    print(_("Слово «{0}» забыто: оно снова может исправляться.").format(word))
    return 0


def cmd_learn(args: argparse.Namespace) -> int:
    """Show or change the always-on learning settings.

    The learned words themselves live in the daemon's memory only (nothing the
    user types is ever written to disk), so this reports the persisted
    *counters* and the current setting, never a word. ``learn list`` /
    ``promote`` / ``forget`` are the exception: the user names a word on
    purpose, and it is exchanged with the running daemon over the local control
    socket — it is still never written to the learning profile.
    """
    from .learning import LearningStore

    action = getattr(args, "learn_action", None)
    if action in {"list", "promote", "forget"}:
        return _cmd_learn_words(action, args)

    config = load_config()
    if args.on:
        config.learning_enabled = True
    if args.off:
        config.learning_enabled = False
    if args.on or args.off:
        config.validate()
        save_config(config)
        from .daemon_control import is_running, reload_config

        if is_running():
            reload_config()
    if args.reset:
        LearningStore().reset()
        print(_("Счётчики обучения сброшены."))
    stats = LearningStore().load()
    print(_("Обучение: {0}").format(_("включено") if config.learning_enabled else _("выключено")))
    print(_("Порог закрепления слова: {0}").format(config.learning_promote_threshold))
    print(_("Наблюдаемые слова хранятся только в памяти демона и никогда не пишутся на диск."))
    print(_("Слов увидено: {0}").format(stats.observed))
    print(_("Оставлено без изменений: {0}").format(stats.kept))
    print(_("Исправлено: {0}").format(stats.corrected))
    print(_("Отклонено (Ctrl+Z / отмена): {0}").format(stats.rejected))
    print(_("Закреплено слов: {0}").format(stats.promoted))
    return 0


def cmd_dict(args: argparse.Namespace) -> int:
    """Manage the user dictionary and the extended (frequency) dictionaries."""
    from .dictionary import (
        BUNDLED_DICTIONARY_LANGUAGES,
        add_user_word,
        default_extended_dictionary_dir,
        load_user_dictionary,
        save_user_dictionary,
    )

    action = args.dict_action

    if action in ("download", "import-file"):
        return _cmd_dict_extended(action, args, default_extended_dictionary_dir)

    if action in ("categories", "install", "list-installed", "remove-category"):
        return _cmd_dict_thematic(action, args, default_extended_dictionary_dir)

    if action in ("pack", "verify", "install-file", "uninstall-file"):
        return _cmd_dict_langpack(action, args, default_extended_dictionary_dir)

    path = config_path_for_dict()
    if action == "list":
        words = load_user_dictionary(str(path))
        if not words:
            print(_("Словарь пуст ({0}).").format(path))
            return 0
        print("\n".join(words))
        return 0
    if action == "add":
        if not args.word:
            print(_("Укажите слово: klyrshift dict add <слово>"))
            return 2
        words = add_user_word(args.word, str(path))
        print(_("Добавлено. Всего слов: {0}.").format(len(words)))
        return 0
    if action == "remove":
        if not args.word:
            print(_("Укажите слово: klyrshift dict remove <слово>"))
            return 2
        words = load_user_dictionary(str(path))
        remaining = [w for w in words if w.lower() != args.word.lower()]
        if len(remaining) == len(words):
            print(_("Слово {0!r} не найдено.").format(args.word))
            return 1
        save_user_dictionary(remaining, str(path))
        print(_("Удалено. Всего слов: {0}.").format(len(remaining)))
        return 0
    languages = "|".join(BUNDLED_DICTIONARY_LANGUAGES)
    print(
        _(
            "Использование:\n  klyrshift dict list|add <слово>|remove <слово>\n  klyrshift dict download <{0}>\n  klyrshift dict import-file <путь>\n  klyrshift dict categories\n  klyrshift dict install <категория> [--lang ru]\n  klyrshift dict list-installed\n  klyrshift dict remove-category <категория>\n  klyrshift dict pack <файл> --name <имя> --lang <язык> [--kind frequency]\n  klyrshift dict verify <пакет.tar.gz>\n  klyrshift dict install-file <пакет.tar.gz>\n  klyrshift dict uninstall-file <пакет.tar.gz>"
        ).format(languages)
    )
    return 2


def _cmd_dict_extended(
    action: str, args: argparse.Namespace, default_dir: Callable[[], Path]
) -> int:
    """Handle ``dict download`` / ``dict import-file`` (extended dictionaries)."""
    from .config import load_config, save_config
    from .dictionary import (
        download_extended_dictionary,
        extended_dictionary_path,
        import_dictionary_file,
    )

    config = load_config()
    directory = config.extended_dictionary_dir or str(default_dir())

    if action == "import-file":
        if not args.word:
            print(_("Укажите путь к файлу: klyrshift dict import-file ~/Downloads/ru-50k.txt"))
            return 2
        # The language is inferred from the file name prefix (``ru-50k.txt`` ->
        # ``ru``) unless an explicit --lang is given.
        language = getattr(args, "lang", "") or Path(args.word).name.split("-")[0].split(".")[0]
        if not language:
            print(_("Не удалось определить язык: klyrshift dict import-file <путь> --lang ru"))
            return 2
        try:
            count = import_dictionary_file(args.word, language, directory)
        except FileNotFoundError:
            print(_("Файл не найден: {0}").format(args.word))
            return 1
        except (OSError, ValueError) as exc:
            print(_("Не удалось импортировать словарь: {0}").format(exc))
            return 1
        _remember_extended_dir(config, directory, save_config)
        target = extended_dictionary_path(language, directory)
        print(_("Импортировано {0} слов ({1}) в {2}.").format(count, language, target))
        print(_("Перезапустите демон или нажмите хоткей перезагрузки конфигурации."))
        return 0

    if not args.word:
        print(_("Укажите язык: klyrshift dict download ru"))
        return 2
    try:
        target, count = download_extended_dictionary(args.word, directory)
    except ValueError as exc:
        print(str(exc))
        return 2
    except OSError as exc:
        print(_("Не удалось скачать словарь: {0}").format(exc))
        return 1
    _remember_extended_dir(config, directory, save_config)
    print(_("Скачано {0} слов ({1}) в {2}.").format(count, args.word, target))
    print(_("Перезапустите демон или нажмите хоткей перезагрузки конфигурации."))
    return 0


def _remember_extended_dir(
    config: Config, directory: str, save_config: Callable[[Config], Path]
) -> None:
    """Persist ``extended_dictionary_dir`` so the daemon loads the new list."""
    config.extended_dictionary_dir = directory
    save_config(config)


def _cmd_dict_thematic(
    action: str, args: argparse.Namespace, default_dir: Callable[[], Path]
) -> int:
    """Handle the thematic-dictionary actions (categories/install/...)."""
    from .config import load_config, save_config
    from .thematic import (
        CATEGORIES,
        category,
        category_slugs,
        disable_category,
        download_category,
        enable_category,
        installed_category_slugs,
    )

    config = load_config()
    directory = config.extended_dictionary_dir or str(default_dir())

    if action == "categories":
        enabled = set(config.installed_dict_categories)
        print(_("Категории тематических словарей:"))
        for cat in CATEGORIES:
            langs = ", ".join(cat.languages)
            mark = _(" [установлена]") if cat.slug in enabled else ""
            print(f"  {cat.slug:<12} {cat.title()} ({langs}){mark}")
        print(_("\nУстановка: klyrshift dict install <категория> --lang ru"))
        return 0

    if action == "list-installed":
        slugs = installed_category_slugs("ru", directory)
        print(_("Включённые категории: ") + ", ".join(config.installed_dict_categories))
        if slugs:
            print(_("Файлы на диске (ru): ") + ", ".join(slugs))
        else:
            print(_("Тематические файлы ещё не скачаны."))
        return 0

    slug = (args.word or "").strip().lower()
    if not slug:
        print(
            _("Укажите категорию: klyrshift dict {0} <{1}>").format(
                action, "|".join(category_slugs())
            )
        )
        return 2
    if category(slug) is None:
        print(
            _("Неизвестная категория {0!r}. Доступны: {1}.").format(
                slug, ", ".join(category_slugs())
            )
        )
        return 2

    if action == "remove-category":
        config.installed_dict_categories = disable_category(config.installed_dict_categories, slug)
        save_config(config)
        print(_("Категория {0!r} отключена. Файл на диске сохранён.").format(slug))
        return 0

    # action == "install"
    language = (getattr(args, "lang", "") or "ru").strip().lower()
    try:
        target, count = download_category(slug, language, directory)
    except ValueError as exc:
        print(str(exc))
        return 2
    except OSError as exc:
        print(_("Не удалось скачать категорию: {0}").format(exc))
        return 1
    config.installed_dict_categories = enable_category(config.installed_dict_categories, slug)
    _remember_extended_dir(config, directory, save_config)
    print(_("Установлено {0} слов ({1}/{2}) в {3}.").format(count, slug, language, target))
    print(_("Категория подключена. Перезапустите демон или нажмите хоткей перезагрузки."))
    return 0


def config_path_for_dict() -> Path:
    """Return the user-dictionary path from the current configuration."""
    from .dictionary import user_dictionary_path

    return user_dictionary_path(load_config().dictionary_custom_path)


def _cmd_dict_langpack(
    action: str, args: argparse.Namespace, default_dir: Callable[[], Path]
) -> int:
    """Handle the versioned language-package actions (pack/verify/install-file/...)."""
    from .config import load_config, save_config
    from .langpack import (
        PackageError,
        build_package,
        install_package,
        read_manifest,
        uninstall_package,
        verify_package,
    )

    config = load_config()
    directory = config.extended_dictionary_dir or str(default_dir())

    if action == "pack":
        requested = ([args.word] if args.word else []) + list(getattr(args, "file", []) or [])
        if not requested:
            print(
                _(
                    "Укажите файлы: klyrshift dict pack <файл> [--file <файл> ...] --name ru-50k --lang ru"
                )
            )
            return 2
        sources = [Path(p).expanduser() for p in requested]
        missing = [str(p) for p in sources if not p.is_file()]
        if missing:
            print(_("Файлы не найдены: ") + ", ".join(missing))
            return 1
        name = args.name or sources[0].stem
        language = (args.lang or "").strip().lower()
        if not language:
            # Infer from the name prefix, the same convention import-file uses.
            language = sources[0].name.split("-")[0].split(".")[0].lower()
        destination = Path(args.output).expanduser() if args.output else Path(f"{name}.tar.gz")
        try:
            manifest = build_package(
                sources,
                destination,
                name=name,
                language=language,
                kind=args.kind,
                version=args.package_version,
                license=args.license,
                source="klyrshift dict pack",
            )
        except (PackageError, OSError) as exc:
            print(_("Не удалось собрать пакет: {0}").format(exc))
            return 1
        print(
            _("Собран пакет {0} ({1}/{2}, {3}).").format(
                destination, manifest.kind, manifest.language, name
            )
        )
        for entry in manifest.files:
            print(
                _("  {0}: {1} слов, sha256 {2}…").format(entry.name, entry.words, entry.sha256[:12])
            )
        return 0

    if action == "verify":
        if not args.word:
            print(_("Укажите пакет: klyrshift dict verify <пакет.tar.gz>"))
            return 2
        archive = Path(args.word).expanduser()
        if not archive.is_file():
            print(_("Файл не найден: {0}").format(archive))
            return 1
        try:
            manifest = read_manifest(archive)
        except PackageError as exc:
            print(_("Пакет недействителен: {0}").format(exc))
            return 1
        problems = verify_package(archive, manifest)
        if problems:
            print(_("Пакет {0} не прошёл проверку:").format(archive))
            for problem in problems:
                print(f"  - {problem}")
            return 1
        print(_("Пакет {0} в порядке.").format(archive))
        print(
            _("  {0}/{1}, версия {2}, формат {3}, файлов {4}").format(
                manifest.kind,
                manifest.language,
                manifest.version,
                manifest.format,
                len(manifest.files),
            )
        )
        if manifest.license:
            print(_("  лицензия: {0}").format(manifest.license))
        return 0

    if action == "install-file":
        if not args.word:
            print(_("Укажите пакет: klyrshift dict install-file <пакет.tar.gz>"))
            return 2
        archive = Path(args.word).expanduser()
        if not archive.is_file():
            print(_("Файл не найден: {0}").format(archive))
            return 1
        try:
            result = install_package(archive, Path(directory))
        except PackageError as exc:
            print(_("Установка отклонена: {0}").format(exc))
            return 1
        except OSError as exc:
            print(_("Не удалось установить пакет: {0}").format(exc))
            return 1
        _remember_extended_dir(config, directory, save_config)
        print(
            _("Установлен пакет {0} ({1}/{2}): {3} файл(ов) в {4}.").format(
                result.manifest.name,
                result.manifest.kind,
                result.manifest.language,
                len(result.installed),
                directory,
            )
        )
        if result.replaced:
            print(
                _("Заменено файлов: {0} (старые версии сохранены как резерв).").format(
                    len(result.replaced)
                )
            )
        print(_("Перезапустите демон или нажмите хоткей перезагрузки конфигурации."))
        return 0

    # action == "uninstall-file"
    if not args.word:
        print(_("Укажите пакет: klyrshift dict uninstall-file <пакет.tar.gz>"))
        return 2
    archive = Path(args.word).expanduser()
    if not archive.is_file():
        print(_("Файл не найден: {0}").format(archive))
        return 1
    try:
        manifest = read_manifest(archive)
    except PackageError as exc:
        print(_("Пакет недействителен: {0}").format(exc))
        return 1
    removed = uninstall_package(
        manifest.kind, manifest.language, [f.name for f in manifest.files], Path(directory)
    )
    print(_("Удалено файлов: {0}.").format(len(removed)))
    return 0


def cmd_config(args: argparse.Namespace) -> int:
    """Show, edit, reset or migrate the configuration file."""
    if args.config_action == "show":
        path = config_path()
        if not path.exists():
            save_config(Config())
        # Loading applies migrations in memory *and* persists them, so what is
        # printed is what the daemon will actually use.
        load_config(path)
        print(path.read_text(encoding="utf-8"))
        pending = preview_migrations(path)
        if pending:
            # Only reachable when the file could not be rewritten (read-only
            # config dir): the runtime differs from the file, so say so instead
            # of silently disagreeing with the daemon.
            print(_("Предупреждение: значения в файле отличаются от действующих:"))
            for field, old, new in pending:
                print(_("  {0}: {1!r} -> {2!r} (не сохранено)").format(field, old, new))
            print(_("Проверьте права на каталог конфигурации."))
        return 0
    if args.config_action == "migrate":
        path = config_path()
        changes = preview_migrations(path)
        if not changes:
            print(_("Миграции не требуются: конфигурация актуальна."))
            return 0
        if args.dry_run:
            print(_("Будут применены и сохранены:"))
            for field, old, new in changes:
                print(f"  {field}: {old!r} -> {new!r}")
            return 0
        load_config(path)
        print(_("Миграции применены и сохранены в {0}:").format(path))
        for field, old, new in changes:
            print(f"  {field}: {old!r} -> {new!r}")
        return 0
    if args.config_action == "edit":
        editor = os.environ.get("EDITOR", "nano")
        if not config_path().exists():
            save_config(Config())
        try:
            # Not captured: the editor needs the terminal.
            return subprocess.run([editor, str(config_path())], check=False).returncode
        except OSError as exc:
            print(_("Не удалось запустить редактор {0}: {1}").format(editor, exc))
            return 1
    if args.config_action == "reset":
        save_config(Config())
        print(_(MSG_CONFIG_RESET))
        return 0
    if args.config_action == "path":
        print(config_path())
        return 0
    print(_("Использование: klyrshift config show|edit|reset|path"))
    return 2


def cmd_export(args: argparse.Namespace) -> int:
    """Write a JSON backup of the user settings."""
    from .backup import write_backup

    try:
        path = write_backup(Path(args.output).expanduser())
    except OSError as exc:
        print(_("Не удалось сохранить бэкап: {0}").format(exc))
        return 1
    print(_("Настройки сохранены в {0}.").format(path))
    return 0


def cmd_import(args: argparse.Namespace) -> int:
    """Restore user settings from a JSON backup."""
    from .backup import apply_backup, read_backup

    try:
        data = read_backup(Path(args.source).expanduser())
    except (OSError, ValueError) as exc:
        print(_("Не удалось прочитать бэкап: {0}").format(exc))
        return 1
    result = apply_backup(data)
    summary = ", ".join(f"{key}={value}" for key, value in result.items() if value)
    print(_("Восстановлено: {0}.").format(summary or _("ничего")))
    return 0


def _typo_correction_for_cli(
    text: str, current: str, detector: LanguageDetector, config: Config
) -> str | None:
    """Return a T9 correction for a single word, or ``None``.

    Mirrors ``KlyrshiftDaemon._typo_correction`` so ``klyrshift fix`` agrees
    with what the daemon would do to the same word: only an alpha word in the
    language the current layout types, only when T9 is enabled, and never a
    word the user taught or one with a structural separator.
    """
    from .daemon import _INTERNAL_SEPARATOR_RE
    from .typo import TypoCorrector

    if config.typo_mode == "off":
        return None
    word = text.strip()
    if len(word) < config.typo_min_word_length or not word.isalpha():
        return None
    if detector.is_user_word(word) or _INTERNAL_SEPARATOR_RE.search(word):
        return None
    language = detector.language_for_layout(current)
    if language is None:
        return None
    corrector = TypoCorrector(
        detector.ordered_vocabulary(language),
        max_distance=config.typo_max_distance,
        min_length=config.typo_min_word_length,
        long_word_threshold=config.typo_long_word_threshold,
        long_word_max_distance=config.typo_max_distance_long,
        top1_ratio_strict=config.typo_top1_ratio_strict,
    )
    suggestion = corrector.suggest(word)
    if suggestion is None or suggestion == word:
        return None
    if word[0].isupper():
        suggestion = suggestion[:1].upper() + suggestion[1:]
    return suggestion


def cmd_fix(args: argparse.Namespace) -> int:
    """Manually correct a piece of text."""
    config = load_config()
    text = args.text if args.text else sys.stdin.read().strip()
    if not text:
        print(_("Нет текста для исправления."))
        return 2

    converter = LayoutConverter()
    detector = LanguageDetector(
        converter=converter,
        stop_words=config.stop_words,
        min_word_length=config.min_word_length,
    )
    # Match the daemon: taught words must make an otherwise unknown token (a
    # brand such as ``vercel``) a valid target, or ``fix`` disagrees with it.
    detector.set_user_words(load_user_dictionary(config.dictionary_custom_path))
    injector = TextInjector(converter=converter, backend=config.backend)
    switcher = LayoutSwitcher(
        layouts=config.layouts,
        switch_method=config.switch_method,
        key_sender=key_sender_for(injector),
    )

    current = switcher.get_current_layout(force=True)
    target = detector.target_layout(text, current)
    if target is None:
        # Layout detection found nothing. Mirror the daemon's opt-in typo pass:
        # a single-word typo in the language the current layout types is fixed
        # in place, so ``fix --text "превет"`` gives ``привет`` when T9 is on.
        corrected = _typo_correction_for_cli(text, current, detector, config)
        if corrected is None:
            print(_("Исправление не требуется (раскладка {0}).").format(current))
            return 0
        # A typo fix never changes the layout, so the target stays ``current``.
        converted, target, kind = corrected, current, "typo"
    else:
        converted = converter.convert(text, current, target)
        kind = "layout"

    # Keep the dry-run contract identical to the daemon: report the intended
    # action to the logger as well as to stdout, then do not touch anything.
    logger.info("fix (%s): %d chars, %s -> %s", kind, len(text), current, target)
    if kind == "typo":
        print(f"{text} -> {converted} (typo)")
    else:
        print(f"{text} -> {converted} ({current} -> {target})")
    if args.dry_run:
        logger.info("Dry run: skipping layout switch and text replacement")
        print(_("Режим --dry-run: изменения не применены."))
        return 0
    if args.apply:
        if kind == "layout":
            switcher.switch_to(target)
            time.sleep(0.05)
        if not injector.replace_text(len(text), converted, target):
            print(_("Не удалось применить исправление."))
            return 1
    return 0


def _bundled_data_file(name: str) -> Path | None:
    """Return the path of a bundled data file (icon, service, desktop)."""
    try:
        from importlib import resources

        candidate = Path(str(resources.files("klyrshift") / "data" / name))
        if candidate.exists():
            return candidate
    except (ModuleNotFoundError, FileNotFoundError):
        pass
    # Fall back to the source tree layout when running from a checkout.
    fallback = Path(__file__).resolve().parent.parent.parent / "data" / name
    return fallback if fallback.exists() else None


def _run_quiet(argv: list[str]) -> int:
    """Run ``argv`` ignoring failures, including a missing executable.

    ``check=False`` does not suppress ``FileNotFoundError`` when the binary is
    absent (for example ``systemctl`` in a container), so it is caught here.
    """
    try:
        return subprocess.run(argv, check=False, capture_output=True).returncode
    except OSError as exc:
        logger.debug("Command %s failed: %s", argv, exc)
        return 127


def _launcher_path() -> str:
    """Return the path used to launch the daemon from the unit/autostart files."""
    launcher = shutil.which("klyrshift")
    if launcher:
        return launcher
    return str(Path(sys.executable).with_name("klyrshift"))


def _render_template(text: str) -> str:
    """Substitute the ``@BIN@`` placeholder with the launcher path."""
    return text.replace("@BIN@", _launcher_path())


def cmd_install_autostart(_args: argparse.Namespace) -> int:
    """Install the XDG autostart entry and enable the systemd user unit."""
    from .daemon_control import enable_autostart

    source = _bundled_data_file("klyrshift-autostart.desktop")
    if source is None:
        print(_("Не найден файл klyrshift-autostart.desktop."))
        return 1
    target = _autostart_path()
    target.parent.mkdir(parents=True, exist_ok=True)
    target.write_text(_render_template(source.read_text(encoding="utf-8")), encoding="utf-8")

    unit_source = _bundled_data_file("klyrshift.service")
    if unit_source is not None:
        unit_dir = _config_home() / "systemd" / "user"
        unit_dir.mkdir(parents=True, exist_ok=True)
        (unit_dir / "klyrshift.service").write_text(
            _render_template(unit_source.read_text(encoding="utf-8")), encoding="utf-8"
        )
        _run_quiet(["systemctl", "--user", "daemon-reload"])
    # Lift a mask left by a previous uninstall; otherwise the unit stays
    # suppressed and the entry has no effect.
    enable_autostart()
    print(_(MSG_AUTOSTART_INSTALLED))
    return 0


def cmd_uninstall_autostart(_args: argparse.Namespace) -> int:
    """Remove the XDG autostart entry and disable the systemd user unit."""
    from .daemon_control import disable_autostart

    # Delegates to the shared helper so the CLI and the GUI agree: it removes
    # the XDG entry, disables the unit and masks a globally enabled one (which
    # an unprivileged user cannot disable outright).
    disable_autostart()
    _run_quiet(["systemctl", "--user", "disable", "--now", "klyrshift.service"])
    print(_(MSG_AUTOSTART_REMOVED))
    return 0


def cmd_gui(_args: argparse.Namespace) -> int:
    """Open the GTK4 graphical interface."""
    from .gui import main as gui_main

    return gui_main()


def cmd_version(_args: argparse.Namespace) -> int:
    """Print the Klyrshift version."""
    print(f"Klyrshift {__version__}")
    return 0


def cmd_collect_logs(args: argparse.Namespace) -> int:
    """Build a diagnostic tarball for a bug report."""
    output_dir = Path(args.output).expanduser() if args.output else None
    try:
        archive = collect_logs(output_dir)
    except OSError as exc:
        print(_("Не удалось создать архив: {0}").format(exc))
        return 1
    print(_("Диагностический архив создан: {0}").format(archive))
    print(_("Приложите его к issue на GitHub (текст, который вы набирали, в него не попадает)."))
    return 0


def cmd_explain(args: argparse.Namespace) -> int:
    """Explain how the detector would treat a word, with calibrated confidence.

    Read-only: nothing is corrected, switched or written. Meant to answer "why
    did Klyrshift (not) touch this word?".
    """
    from .converter import LayoutConverter
    from .detector import LanguageDetector

    config = load_config()
    text = args.text if args.text else sys.stdin.read().strip()
    if not text:
        print(_("Нет текста для анализа."))
        return 2

    converter = LayoutConverter()
    detector = LanguageDetector(
        converter=converter,
        stop_words=config.stop_words,
        min_word_length=config.min_word_length,
        languages=tuple(config.languages),
        extended_dictionary_dir=config.extended_dictionary_dir,
        thematic_categories=config.installed_dict_categories,
    )
    detector.set_user_words(load_user_dictionary(config.dictionary_custom_path))
    switcher = LayoutSwitcher(
        layouts=config.layouts,
        switch_method=config.switch_method,
        key_sender=key_sender_for(TextInjector(backend=config.backend)),
    )
    current = args.layout or switcher.get_current_layout(force=True)

    target = detector.target_layout(text, current)
    confidence = detector.analyze(text, current)
    print(_("Текст: {0}").format(text))
    print(_("Текущая раскладка: {0}").format(current))
    if target is None:
        print(_("Решение: не исправлять."))
    else:
        converted = converter.convert(text, current, target)
        print(_("Решение: исправить в {0} -> {1}").format(target, converted))
    print(_("Оценка: {0}").format(confidence.describe()))
    if confidence.evidence == "model":
        print(_("  доля известных слов в цели: {0:.0%}").format(confidence.vocabulary_share))
    return 0


def cmd_doctor(_args: argparse.Namespace) -> int:
    """Run environment self-diagnosis and print a status table."""
    return run_doctor()


def cmd_verify(_args: argparse.Namespace) -> int:
    """Verify the installed package files against the md5sums manifest."""
    from .integrity import run_verify

    return run_verify()


def cmd_logs(args: argparse.Namespace) -> int:
    """Print (or follow) the daemon log."""
    from .logs import follow, log_file_path, read_tail

    path = log_file_path()
    lines = int(args.lines)
    level = args.level
    if args.follow:
        return follow(path, lines, level)
    if not path.exists():
        print(_("Лог не найден: {0}").format(path))
        print(_("Запустите демон: klyrshift start"))
        return 0
    for line in read_tail(path, lines, level):
        print(line)
    return 0


def build_parser() -> argparse.ArgumentParser:
    """Build the top-level argument parser."""
    parser = argparse.ArgumentParser(
        prog="klyrshift",
        description=_("Klyrshift — автоматический переключатель раскладки клавиатуры."),
    )
    parser.add_argument("--version", action="version", version=f"Klyrshift {__version__}")
    parser.add_argument(
        "--lang",
        default="",
        metavar="LOCALE",
        help=_("язык вывода: auto (по окружению) или один из: {0}").format(
            ", ".join(SUPPORTED_LOCALES)
        ),
    )
    subparsers = parser.add_subparsers(dest="command", required=True)

    start = subparsers.add_parser("start", help=_("запустить демон"))
    start.add_argument("--foreground", action="store_true", help=_("не уходить в фон"))
    start.add_argument(
        "--dry-run",
        action="store_true",
        help=_("анализировать, но не менять раскладку и не заменять текст"),
    )
    start.set_defaults(func=cmd_start)

    stop = subparsers.add_parser("stop", help=_("остановить демон"))
    stop.set_defaults(func=cmd_stop)

    kill = subparsers.add_parser("kill", help=_("принудительно завершить зависший демон (SIGKILL)"))
    kill.set_defaults(func=cmd_kill)

    status = subparsers.add_parser("status", help=_("показать статус"))
    status.set_defaults(func=cmd_status)

    mode = subparsers.add_parser("mode", help=_("показать или сменить режим (auto/manual/hybrid)"))
    mode.add_argument("mode", nargs="?", choices=["auto", "manual", "hybrid"], default=None)
    mode.set_defaults(func=cmd_mode)

    undo = subparsers.add_parser("undo", help=_("отменить последнее исправление"))
    undo.set_defaults(func=cmd_undo)

    app_mode = subparsers.add_parser(
        "app-mode",
        help=_("показать или задать режим для отдельного приложения"),
    )
    app_mode.add_argument("app", nargs="?", default=None, help=_("имя процесса, например code"))
    app_mode.add_argument(
        "mode",
        nargs="?",
        choices=["auto", "manual", "hybrid"],
        default=None,
        help=_("режим для этого приложения"),
    )
    app_mode.add_argument("--clear", action="store_true", help=_("убрать приложение из списка"))
    app_mode.set_defaults(func=cmd_app_mode)

    learn = subparsers.add_parser("learn", help=_("обучение: статистика, список слов, вкл/выкл"))
    learn.add_argument(
        "learn_action",
        nargs="?",
        choices=["list", "promote", "forget"],
        help=_("list — показать выученные слова; promote/forget — закрепить/забыть слово"),
    )
    learn.add_argument("word", nargs="?", help=_("слово для promote/forget"))
    learn.add_argument("--on", action="store_true", help=_("включить обучение"))
    learn.add_argument("--off", action="store_true", help=_("выключить обучение"))
    learn.add_argument("--reset", action="store_true", help=_("сбросить счётчики обучения"))
    learn.set_defaults(func=cmd_learn)

    hotkeys = subparsers.add_parser("hotkeys", help=_("показать действующие хоткеи"))
    hotkeys.set_defaults(func=cmd_hotkeys)

    dict_parser = subparsers.add_parser("dict", help=_("словарь слов, которые не исправлять"))
    dict_parser.add_argument(
        "dict_action",
        choices=[
            "list",
            "add",
            "remove",
            "download",
            "import-file",
            "categories",
            "install",
            "list-installed",
            "remove-category",
            "pack",
            "verify",
            "install-file",
            "uninstall-file",
        ],
        help=(
            _(
                "list/add/remove — словарь пользователя; download/import-file — базовые "
                "расширенные словари; categories/install/list-installed/remove-category — "
                "тематические словари; pack/verify/install-file/uninstall-file — "
                "версионированные пакеты языков (manifest + sha256)"
            )
        ),
    )
    dict_parser.add_argument(
        "word", nargs="?", help=_("слово (add/remove) или язык/путь (download/import-file)")
    )
    dict_parser.add_argument(
        "--lang", default="", help=_("язык для import-file/pack, если его нет в имени файла")
    )
    dict_parser.add_argument(
        "--file", action="append", default=[], help=_("дополнительный файл для dict pack")
    )
    dict_parser.add_argument("--name", default="", help=_("имя пакета для dict pack"))
    dict_parser.add_argument(
        "--kind",
        default="frequency",
        choices=["frequency", "thematic", "ngrams"],
        help=_("тип пакета для dict pack"),
    )
    dict_parser.add_argument("--output", default="", help=_("куда записать пакет (dict pack)"))
    dict_parser.add_argument(
        "--package-version", default="1.0.0", help=_("версия пакета (dict pack)")
    )
    dict_parser.add_argument("--license", default="", help=_("лицензия пакета (dict pack)"))
    dict_parser.set_defaults(func=cmd_dict)

    config = subparsers.add_parser("config", help=_("работа с конфигурацией"))
    config.add_argument("config_action", choices=["show", "edit", "reset", "path", "migrate"])
    config.add_argument(
        "--dry-run",
        action="store_true",
        help=_("для migrate: показать изменения, ничего не записывать"),
    )
    config.set_defaults(func=cmd_config)

    export = subparsers.add_parser("export", help=_("сохранить настройки в файл (JSON)"))
    export.add_argument(
        "output", nargs="?", default="klyrshift-backup.json", help=_("файл для бэкапа")
    )
    export.set_defaults(func=cmd_export)

    imp = subparsers.add_parser("import", help=_("восстановить настройки из файла (JSON)"))
    imp.add_argument("source", help=_("файл бэкапа"))
    imp.set_defaults(func=cmd_import)

    restart = subparsers.add_parser("restart", help=_("перезапустить демон"))
    restart.set_defaults(func=cmd_restart)

    fix = subparsers.add_parser("fix", help=_("исправить текст вручную"))
    fix.add_argument("--text", help=_("текст для исправления (иначе читается из stdin)"))
    fix.add_argument("--apply", action="store_true", help=_("применить исправление на экране"))
    fix.add_argument(
        "--dry-run",
        action="store_true",
        help=_("только показать исправление, ничего не применять"),
    )
    fix.set_defaults(func=cmd_fix)

    explain = subparsers.add_parser(
        "explain", help=_("объяснить решение детектора для слова (только чтение)")
    )
    explain.add_argument("--text", help=_("текст для анализа (иначе читается из stdin)"))
    explain.add_argument("--layout", default="", help=_("текущая раскладка (иначе определяется)"))
    explain.set_defaults(func=cmd_explain)

    doctor = subparsers.add_parser("doctor", help=_("самодиагностика окружения"))
    doctor.set_defaults(func=cmd_doctor)

    verify = subparsers.add_parser(
        "verify", help=_("проверить целостность файлов установленного пакета")
    )
    verify.set_defaults(func=cmd_verify)

    collect = subparsers.add_parser(
        "collect-logs", help=_("собрать диагностический архив для issue")
    )
    collect.add_argument(
        "--output",
        metavar="DIR",
        help=_("каталог для архива (по умолчанию — домашний каталог)"),
    )
    collect.set_defaults(func=cmd_collect_logs)

    logs = subparsers.add_parser("logs", help=_("показать журнал демона"))
    logs.add_argument(
        "-n",
        "--lines",
        type=int,
        default=50,
        metavar="N",
        help=_("сколько последних строк показать (по умолчанию 50)"),
    )
    logs.add_argument(
        "-f",
        "--follow",
        action="store_true",
        help=_("следить за журналом в реальном времени"),
    )
    logs.add_argument(
        "--level",
        default=None,
        metavar="LEVEL",
        help=_("показывать только строки этого уровня (DEBUG/INFO/WARNING/ERROR)"),
    )
    logs.set_defaults(func=cmd_logs)

    install = subparsers.add_parser("install-autostart", help=_("включить автозапуск"))
    install.set_defaults(func=cmd_install_autostart)

    uninstall = subparsers.add_parser("uninstall-autostart", help=_("выключить автозапуск"))
    uninstall.set_defaults(func=cmd_uninstall_autostart)

    version = subparsers.add_parser("version", help=_("показать версию"))
    version.set_defaults(func=cmd_version)

    gui = subparsers.add_parser("gui", help=_("открыть графический интерфейс (GTK4)"))
    gui.set_defaults(func=cmd_gui)

    return parser


def _locale_from_argv(argv: list[str]) -> str:
    """Return the ``--lang`` value in ``argv`` without a full parse.

    The parser is built before ``--lang`` is known, so its help strings would
    otherwise always be Russian. Pre-scanning the vector lets the locale be set
    before the parser is built, which is also what makes ``--help`` translate.
    """
    for index, item in enumerate(argv):
        if item == "--lang" and index + 1 < len(argv):
            return argv[index + 1]
        if item.startswith("--lang="):
            return item.partition("=")[2]
    return ""


def main(argv: list[str] | None = None) -> int:
    """Entry point for the ``klyrshift`` console script.

    Args:
        argv: Optional argument vector (defaults to ``sys.argv[1:]``).

    Returns:
        The process exit code.
    """
    arguments = list(sys.argv[1:] if argv is None else argv)
    set_locale(_locale_from_argv(arguments))
    parser = build_parser()
    args = parser.parse_args(arguments)
    try:
        return int(args.func(args))
    except KeyboardInterrupt:
        return 130
