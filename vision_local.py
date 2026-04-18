import base64
import io
import os
import threading
import time

import requests

from contexto_visao import (
    atualizar_contexto_visao,
    definir_visao_ativa,
    limpar_contexto_visao,
    obter_contexto_visao,
)


def _resolver_url_vision() -> str:
    raw = os.getenv("VISION_API_URL", "").strip()
    if not raw and os.getenv("VISION_USE_AI_FALLBACK", "0") == "1":
        raw = os.getenv("AI_API_URL", "").strip()
    if not raw:
        return ""

    raw = raw.rstrip("/")
    if raw.endswith("/v1/chat/completions"):
        return raw
    if raw.endswith("/v1"):
        return raw + "/chat/completions"
    return raw + "/v1/chat/completions"


def _capturar_jpeg_base64():
    import mss
    from PIL import Image

    with mss.mss() as sct:
        monitor = sct.monitors[1]
        shot = sct.grab(monitor)

    img = Image.frombytes("RGB", shot.size, shot.rgb)

    max_lado = int(os.getenv("VISION_MAX_SIDE", "1280"))
    w, h = img.size
    maior = max(w, h)
    if maior > max_lado:
        escala = max_lado / float(maior)
        img = img.resize((int(w * escala), int(h * escala)))

    buffer = io.BytesIO()
    qualidade = int(os.getenv("VISION_JPEG_QUALITY", "70"))
    img.save(buffer, format="JPEG", quality=qualidade, optimize=True)
    return base64.b64encode(buffer.getvalue()).decode("ascii")


def _gerar_resumo_visual():
    url = _resolver_url_vision()
    if not url:
        raise RuntimeError(
            "VISION_API_URL nao configurada. "
            "Defina um endpoint multimodal dedicado para visao."
        )

    modelo = os.getenv("VISION_MODEL", "local-model").strip() or "local-model"
    prompt = os.getenv(
        "VISION_PROMPT",
        "Descreva a tela atual em portugues do Brasil, em ate 3 frases curtas. "
        "Foque no que a pessoa esta fazendo agora e no que mudou recentemente.",
    ).strip()

    imagem_b64 = _capturar_jpeg_base64()
    payload = {
        "model": modelo,
        "messages": [
            {"role": "system", "content": "Voce descreve telas de forma objetiva e util."},
            {
                "role": "user",
                "content": [
                    {"type": "text", "text": prompt},
                    {"type": "image_url", "image_url": {"url": f"data:image/jpeg;base64,{imagem_b64}"}},
                ],
            },
        ],
        "temperature": 0.2,
        "max_tokens": 180,
    }

    r = requests.post(url, json=payload, timeout=120)
    if r.status_code >= 400:
        detalhe = r.text
        if "image input is not supported" in detalhe.lower():
            raise RuntimeError(
                "Endpoint de visao nao suporta imagem (faltando modelo multimodal/mmproj)."
            )
    r.raise_for_status()
    data = r.json()
    return str(data["choices"][0]["message"]["content"]).strip()


class VisionWatcher:
    def __init__(self):
        self.intervalo = float(os.getenv("VISION_INTERVAL_SEC", "3"))
        self._thread = None
        self._stop = threading.Event()
        self._enabled = False
        self._ultima_tentativa = 0.0
        self._ultimo_erro = ""

    def _loop(self):
        while not self._stop.is_set():
            self._ultima_tentativa = time.time()
            try:
                resumo = _gerar_resumo_visual()
                if resumo:
                    atualizar_contexto_visao(resumo)
                    self._ultimo_erro = ""
            except Exception as e:
                self._ultimo_erro = str(e)
                if os.getenv("VISION_DEBUG", "0") == "1":
                    print(f"[VISAO] Falha ao gerar resumo: {e}")
            self._stop.wait(self.intervalo)

    def start(self):
        if self._enabled:
            return False
        self._enabled = True
        definir_visao_ativa(True)
        self._stop.clear()
        self._thread = threading.Thread(target=self._loop, daemon=True, name="vision-watcher")
        self._thread.start()
        return True

    def stop(self):
        if not self._enabled:
            return False
        self._enabled = False
        definir_visao_ativa(False)
        self._stop.set()
        if self._thread:
            self._thread.join(timeout=2)
        self._thread = None
        if os.getenv("VISION_CLEAR_ON_STOP", "1") == "1":
            limpar_contexto_visao()
        return True

    def force_once(self):
        resumo = _gerar_resumo_visual()
        atualizar_contexto_visao(resumo)
        return resumo

    def status(self):
        ctx = obter_contexto_visao()
        return {
            "enabled": self._enabled,
            "intervalo": self.intervalo,
            "ultimo_erro": self._ultimo_erro,
            "ultima_tentativa": self._ultima_tentativa,
            "resumo": ctx["resumo"],
            "resumo_timestamp": ctx["timestamp"],
        }
