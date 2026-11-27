@echo off
chcp 65001 >nul
set PYTHONUTF8=1
REM Dry-run c14 en MODO LECTURA. Dejalo corriendo; Ctrl+C para cortar (guarda lo abierto).
cd /d %~dp0
call .venv\Scripts\activate.bat
python -m c14_usdt_ars.dryrun
python reporte.py c14
pause
