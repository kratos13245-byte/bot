@echo off
cd /d "%~dp0"
if not exist ".venv-xtts\Scripts\python.exe" (
  echo Rode setup_local_xtts.ps1 primeiro.
  pause
  exit /b 1
)
set XTTS_MODEL_DIR=%~dp0work\local-xtts\tts_models--multilingual--multi-dataset--xtts_v2
set TTS_SPEAKER_WAV=%~dp0voz_referencia.wav
set TTS_API_HOST=127.0.0.1
set TTS_API_PORT=8092
set TTS_PRELOAD=1
set IARA_API_KEY=local-test
".venv-xtts\Scripts\python.exe" tts_api.py
pause
