"""
Export utilities for CSV, JSON, Markdown, and HTML reports,
including Bayesian scores, review counts, and avatar assets.
"""

from __future__ import annotations
import csv
import io
import json
from typing import Optional

from .ranker import RankingReport


class Exporter:
    """Exports RankingReport into various human and machine-readable formats."""

    @classmethod
    def to_json(cls, report: RankingReport, filepath: Optional[str] = None) -> str:
        data = report.to_dict()
        content = json.dumps(data, ensure_ascii=False, indent=2)
        if filepath:
            with open(filepath, "w", encoding="utf-8") as f:
                f.write(content)
        return content

    @classmethod
    def to_csv(cls, report: RankingReport, filepath: Optional[str] = None) -> str:
        output = io.StringIO()
        writer = csv.writer(output, delimiter=";")

        # Section 1: Best players
        writer.writerow([f"=== ЛУЧШИЕ ИГРОКИ (ТОП) [{report.ranking_mode.upper()}] ==="])
        writer.writerow(
            [
                "Место",
                "ID",
                "Имя игрока",
                "Средний балл",
                "Байесовский балл",
                "Количество отзывов",
                "Ссылка на профиль",
                "Аватарка",
                "Исходный ввод",
                "Примечание",
            ]
        )
        for p in report.best_players:
            writer.writerow(
                [
                    p.rank,
                    p.player_id,
                    p.name,
                    f"{p.avg_rating:.2f}".replace(".", ","),
                    f"{p.bayesian_score:.2f}".replace(".", ","),
                    p.reviews_count,
                    p.profile_url,
                    p.avatar_url,
                    p.original_input,
                    p.note or "",
                ]
            )
        writer.writerow([])

        # Section 2: Worst players
        writer.writerow([f"=== ХУДШИЕ ИГРОКИ (АНТИТОП) [{report.ranking_mode.upper()}] ==="])
        writer.writerow(
            [
                "Место",
                "ID",
                "Имя игрока",
                "Средний балл",
                "Байесовский балл",
                "Количество отзывов",
                "Ссылка на профиль",
                "Аватарка",
                "Исходный ввод",
                "Примечание",
            ]
        )
        for p in report.worst_players:
            writer.writerow(
                [
                    p.rank,
                    p.player_id,
                    p.name,
                    f"{p.avg_rating:.2f}".replace(".", ","),
                    f"{p.bayesian_score:.2f}".replace(".", ","),
                    p.reviews_count,
                    p.profile_url,
                    p.avatar_url,
                    p.original_input,
                    p.note or "",
                ]
            )
        writer.writerow([])

        # Section 3: Unrated players
        if report.unrated_players:
            writer.writerow(["=== ИГРОКИ БЕЗ ОЦЕНОК / РЕЙТИНГ НЕДОСТУПЕН ==="])
            writer.writerow(
                [
                    "Строка",
                    "ID",
                    "Имя игрока",
                    "Отзывы",
                    "Ссылка на профиль",
                    "Исходный ввод",
                    "Причина",
                ]
            )
            for p in report.unrated_players:
                writer.writerow(
                    [
                        p.line_number,
                        p.player_id or "",
                        p.name or "",
                        p.reviews_count or 0,
                        p.profile_url or "",
                        p.input_text,
                        p.resolution_note or "Нет отзывов",
                    ]
                )
            writer.writerow([])

        # Section 4: Ambiguous players
        if report.ambiguous_players:
            writer.writerow(["=== НЕОДНОЗНАЧНЫЕ СОВПАДЕНИЯ (ОМОНИМЫ) ==="])
            writer.writerow(["Строка", "Исходный ввод", "Количество кандидатов", "Кандидаты"])
            for p in report.ambiguous_players:
                cands_str = " | ".join(
                    f"ID {c.get('id')} ({c.get('name')}, {c.get('count')} отз., балл {c.get('avg')})"
                    for c in p.candidates
                )
                writer.writerow(
                    [
                        p.line_number,
                        p.input_text,
                        len(p.candidates),
                        cands_str,
                    ]
                )
            writer.writerow([])

        # Section 5: Missing profiles
        if report.missing_players:
            writer.writerow(["=== ОТСУТСТВУЮЩИЕ ПРОФИЛИ (НЕ НАЙДЕНЫ) ==="])
            writer.writerow(["Строка", "Исходный ввод", "Причина"])
            for p in report.missing_players:
                writer.writerow(
                    [
                        p.line_number,
                        p.input_text,
                        p.resolution_note or "Не найден",
                    ]
                )
            writer.writerow([])

        # Section 6: Duplicates
        if report.duplicates:
            writer.writerow(["=== ОБНАРУЖЕННЫЕ ДУБЛИКАТЫ ВО ВВОДЕ ==="])
            writer.writerow(
                ["Строка", "Исходный ввод", "ID дублируемого", "Имя дублируемого", "Примечание"]
            )
            for p in report.duplicates:
                writer.writerow(
                    [
                        p.line_number,
                        p.input_text,
                        p.duplicate_of_id or "",
                        p.duplicate_of_name or "",
                        p.resolution_note or "Дубликат",
                    ]
                )

        content = output.getvalue()
        if filepath:
            with open(filepath, "w", encoding="utf-8-sig", newline="") as f:
                f.write(content)

        return content

    @classmethod
    def to_markdown(cls, report: RankingReport) -> str:
        lines: List[str] = [
            "# Рейтинг игроков Shinri Reviews",
            "",
            f"- **Режим ранжирования:** {('Байесовский рейтинг (взвешенный)' if report.ranking_mode == 'bayesian' else 'Классический средний балл')}",
            f"- **Всего строк во вводе:** {report.total_inputs} | **Уникальных игроков:** {report.unique_inputs}",
            f"- **Количество мест:** {report.top_n} (мин. отзывов: {report.min_reviews})",
            "",
            "## Топ лучших игроков",
            "",
            "| № | Имя игрока | Средний балл | Взвешенный балл | Отзывы | Ссылка на профиль |",
            "|---|---|---|---|---|---|",
        ]

        if not report.best_players:
            lines.append("| - | *Нет подходящих игроков* | - | - | - | - |")
        else:
            for p in report.best_players:
                lines.append(
                    f"| **{p.rank}** | {p.name} | **{p.avg_rating:.2f}** | {p.bayesian_score:.2f} | {p.reviews_count} | [{p.profile_url}]({p.profile_url}) |"
                )

        lines.extend(
            [
                "",
                "## Антитоп (худшие игроки)",
                "",
                "| № | Имя игрока | Средний балл | Взвешенный балл | Отзывы | Ссылка на профиль |",
                "|---|---|---|---|---|---|",
            ]
        )

        if not report.worst_players:
            lines.append("| - | *Нет подходящих игроков* | - | - | - | - |")
        else:
            for p in report.worst_players:
                lines.append(
                    f"| **{p.rank}** | {p.name} | **{p.avg_rating:.2f}** | {p.bayesian_score:.2f} | {p.reviews_count} | [{p.profile_url}]({p.profile_url}) |"
                )

        if report.unrated_players:
            lines.extend(
                [
                    "",
                    "## Игроки без рейтинга (0 отзывов)",
                    "",
                    "| Строка | Имя / Ввод | Ссылка | Статус |",
                    "|---|---|---|---|",
                ]
            )
            for p in report.unrated_players:
                link = f"[{p.profile_url}]({p.profile_url})" if p.profile_url else "-"
                lines.append(
                    f"| {p.line_number} | {p.name or p.input_text} | {link} | {p.resolution_note} |"
                )

        if report.ambiguous_players:
            lines.extend(
                [
                    "",
                    "## Неоднозначные совпадения (омонимы)",
                    "",
                    "| Строка | Ввод | Варианты кандидатов |",
                    "|---|---|---|",
                ]
            )
            for p in report.ambiguous_players:
                cands = ", ".join(
                    f"[{c.get('name')} (ID: {c.get('id')})](https://shinrireviews.com/p/{c.get('id')})"
                    for c in p.candidates[:5]
                )
                lines.append(f"| {p.line_number} | `{p.input_text}` | {cands} |")

        if report.missing_players:
            lines.extend(
                [
                    "",
                    "## Не найдены на сайте",
                    "",
                    "| Строка | Ввод | Ошибка |",
                    "|---|---|---|",
                ]
            )
            for p in report.missing_players:
                lines.append(f"| {p.line_number} | `{p.input_text}` | {p.resolution_note} |")

        if report.duplicates:
            lines.extend(
                [
                    "",
                    "## Обнаруженные дубликаты",
                    "",
                    "| Строка | Ввод | Пояснение |",
                    "|---|---|---|",
                ]
            )
            for p in report.duplicates:
                lines.append(f"| {p.line_number} | `{p.input_text}` | {p.resolution_note} |")

        return "\n".join(lines)
