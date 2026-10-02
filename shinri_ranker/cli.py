"""
Command-Line Interface (CLI) for Shinri Reviews Ranker.
Supports rich console formatting, batch file processing, and multiple export formats.
"""

from __future__ import annotations
import argparse
import os
import sys
from typing import List, Optional

from .client import ShinriClient, ShinriNetworkError
from .exporter import Exporter
from .matcher import InputParser, MatchStatus, ProfileMatcher
from .ranker import Ranker, RankingReport
from .analytics import (
    TeamBalancer,
    LobbySafetyMeter,
    ClanDetector,
    TournamentGenerator,
    EloConverter,
)
from .ocr import OcrProcessor

# Ensure stdout/stderr encoding
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

# Check if rich is available for enhanced terminal tables
try:
    from rich.console import Console
    from rich.panel import Panel
    from rich.table import Table
    from rich import box

    HAS_RICH = True
except ImportError:
    HAS_RICH = False


def print_rich_report(report: RankingReport, console: "Console") -> None:
    """Print beautifully styled tables using rich."""
    mode_text = (
        "Байесовский рейтинг (взвешенный)"
        if report.ranking_mode == "bayesian"
        else "Классический средний балл"
    )
    console.print()
    console.print(
        Panel.fit(
            f"[bold cyan]Shinri Reviews Анализ и Рейтинг игроков DRO[/bold cyan]\n"
            f"[dim]Режим:[/dim] [bold yellow]{mode_text}[/bold yellow] | "
            f"[dim]Всего во вводе:[/dim] [bold]{report.total_inputs}[/bold] | "
            f"[dim]Уникальных:[/dim] [bold]{report.unique_inputs}[/bold] | "
            f"[dim]Топ:[/dim] [bold]Топ-{report.top_n}[/bold] (мин. {report.min_reviews} отз.)",
            border_style="magenta",
            title="Сводка",
        )
    )
    console.print()

    # Best players table
    table_best = Table(
        title=f"ТОП ЛУЧШИХ ИГРОКОВ (Топ {report.top_n})",
        box=box.ROUNDED,
        header_style="bold yellow",
        border_style="yellow",
    )
    table_best.add_column("№", justify="center", style="bold", width=4)
    table_best.add_column("Имя игрока", style="bold white")
    table_best.add_column("ID", justify="center", style="dim")
    table_best.add_column("Средний балл", justify="center", style="bold green")
    table_best.add_column("Байес", justify="center", style="bold cyan")
    table_best.add_column("Отзывы", justify="center", style="white")
    table_best.add_column("Ссылка на профиль", style="blue")

    if not report.best_players:
        table_best.add_row("-", "[dim]Нет подходящих игроков[/dim]", "-", "-", "-", "-", "-")
    else:
        for p in report.best_players:
            medal = str(p.rank)
            table_best.add_row(
                medal,
                p.name,
                str(p.player_id),
                f"{p.avg_rating:.2f}",
                f"{p.bayesian_score:.2f}",
                str(p.reviews_count),
                p.profile_url,
            )

    console.print(table_best)
    console.print()

    # Worst players table
    table_worst = Table(
        title=f"АНТИТОП (ХУДШИЕ ИГРОКИ) (Топ {report.top_n})",
        box=box.ROUNDED,
        header_style="bold red",
        border_style="red",
    )
    table_worst.add_column("№", justify="center", style="bold", width=4)
    table_worst.add_column("Имя игрока", style="bold white")
    table_worst.add_column("ID", justify="center", style="dim")
    table_worst.add_column("Средний балл", justify="center", style="bold red")
    table_worst.add_column("Байес", justify="center", style="bold magenta")
    table_worst.add_column("Отзывы", justify="center", style="white")
    table_worst.add_column("Ссылка на профиль", style="blue")

    if not report.worst_players:
        table_worst.add_row("-", "[dim]Нет подходящих игроков[/dim]", "-", "-", "-", "-", "-")
    else:
        for p in report.worst_players:
            table_worst.add_row(
                str(p.rank),
                p.name,
                str(p.player_id),
                f"{p.avg_rating:.2f}",
                f"{p.bayesian_score:.2f}",
                str(p.reviews_count),
                p.profile_url,
            )

    console.print(table_worst)
    console.print()

    # Diagnostics sections if any
    if report.unrated_players:
        table_unrated = Table(
            title="Профили без оценок (0 отзывов)", box=box.SIMPLE, header_style="dim"
        )
        table_unrated.add_column("Стр.")
        table_unrated.add_column("Имя / Ввод")
        table_unrated.add_column("ID")
        table_unrated.add_column("Ссылка")
        for p in report.unrated_players:
            table_unrated.add_row(
                str(p.line_number),
                p.name or p.input_text,
                str(p.player_id or "-"),
                p.profile_url or "-",
            )
        console.print(table_unrated)
        console.print()

    if report.ambiguous_players:
        table_amb = Table(
            title="Неоднозначные совпадения (омонимы)", box=box.SIMPLE, header_style="magenta"
        )
        table_amb.add_column("Стр.")
        table_amb.add_column("Ввод")
        table_amb.add_column("Кандидаты в базе")
        for p in report.ambiguous_players:
            cands = ", ".join(
                f"{c['name']} (ID {c['id']}, {c['count']} отз., балл {c['avg']})"
                for c in p.candidates
            )
            table_amb.add_row(str(p.line_number), p.input_text, cands)
        console.print(table_amb)
        console.print()

    if report.missing_players:
        table_miss = Table(title="Не найдены на сайте", box=box.SIMPLE, header_style="dim red")
        table_miss.add_column("Стр.")
        table_miss.add_column("Исходный ввод")
        table_miss.add_column("Причина")
        for p in report.missing_players:
            table_miss.add_row(str(p.line_number), p.input_text, p.resolution_note or "Не найден")
        console.print(table_miss)
        console.print()

    if report.duplicates:
        table_dup = Table(
            title="Обнаруженные дубликаты во вводе", box=box.SIMPLE, header_style="dim"
        )
        table_dup.add_column("Стр.")
        table_dup.add_column("Исходный ввод")
        table_dup.add_column("Дублирует")
        for p in report.duplicates:
            table_dup.add_row(str(p.line_number), p.input_text, p.resolution_note or "Дубликат")
        console.print(table_dup)
        console.print()


def print_plain_report(report: RankingReport) -> None:
    """Fallback plain text printer."""
    print("=" * 70)
    print("Shinri Reviews Анализ и Рейтинг игроков")
    print(
        f"Всего во вводе: {report.total_inputs} | Уникальных: {report.unique_inputs} | Топ-{report.top_n}"
    )
    print("=" * 70)
    print("\n[ТОП ЛУЧШИХ ИГРОКОВ]")
    print(f"{'№':<4} {'Имя игрока':<25} {'Рейтинг':<10} {'Отзывы':<8} {'Ссылка на профиль'}")
    print("-" * 70)
    for p in report.best_players:
        print(f"{p.rank:<4} {p.name:<25} {p.avg_rating:<8.2f} {p.reviews_count:<8} {p.profile_url}")

    print("\n[АНТИТОП (ХУДШИЕ ИГРОКИ)]")
    print(f"{'№':<4} {'Имя игрока':<25} {'Рейтинг':<10} {'Отзывы':<8} {'Ссылка на профиль'}")
    print("-" * 70)
    for p in report.worst_players:
        print(f"{p.rank:<4} {p.name:<25} {p.avg_rating:<8.2f} {p.reviews_count:<8} {p.profile_url}")

    if report.unrated_players:
        print(f"\n[Без оценок: {len(report.unrated_players)} чел.]")
        for p in report.unrated_players:
            print(
                f"  Стр. {p.line_number}: {p.name or p.input_text} (ID: {p.player_id or '—'}) — 0 отзывов"
            )

    if report.ambiguous_players:
        print(f"\n[Неоднозначные совпадения: {len(report.ambiguous_players)}]")
        for p in report.ambiguous_players:
            cands = ", ".join(f"ID {c['id']}" for c in p.candidates)
            print(f"  Стр. {p.line_number}: {p.input_text} -> варианты: {cands}")

    if report.missing_players:
        print(f"\n[Не найдены на сайте: {len(report.missing_players)}]")
        for p in report.missing_players:
            print(f"  Стр. {p.line_number}: {p.input_text}")

    if report.duplicates:
        print(f"\n[Дубликаты во вводе: {len(report.duplicates)}]")
        for p in report.duplicates:
            print(f"  Стр. {p.line_number}: {p.input_text} -> {p.resolution_note}")
    print()


def print_rich_balance_teams(balance: dict, console: "Console") -> None:
    """Print beautifully styled balanced teams."""
    fairness = balance.get("fairness", 100.0)
    color = "green" if fairness >= 85 else ("yellow" if fairness >= 70 else "red")
    win_a = float(balance.get("win_prob_a", 50.0))
    if win_a <= 1.0:
        win_a *= 100.0
    win_b = float(balance.get("win_prob_b", 50.0))
    if win_b <= 1.0:
        win_b *= 100.0
    console.print()
    console.print(
        Panel.fit(
            f"[bold cyan]Честный балансировщик команд (Fair Matchmaking)[/bold cyan]\n"
            f"Честность матча: [bold {color}]{fairness:.1f}%[/bold {color}] | Разница баллов (Delta): [bold]{balance.get('delta', 0.0):.2f}[/bold]\n"
            f"Прогноз исхода (Elo): [bold blue]Синие {win_a:.1f}%[/bold blue] vs [bold red]Красные {win_b:.1f}%[/bold red]\n"
            f"[dim]Команда Синих:[/dim] ср. балл {balance.get('avg_a', 0.0):.2f} (Elo: [cyan]{balance.get('elo_a', 1500)}[/cyan], Сумма: {balance.get('score_a', 0.0):.2f}) | "
            f"[dim]Команда Красных:[/dim] ср. балл {balance.get('avg_b', 0.0):.2f} (Elo: [magenta]{balance.get('elo_b', 1500)}[/magenta], Сумма: {balance.get('score_b', 0.0):.2f})",
            border_style="cyan",
            title="Баланс матча",
        )
    )
    console.print()

    # Team Blue Table
    table_a = Table(
        title="СИНЯЯ КОМАНДА (Team Blue)",
        box=box.ROUNDED,
        header_style="bold blue",
        border_style="blue",
    )
    table_a.add_column("№", justify="center", width=3)
    table_a.add_column("Игрок", style="bold white")
    table_a.add_column("ID", justify="center", style="dim")
    table_a.add_column("Байес", justify="center", style="bold cyan")
    table_a.add_column("Elo", justify="center", style="bold blue")
    table_a.add_column("Ср. балл", justify="center")
    table_a.add_column("Отзывы", justify="center")

    for idx, p in enumerate(balance.get("team_a", []), 1):
        role = " (Капитан)" if idx == 1 else ""
        table_a.add_row(
            str(idx),
            f"{p.get('name', 'Игрок')}{role}",
            str(p.get("player_id", "-")),
            f"{float(p.get('bayesian_score', 0.0)):.2f}",
            str(p.get("elo", 1500)),
            f"{float(p.get('avg_rating', 0.0)):.2f}",
            str(p.get("reviews_count", 0)),
        )
    console.print(table_a)
    console.print()

    # Team Red Table
    table_b = Table(
        title="КРАСНАЯ КОМАНДА (Team Red)",
        box=box.ROUNDED,
        header_style="bold red",
        border_style="red",
    )
    table_b.add_column("№", justify="center", width=3)
    table_b.add_column("Игрок", style="bold white")
    table_b.add_column("ID", justify="center", style="dim")
    table_b.add_column("Байес", justify="center", style="bold magenta")
    table_b.add_column("Elo", justify="center", style="bold red")
    table_b.add_column("Ср. балл", justify="center")
    table_b.add_column("Отзывы", justify="center")

    for idx, p in enumerate(balance.get("team_b", []), 1):
        role = " (Капитан)" if idx == 1 else ""
        table_b.add_row(
            str(idx),
            f"{p.get('name', 'Игрок')}{role}",
            str(p.get("player_id", "-")),
            f"{float(p.get('bayesian_score', 0.0)):.2f}",
            str(p.get("elo", 1500)),
            f"{float(p.get('avg_rating', 0.0)):.2f}",
            str(p.get("reviews_count", 0)),
        )
    console.print(table_b)
    console.print()


def print_plain_balance_teams(balance: dict) -> None:
    """Plain text balanced teams output."""
    win_a = float(balance.get("win_prob_a", 50.0))
    if win_a <= 1.0:
        win_a *= 100.0
    win_b = float(balance.get("win_prob_b", 50.0))
    if win_b <= 1.0:
        win_b *= 100.0
    print("=" * 70)
    print(
        f"Баланс команд: Честность {balance.get('fairness', 100.0):.1f}% (Delta: {balance.get('delta', 0.0):.2f})"
    )
    print(f"Прогноз победы (Elo): Синие {win_a:.1f}% vs Красные {win_b:.1f}%")
    print(
        f"Синие: ср. балл {balance.get('avg_a', 0.0):.2f} (Elo {balance.get('elo_a', 1500)}) | Красные: ср. балл {balance.get('avg_b', 0.0):.2f} (Elo {balance.get('elo_b', 1500)})"
    )
    print("=" * 70)
    print("\nСИНЯЯ КОМАНДА:")
    for idx, p in enumerate(balance.get("team_a", []), 1):
        cap = " [Капитан]" if idx == 1 else ""
        print(
            f"  {idx}. {p.get('name')}{cap} — Байес: {p.get('bayesian_score', 0.0):.2f} | Elo: {p.get('elo', 1500)} (отз.: {p.get('reviews_count', 0)})"
        )
    print("\nКРАСНАЯ КОМАНДА:")
    for idx, p in enumerate(balance.get("team_b", []), 1):
        cap = " [Капитан]" if idx == 1 else ""
        print(
            f"  {idx}. {p.get('name')}{cap} — Байес: {p.get('bayesian_score', 0.0):.2f} | Elo: {p.get('elo', 1500)} (отз.: {p.get('reviews_count', 0)})"
        )
    print()


def print_rich_lobby_safety(safety: dict, console: "Console") -> None:
    """Print lobby safety meter analysis."""
    score = safety.get("score", 100)
    color = "green" if score >= 80 else ("yellow" if score >= 55 else "red")
    console.print()
    console.print(
        Panel.fit(
            f"[bold {color}]Индекс безопасности комнаты: {score}/100[/bold {color}]\n"
            f"Статус: [bold {color}]{safety.get('label')}[/bold {color}] | "
            f"Опасных игроков: [bold red]{safety.get('danger_count', 0)}[/bold red] | "
            f"Новичков без оценок: [bold yellow]{safety.get('unrated_count', 0)}[/bold yellow]",
            border_style=color,
            title="Анализ токсичности и надежности лобби",
        )
    )
    warnings = safety.get("warnings", [])
    if warnings:
        warn_table = Table(box=box.SIMPLE, show_header=False)
        warn_table.add_column("Уровень", min_width=14)
        warn_table.add_column("Предупреждение")
        for w in warnings:
            sev = w.get("severity")
            icon = (
                "Опасность"
                if sev == "danger"
                else ("Предупреждение" if sev == "warning" else "Информация")
            )
            style = "bold red" if sev == "danger" else ("yellow" if sev == "warning" else "dim")
            warn_table.add_row(icon, f"[{style}]{w.get('text')}[/{style}]")
        console.print(warn_table)
    console.print()


def print_plain_lobby_safety(safety: dict) -> None:
    """Plain text lobby safety output."""
    print("=" * 70)
    print(f"Индекс безопасности лобби: {safety.get('score')}/100 — {safety.get('label')}")
    print(
        f"Опасных игроков: {safety.get('danger_count', 0)} | Новичков без оценок: {safety.get('unrated_count', 0)}"
    )
    print("=" * 70)
    for w in safety.get("warnings", []):
        sev = w.get("severity")
        icon = (
            "[ОПАСНОСТЬ]" if sev == "danger" else ("[ВНИМАНИЕ]" if sev == "warning" else "[ИНФО]")
        )
        print(f" {icon} {w.get('text')}")
    print()


def print_rich_clans(clan_stats: dict, teaming_alert: dict, console: "Console") -> None:
    """Print clan membership distribution and teaming alerts."""
    console.print()
    is_risk = teaming_alert.get("is_risk", False)
    color = "red" if is_risk else "green"
    status_msg = (
        "Предупреждение: обнаружен риск тиминга/сговора!"
        if is_risk
        else "Риск сговора не зафиксирован (кланы распределены)"
    )
    console.print(
        Panel.fit(
            f"[bold {color}]Анализ кланов и проверка на сговор[/bold {color}]\n"
            f"Уникальных кланов в лобби: [bold cyan]{len(clan_stats)}[/bold cyan] | Статус: [bold {color}]{status_msg}[/bold {color}]",
            border_style=color,
            title="Клановая аналитика",
        )
    )
    if teaming_alert.get("warnings"):
        for w in teaming_alert["warnings"]:
            console.print(f"  [bold red]{w['text']}[/bold red]")
        console.print()

    if clan_stats:
        table = Table(title="Кланы в лобби", box=box.ROUNDED, header_style="bold yellow")
        table.add_column("Клан", style="bold yellow")
        table.add_column("Участников", justify="center")
        table.add_column("Ср. балл", justify="center")
        table.add_column("Ср. Elo", justify="center", style="bold cyan")
        table.add_column("Состав", style="dim")
        for tag, c in clan_stats.items():
            members_str = ", ".join(c.get("members", []))
            table.add_row(
                f"[{tag}]",
                str(c.get("count", 0)),
                f"{c.get('avg_score', 0.0):.2f}",
                str(c.get("avg_elo", 1500)),
                members_str,
            )
        console.print(table)
    else:
        console.print("[dim]В лобби не обнаружено игроков с клановыми тегами.[/dim]")
    console.print()


def print_plain_clans(clan_stats: dict, teaming_alert: dict) -> None:
    """Plain text clan analytics."""
    print("=" * 70)
    print(f"Клановая аналитика: {len(clan_stats)} кланов")
    print("=" * 70)
    if teaming_alert.get("warnings"):
        for w in teaming_alert["warnings"]:
            print(f" [ВНИМАНИЕ] {w['text']}")
    if clan_stats:
        for tag, c in clan_stats.items():
            print(
                f"  [{tag}] ({c.get('count', 0)} чел., ср. {c.get('avg_score', 0.0):.2f}, Elo {c.get('avg_elo', 1500)}): {', '.join(c.get('members', []))}"
            )
    else:
        print("  Клановых тегов не обнаружено.")
    print()


def print_rich_tournament(tournament_data: dict, console: "Console") -> None:
    """Print tournament bracket."""
    fmt = tournament_data.get("format", "single_elimination")
    console.print()
    if fmt == "single_elimination":
        console.print(
            Panel.fit(
                f"[bold gold1]Турнирная сетка на выбывание (Single Elimination)[/bold gold1]\n"
                f"Всего участников: [bold]{tournament_data.get('total_participants', 0)}[/bold] | "
                f"Раундов: [bold]{len(tournament_data.get('rounds', []))}[/bold]",
                border_style="yellow",
                title="Play-off Bracket",
            )
        )
        for r in tournament_data.get("rounds", []):
            table = Table(
                title=f"{r.get('round_name')}", box=box.ROUNDED, header_style="bold magenta"
            )
            table.add_column("Матч", justify="center", width=4)
            table.add_column("Игрок 1", style="bold white")
            table.add_column("Посев 1", justify="center", style="dim")
            table.add_column("vs", justify="center", style="dim")
            table.add_column("Игрок 2", style="bold white")
            table.add_column("Посев 2", justify="center", style="dim")
            table.add_column("Фаворит / Шанс", style="bold green")

            for m in r.get("matches", []):
                p1 = m["player1"]
                p2 = m["player2"]
                fav = m.get("predicted_winner", "-")
                prob1 = int(m.get("win_prob1", 0.5) * 100)
                prob2 = int(m.get("win_prob2", 0.5) * 100)
                fav_str = (
                    f"{fav} ({prob1 if fav == p1['name'] else prob2}%)"
                    if fav != "BYE"
                    else "Автопроход"
                )
                table.add_row(
                    str(m.get("match_num", 1)),
                    p1["name"],
                    f"#{p1.get('seed', '-')}",
                    "vs",
                    p2["name"],
                    f"#{p2.get('seed', '-')}",
                    fav_str,
                )
            console.print(table)
            console.print()
    else:
        console.print(
            Panel.fit(
                f"[bold gold1]Турнирный групповой этап (Round Robin)[/bold gold1]\n"
                f"Всего участников: [bold]{tournament_data.get('total_participants', 0)}[/bold] | "
                f"Групп: [bold]{len(tournament_data.get('groups', []))}[/bold]",
                border_style="yellow",
                title="Group Stage",
            )
        )
        raw_groups = tournament_data.get("groups", [])
        group_list = list(raw_groups.values()) if isinstance(raw_groups, dict) else raw_groups
        for g in group_list:
            table = Table(
                title=f"{g.get('group_name')}", box=box.ROUNDED, header_style="bold yellow"
            )
            table.add_column("Посев", justify="center", width=5)
            table.add_column("Игрок", style="bold white")
            table.add_column("Ср. балл", justify="center")
            table.add_column("Elo", justify="center", style="bold cyan")
            for p in g.get("players", []):
                p_name = p.get("name") if isinstance(p, dict) else str(p)
                p_score = p.get("score", 0.0) if isinstance(p, dict) else 0.0
                p_elo = p.get("elo", 1500) if isinstance(p, dict) else 1500
                p_seed = p.get("seed", "-") if isinstance(p, dict) else "-"
                table.add_row(f"#{p_seed}", p_name, f"{p_score:.2f}", str(p_elo))
            console.print(table)

            if g.get("matches"):
                m_table = Table(
                    title=f"Матчи {g.get('group_name')}", box=box.SIMPLE, show_header=False
                )
                m_table.add_column("Пара", style="white")
                m_table.add_column("Прогноз", style="green")
                for m in g.get("matches", []):
                    m_table.add_row(
                        f"{m['player1']} vs {m['player2']}",
                        f"Шанс: {int(m.get('win_prob1', 0.5)*100)}% / {int(m.get('win_prob2', 0.5)*100)}%",
                    )
                console.print(m_table)
            console.print()


def print_plain_tournament(tournament_data: dict) -> None:
    """Plain text tournament."""
    fmt = tournament_data.get("format", "single_elimination")
    print("=" * 70)
    print(f"Турнирное расписание ({fmt})")
    print("=" * 70)
    if fmt == "single_elimination":
        for r in tournament_data.get("rounds", []):
            print(f"\n=== {r.get('round_name')} ===")
            for m in r.get("matches", []):
                p1 = m["player1"]["name"]
                p2 = m["player2"]["name"]
                fav = m.get("predicted_winner")
                print(f"  Матч {m.get('match_num')}: {p1} vs {p2} -> Фаворит: {fav}")
    else:
        raw_groups = tournament_data.get("groups", [])
        group_list = list(raw_groups.values()) if isinstance(raw_groups, dict) else raw_groups
        for g in group_list:
            print(f"\n=== {g.get('group_name')} ===")
            for p in g.get("players", []):
                p_name = p.get("name") if isinstance(p, dict) else str(p)
                p_score = p.get("score", 0.0) if isinstance(p, dict) else 0.0
                p_elo = p.get("elo", 1500) if isinstance(p, dict) else 1500
                p_seed = p.get("seed", "-") if isinstance(p, dict) else "-"
                print(f"  #{p_seed} {p_name} (балл {p_score:.2f}, Elo: {p_elo})")
            print("  Матчи:")
            for m in g.get("matches", []):
                print(
                    f"    {m['player1']} vs {m['player2']} (шанс {int(m.get('win_prob1', 0.5)*100)}% / {int(m.get('win_prob2', 0.5)*100)}%)"
                )
    print()


def run_cli(args: argparse.Namespace) -> int:
    """Execute ranking workflow via CLI."""
    client = ShinriClient(offline_mode=args.offline)

    # 1. Handle DB export / import commands
    if args.export_db:
        print(f"Экспорт базы данных в {args.export_db}...")
        client.export_cache(args.export_db)
        print("Экспорт успешно завершен.")
        return 0

    if args.import_db:
        print(f"Импорт базы данных из {args.import_db}...")
        count = client.import_cache(args.import_db)
        print(f"Успешно импортировано {count} игроков в локальную базу.")
        return 0

    # 2. Collect input text
    input_text = ""
    if getattr(args, "ocr", None):
        ocr_path = args.ocr
        if not os.path.isfile(ocr_path):
            print(
                f"Ошибка: входной файл изображения для OCR не найден: {ocr_path}", file=sys.stderr
            )
            return 1
        if not client.is_loaded:
            if not args.quiet:
                print("Загрузка базы данных рейтингов для OCR...", file=sys.stderr)
            client.load_ratings()
        if not args.quiet:
            print(f"Распознавание игроков со скриншота через OCR: {ocr_path}...", file=sys.stderr)
        rec_text, candidates = OcrProcessor.process_image(ocr_path, client, auto_fuzzy_correct=True)
        if not candidates and rec_text:
            candidates = OcrProcessor.process_screenshot_text(
                rec_text, client, auto_fuzzy_correct=True
            )
        if not candidates:
            print("OCR не смог извлечь игроков со скриншота.", file=sys.stderr)
            return 1
        if not args.quiet:
            print(f"Распознано кандидатов: {len(candidates)}", file=sys.stderr)
            for c in candidates:
                if c["corrected"]:
                    print(
                        f"   Исправление OCR: '{c['raw_ocr']}' -> '{c['matched_name']}' (исправлена опечатка, схожесть {int(c['similarity']*100)}%)",
                        file=sys.stderr,
                    )
                elif c["player_id"]:
                    print(
                        f"   '{c['matched_name']}' (найден в базе, балл {c['avg']})",
                        file=sys.stderr,
                    )
                else:
                    print(f"   • '{c['matched_name']}' (не найден в базе)", file=sys.stderr)
        input_text = "\n".join(c["matched_name"] for c in candidates)
    elif args.input:
        if os.path.isfile(args.input):
            with open(args.input, "r", encoding="utf-8", errors="replace") as f:
                input_text = f.read()
        else:
            print(f"Ошибка: входной файл не найден: {args.input}", file=sys.stderr)
            return 1
    elif args.players:
        # Comma or newline separated string from command line argument
        input_text = args.players.replace(",", "\n")
    elif args.interactive:
        print(
            "Введите список игроков (по одному на строку). Для завершения ввода введите пустую строку или нажмите Ctrl+Z (Enter):"
        )
        lines = []
        try:
            while True:
                line = input()
                if not line.strip() and lines:
                    break
                lines.append(line)
        except EOFError:
            pass
        input_text = "\n".join(lines)
    elif not sys.stdin.isatty():
        # Piped input e.g. cat players.txt | python main.py --cli
        input_text = sys.stdin.read()
    else:
        print(
            "Ошибка: не указан источник игроков. Используйте --input <файл>, --players <список>, --ocr <изображение> или --interactive",
            file=sys.stderr,
        )
        return 1

    if not input_text.strip():
        print("Ошибка: передан пустой список игроков.", file=sys.stderr)
        return 1

    # 3. Load ratings database
    try:
        if not client.is_loaded:
            if not args.quiet:
                print("Загрузка базы данных рейтингов с shinrireviews.com...", file=sys.stderr)
            client.load_ratings()
            if not args.quiet:
                print(
                    f"Загружено {client.total_rated_players} игроков (источник: {client.data_source})",
                    file=sys.stderr,
                )
    except ShinriNetworkError as e:
        print(f"Ошибка сети: {e}", file=sys.stderr)
        print(
            "Попробуйте указать флаг --offline или импортировать оффлайн-базу (--import-db).",
            file=sys.stderr,
        )
        return 1

    # 4. Parse & Match
    is_chat_log = getattr(args, "chat_log", False)
    items = InputParser.parse_text(input_text, is_chat_log=is_chat_log)
    if not items:
        print("Не удалось распознать ни одной записи игрока во вводе.", file=sys.stderr)
        return 1

    strategy = "manual" if args.manual_ambiguous else "most_reviews"
    matcher = ProfileMatcher(client)
    matched_results = matcher.process_items(items, resolve_ambiguous_strategy=strategy)

    # 5. Rank
    ranking_mode = getattr(args, "ranking_mode", "bayesian")
    report = Ranker.generate_report(
        matched_results,
        top_n=args.top,
        min_reviews=args.min_reviews,
        ranking_mode=ranking_mode,
        global_avg=client.global_avg_rating,
    )

    # 6. Display results
    console = (
        Console(legacy_windows=False, highlight=False) if (HAS_RICH and not args.plain) else None
    )
    if console:
        try:
            print_rich_report(report, console)
        except Exception:
            print_plain_report(report)
    else:
        print_plain_report(report)

    # 7. Optional Analytics: Lobby Safety Meter
    if getattr(args, "lobby_safety", False):
        ranked_dicts = [p for p in report.analytics_roster() if not p.get("rating_imputed")]
        unrated_dicts = [p for p in report.analytics_roster() if p.get("rating_imputed")]
        safety_analysis = LobbySafetyMeter.analyze_lobby(ranked_dicts, unrated_dicts)
        if console:
            print_rich_lobby_safety(safety_analysis, console)
        else:
            print_plain_lobby_safety(safety_analysis)

    # 8. Optional Analytics: Fair Team Balancer
    if getattr(args, "balance_teams", False):
        all_players_pool = report.analytics_roster()
        balance = TeamBalancer.balance_teams(all_players_pool, metric="bayesian_score")
        if console:
            print_rich_balance_teams(balance, console)
        else:
            print_plain_balance_teams(balance)

    # 8b. Optional Analytics: Clan Detection & Teaming Alerts
    if getattr(args, "clans", False):
        all_players_pool = report.analytics_roster()
        clan_stats = ClanDetector.detect_clans(all_players_pool)
        teaming_alert = ClanDetector.check_teaming_risk(all_players_pool)
        if console:
            print_rich_clans(clan_stats, teaming_alert, console)
        else:
            print_plain_clans(clan_stats, teaming_alert)

    # 8c. Optional Analytics: Tournament Bracket Generator
    if getattr(args, "tournament", None):
        all_players_pool = report.analytics_roster()
        if len(all_players_pool) < 2:
            print(
                "Ошибка: для генерации турнирной сетки необходимо минимум 2 игрока.",
                file=sys.stderr,
            )
        else:
            t_format = args.tournament
            if t_format == "round_robin":
                t_data = TournamentGenerator.generate_round_robin(all_players_pool)
            else:
                t_data = TournamentGenerator.generate_single_elimination(all_players_pool)
            if console:
                print_rich_tournament(t_data, console)
            else:
                print_plain_tournament(t_data)

    # 9. Exports
    if args.export_csv:
        Exporter.to_csv(report, args.export_csv)
        print(f"Результаты экспортированы в CSV: {args.export_csv}")

    if args.export_json:
        Exporter.to_json(report, args.export_json)
        print(f"Результаты экспортированы в JSON: {args.export_json}")

    if args.export_md:
        md_text = Exporter.to_markdown(report)
        with open(args.export_md, "w", encoding="utf-8") as f:
            f.write(md_text)
        print(f"Результаты экспортированы в Markdown: {args.export_md}")

    return 0
