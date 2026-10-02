@echo off
chcp 65001 > nul
cls
"%~dp0ShinriRanker.exe" --cli --input "%~dp0sample_players.txt" --top 10 --balance-teams --lobby-safety --clans
pause
