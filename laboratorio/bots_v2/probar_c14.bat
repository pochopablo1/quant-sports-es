@echo off
chcp 65001 >nul
set PYTHONUTF8=1
REM Una sola pasada de c14 para ver que lee bien las APIs.
cd /d %~dp0
call .venv\Scripts\activate.bat
python -m c14_usdt_ars.dryrun --probar
pause
