@echo off
chcp 65001 >nul
set PYTHONUTF8=1
REM Dry-run c15 en MODO LECTURA. Dejalo corriendo; Ctrl+C para cortar (guarda lo abierto).
cd /d %~dp0
call .venv\Scripts\activate.bat
python -m c15_mep_bonos.dryrun
python reporte.py c15
pause
