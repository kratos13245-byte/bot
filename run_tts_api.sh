#!/usr/bin/env bash
set -euo pipefail

export TTS_API_HOST="${TTS_API_HOST:-0.0.0.0}"
export TTS_API_PORT="${TTS_API_PORT:-8092}"

python3 tts_api.py
