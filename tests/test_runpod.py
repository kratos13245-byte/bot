import os
import argparse
from pathlib import Path
import tempfile
import unittest
from unittest.mock import patch, Mock

import runpod
import vision_local
from configurar_runpod import import_config
from service_auth import service_headers


class RunpodTests(unittest.TestCase):
    def test_service_selection_and_no_minecraft(self):
        self.assertEqual(runpod.services("tts"), ["tts"])
        self.assertEqual(runpod.services("vision"), ["vision"])
        self.assertEqual(runpod.services("text,tts,text"), ["text", "tts"])
        self.assertNotIn("minecraft", runpod.services("all"))
        with self.assertRaises(argparse.ArgumentTypeError):
            runpod.services("minecraft")

    def test_tts_command_does_not_require_llama(self):
        cmd = runpod.command("tts", {})
        self.assertEqual(Path(cmd[-1]).name, "tts_api.py")
        self.assertNotIn("llama-server", " ".join(cmd))

    def test_vision_uses_own_model_and_port(self):
        env = {"LLAMA_BIN": "/llama", "IARA_API_KEY": "test", "VISION_MODEL_HF": "vision/model"}
        cmd = runpod.command("vision", env)
        self.assertIn("vision/model", cmd)
        self.assertIn("8081", cmd)
        self.assertNotIn("8080", cmd)

    def test_local_vision_requires_projector(self):
        with tempfile.TemporaryDirectory() as folder:
            model = Path(folder) / "vision.gguf"
            model.touch()
            env = {"LLAMA_BIN": "/llama", "IARA_API_KEY": "test", "VISION_MODEL_LOCAL": str(model)}
            with self.assertRaisesRegex(RuntimeError, "VISION_MMPROJ"):
                runpod.command("vision", env)

    def test_export_only_selected_service_and_preserve_client_memory(self):
        with tempfile.TemporaryDirectory() as folder:
            root = Path(folder)
            with patch.object(runpod, "ROOT", root), patch.object(runpod, "config", return_value={"IARA_API_KEY": "test"}):
                runpod.client_env(["tts"], "newpod")
            source = root / "client-runpod.env"
            target = root / ".env"
            target.write_text("OBSIDIAN_VAULT_DIR=my-vault\nAI_API_URL=existing-text\n", encoding="utf-8")
            import_config(source, target)
            content = target.read_text()
            self.assertIn("OBSIDIAN_VAULT_DIR=my-vault", content)
            self.assertIn("AI_API_URL=existing-text", content)
            self.assertIn("https://newpod-8092.proxy.runpod.net", content)
            self.assertEqual(len(list(root.glob(".env.backup-*"))), 1)

    def test_private_configuration_is_preserved_on_rerun(self):
        with tempfile.TemporaryDirectory() as folder:
            path = Path(folder) / "runpod.env"
            with patch.object(runpod, "CONFIG", path):
                runpod.initialize_config()
                old = path.read_text()
                runpod.initialize_config()
                self.assertEqual(path.read_text(), old)
                self.assertIn("IARA_API_KEY=", old)

    def test_auth_key_has_service_override(self):
        with patch.dict(os.environ, {"IARA_API_KEY": "shared", "TTS_API_KEY": "voice"}):
            self.assertEqual(service_headers("tts"), {"Authorization": "Bearer voice"})

    def test_vision_request_is_independent_of_minecraft(self):
        response = Mock(status_code=200)
        response.json.return_value = {"choices": [{"message": {"content": "Uma janela aberta."}}]}
        with patch.dict(os.environ, {"ENABLE_MINECRAFT": "0", "VISION_API_URL": "http://vision", "IARA_API_KEY": "test"}), \
             patch.object(vision_local, "_capturar_jpeg_base64", return_value="image"), \
             patch.object(vision_local.requests, "post", return_value=response) as post:
            self.assertEqual(vision_local._gerar_resumo_visual(), "Uma janela aberta.")
            self.assertEqual(post.call_args.args[0], "http://vision/v1/chat/completions")
            self.assertEqual(post.call_args.kwargs["headers"], {"Authorization": "Bearer test"})

    def test_supervisor_cleans_up_other_services_on_failure(self):
        with tempfile.TemporaryDirectory() as folder:
            failed = Mock()
            failed.poll.return_value = 1
            failed.returncode = 1
            running = Mock()
            running.poll.return_value = None
            env = {"IARA_API_KEY": "test", "TTS_SPEAKER_WAV": "voice.wav"}
            with patch.object(runpod, "ROOT", Path(folder)), \
                 patch.object(runpod, "config", return_value=env), \
                 patch.object(runpod, "command", return_value=["fake-service"]), \
                 patch.object(runpod.Path, "is_file", return_value=True), \
                 patch.object(runpod, "healthy", return_value=False), \
                 patch.object(runpod.subprocess, "Popen", side_effect=[failed, running]):
                with self.assertRaisesRegex(RuntimeError, "encerrou"):
                    runpod.start(["text", "tts"])
            running.terminate.assert_called_once()
            running.wait.assert_called_once()
