import os
import re
import threading
import time
import unicodedata
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

    def send_action(self, action: str, payload: Optional[dict] = None):
        action = (action or "").strip()
        if not action:
            return {"ok": False, "error": "action vazia"}
        r = requests.post(
            f"{self.base_url}/action",
            json={"action": action, "payload": payload or {}},
            timeout=12,
        )
        if r.status_code >= 400:
            detail = ""
            try:
                body = r.json()
                if isinstance(body, dict):
                    detail = str(body.get("error") or body)
                else:
                    detail = str(body)
            except Exception:
                detail = (r.text or "").strip()
            msg = (
                f"{r.status_code} Client Error em /action "
                f"(action={action}, payload={payload or {}}): {detail}"
            )
            raise requests.HTTPError(msg, response=r)
        return r.json()

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

    def _normalize(self, text: str) -> str:
        text = str(text or "").lower().strip()
        text = unicodedata.normalize("NFD", text)
        text = "".join(ch for ch in text if unicodedata.category(ch) != "Mn")
        text = re.sub(r"[^\w\s\-]", " ", text)
        text = re.sub(r"\s+", " ", text)
        return text

    def _contains_any(self, text: str, terms: list[str]) -> bool:
        return any(term in text for term in terms)

    def _strip_bot_invocation(self, text: str) -> str:
        text = text.strip()
        # Aceita chamadas como "iara, ...", "bot ...", "ei iara ..."
        text = re.sub(
            r"^(?:ei\s+)?(?:iara|bot|ia)\s*[:,\-]?\s*",
            "",
            text,
            flags=re.IGNORECASE,
        )
        return text.strip()

    def _extract_follow_target(self, raw: str):
        low = self._normalize(raw)
        # Evita interpretar "para de seguir X" como comando de seguir.
        if self._contains_any(
            low,
            [
                "para de seguir",
                "pare de seguir",
                "deixa de seguir",
                "nao siga",
                "não siga",
                "nao me siga",
                "não me siga",
            ],
        ):
            return None
        patterns = [
            r"(?:siga|segue|acompanha|acompanhe)\s+(?:o|a)?\s*([a-zA-Z0-9_]{3,20})",
            r"(?:vai\s+atras\s+de|gruda\s+em)\s+(?:o|a)?\s*([a-zA-Z0-9_]{3,20})",
        ]
        for p in patterns:
            m = re.search(p, raw, flags=re.IGNORECASE)
            if m:
                return m.group(1).strip()
        return None

    def _extract_coordinates(self, msg: str):
        # Formatos: "x 100 y 64 z -30" ou "100 64 -30"
        labeled = re.search(
            r"x\s*(-?\d+)\s*y\s*(-?\d+)\s*z\s*(-?\d+)",
            msg,
            flags=re.IGNORECASE,
        )
        if labeled:
            return int(labeled.group(1)), int(labeled.group(2)), int(labeled.group(3))

        generic = re.search(
            r"(?:ir|vai|va|v|teleporta|andar|anda)\s*(?:para|pra|ate)?\s*(-?\d+)\s+(-?\d+)\s+(-?\d+)",
            msg,
            flags=re.IGNORECASE,
        )
        if generic:
            return int(generic.group(1)), int(generic.group(2)), int(generic.group(3))
        return None

    def _sanitize_item_query(self, text: str) -> str:
        q = self._normalize(text)
        q = re.sub(r"^(?:um|uma|uns|umas|o|a|os|as)\s+", "", q).strip()
        return q

    def _sanitize_block_query(self, text: str) -> str:
        q = self._normalize(text)
        q = re.sub(r"^(?:um|uma|uns|umas|o|a|os|as)\s+", "", q).strip()
        return q

    def try_handle_natural_command(self, author: str, text: str):
        raw = (text or "").strip()
        if not raw:
            return {"handled": False}

        raw = self._strip_bot_invocation(raw)
        msg = self._normalize(raw)

        if msg in {"pare", "parar", "stop", "quieta", "fica quieta", "fica de boa", "espera ai"}:
            self.send_action("stop", {})
            return {"handled": True, "summary": "Parei tudo no Minecraft."}

        if self._contains_any(
            msg,
            [
                "para de seguir",
                "pare de seguir",
                "deixa de seguir",
                "nao me siga",
                "não me siga",
                "para de me seguir",
                "pare de me seguir",
                "me deixa",
                "me larga",
            ],
        ):
            self.send_action("stop", {})
            return {"handled": True, "summary": "Beleza, parei de seguir."}

        if self._contains_any(
            msg,
            [
                "siga-me",
                "siga me",
                "me siga",
                "me acompanha",
                "me acompanhe",
                "cola em mim",
                "vem comigo",
                "gruda em mim",
            ],
        ):
            self.send_action("follow_player", {"player": author})
            return {"handled": True, "summary": f"Vou seguir {author}."}

        target = self._extract_follow_target(raw)
        if target:
            self.send_action("follow_player", {"player": target})
            return {"handled": True, "summary": f"Vou seguir {target}."}

        coords = self._extract_coordinates(msg)
        if coords:
            x, y, z = coords
            self.send_action("goto", {"x": x, "y": y, "z": z, "range": 2})
            return {"handled": True, "summary": f"Indo para {x} {y} {z}."}

        if self._contains_any(
            msg,
            [
                "explore",
                "explorar",
                "vai explorando",
                "explora ai",
                "explora por ai",
                "anda por ai",
                "vai andando",
                "roda o mapa",
                "vagueia",
            ],
        ):
            self.send_action("explore", {"enabled": True})
            return {"handled": True, "summary": "Ativei exploracao autonoma."}

        if self._contains_any(
            msg,
            [
                "modo aventura",
                "aventura on",
                "ativa aventura",
                "ligar aventura",
                "fica autonoma",
                "vai se virar",
            ],
        ):
            if "off" in msg or "desativa" in msg or "desliga" in msg:
                self.send_action("set_adventure", {"enabled": False})
                return {"handled": True, "summary": "Modo aventura desativado."}
            self.send_action("set_adventure", {"enabled": True})
            return {"handled": True, "summary": "Modo aventura ativado."}

        if self._contains_any(
            msg,
            [
                "marcar base",
                "marca base",
                "seta base",
                "define base",
                "salva base",
            ],
        ):
            self.send_action("set_base_here", {})
            return {"handled": True, "summary": "Base marcada neste ponto."}

        if self._contains_any(
            msg,
            [
                "inventario",
                "inv",
                "mochila",
                "itens",
                "mostra inventario",
            ],
        ):
            out = self.send_action("inventory_summary", {})
            resumo = str(out.get("summary", "")).strip() or "Nao consegui ler o inventario agora."
            return {"handled": True, "summary": f"Inventario: {resumo}"}

        if self._contains_any(
            msg,
            [
                "voltar base",
                "volta pra base",
                "volta para base",
                "ir base",
                "vai pra base",
                "retorna base",
            ],
        ):
            self.send_action("go_base", {})
            return {"handled": True, "summary": "Voltando para a base."}

        m = re.search(
            r"(?:craft|faca|faz|cria|monta|construi|construir|transforma|transformar|converter|converte)\s+([a-z0-9_\-\s]+?)(?:\s+(?:x|por)?\s*(\d+))?$",
            msg,
        )
        if m:
            item = self._sanitize_item_query(m.group(1) or "")
            count = int(m.group(2) or "1")
            out = self.send_action("craft_tool", {"item": item, "count": count})
            if out.get("ok"):
                crafted = int(out.get("crafted", out.get("requested", count)))
                return {"handled": True, "summary": f"Craft concluido: {out.get('item', item)} x{crafted}."}
            err = str(out.get("error", "erro desconhecido")).strip()
            return {"handled": True, "summary": f"Nao consegui craftar agora: {err}"}

        m = re.search(
            r"(?:largar|larga|dropar|dropa|joga fora|descarta)\s+([a-z0-9_\-\s]+?)(?:\s+(?:x|por)?\s*(\d+))?$",
            msg,
        )
        if m:
            item = self._sanitize_item_query(m.group(1) or "")
            count = int(m.group(2) or "1")
            out = self.send_action("drop_item", {"item": item, "count": count})
            if out.get("ok"):
                dropped = int(out.get("dropped", out.get("requested", count)))
                return {"handled": True, "summary": f"Larguei {out.get('item', item)} x{dropped}."}
            err = str(out.get("error", "erro desconhecido")).strip()
            return {"handled": True, "summary": f"Nao consegui largar item: {err}"}

        m = re.search(
            r"(?:coloca|coloque|por|poe|põe|posiciona)\s+([a-z0-9_\-\s]+?)(?:\s+(?:x|por)?\s*(\d+))?(?:\s+(no chao|na frente|aqui))?$",
            msg,
        )
        if m:
            item = self._sanitize_item_query(m.group(1) or "")
            count = int(m.group(2) or "1")
            loc = (m.group(3) or "").strip()
            position = "here" if loc in {"no chao", "aqui"} else "front"
            out = self.send_action("place_block", {"item": item, "count": count, "position": position})
            if out.get("ok"):
                placed = int(out.get("placed", out.get("requested", count)))
                return {"handled": True, "summary": f"Coloquei {out.get('item', item)} x{placed}."}
            err = str(out.get("error", "erro desconhecido")).strip()
            return {"handled": True, "summary": f"Nao consegui colocar bloco: {err}"}

        m = re.search(
            r"(?:interage|interagir|usa|use|abre|abrir)\s+(?:o|a)?\s*([a-z0-9_\-\s]+)$",
            msg,
        )
        if m:
            block = self._sanitize_block_query(m.group(1) or "")
            out = self.send_action("interact_block", {"block": block})
            if out.get("ok"):
                return {"handled": True, "summary": f"Interagi com {out.get('block', block)}."}
            err = str(out.get("error", "erro desconhecido")).strip()
            return {"handled": True, "summary": f"Nao consegui interagir: {err}"}

        if self._contains_any(
            msg,
            [
                "para de explorar",
                "pare de explorar",
                "para exploracao",
                "pare exploracao",
                "deixa de explorar",
                "fica parado",
                "nao explora",
            ],
        ):
            self.send_action("explore", {"enabled": False})
            return {"handled": True, "summary": "Parei a exploracao autonoma."}

        m = re.search(
            r"(?:va ate|vai ate|v ate|procura|busca).*(?:bioma)\s+([a-z0-9_\-\s]+?)(?:\s+e\s+(?:procura|busca)\s+([a-z0-9_\-\s]+))?$",
            msg,
            flags=re.IGNORECASE,
        )
        if m:
            biome = (m.group(1) or "").strip()
            resource = (m.group(2) or "").strip()
            self.send_action("find_biome", {"biome": biome, "resource": resource})
            if resource:
                return {"handled": True, "summary": f"Vou ate o bioma {biome} e procuro {resource}."}
            return {"handled": True, "summary": f"Vou procurar o bioma {biome}."}

        m = re.search(r"(?:vai|va|ir)\s+(?:pro|para o|para)\s+bioma\s+([a-z0-9_\-\s]+)$", msg)
        if m:
            biome = (m.group(1) or "").strip()
            self.send_action("find_biome", {"biome": biome, "resource": ""})
            return {"handled": True, "summary": f"Vou procurar o bioma {biome}."}

        m = re.search(r"(?:procura|busca|acha|encontra)\s+(?:por\s+)?([a-z0-9_\-\s]+)$", msg, flags=re.IGNORECASE)
        if m:
            resource = (m.group(1) or "").strip()
            self.send_action("find_resource", {"resource": resource})
            return {"handled": True, "summary": f"Vou procurar {resource} por perto."}

        m = re.search(
            r"(?:mine|minera|minerar|quebra|coleta)\s+([a-z0-9_\-\s]+?)(?:\s+(?:x|por)?\s*(\d+))?$",
            msg,
        )
        if m:
            resource = (m.group(1) or "").strip()
            count = int(m.group(2) or "1")
            self.send_action("mine", {"resource": resource, "count": count})
            return {"handled": True, "summary": f"Vou minerar {resource} x{count}."}

        m = re.search(
            r"(?:colet[ea]|junta|junte|farm|farma|pegue|pega)\s+(?:materiais|recursos)\s+(?:pra|para)\s+([a-z0-9_\-\s]+?)(?:\s+(?:x|por)?\s*(\d+))?$",
            msg,
            flags=re.IGNORECASE,
        )
        if m:
            item = self._sanitize_item_query(m.group(1) or "")
            count = int(m.group(2) or "1")
            out = self.send_action("collect_for_item", {"item": item, "count": count})
            if out.get("ok"):
                if out.get("done"):
                    return {"handled": True, "summary": f"Ja temos materiais para {out.get('item', item)}."}
                nxt = str(out.get("next_resource", "material")).strip()
                missing = int(out.get("missing", count))
                return {
                    "handled": True,
                    "summary": f"Fechou. Vou coletar {nxt} x{missing} para fazer {out.get('item', item)}.",
                }
            err = str(out.get("error", "erro desconhecido")).strip()
            return {"handled": True, "summary": f"Nao consegui iniciar coleta de materiais: {err}"}

        if self._contains_any(
            msg,
            ["combate on", "ativar combate", "liga combate", "combate ligado", "auto combate on"],
        ):
            self.send_action("set_combat", {"enabled": True})
            return {"handled": True, "summary": "Combate automatico ativado."}
        if self._contains_any(
            msg,
            ["combate off", "desativar combate", "desliga combate", "combate desligado", "auto combate off"],
        ):
            self.send_action("set_combat", {"enabled": False})
            return {"handled": True, "summary": "Combate automatico desativado."}

        if self._contains_any(msg, ["loot on", "ativar loot", "liga loot", "loot ligado"]):
            self.send_action("set_loot", {"enabled": True})
            return {"handled": True, "summary": "Loot automatico ativado."}
        if self._contains_any(msg, ["loot off", "desativar loot", "desliga loot", "loot desligado"]):
            self.send_action("set_loot", {"enabled": False})
            return {"handled": True, "summary": "Loot automatico desativado."}

        if self._contains_any(msg, ["sobrevivencia on", "ativar sobrevivencia", "liga sobrevivencia"]):
            self.send_action("set_survival", {"enabled": True})
            return {"handled": True, "summary": "Modo sobrevivencia ativado."}
        if self._contains_any(msg, ["sobrevivencia off", "desativar sobrevivencia", "desliga sobrevivencia"]):
            self.send_action("set_survival", {"enabled": False})
            return {"handled": True, "summary": "Modo sobrevivencia desativado."}

        return {"handled": False}
