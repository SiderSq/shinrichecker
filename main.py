#!/usr/bin/env python3
"""
Shinri Reviews Ranker - Главная точка входа.
Запуск локального веб-интерфейса или консольного режима CLI.
"""

from __future__ import annotations
import argparse
import logging
import os
import sys
import threading
import time
import webbrowser


def setup_windows_console() -> bool:
    """Attach to existing console if invoked from CMD or PowerShell in GUI mode."""
    if sys.platform == "win32":
        try:
            import ctypes

            if ctypes.windll.kernel32.AttachConsole(-1):
                try:
                    sys.stdout = open("CONOUT$", "w", encoding="utf-8", errors="replace")
                    sys.stderr = open("CONOUT$", "w", encoding="utf-8", errors="replace")
                    return True
                except Exception:
                    pass
        except Exception:
            pass
    if sys.stdout and hasattr(sys.stdout, "reconfigure"):
        try:
            sys.stdout.reconfigure(encoding="utf-8", errors="replace")
        except Exception:
            pass
    if sys.stderr and hasattr(sys.stderr, "reconfigure"):
        try:
            sys.stderr.reconfigure(encoding="utf-8", errors="replace")
        except Exception:
            pass
    return False


setup_windows_console()

from shinri_ranker.client import ShinriClient
from shinri_ranker.server import create_server
from shinri_ranker.cli import run_cli


def main() -> int:
    parser = argparse.ArgumentParser(
        description="Shinri Reviews Ranker - Анализ и Рейтинг игроков с shinrireviews.com",
        formatter_class=argparse.RawTextHelpFormatter,
    )

    # Mode selection
    mode_group = parser.add_argument_group("Режимы работы")
    mode_group.add_argument(
        "--gui",
        action="store_true",
        help="Запустить отдельную программу с красивым оконным интерфейсом (по умолчанию)",
    )
    mode_group.add_argument(
        "--browser",
        action="store_true",
        help="Открыть веб-интерфейс в обычном браузере вместо отдельного окна программы",
    )
    mode_group.add_argument(
        "--cli",
        action="store_true",
        help="Запустить в консольном режиме командной строки",
    )
    mode_group.add_argument(
        "-i",
        "--interactive",
        action="store_true",
        help="Интерактивный ввод списка игроков через терминал",
    )

    # CLI Inputs
    cli_group = parser.add_argument_group("Параметры ввода (для CLI)")
    cli_group.add_argument(
        "--input",
        "-f",
        type=str,
        help="Путь к файлу со списком игроков (.txt, .csv, .json)",
    )
    cli_group.add_argument(
        "--players",
        "-p",
        type=str,
        help="Список игроков через запятую (например: 'Hunk, mercyflower^-^, 35262')",
    )

    # Ranking configuration
    rank_group = parser.add_argument_group("Настройка рейтинга")
    rank_group.add_argument(
        "--top",
        "-n",
        type=int,
        default=10,
        help="Количество мест в топе лучших и антитопе худших игроков (по умолчанию: 10)",
    )
    rank_group.add_argument(
        "--min-reviews",
        "-m",
        type=int,
        default=1,
        help="Минимальное количество отзывов для попадания в рейтинг (по умолчанию: 1)",
    )
    rank_group.add_argument(
        "--ranking-mode",
        choices=["bayesian", "classic"],
        default="bayesian",
        help="Алгоритм расчета: 'bayesian' (взвешенный балл с учетом числа отзывов, по умолчанию) или 'classic' (простой средний балл)",
    )
    rank_group.add_argument(
        "--manual-ambiguous",
        action="store_true",
        help="Не разрешать омонимы автоматически, а выводить их в отдельный список",
    )
    cli_group.add_argument(
        "--chat-log",
        action="store_true",
        help="Режим парсера лога чата/лобби DRO: извлечь ники игроков из сырого текста чата",
    )

    # Exports
    export_group = parser.add_argument_group("Экспорт результатов (CLI)")
    export_group.add_argument("--export-csv", type=str, help="Путь для сохранения CSV (Excel)")
    export_group.add_argument("--export-json", type=str, help="Путь для сохранения JSON")
    export_group.add_argument("--export-md", type=str, help="Путь для сохранения Markdown отчета")

    # Analytics & OCR Tools
    analytics_group = parser.add_argument_group("Продвинутая аналитика и OCR (CLI)")
    analytics_group.add_argument(
        "--ocr",
        type=str,
        help="Путь к скриншоту таблицы/лобби/чата для извлечения ников через OCR",
    )
    analytics_group.add_argument(
        "--balance-teams",
        action="store_true",
        help="Сбалансировать участников на две равные команды (Синяя vs Красная)",
    )
    analytics_group.add_argument(
        "--lobby-safety",
        action="store_true",
        help="Рассчитать индекс безопасности и надежности комнаты (Lobby Safety Meter)",
    )
    analytics_group.add_argument(
        "--tournament",
        choices=["single_elimination", "round_robin"],
        help="Сгенерировать турнирную сетку: 'single_elimination' (плей-офф) или 'round_robin' (группы)",
    )
    analytics_group.add_argument(
        "--clans",
        action="store_true",
        help="Проанализировать клановые теги и риск сговора/тиминга в лобби",
    )

    # Offline and Database Management
    db_group = parser.add_argument_group("Управление базой данных и оффлайн-режим")
    db_group.add_argument(
        "--offline",
        action="store_true",
        help="Работать исключительно из локального кэша, без обращений к сети",
    )
    db_group.add_argument(
        "--export-db",
        type=str,
        help="Экспортировать текущую базу данных рейтингов в JSON-файл",
    )
    db_group.add_argument(
        "--import-db",
        type=str,
        help="Импортировать базу данных рейтингов из JSON-файла",
    )

    # Web Server configuration
    web_group = parser.add_argument_group("Настройки веб-сервера")
    web_group.add_argument(
        "--host", type=str, default="127.0.0.1", help="Хост веб-сервера (по умолчанию: 127.0.0.1)"
    )
    web_group.add_argument(
        "--port", type=int, default=8088, help="Порт веб-сервера (по умолчанию: 8088)"
    )
    web_group.add_argument(
        "--no-browser", action="store_true", help="Не открывать браузер автоматически"
    )

    # Other
    parser.add_argument(
        "--plain",
        action="store_true",
        help="Использовать простой текстовый вывод без форматирования",
    )
    parser.add_argument(
        "--quiet", "-q", action="store_true", help="Тихий режим без служебных сообщений"
    )
    parser.add_argument("--debug", action="store_true", help="Включить подробный вывод отладки")

    args = parser.parse_args()
    if args.top < 1 or args.min_reviews < 0 or not 0 <= args.port <= 65535:
        parser.error("Проверьте --top (>=1), --min-reviews (>=0) и --port (0..65535)")

    # Logging setup
    log_level = logging.DEBUG if args.debug else (logging.WARNING if args.quiet else logging.INFO)
    logging.basicConfig(level=log_level, format="%(asctime)s [%(levelname)s] %(message)s")

    # Decide mode: CLI if explicitly requested or if CLI-specific flags were provided
    is_cli_mode = (
        args.cli
        or args.input
        or args.players
        or args.interactive
        or args.export_db
        or args.import_db
        or args.ocr
        or args.balance_teams
        or args.lobby_safety
        or args.clans
        or args.tournament
    )

    if is_cli_mode:
        return run_cli(args)

    # Otherwise launch Standalone Desktop App (or browser if requested)
    if sys.platform == "win32":
        try:
            import ctypes

            ctypes.windll.kernel32.SetConsoleTitleW("★ Shinri Reviews Ranker (DRO Edition) v2.1 ★")
        except Exception:
            pass

    client = ShinriClient(offline_mode=args.offline)
    # Preload database cache in background thread immediately so the window opens to an instantly ready database
    threading.Thread(target=client.load_ratings, daemon=True).start()

    server = create_server(host=args.host, port=args.port, client=client)

    server_host, server_port = server.server_address
    url = f"http://{server_host}:{server_port}"

    return run_desktop_app(args, client, server, url)


def run_desktop_app(args, client: ShinriClient, server, url: str) -> int:
    """Запуск отдельной оконной программы с поддержкой оффлайн-сервера."""
    # Запускаем локальный API-сервер в фоновом потоке
    server_thread = threading.Thread(target=server.serve_forever, daemon=True)
    server_thread.start()

    # Если запрошен явный режим работы через браузер
    if getattr(args, "browser", False):
        print("=" * 70, flush=True)
        print("  ★ SHINRI REVIEWS RANKER (DRO EDITION) v2.1 ★", flush=True)
        print(f"  ✓ Локальный веб-сервер запущен: {url}", flush=True)
        print("  ✓ Открываем панель управления в браузере...", flush=True)
        print("=" * 70, flush=True)
        if not getattr(args, "no_browser", False):

            def open_browser():
                time.sleep(0.6)
                webbrowser.open(url)

            threading.Thread(target=open_browser, daemon=True).start()
        try:
            while True:
                time.sleep(1)
        except KeyboardInterrupt:
            pass
        server.shutdown()
        server.server_close()
        return 0

    # Полноценная отдельная оконная программа (Standalone Desktop Window)
    gui_started = False
    try:
        import webview

        # Allow PNG/CSV/JSON exports and file downloads inside WebView2
        try:
            webview.settings["ALLOW_DOWNLOADS"] = True
            webview.settings["OPEN_EXTERNAL_LINKS_IN_BROWSER"] = True
        except Exception:
            pass

        if sys.platform == "win32":
            try:
                import ctypes

                ctypes.windll.shell32.SetCurrentProcessExplicitAppUserModelID(
                    "shinri.dro.ranker.v2"
                )
            except Exception:
                pass
            # Optimize Edge WebView2 Chromium runtime: disable telemetry and background network overhead
            os.environ["WEBVIEW2_ADDITIONAL_BROWSER_ARGUMENTS"] = (
                "--disable-background-networking "
                "--disable-background-timer-throttling "
                "--disable-backgrounding-occluded-windows "
                "--disable-breakpad "
                "--disable-component-update "
                "--disable-domain-reliability "
                "--disable-extensions "
                "--disable-features=Translate,OptimizationHints,MediaRouter "
                "--disable-renderer-backgrounding "
                "--disable-sync "
                "--force-color-profile=srgb "
                "--no-first-run"
            )

        window = webview.create_window(
            title="★ Shinri Reviews Ranker (DRO Edition) v2.1 ★",
            url=url,
            width=1260,
            height=820,
            min_size=(960, 600),
            background_color="#0a0e17",
            text_select=True,
            zoomable=True,
            easy_drag=False,
        )
        gui_started = True
        # Запуск нативного оконного цикла приложения (блокирует поток до закрытия окна)
        webview.start(gui="edgechromium", debug=getattr(args, "debug", False))
    except Exception as exc:
        logging.warning("Не удалось открыть окно pywebview (%s), переключаемся на браузер...", exc)
        gui_started = False

    # Резервный режим на случай, если графическая подсистема Windows повреждена
    if not gui_started:
        print("=" * 70, flush=True)
        print("  ★ SHINRI REVIEWS RANKER (DRO EDITION) v2.1 ★", flush=True)
        print(f"  ✓ Сервер запущен: {url}", flush=True)
        print("  ✓ Открываем панель управления в браузере...", flush=True)
        print("=" * 70, flush=True)
        if not getattr(args, "no_browser", False):

            def open_browser():
                time.sleep(0.6)
                webbrowser.open(url)

            threading.Thread(target=open_browser, daemon=True).start()
        try:
            while True:
                time.sleep(1)
        except KeyboardInterrupt:
            pass

    # Корректное завершение работы при закрытии окна
    try:
        server.shutdown()
        server.server_close()
    except Exception:
        pass
    return 0


if __name__ == "__main__":
    try:
        sys.exit(main())
    except KeyboardInterrupt:
        sys.exit(0)
    except Exception as exc:
        import traceback

        traceback.print_exc()
        print("\n" + "=" * 70)
        print(" [ОШИБКА] Произошла непредвиденная ошибка при выполнении программы.")
        print(f" Подробности: {exc}")
        print(" Нажмите клавишу Enter для закрытия этого окна...")
        print("=" * 70)
        try:
            input()
        except Exception:
            pass
        sys.exit(1)
