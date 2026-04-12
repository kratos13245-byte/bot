#!/usr/bin/env bash
set -euo pipefail

ROOT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"

LLAMA_BIN="${LLAMA_BIN:-/workspace/llama.cpp/build/bin/llama-server}"
LLAMA_MODEL_HF="${LLAMA_MODEL_HF:-QuantFactory/DarkIdol-Llama-3.1-8B-Instruct-1.2-Uncensored-GGUF:Q4_K_M}"
LLAMA_HOST="${LLAMA_HOST:-0.0.0.0}"
LLAMA_PORT="${LLAMA_PORT:-8080}"
LLAMA_THREADS="${LLAMA_THREADS:-10}"
LLAMA_CTX="${LLAMA_CTX:-2048}"
LLAMA_NGL="${LLAMA_NGL:-999}"

TTS_API_HOST="${TTS_API_HOST:-0.0.0.0}"
TTS_API_PORT="${TTS_API_PORT:-8092}"
export TTS_API_HOST TTS_API_PORT

export XTTS_MODEL_DIR="${XTTS_MODEL_DIR:-/workspace/models/xtts/tts_models--multilingual--multi-dataset--xtts_v2}"

if [ -f "$ROOT_DIR/.venv/bin/activate" ]; then
  echo "[RUNPOD STACK] Ativando venv: $ROOT_DIR/.venv"
  # shellcheck disable=SC1091
  source "$ROOT_DIR/.venv/bin/activate"
else
  echo "[RUNPOD STACK] Aviso: .venv nao encontrada em $ROOT_DIR/.venv"
fi

if [ ! -x "$LLAMA_BIN" ]; then
  echo "[RUNPOD STACK] llama-server nao encontrado/executavel em: $LLAMA_BIN"
  exit 1
fi

cleanup() {
  if [ -n "${LLAMA_PID:-}" ] && kill -0 "$LLAMA_PID" 2>/dev/null; then
    kill "$LLAMA_PID" 2>/dev/null || true
  fi
}
trap cleanup EXIT INT TERM

echo "[RUNPOD STACK] Subindo llama-server..."
echo "[RUNPOD STACK] Modelo: $LLAMA_MODEL_HF"
"$LLAMA_BIN" \
  -hf "$LLAMA_MODEL_HF" \
  --host "$LLAMA_HOST" \
  --port "$LLAMA_PORT" \
  -ngl "$LLAMA_NGL" \
  -c "$LLAMA_CTX" \
  --threads "$LLAMA_THREADS" &
LLAMA_PID=$!

sleep 2
echo "[RUNPOD STACK] Subindo tts_api.py em ${TTS_API_HOST}:${TTS_API_PORT}..."
python3 "$ROOT_DIR/tts_api.py"
