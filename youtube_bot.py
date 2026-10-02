"""Bridge opcional para mensagens do YouTube Live Chat."""
import asyncio
import os
from collections import deque
from typing import Optional

import aiohttp

API = "https://www.googleapis.com/youtube/v3"


def _env(name):
    return os.getenv(name, "").strip()


class YouTubeChatBridge:
    def __init__(self, incoming_queue: asyncio.Queue, outgoing_queue: asyncio.Queue):
        self.incoming_queue = incoming_queue
        self.outgoing_queue = outgoing_queue
        self.token = _env("YOUTUBE_ACCESS_TOKEN")
        self.api_key = _env("YOUTUBE_API_KEY")
        self.video_id = _env("YOUTUBE_VIDEO_ID")
        self.chat_id = _env("YOUTUBE_LIVE_CHAT_ID")
        self.poll_seconds = max(1.0, float(_env("YOUTUBE_POLL_INTERVAL_SEC") or "5"))
        self._session: Optional[aiohttp.ClientSession] = None
        self._sender_task = None
        self._closed = False
        self._page_token = None
        self._recent_outgoing = deque(maxlen=20)

    def _headers(self):
        return {"Authorization": f"Bearer {self.token}"} if self.token else {}

    async def _get(self, path, params):
        assert self._session is not None
        params = dict(params)
        if self.api_key:
            params["key"] = self.api_key
        async with self._session.get(API + path, params=params, headers=self._headers()) as response:
            payload = await response.json(content_type=None)
            if response.status >= 400:
                raise RuntimeError(f"YouTube API {response.status}: {payload}")
            return payload

    async def _resolve_chat_id(self):
        if self.chat_id:
            return self.chat_id
        if not self.video_id:
            raise RuntimeError("Configure YOUTUBE_LIVE_CHAT_ID ou YOUTUBE_VIDEO_ID.")
        payload = await self._get("/videos", {"part": "liveStreamingDetails", "id": self.video_id})
        items = payload.get("items") or []
        if not items:
            raise RuntimeError("YOUTUBE_VIDEO_ID não foi encontrado.")
        self.chat_id = (items[0].get("liveStreamingDetails") or {}).get("activeLiveChatId", "")
        if not self.chat_id:
            raise RuntimeError("A transmissão não está ao vivo ou não tem chat ativo.")
        return self.chat_id

    async def _outgoing_sender(self):
        while not self._closed:
            item = await self.outgoing_queue.get()
            try:
                text = str(item.get("text", "")).strip()
                if not text:
                    continue
                if text in self._recent_outgoing:
                    continue
                assert self._session is not None
                params = {"part": "snippet"}
                if self.api_key:
                    params["key"] = self.api_key
                body = {"snippet": {"liveChatId": self.chat_id, "type": "textMessageEvent", "textMessageDetails": {"messageText": text}}}
                async with self._session.post(API + "/liveChat/messages", params=params, headers=self._headers(), json=body) as response:
                    if response.status >= 400:
                        raise RuntimeError(f"YouTube API {response.status}: {await response.text()}")
                self._recent_outgoing.append(text)
            except Exception as exc:
                print(f"[YOUTUBE] Erro enviando mensagem: {exc}")
            finally:
                self.outgoing_queue.task_done()

    async def start(self):
        if not self.token:
            raise RuntimeError("Configure YOUTUBE_ACCESS_TOKEN no .env.")
        self._session = aiohttp.ClientSession()
        self.chat_id = await self._resolve_chat_id()
        self._sender_task = asyncio.create_task(self._outgoing_sender())
        print(f"[YOUTUBE] Escutando liveChatId={self.chat_id}")
        try:
            while not self._closed:
                params = {"part": "snippet,authorDetails", "liveChatId": self.chat_id, "maxResults": 200}
                if self._page_token:
                    params["pageToken"] = self._page_token
                payload = await self._get("/liveChat/messages", params)
                self._page_token = payload.get("nextPageToken")
                for item in payload.get("items") or []:
                    snippet = item.get("snippet") or {}
                    if snippet.get("type") != "textMessageEvent":
                        continue
                    details = snippet.get("textMessageDetails") or {}
                    text = str(details.get("messageText", "")).strip()
                    author = (item.get("authorDetails") or {}).get("displayName", "desconhecido")
                    if text:
                        print(f"[YOUTUBE] {author}: {text}")
                        await self.incoming_queue.put({"source": "youtube", "user": author, "user_id": (item.get("authorDetails") or {}).get("channelId", ""), "text": text})
                delay = payload.get("pollingIntervalMillis", int(self.poll_seconds * 1000)) / 1000
                await asyncio.sleep(max(1.0, delay))
        finally:
            await self.close()

    async def close(self):
        self._closed = True
        if self._sender_task:
            self._sender_task.cancel()
            await asyncio.gather(self._sender_task, return_exceptions=True)
            self._sender_task = None
        if self._session and not self._session.closed:
            await self._session.close()
        self._session = None
