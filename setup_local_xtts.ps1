$ErrorActionPreference = 'Stop'
$root = Split-Path -Parent $MyInvocation.MyCommand.Path
$venv = Join-Path $root '.venv-xtts'
$modelDir = Join-Path $root 'work\local-xtts'
$python = Join-Path $venv 'Scripts\python.exe'
if (-not (Test-Path $python)) { py -3.11 -m venv $venv }
& $python -m pip install --upgrade pip
& $python -m pip install -r (Join-Path $root 'requirements-server.txt')
New-Item -ItemType Directory -Force $modelDir | Out-Null
Write-Host 'A Coqui vai pedir a confirmação da licença CPML. Para uso pessoal, responda y.'
& $python -c "from TTS.utils.manage import ModelManager; import sys; ModelManager(output_prefix=sys.argv[1]).download_model('tts_models/multilingual/multi-dataset/xtts_v2')" $modelDir
Write-Host 'XTTS instalado. Inicie INICIAR-TTS-LOCAL.cmd.'
