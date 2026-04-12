import asyncio
import os

from aiohttp import web

from tts import ARQUIVO_VOZ, gerar_audio_wav_bytes


async def health_handler(_request):
    return web.json_response({"ok": True})


async def tts_handler(request):
    data = await request.json()
    texto = str(data.get("text") or data.get("texto") or "").strip()
    emocao = str(data.get("emotion") or data.get("emocao") or "auto").strip()
    language = str(data.get("language") or "pt").strip()
    speaker_wav = str(data.get("speaker_wav") or ARQUIVO_VOZ).strip()

    if not texto:
        return web.json_response({"error": "text vazio"}, status=400)

    wav_bytes, emocao_usada = await asyncio.to_thread(
        gerar_audio_wav_bytes,
        texto,
        speaker_wav,
        language,
        emocao,
    )

    return web.Response(
        body=wav_bytes,
        content_type="audio/wav",
        headers={"X-Emotion-Used": emocao_usada},
    )


def build_app():
    app = web.Application(client_max_size=8 * 1024 * 1024)
    app.router.add_get("/health", health_handler)
    app.router.add_post("/tts", tts_handler)
    return app


if __name__ == "__main__":
    host = os.getenv("TTS_API_HOST", "0.0.0.0")
    port = int(os.getenv("TTS_API_PORT", "8092"))
    print(f"[TTS API] Iniciando em http://{host}:{port}")
    web.run_app(build_app(), host=host, port=port)
