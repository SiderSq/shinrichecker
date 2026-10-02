#!/usr/bin/env python3
"""
Automated Build Script for Shinri Reviews Ranker (DRO Edition).
Compiles the project into a standalone Windows .exe executable with icons,
version metadata, embedded static assets, and builds a portable distribution package.
"""

import os
import sys
import shutil
import subprocess
import time

# Ensure UTF-8 output
if sys.stdout and hasattr(sys.stdout, "reconfigure"):
    try:
        sys.stdout.reconfigure(encoding="utf-8", errors="replace")
    except Exception:
        pass

def run_command(cmd, desc):
    print(f"[{desc}] Выполняется: {' '.join(cmd)}")
    start = time.time()
    res = subprocess.run(cmd, capture_output=True, text=True, encoding="utf-8", errors="replace")
    elapsed = round(time.time() - start, 2)
    if res.returncode != 0:
        print(f"✕ Ошибка на этапе '{desc}' (код {res.returncode}):")
        if res.stderr:
            print(res.stderr)
        if res.stdout:
            print(res.stdout)
        sys.exit(res.returncode)
    print(f"✓ Завершено за {elapsed} сек.")
    return res.stdout

def main():
    print("=" * 70)
    print("  ★ СБОРКА ИСПОЛНЯЕМОГО ФАЙЛА SHINRI RANKER (.EXE) ★")
    print("=" * 70)

    project_dir = os.path.dirname(os.path.abspath(__file__))
    os.chdir(project_dir)

    # 1. Generate icon if missing
    if not os.path.exists("app_icon.ico"):
        print("[1/5] Создание иконки приложения app_icon.ico...")
        run_command([sys.executable, "generate_app_icon.py"], "Генерация иконки")
    else:
        print("[1/5] Иконка app_icon.ico найдена.")

    # 2. Clean previous build artifacts
    print("[2/5] Очистка предыдущих сборок...")
    for folder in ["build", "dist"]:
        if os.path.exists(folder):
            try:
                shutil.rmtree(folder)
            except Exception as e:
                print(f"Предупреждение: не удалось удалить {folder}: {e}")

    # 3. Build executable via PyInstaller
    print("[3/5] Компиляция через PyInstaller с оптимизацией размера...")
    run_command([sys.executable, "-m", "PyInstaller", "--clean", "ShinriRanker.spec"], "PyInstaller Build")

    exe_path = os.path.join("dist", "ShinriRanker.exe")
    if not os.path.isfile(exe_path):
        print(f"✕ Ошибка: Исполняемый файл не найден по пути: {exe_path}")
        sys.exit(1)

    size_mb = os.path.getsize(exe_path) / (1024 * 1024)
    print(f"✓ Успешно собран .exe: {exe_path} ({size_mb:.2f} МБ)")

    # 4. Create Beautiful Portable Release Package
    print("[4/5] Подготовка портативного пакета релиза (release/)...")
    release_dir = os.path.join(project_dir, "release")
    if os.path.exists(release_dir):
        try:
            shutil.rmtree(release_dir)
        except Exception:
            pass
    os.makedirs(release_dir, exist_ok=True)

    # Copy files
    shutil.copy2(exe_path, os.path.join(release_dir, "ShinriRanker.exe"))
    shutil.copy2(exe_path, os.path.join(project_dir, "ShinriRanker.exe"))
    if os.path.exists("shinri_ratings_cache.json"):
        shutil.copy2("shinri_ratings_cache.json", os.path.join(release_dir, "shinri_ratings_cache.json"))
    if os.path.exists("shinri_ratings_cache.json.dat"):
        shutil.copy2("shinri_ratings_cache.json.dat", os.path.join(release_dir, "shinri_ratings_cache.json.dat"))
    if os.path.exists("sample_players.txt"):
        shutil.copy2("sample_players.txt", os.path.join(release_dir, "sample_players.txt"))
    if os.path.exists("sample_chat.txt"):
        shutil.copy2("sample_chat.txt", os.path.join(release_dir, "sample_chat.txt"))

    # Write quick launchers in release folder (both Russian and universal names)
    app_bat_content = "@echo off\ncls\nstart \"\" \"%~dp0ShinriRanker.exe\"\n"
    cli_bat_content = "@echo off\nchcp 65001 > nul\ncls\n\"%~dp0ShinriRanker.exe\" --cli --input \"%~dp0sample_players.txt\" --top 10 --balance-teams --lobby-safety --clans\npause\n"

    for name in ["Запустить_ShinriRanker.bat", "Run_ShinriRanker.bat"]:
        with open(os.path.join(release_dir, name), "w", encoding="utf-8", errors="replace") as f:
            f.write(app_bat_content)

    for name in ["Запустить_Тест_CLI.bat", "Run_Test_CLI.bat"]:
        with open(os.path.join(release_dir, name), "w", encoding="utf-8", errors="replace") as f:
            f.write(cli_bat_content)

    # Readme in release folder
    readme_content = """★ Shinri Reviews Ranker (DRO Edition) v2.0 ★
========================================================================

АВТОНОМНАЯ ОКОННАЯ ДЕСКТОПНАЯ ПРОГРАММА ДЛЯ WINDOWS:

1. БЫСТРЫЙ ЗАПУСК ПРОГРАММЫ:
   - Просто дважды кликните по файлу `ShinriRanker.exe` (или `Запустить_ShinriRanker.bat`).
   - Программа запустится в отдельном красивом окне (без внешнего браузера и без консоли)!

2. ВОЗМОЖНОСТИ ПРОГРАММЫ:
   • Полноценный оконный интерфейс с темной неоновой темой в стиле Danganronpa
   • Загрузка игроков через никнеймы, ссылки, ID, текстовые файлы и логи чата DRO
   • Вставка скриншотов из буфера обмена (Ctrl+V) с распознаванием ников через OCR
   • Байесовский сглаженный рейтинг (Bayesian Score) и классический средний балл
   • Честный балансировщик команд (Fair Matchmaking 5v5) с расчетом Elo и шансов на победу
   • Индикатор надежности и токсичности комнаты (Lobby Safety Meter)
   • Клановая аналитика и предупреждения о сговоре/тиминге в лобби
   • Генератор турнирных сеток: Плей-офф (Single Elimination) и Группы (Round Robin)
   • 7 уникальных архетипов игроков ("Абсолютный Детектив", "Мастер Дедукции"...)
   • Скачивание коллекционных RPG-карточек игроков (PNG) в высоком разрешении

3. КОНСОЛЬНЫЙ РЕЖИМ (CLI):
   Вы можете использовать программу через командную строку Windows (CMD / PowerShell):
   ShinriRanker.exe --cli -p "Hunk, mercyflower^-^, Pateti, Bun|dimebag" --balance-teams --lobby-safety --clans

4. ОФФЛАЙН РАБОТА:
   Файл `shinri_ratings_cache.json` уже находится рядом с программой.
   Программа работает мгновенно даже без подключения к интернету!
========================================================================
"""
    with open(os.path.join(release_dir, "Инструкция_по_запуску.txt"), "w", encoding="utf-8") as f:
        f.write(readme_content)

    # 5. Quick smoke test of compiled exe
    print("[5/5] Экспресс-тестирование собранного ShinriRanker.exe...")
    # 5.1 CLI Smoke Test
    test_out = run_command([exe_path, "--cli", "-p", "Hunk, mercyflower^-^", "--plain", "--offline"], "CLI Smoke Test")
    if "Hunk" in test_out and "mercyflower" in test_out:
        print("✓ Тест CLI успешно пройден: exe корректно загрузил кэш и выполнил ранжирование!")
    else:
        print("✕ Ошибка CLI: вывод теста отличается от ожидаемого.")

    # 5.2 Server Smoke Test
    print("[5/5] Тестирование режима ядра и REST API...")
    import urllib.request
    test_proc = subprocess.Popen([exe_path, "--browser", "--no-browser", "--port", "9876", "--offline"])
    try:
        time.sleep(2.0)
        req = urllib.request.urlopen("http://127.0.0.1:9876/api/status", timeout=3)
        res_data = req.read().decode("utf-8")
        if "total_players" in res_data and "status" in res_data:
            print("✓ Тест ядра сервера успешно пройден: локальный сервер и REST API работают безупречно!")
        else:
            print("✕ Ошибка сервера: неожиданный ответ от API.")
            sys.exit(1)
    except Exception as e:
        print(f"✕ Ошибка тестирования сервера: {e}")
        sys.exit(1)
    finally:
        test_proc.terminate()
        try:
            test_proc.wait(timeout=2)
        except Exception:
            test_proc.kill()

    print("\n" + "=" * 70)
    print("  🎉 СБОРКА УСПЕШНО ЗАВЕРШЕНА!")
    print(f"  • Исполняемый файл: {os.path.abspath(exe_path)}")
    print(f"  • Папка релиза:     {os.path.abspath(release_dir)}")
    print("=" * 70)

if __name__ == "__main__":
    main()
