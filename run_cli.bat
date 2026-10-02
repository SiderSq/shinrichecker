@echo off
chcp 65001 > nul
title Shinri Reviews Ranker - CLI
echo Запуск расчета рейтинга через консоль...
python main.py --cli --input sample_players.txt --top 10 --balance-teams --lobby-safety --export-csv results.csv --export-json results.json --export-md results.md
pause
