#!/usr/bin/env bash
set -euo pipefail

REPO_URL="${IARA_REPO_URL:-https://github.com/kratos13245-byte/bot.git}"
TARGET="${IARA_TARGET_DIR:-/workspace/bot}"
PYTHON_BIN=""

if [[ "$(id -u)" -ne 0 ]]; then
  SUDO=sudo
else
  SUDO=""
fi

echo "== IARA: preparando o Pod =="
$SUDO apt-get update
$SUDO apt-get install -y git curl unzip build-essential cmake ffmpeg libsndfile1 python3-venv python3.11 python3.11-venv

if command -v python3.11 >/dev/null 2>&1; then
  PYTHON_BIN=python3.11
elif command -v python3.10 >/dev/null 2>&1; then
  PYTHON_BIN=python3.10
else
  echo "Python 3.10/3.11 não está disponível nesta imagem."
  echo "Escolha uma imagem CUDA devel com Python 3.11 e rode este script novamente."
  exit 2
fi

echo "Python selecionado: $($PYTHON_BIN --version)"
mkdir -p "$(dirname "$TARGET")"
rm -rf "$TARGET"

# O volume /workspace de alguns Pods não aceita chmod no .git/config.lock.
# O ZIP mantém o código completo e não precisa criar um repositório Git nesse volume.
TMP_DIR="$(mktemp -d)"
trap 'rm -rf "$TMP_DIR"' EXIT
curl -fsSL "https://github.com/kratos13245-byte/bot/archive/refs/heads/main.zip" -o "$TMP_DIR/iara.zip"
unzip -q "$TMP_DIR/iara.zip" -d "$TMP_DIR"
mv "$TMP_DIR/bot-main" "$TARGET"

cd "$TARGET/IARA"
echo "== IARA: instalando texto, TTS e visão =="
"$PYTHON_BIN" runpod.py setup

cat <<EOF

Instalação concluída.
Projeto: $TARGET/IARA
Python: $PYTHON_BIN

Envie voz_referencia.wav para /workspace/iara-data/voz_referencia.wav e inicie com:
  cd $TARGET/IARA
  bash run_runpod_stack.sh
EOF
