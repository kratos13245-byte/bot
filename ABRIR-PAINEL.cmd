@echo off
cd /d "%~dp0"
if not exist ".venv\Scripts\python.exe" (
  echo Ambiente Python nao encontrado. Rode setup_runpod.sh no servidor ou instale requirements-client.txt.
  pause
  exit /b 1
)
start "IARA painel" /min "%~dp0.venv\Scripts\python.exe" iara_panel.py
timeout /t 2 /nobreak >nul
start "" http://127.0.0.1:8765
