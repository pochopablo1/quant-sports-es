@echo off
chcp 65001 >nul
set PYTHONUTF8=1
cd /d %~dp0
call .venv\Scripts\activate.bat
python reporte.py c14
pause
