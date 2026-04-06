import asyncio
import threading
import random
import time
from typing import Optional

import pyvts

MAPA_HUMOR = {
    "calma": "exp_calma",
    "provocadora": "exp_provocadora",
    "irritada": "exp_irritada",
    "animada": "exp_animada",
}

MAPA_EMOCAO = {
    "normal": "emo_normal",
    "amor": "emo_amor",
    "choro": "emo_choro",
    "irritada": "emo_irritada",
    "animada": "emo_animada",
    "negar": "emo_negar",
    "choque": "emo_choque",
}

HOTKEY_ESCUTANDO_ON = "estado_escutando_on"
HOTKEY_ESCUTANDO_OFF = "estado_escutando_off"
HOTKEY_PENSANDO_ON = "estado_pensando_on"
HOTKEY_PENSANDO_OFF = "estado_pensando_off"

PARAM_MOUTH_AI = "MouthOpenAI"
PARAM_EYE_X_AI = "EyeXAI"
PARAM_EYE_Y_AI = "EyeYAI"
PARAM_HEAD_X_AI = "HeadXAI"
PARAM_HEAD_Y_AI = "HeadYAI"
PARAM_BLINK_LEFT_AI = "EyeBlinkLeftAI"
PARAM_BLINK_RIGHT_AI = "EyeBlinkRightAI"

# ===== AJUSTES DE MOVIMENTO =====
IDLE_TICK = 0.04              # frequência do loop
EYE_LERP = 0.28               # olhos mais rápidos
HEAD_LERP = 0.08              # cabeça mais suave
HEAD_MICRO_DRIFT = 0.1     # drift contínuo da cabeça
EYE_TARGET_HOLD_MIN = 0.25
EYE_TARGET_HOLD_MAX = 0.80
HEAD_TARGET_HOLD_MIN = 0.90
HEAD_TARGET_HOLD_MAX = 2.20
# ================================


class AvatarController:
    def __init__(self):
        self._request_lock = None
        self.loop = asyncio.new_event_loop()
        self.thread = threading.Thread(target=self._run_loop, daemon=True)
        self.thread.start()

        self.vts = None
        self.connected = False

        self.ultimo_humor: Optional[str] = None
        self.ultima_emocao: Optional[str] = None
        self.falando = False
        self.escutando = False
        self.pensando = False
        self.humor_atual = "calma"

        self._registered_params = set()

        self._idle_running = False
        self._idle_thread = None

        self._blink_running = False
        self._blink_thread = None

        self._eye_x = 0.0
        self._eye_y = 0.0
        self._head_x = 0.0
        self._head_y = 0.0

        self._target_eye_x = 0.0
        self._target_eye_y = 0.0
        self._target_head_x = 0.0
        self._target_head_y = 0.0

        self._next_eye_change = 0.0
        self._next_head_change = 0.0

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

        self._request_lock = asyncio.Lock()

        self.connected = True
        print("✅ Conectado ao VTube Studio")

        await self._ensure_all_parameters_async()

    def connect(self):
        future = asyncio.run_coroutine_threadsafe(self._connect_async(), self.loop)
        return future.result()

    async def _request_async(self, message_type: str, data: dict):
        if not self.connected or self._request_lock is None:
            return None

        payload = {
            "apiName": "VTubeStudioPublicAPI",
            "apiVersion": "1.0",
            "requestID": f"req_{message_type}_{int(time.time() * 1000)}",
            "messageType": message_type,
            "data": data,
        }

        async with self._request_lock:
            return await self.vts.request(payload)

    async def _ensure_parameter_async(self, parameter_name: str, explanation: str):
        if parameter_name in self._registered_params or not self.connected:
            return

        try:
            await self._request_async(
                "ParameterCreationRequest",
                {
                    "parameterName": parameter_name,
                    "explanation": explanation,
                    "min": -1.0 if parameter_name not in {PARAM_MOUTH_AI, PARAM_BLINK_LEFT_AI, PARAM_BLINK_RIGHT_AI} else 0.0,
                    "max": 1.0,
                    "defaultValue": 0.0,
                },
            )
            self._registered_params.add(parameter_name)
            print(f"🧩 Parâmetro garantido: {parameter_name}")
        except Exception as e:
            print(f"⚠️ Não consegui criar/garantir {parameter_name}: {e}")

    async def _ensure_all_parameters_async(self):
        await self._ensure_parameter_async(PARAM_MOUTH_AI, "Mouth open value driven by AI TTS audio.")
        await self._ensure_parameter_async(PARAM_EYE_X_AI, "Eye X movement driven by AI idle motion.")
        await self._ensure_parameter_async(PARAM_EYE_Y_AI, "Eye Y movement driven by AI idle motion.")
        await self._ensure_parameter_async(PARAM_HEAD_X_AI, "Head X movement driven by AI idle motion.")
        await self._ensure_parameter_async(PARAM_HEAD_Y_AI, "Head Y movement driven by AI idle motion.")
        await self._ensure_parameter_async(PARAM_BLINK_LEFT_AI, "Left eye blink driven by AI.")
        await self._ensure_parameter_async(PARAM_BLINK_RIGHT_AI, "Right eye blink driven by AI.")

    async def _trigger_hotkey_async(self, hotkey_name: str):
        if not self.connected or not hotkey_name or self._request_lock is None:
            return

        try:
            request = self.vts.vts_request.requestTriggerHotKey(hotkey_name)
            async with self._request_lock:
                await self.vts.request(request)
            print(f"🎯 Hotkey enviada: {hotkey_name}")
        except Exception as e:
            print(f"⚠️ Hotkey '{hotkey_name}' falhou: {e}")

    def trigger_hotkey(self, hotkey_name: str):
        if not self.connected:
            return

        future = asyncio.run_coroutine_threadsafe(
            self._trigger_hotkey_async(hotkey_name),
            self.loop
        )
        return future.result()

    def atualizar_humor(self, humor: str, force: bool = False):
        self.humor_atual = humor

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

    async def _inject_parameters_async(self, values: dict):
        if not self.connected:
            return

        await self._ensure_all_parameters_async()

        parameter_values = [{"id": k, "value": float(v)} for k, v in values.items()]

        try:
            await self._request_async(
                "InjectParameterDataRequest",
                {
                    "faceFound": False,
                    "mode": "set",
                    "parameterValues": parameter_values,
                },
            )
        except Exception as e:
            print(f"❌ Erro ao injetar parâmetros: {e}")

    def inject_parameters(self, values: dict):
        if not self.connected:
            return

        future = asyncio.run_coroutine_threadsafe(
            self._inject_parameters_async(values),
            self.loop
        )
        return future.result()

    def set_mouth_value(self, value: float):
        value = max(0.0, min(1.0, float(value)))
        self.inject_parameters({PARAM_MOUTH_AI: value})

    def set_blink_values(self, left=None, right=None):
        values = {}

        if left is not None:
            values[PARAM_BLINK_LEFT_AI] = max(0.0, min(1.0, float(left)))

        if right is not None:
            values[PARAM_BLINK_RIGHT_AI] = max(0.0, min(1.0, float(right)))

        if values:
            self.inject_parameters(values)

    def piscar(self, duration=0.08, assimetrica=False):
        if not self.connected:
            return

        def _blink_sequence():
            if assimetrica:
                left_close = random.uniform(0.85, 1.0)
                right_close = random.uniform(0.75, 1.0)
            else:
                left_close = 1.0
                right_close = 1.0

            self.set_blink_values(left_close, right_close)
            time.sleep(duration)
            self.set_blink_values(0.0, 0.0)

        threading.Thread(target=_blink_sequence, daemon=True).start()

    def set_idle_values(self, eye_x=None, eye_y=None, head_x=None, head_y=None):
        values = {}

        if eye_x is not None:
            self._eye_x = max(-1.0, min(1.0, float(eye_x)))
            values[PARAM_EYE_X_AI] = self._eye_x

        if eye_y is not None:
            self._eye_y = max(-1.0, min(1.0, float(eye_y)))
            values[PARAM_EYE_Y_AI] = self._eye_y

        if head_x is not None:
            self._head_x = max(-1.0, min(1.0, float(head_x)))
            values[PARAM_HEAD_X_AI] = self._head_x

        if head_y is not None:
            self._head_y = max(-1.0, min(1.0, float(head_y)))
            values[PARAM_HEAD_Y_AI] = self._head_y

        if values:
            self.inject_parameters(values)

    def falando_on(self):
        self.pensando_off()
        self.escutando_off()
        self.falando = True


    def falando_off(self):
        self.set_mouth_value(0.0)
        self.falando = False

    def escutando_on(self):
        if self.escutando:
            return
        self.trigger_hotkey(HOTKEY_ESCUTANDO_ON)
        self.escutando = True

    def escutando_off(self):
        if not self.escutando:
            return
        self.trigger_hotkey(HOTKEY_ESCUTANDO_OFF)
        self.escutando = False

    def pensando_on(self):
        if self.pensando:
            return
        self.trigger_hotkey(HOTKEY_PENSANDO_ON)
        self.pensando = True

    def pensando_off(self):
        if not self.pensando:
            return
        self.trigger_hotkey(HOTKEY_PENSANDO_OFF)
        self.pensando = False

    def resetar_estado_visual(self):
        self.ultimo_humor = None
        self.ultima_emocao = None
        self.falando = False
        self.escutando = False
        self.pensando = False

        self._eye_x = 0.0
        self._eye_y = 0.0
        self._head_x = 0.0
        self._head_y = 0.0

        self._target_eye_x = 0.0
        self._target_eye_y = 0.0
        self._target_head_x = 0.0
        self._target_head_y = 0.0

        self.set_mouth_value(0.0)
        self.set_blink_values(0.0, 0.0)
        self.set_idle_values(0.0, 0.0, 0.0, 0.0)
        print("♻️ Estado visual resetado")

    def _idle_profile(self):
        if self.humor_atual == "irritada":
            base = {
                "eye_range_x": 0.08,
                "eye_range_y": 0.05,
                "head_range_x": 0.08,
                "head_range_y": 0.05,
            }
        elif self.humor_atual == "provocadora":
            base = {
                "eye_range_x": 0.22,
                "eye_range_y": 0.10,
                "head_range_x": 0.14,
                "head_range_y": 0.09,
            }
        elif self.humor_atual == "animada":
            base = {
                "eye_range_x": 0.30,
                "eye_range_y": 0.18,
                "head_range_x": 0.18,
                "head_range_y": 0.12,
            }
        else:
            base = {
                "eye_range_x": 0.25,
                "eye_range_y": 0.18,
                "head_range_x": 0.20,
                "head_range_y": 0.15,
            }

        if self.escutando:
            base["head_range_x"] *= 0.9
            base["head_range_y"] *= 0.9

        if self.pensando:
            base["eye_range_x"] *= 1.4
            base["eye_range_y"] *= 1.2

        if self.falando:
            base["eye_range_x"] *= 0.7
            base["eye_range_y"] *= 0.7
            base["head_range_x"] *= 0.9
            base["head_range_y"] *= 0.9

        return base

    def _lerp(self, current, target, amount):
        return current + (target - current) * amount

    def _choose_eye_target(self, p):
        if self.pensando:
            return (
                random.choice([-1, 1]) * random.uniform(0.14, p["eye_range_x"]),
                random.uniform(-0.04, 0.08),
            )
        if self.humor_atual == "irritada":
            return (
                random.uniform(-0.04, 0.04),
                random.uniform(-0.03, 0.03),
            )
        return (
            random.uniform(-p["eye_range_x"], p["eye_range_x"]),
            random.uniform(-p["eye_range_y"], p["eye_range_y"]),
        )

    def _choose_head_target(self, p):
        if self.escutando:
            return (
                random.choice([-1, 1]) * random.uniform(0.04, 0.10),
                random.uniform(0.02, 0.08),
            )
        return (
            random.uniform(-p["head_range_x"], p["head_range_x"]),
            random.uniform(-p["head_range_y"], p["head_range_y"]),
        )

    def _idle_loop(self):
        self._next_eye_change = time.time()
        self._next_head_change = time.time()

        while self._idle_running:
            if not self.connected:
                time.sleep(1.0)
                continue

            now = time.time()
            p = self._idle_profile()

            if now >= self._next_eye_change:
                self._target_eye_x, self._target_eye_y = self._choose_eye_target(p)
                self._next_eye_change = now + random.uniform(EYE_TARGET_HOLD_MIN, EYE_TARGET_HOLD_MAX)

            if now >= self._next_head_change:
                self._target_head_x, self._target_head_y = self._choose_head_target(p)
                self._next_head_change = now + random.uniform(HEAD_TARGET_HOLD_MIN, HEAD_TARGET_HOLD_MAX)

            # olhos rápidos
            self._eye_x = self._lerp(self._eye_x, self._target_eye_x, EYE_LERP)
            self._eye_y = self._lerp(self._eye_y, self._target_eye_y, EYE_LERP)

            # cabeça suave com micro drift
            drift_x = random.uniform(-HEAD_MICRO_DRIFT, HEAD_MICRO_DRIFT)
            drift_y = random.uniform(-HEAD_MICRO_DRIFT, HEAD_MICRO_DRIFT)

            self._head_x = self._lerp(self._head_x, self._target_head_x + drift_x, HEAD_LERP)
            self._head_y = self._lerp(self._head_y, self._target_head_y + drift_y, HEAD_LERP)

            self.set_idle_values(
                eye_x=self._eye_x,
                eye_y=self._eye_y,
                head_x=self._head_x,
                head_y=self._head_y,
            )

            time.sleep(IDLE_TICK)

    def _blink_loop(self):
        while self._blink_running:
            if not self.connected:
                time.sleep(1.0)
                continue

            if self.humor_atual == "irritada":
                delay = random.uniform(4.0, 7.0)
            elif self.pensando:
                delay = random.uniform(2.5, 4.5)
            elif self.humor_atual == "animada":
                delay = random.uniform(2.8, 4.0)
            else:
                delay = random.uniform(3.5, 6.0)

            time.sleep(delay)

            if self._blink_running:
                self.piscar(assimetrica=random.random() < 0.2)

    def iniciar_idle(self):
        if self._idle_running:
            return

        self._idle_running = True
        self._idle_thread = threading.Thread(target=self._idle_loop, daemon=True)
        self._idle_thread.start()
        print("👀 Idle do avatar iniciado")

    def parar_idle(self):
        self._idle_running = False
        if self._idle_thread and self._idle_thread.is_alive():
            self._idle_thread.join(timeout=1.0)
        print("🛑 Idle do avatar parado")

    def iniciar_piscada(self):
        if self._blink_running:
            return

        self._blink_running = True
        self._blink_thread = threading.Thread(target=self._blink_loop, daemon=True)
        self._blink_thread.start()
        print("😉 Piscada automática iniciada")

    def parar_piscada(self):
        self._blink_running = False
        if self._blink_thread and self._blink_thread.is_alive():
            self._blink_thread.join(timeout=1.0)
        print("🛑 Piscada automática parada")