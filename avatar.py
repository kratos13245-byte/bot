import asyncio
import threading
from typing import Optional

import pyvts

# HUMOR = expressão base da personagem
MAPA_HUMOR = {
    "calma": "exp_calma",
    "provocadora": "exp_provocadora",
    "irritada": "exp_irritada",
    "animada": "exp_animada",
}

# EMOÇÃO = reação momentânea da fala
MAPA_EMOCAO = {
    "normal": "emo_normal",
    "amor": "emo_amor",
    "choro": "emo_choro",
    "irritada": "emo_irritada",
    "animada": "emo_animada",
    "negar": "emo_negar",
    "choque": "emo_choque",
}

HOTKEY_FALANDO_ON = "boca_falando_on"
HOTKEY_FALANDO_OFF = "boca_falando_off"

PARAM_MOUTH_AI = "MouthOpenAI"


class AvatarController:
    def __init__(self):
        self.loop = asyncio.new_event_loop()
        self.thread = threading.Thread(target=self._run_loop, daemon=True)
        self.thread.start()

        self.vts = None
        self.connected = False

        self.ultimo_humor: Optional[str] = None
        self.ultima_emocao: Optional[str] = None
        self.falando = False

        self._mouth_registered = False

    def _run_loop(self):
        asyncio.set_event_loop(self.loop)
        self.loop.run_forever()

    async def _connect_async(self):
        plugin_info = {
            "plugin_name": "IA VTuber Renato",
            "developer": "Renato + ChatGPT",
            "authentication_token_path": "./token_vts.json",
        }

        print("🔌 Conectando ao VTube Studio...")
        self.vts = pyvts.vts(plugin_info=plugin_info)
        await self.vts.connect()
        await self.vts.request_authenticate_token()
        await self.vts.request_authenticate()

        self.connected = True
        print("✅ Conectado ao VTube Studio")

        await self._ensure_mouth_parameter_async()

    def connect(self):
        future = asyncio.run_coroutine_threadsafe(self._connect_async(), self.loop)
        return future.result()

    async def _request_async(self, message_type: str, data: dict):
        if not self.connected:
            return None

        payload = {
            "apiName": "VTubeStudioPublicAPI",
            "apiVersion": "1.0",
            "requestID": f"req_{message_type}",
            "messageType": message_type,
            "data": data,
        }

        return await self.vts.request(payload)

    async def _ensure_mouth_parameter_async(self):
        if self._mouth_registered or not self.connected:
            return

        try:
            await self._request_async(
                "ParameterCreationRequest",
                {
                    "parameterName": PARAM_MOUTH_AI,
                    "explanation": "Mouth open value driven by AI TTS audio chunks.",
                    "min": 0.0,
                    "max": 1.0,
                    "defaultValue": 0.0,
                },
            )
            self._mouth_registered = True
            print(f"🧩 Custom parameter garantido: {PARAM_MOUTH_AI}")
        except Exception as e:
            print(f"⚠️ Não consegui criar/garantir o parâmetro {PARAM_MOUTH_AI}: {e}")

    async def _trigger_hotkey_async(self, hotkey_name: str):
        if not self.connected or not hotkey_name:
            return

        try:
            request = self.vts.vts_request.requestTriggerHotKey(hotkey_name)
            await self.vts.request(request)
            print(f"🎯 Hotkey enviada: {hotkey_name}")
        except Exception as e:
            print(f"❌ Erro ao enviar hotkey '{hotkey_name}': {e}")

    def trigger_hotkey(self, hotkey_name: str):
        if not self.connected:
            print("⚠️ Avatar não conectado")
            return

        future = asyncio.run_coroutine_threadsafe(
            self._trigger_hotkey_async(hotkey_name),
            self.loop
        )
        return future.result()

    def atualizar_humor(self, humor: str, force: bool = False):
        if not force and humor == self.ultimo_humor:
            return

        hotkey = MAPA_HUMOR.get(humor)
        if hotkey:
            self.trigger_hotkey(hotkey)
            self.ultimo_humor = humor

    def atualizar_emocao(self, emocao: str, force: bool = False):
        if not force and emocao == self.ultima_emocao:
            return

        hotkey = MAPA_EMOCAO.get(emocao)
        if hotkey:
            self.trigger_hotkey(hotkey)
            self.ultima_emocao = emocao

    def aplicar_expressao_completa(self, humor: str, emocao: str):
        self.atualizar_humor(humor, force=True)

        async def _delayed_emotion():
            await asyncio.sleep(0.08)
            hotkey = MAPA_EMOCAO.get(emocao, "emo_normal")
            await self._trigger_hotkey_async(hotkey)

        if self.connected:
            asyncio.run_coroutine_threadsafe(_delayed_emotion(), self.loop)
            self.ultima_emocao = emocao

    async def _set_mouth_value_async(self, value: float):
        if not self.connected:
            return

        await self._ensure_mouth_parameter_async()

        value = max(0.0, min(1.0, float(value)))

        try:
            await self._request_async(
                "InjectParameterDataRequest",
                {
                    "faceFound": False,
                    "mode": "set",
                    "parameterValues": [
                        {
                            "id": PARAM_MOUTH_AI,
                            "value": value,
                        }
                    ],
                },
            )
        except Exception as e:
            print(f"❌ Erro ao injetar parâmetro {PARAM_MOUTH_AI}: {e}")

    def set_mouth_value(self, value: float):
        if not self.connected:
            return

        future = asyncio.run_coroutine_threadsafe(
            self._set_mouth_value_async(value),
            self.loop
        )
        return future.result()

    def falando_on(self):
        self.trigger_hotkey(HOTKEY_FALANDO_ON)
        self.falando = True

    def falando_off(self):
        self.trigger_hotkey(HOTKEY_FALANDO_OFF)
        self.set_mouth_value(0.0)
        self.falando = False

    def resetar_estado_visual(self):
        self.ultimo_humor = None
        self.ultima_emocao = None
        self.falando = False
        print("♻️ Estado visual resetado")