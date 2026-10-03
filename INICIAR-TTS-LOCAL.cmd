@echo off
cd /d "%~dp0"
if not exist ".venv-xtts\Scripts\python.exe" (
  echo Rode setup_local_xtts.ps1 primeiro.
  pause
  exit /b 1
)
rem O ModelManager do Coqui cria os modelos dentro de uma subpasta `tts`.
set XTTS_MODEL_DIR=%~dp0work\local-xtts\tts\tts_models--multilingual--multi-dataset--xtts_v2
if not exist "%XTTS_MODEL_DIR%\config.json" (
  echo Modelo XTTS nao encontrado em:
  echo %XTTS_MODEL_DIR%
  echo Execute setup_local_xtts.ps1 novamente e aceite a licenca CPML.
  pause
  exit /b 1
)
set TTS_SPEAKER_WAV=%~dp0voz_referencia.wav
set TTS_API_HOST=127.0.0.1
set TTS_API_PORT=8092
set TTS_PRELOAD=1
set IARA_API_KEY=local-test
".venv-xtts\Scripts\python.exe" tts_api.py
pause
