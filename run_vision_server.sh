#!/usr/bin/env bash
set -euo pipefail

LLAMA_BIN="${LLAMA_BIN:-/workspace/llama.cpp/build/bin/llama-server}"
VISION_MODEL_HF="${VISION_MODEL_HF:-ggml-org/Ministral-3-3B-Instruct-2512-GGUF:Q8_0}"
VISION_HOST="${VISION_HOST:-0.0.0.0}"
VISION_PORT="${VISION_PORT:-8081}"
VISION_THREADS="${VISION_THREADS:-8}"
VISION_CTX="${VISION_CTX:-2048}"
VISION_NGL="${VISION_NGL:-999}"

if [ ! -x "$LLAMA_BIN" ]; then
  echo "[VISION SERVER] llama-server nao encontrado/executavel em: $LLAMA_BIN"
  exit 1
fi

echo "[VISION SERVER] Subindo modelo: $VISION_MODEL_HF"
echo "[VISION SERVER] Endpoint: http://${VISION_HOST}:${VISION_PORT}/v1/chat/completions"

"$LLAMA_BIN" \
  -hf "$VISION_MODEL_HF" \
  --host "$VISION_HOST" \
  --port "$VISION_PORT" \
  -ngl "$VISION_NGL" \
  -c "$VISION_CTX" \
  --threads "$VISION_THREADS"
