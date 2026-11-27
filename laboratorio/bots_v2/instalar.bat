@echo off
chcp 65001 >nul
set PYTHONUTF8=1
REM Crea el entorno de Python e instala las dependencias (una sola vez).
cd /d %~dp0
py -m venv .venv || (echo No encuentro Python. Instalalo desde python.org marcando "Add python.exe to PATH". & pause & exit /b 1)
call .venv\Scripts\activate.bat
python -m pip install --upgrade pip
pip install -r requirements.txt
if not exist config.yaml copy config.ejemplo.yaml config.yaml
python -m pytest -q
echo.
echo Listo. Ahora proba: probar_c14.bat
pause
