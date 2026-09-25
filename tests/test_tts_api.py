import os
import unittest
from unittest.mock import patch
from aiohttp.test_utils import TestClient, TestServer
import tts_api


class TtsApiTests(unittest.IsolatedAsyncioTestCase):
    async def asyncSetUp(self):
        self.env = patch.dict(os.environ, {"IARA_API_KEY": "test-key", "TTS_API_KEY": "", "TTS_PRELOAD": "0"})
        self.env.start()
        self.client = TestClient(TestServer(tts_api.build_app()))
        await self.client.start_server()

    async def asyncTearDown(self):
        await self.client.close()
        self.env.stop()

    async def test_requires_key_and_can_run_without_minecraft(self):
        response = await self.client.get('/health')
        self.assertEqual(response.status, 401)
        response = await self.client.get('/health', headers={"Authorization": "Bearer test-key"})
        self.assertEqual(response.status, 200)

    async def test_voice_endpoint_and_invalid_input(self):
        headers = {"Authorization": "Bearer test-key"}
        response = await self.client.post('/tts', json=[], headers=headers)
        self.assertEqual(response.status, 400)
        with patch.object(tts_api, "gerar_audio_wav_bytes", return_value=(b"test-wav", "normal")) as synth:
            response = await self.client.post('/tts', json={"text": "Oi", "speaker_wav": "/ignored"}, headers=headers)
            self.assertEqual(response.status, 200)
            self.assertEqual(await response.read(), b"test-wav")
            self.assertEqual(synth.call_args.args[1], tts_api.ARQUIVO_VOZ)
