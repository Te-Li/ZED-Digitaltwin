@echo off
chcp 65001 >nul
cd /d "%~dp0"
python entity_to_heatmap.py --only-2d --serve
pause
