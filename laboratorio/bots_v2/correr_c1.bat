@echo off
chcp 65001 >nul
set PYTHONUTF8=1
REM Dry-run c1 en MODO LECTURA. Dejalo corriendo; Ctrl+C para cortar (guarda lo abierto).
cd /d %~dp0
call .venv\Scripts\activate.bat
python -m c1_rescate.dryrun
python reporte.py c1
pause
