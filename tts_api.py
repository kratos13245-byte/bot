import asyncio
import os
import hmac

from aiohttp import web

from tts import ARQUIVO_VOZ, gerar_audio_wav_bytes, _carregar_condicionamento

TTS_LOCK = web.AppKey("tts_lock", asyncio.Lock)


@web.middleware
async def authenticate(request, handler):
    key = os.getenv("TTS_API_KEY", "") or os.getenv("IARA_API_KEY", "")
    if key and not hmac.compare_digest(request.headers.get("Authorization", ""), f"Bearer {key}"):
        return web.json_response({"error": "unauthorized"}, status=401)
    return await handler(request)


async def preload(_app):
    if os.getenv("TTS_PRELOAD", "0") == "1":
        await asyncio.to_thread(_carregar_condicionamento, ARQUIVO_VOZ)


async def health_handler(_request):
    return web.json_response({"ok": True})


async def tts_handler(request):
    try:
        data = await request.json()
    except (ValueError, TypeError):
        return web.json_response({"error": "JSON invalido"}, status=400)
    if not isinstance(data, dict):
        return web.json_response({"error": "JSON deve ser um objeto"}, status=400)
    texto = str(data.get("text") or data.get("texto") or "").strip()
    emocao = str(data.get("emotion") or data.get("emocao") or "auto").strip()
    language = str(data.get("language") or "pt").strip()
    speaker_wav = ARQUIVO_VOZ

    if not texto:
        return web.json_response({"error": "text vazio"}, status=400)

    async with request.app[TTS_LOCK]:
        wav_bytes, emocao_usada = await asyncio.to_thread(
            gerar_audio_wav_bytes, texto, speaker_wav, language, emocao,
        )

    return web.Response(
        body=wav_bytes,
        content_type="audio/wav",
        headers={"X-Emotion-Used": emocao_usada},
    )


def build_app():
    app = web.Application(client_max_size=8 * 1024 * 1024, middlewares=[authenticate])
    app[TTS_LOCK] = asyncio.Lock()
    app.on_startup.append(preload)
    app.router.add_get("/health", health_handler)
    app.router.add_post("/tts", tts_handler)
    return app


if __name__ == "__main__":
    host = os.getenv("TTS_API_HOST", "0.0.0.0")
    port = int(os.getenv("TTS_API_PORT", "8092"))
    print(f"[TTS API] Iniciando em http://{host}:{port}")
    web.run_app(build_app(), host=host, port=port)
