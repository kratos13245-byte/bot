import os
import threading
import time
from typing import Callable, Optional

import requests

from contexto_minecraft import atualizar_contexto_minecraft


class MinecraftBridge:
    def __init__(self):
        self.base_url = os.getenv("MC_BRIDGE_URL", "http://127.0.0.1:8095").rstrip("/")
        self.enabled = os.getenv("ENABLE_MINECRAFT", "0") == "1"
        self.poll_interval = float(os.getenv("MC_POLL_INTERVAL_SEC", "1.0"))
        self._cursor = 0
        self._thread: Optional[threading.Thread] = None
        self._stop = threading.Event()
        self._handler: Optional[Callable[[str, str], None]] = None
        self.context_enabled = os.getenv("MC_CONTEXT_ENABLED", "1") == "1"
        self.context_ttl_sec = float(os.getenv("MC_CONTEXT_TTL_SEC", "6"))

    def health(self):
        r = requests.get(f"{self.base_url}/health", timeout=5)
        r.raise_for_status()
        return r.json()

    def send_chat(self, text: str):
        text = (text or "").strip()
        if not text:
            return
        r = requests.post(f"{self.base_url}/chat", json={"text": text}, timeout=10)
        r.raise_for_status()

    def send_command(self, command: str):
        command = (command or "").strip()
        if not command:
            return
        r = requests.post(f"{self.base_url}/command", json={"command": command}, timeout=10)
        r.raise_for_status()

    def get_context(self):
        r = requests.get(f"{self.base_url}/context", timeout=8)
        r.raise_for_status()
        return r.json()

    def _poll_loop(self):
        last_context_pull = 0.0
        while not self._stop.is_set():
            try:
                r = requests.get(
                    f"{self.base_url}/events",
                    params={"cursor": self._cursor},
                    timeout=10,
                )
                r.raise_for_status()
                data = r.json()
                self._cursor = int(data.get("cursor", self._cursor))
                for ev in data.get("events", []):
                    if ev.get("type") != "chat":
                        continue
                    payload = ev.get("payload", {})
                    user = str(payload.get("username", "")).strip()
                    msg = str(payload.get("message", "")).strip()
                    if user and msg and self._handler:
                        self._handler(user, msg)
            except Exception:
                pass

            if self.context_enabled:
                now = time.time()
                if (now - last_context_pull) >= self.context_ttl_sec:
                    try:
                        ctx = self.get_context()
                        resumo = str(ctx.get("summary", "")).strip()
                        if resumo:
                            atualizar_contexto_minecraft(resumo)
                    except Exception:
                        pass
                    last_context_pull = now

            self._stop.wait(self.poll_interval)

    def start_polling(self, handler: Callable[[str, str], None]):
        self._handler = handler
        self._stop.clear()
        if self._thread and self._thread.is_alive():
            return
        self._thread = threading.Thread(target=self._poll_loop, daemon=True, name="mc-bridge-poll")
        self._thread.start()

    def stop(self):
        self._stop.set()
        if self._thread and self._thread.is_alive():
            self._thread.join(timeout=2)
