"""Test TTS or screen vision without Minecraft, Twitch, avatar or microphone."""
import argparse
import os
from pathlib import Path


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("service", choices=["tts", "vision"])
    parser.add_argument("--text", default="Porra, agora sim. Minha voz esta funcionando!")
    parser.add_argument("--output", type=Path, default=Path("teste-voz.wav"))
    args = parser.parse_args()
    env_file = Path(__file__).resolve().parent / ".env"
    if env_file.exists():
        for line in env_file.read_text(encoding="utf-8-sig").splitlines():
            if line.strip() and not line.lstrip().startswith("#") and "=" in line:
                key, value = line.split("=", 1)
                os.environ.setdefault(key.strip(), value.strip().strip('"').strip("'"))
    if args.service == "vision":
        from vision_local import _gerar_resumo_visual
        print(_gerar_resumo_visual())
    else:
        import requests
        from service_auth import service_headers
        base = os.getenv("REMOTE_TTS_URL", "").rstrip("/")
        if not base:
            raise RuntimeError("Configure REMOTE_TTS_URL no .env.")
        url = base if base.endswith("/tts") else base + "/tts"
        response = requests.post(url, json={"text": args.text, "emotion": "normal", "language": "pt"},
                                 headers=service_headers("tts"), timeout=(10, 90))
        response.raise_for_status()
        args.output.write_bytes(response.content)
        print(f"Audio salvo: {args.output.resolve()}")


if __name__ == "__main__":
    main()
