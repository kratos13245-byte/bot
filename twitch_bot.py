import asyncio
import json
import os
from collections import deque
from typing import Optional

import aiohttp
import websockets
from twitchio import eventsub
from twitchio.ext import commands


def _load_local_env(path: str = ".env") -> None:
    if not os.path.exists(path):
        return

    try:
        with open(path, "r", encoding="utf-8") as env_file:
            for raw_line in env_file:
                line = raw_line.strip()

                if not line or line.startswith("#") or "=" not in line:
                    continue

                key, value = line.split("=", 1)
                key = key.strip()
                value = value.strip().strip('"').strip("'")

                if key and key not in os.environ:
                    os.environ[key] = value
    except Exception as e:
        print(f"[TWITCH] Aviso ao carregar .env: {e}")


_load_local_env()


TWITCH_CLIENT_ID = os.getenv("TWITCH_CLIENT_ID", "").strip()
TWITCH_CLIENT_SECRET = os.getenv("TWITCH_CLIENT_SECRET", "").strip()
TWITCH_BOT_ID = os.getenv("TWITCH_BOT_ID", "").strip()
TWITCH_OWNER_ID = os.getenv("TWITCH_OWNER_ID", "").strip()
TWITCH_CHANNEL = os.getenv("TWITCH_CHANNEL", "").strip()
TWITCH_TRIGGER_MODE = os.getenv("TWITCH_TRIGGER_MODE", "chat").strip().lower()
TWITCH_REWARD_ID = os.getenv("TWITCH_REWARD_ID", "").strip()
TWITCH_ACCESS_TOKEN = os.getenv("TWITCH_ACCESS_TOKEN", "").strip()

EVENTSUB_WS_URL = "wss://eventsub.wss.twitch.tv/ws"
EVENTSUB_SUB_URL = "https://api.twitch.tv/helix/eventsub/subscriptions"
SEND_CHAT_URL = "https://api.twitch.tv/helix/chat/messages"


class _TwitchChatBot(commands.AutoBot):
    def __init__(self, incoming_queue: asyncio.Queue, outgoing_queue: asyncio.Queue):
        super().__init__(
            client_id=TWITCH_CLIENT_ID,
            client_secret=TWITCH_CLIENT_SECRET,
            bot_id=TWITCH_BOT_ID,
            owner_id=TWITCH_OWNER_ID,
            prefix="!",
            subscriptions=[
                eventsub.ChatMessageSubscription(
                    broadcaster_user_id=TWITCH_OWNER_ID,
                    user_id=TWITCH_BOT_ID,
                )
            ],
            force_subscribe=True,
        )
        self.incoming_queue = incoming_queue
        self.outgoing_queue = outgoing_queue
        self._sender_task: Optional[asyncio.Task] = None
        self._channel_user = None
        self._recent_outgoing_messages = deque(maxlen=20)

    async def setup_hook(self) -> None:
        users = await self.fetch_users(ids=[TWITCH_OWNER_ID])
        self._channel_user = users[0] if users else None
        self._sender_task = asyncio.create_task(self._outgoing_sender())

    async def event_ready(self):
        return

    async def event_message(self, payload):
        chatter_name = getattr(payload.chatter, "name", None) or getattr(payload.chatter, "display_name", "desconhecido")
        chatter_id = getattr(payload.chatter, "id", "")
        text = getattr(payload, "text", "").strip()

        if not text:
            return

        if text in self._recent_outgoing_messages:
            return

        print(f"[TWITCH] {chatter_name}: {text}")

        await self.incoming_queue.put({
            "source": "twitch",
            "user": chatter_name,
            "user_id": str(chatter_id),
            "text": text,
        })

    async def _outgoing_sender(self):
        while True:
            item = await self.outgoing_queue.get()
            try:
                message = str(item.get("text", "")).strip()
                if not message:
                    continue

                if self._channel_user is None:
                    raise RuntimeError("Canal da Twitch nao foi carregado para envio de mensagens.")

                await self._channel_user.send_message(
                    sender=TWITCH_BOT_ID,
                    message=message,
                )
                self._recent_outgoing_messages.append(message)
            except Exception as e:
                print(f"[TWITCH] Erro enviando mensagem: {e}")
            finally:
                self.outgoing_queue.task_done()

    async def close(self, **options):
        if self._sender_task is not None:
            self._sender_task.cancel()
            await asyncio.gather(self._sender_task, return_exceptions=True)
            self._sender_task = None

        await super().close(**options)


class TwitchChatBridge:
    def __init__(self, incoming_queue: asyncio.Queue, outgoing_queue: asyncio.Queue):
        self.incoming_queue = incoming_queue
        self.outgoing_queue = outgoing_queue
        self.channel_name = TWITCH_CHANNEL
        self.mode = TWITCH_TRIGGER_MODE

        self._chat_bot: Optional[_TwitchChatBot] = None
        self._sender_task: Optional[asyncio.Task] = None
        self._http_session: Optional[aiohttp.ClientSession] = None
        self._websocket = None
        self._closed = False

    async def start(self, **options):
        if self.mode == "points":
            await self._start_points_mode()
            return

        self._chat_bot = _TwitchChatBot(self.incoming_queue, self.outgoing_queue)
        await self._chat_bot.start(**options)

    async def close(self, **options):
        self._closed = True

        if self._chat_bot is not None:
            await self._chat_bot.close(**options)
            self._chat_bot = None

        if self._websocket is not None:
            await self._websocket.close()
            self._websocket = None

        if self._sender_task is not None:
            self._sender_task.cancel()
            await asyncio.gather(self._sender_task, return_exceptions=True)
            self._sender_task = None

        if self._http_session is not None and not self._http_session.closed:
            await self._http_session.close()
            self._http_session = None

    def _validate_points_config(self) -> None:
        required = {
            "TWITCH_CLIENT_ID": TWITCH_CLIENT_ID,
            "TWITCH_ACCESS_TOKEN": TWITCH_ACCESS_TOKEN,
            "TWITCH_OWNER_ID": TWITCH_OWNER_ID,
        }
        missing = [name for name, value in required.items() if not value]

        if missing:
            raise RuntimeError(f"Variaveis ausentes no .env para modo points: {', '.join(missing)}")

    def _points_headers(self) -> dict:
        return {
            "Client-Id": TWITCH_CLIENT_ID,
            "Authorization": f"Bearer {TWITCH_ACCESS_TOKEN}",
            "Content-Type": "application/json",
        }

    async def _create_redemption_subscription(self, session_id: str) -> None:
        condition = {"broadcaster_user_id": TWITCH_OWNER_ID}
        if TWITCH_REWARD_ID:
            condition["reward_id"] = TWITCH_REWARD_ID

        payload = {
            "type": "channel.channel_points_custom_reward_redemption.add",
            "version": "1",
            "condition": condition,
            "transport": {
                "method": "websocket",
                "session_id": session_id,
            },
        }

        assert self._http_session is not None
        async with self._http_session.post(EVENTSUB_SUB_URL, headers=self._points_headers(), json=payload) as response:
            text = await response.text()

            if response.status not in {202, 409}:
                raise RuntimeError(f"Falha criando inscricao de rewards ({response.status}): {text}")

            if TWITCH_REWARD_ID:
                print(f"[TWITCH POINTS] Escutando reward_id={TWITCH_REWARD_ID}")
            else:
                print("[TWITCH POINTS] Escutando qualquer recompensa customizada")

    async def _handle_redemption_notification(self, message: dict) -> None:
        payload = message.get("payload", {})
        event = payload.get("event", {})

        user_name = event.get("user_name") or event.get("user_login") or "desconhecido"
        user_id = event.get("user_id", "")
        reward = event.get("reward", {}) or {}
        reward_title = reward.get("title", "Recompensa")
        reward_id = reward.get("id", "")
        user_input = (event.get("user_input") or "").strip()
        text = user_input or f"[Resgate sem texto] {reward_title}"

        print(f"[TWITCH] {user_name}: {text}")

        await self.incoming_queue.put({
            "source": "twitch_points",
            "user": user_name,
            "user_id": str(user_id),
            "text": text,
            "reward_id": str(reward_id),
            "reward_title": reward_title,
        })

    async def _points_outgoing_sender(self) -> None:
        while True:
            item = await self.outgoing_queue.get()
            try:
                message = str(item.get("text", "")).strip()
                if not message:
                    continue

                assert self._http_session is not None
                payload = {
                    "broadcaster_id": TWITCH_OWNER_ID,
                    "sender_id": TWITCH_BOT_ID,
                    "message": message,
                }

                async with self._http_session.post(SEND_CHAT_URL, headers=self._points_headers(), json=payload) as response:
                    text = await response.text()
                    if response.status >= 400:
                        raise RuntimeError(f"Falha ao enviar mensagem ({response.status}): {text}")
            except Exception as e:
                print(f"[TWITCH] Erro enviando mensagem: {e}")
            finally:
                self.outgoing_queue.task_done()

    async def _start_points_mode(self) -> None:
        self._validate_points_config()
        self._http_session = aiohttp.ClientSession()
        self._sender_task = asyncio.create_task(self._points_outgoing_sender())

        try:
            async with websockets.connect(EVENTSUB_WS_URL) as websocket:
                self._websocket = websocket

                while not self._closed:
                    raw_message = await websocket.recv()
                    message = json.loads(raw_message)
                    metadata = message.get("metadata", {})
                    message_type = metadata.get("message_type", "")

                    if message_type == "session_welcome":
                        session = message["payload"]["session"]
                        session_id = session["id"]
                        await self._create_redemption_subscription(session_id)
                        continue

                    if message_type == "session_keepalive":
                        continue

                    if message_type == "session_reconnect":
                        reconnect_url = message["payload"]["session"].get("reconnect_url", "")
                        raise RuntimeError(f"Twitch pediu reconexao do EventSub: {reconnect_url}")

                    if message_type == "revocation":
                        raise RuntimeError(f"Inscricao de rewards revogada: {json.dumps(message, ensure_ascii=False)}")

                    if message_type == "notification":
                        await self._handle_redemption_notification(message)
        finally:
            if self._sender_task is not None:
                self._sender_task.cancel()
                await asyncio.gather(self._sender_task, return_exceptions=True)
                self._sender_task = None

            if self._http_session is not None and not self._http_session.closed:
                await self._http_session.close()
                self._http_session = None
