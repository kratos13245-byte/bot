import ast
from concurrent.futures import ThreadPoolExecutor
import json
import os
from pathlib import Path
import random
import re
import tempfile
import time
import unittest
import requests
from unittest.mock import Mock, patch

import memory
from minecraft_bridge import MinecraftBridge
from obsidian_memory import ObsidianMemory
from procedure_memory import buscar_procedures
from storage import write_json_atomic


class Regressions(unittest.TestCase):
    def test_memory_concurrent_notes_are_preserved(self):
        with tempfile.TemporaryDirectory() as folder:
            with patch.object(memory, "ARQUIVO_MEMORIA", str(Path(folder) / "memory.json")):
                with ThreadPoolExecutor(max_workers=8) as pool:
                    list(pool.map(lambda i: memory.salvar_nota("user", f"nota {i}"), range(40)))
                self.assertEqual(len(memory.listar_notas()), 40)

    def test_atomic_failure_preserves_previous_file(self):
        with tempfile.TemporaryDirectory() as folder:
            path = Path(folder) / "state.json"
            write_json_atomic(path, {"old": True})
            with patch("storage.os.replace", side_effect=OSError("disk error")):
                with self.assertRaises(OSError):
                    write_json_atomic(path, {"new": True})
            self.assertEqual(json.loads(path.read_text()), {"old": True})
            self.assertEqual(list(Path(folder).iterdir()), [path])

    def test_pending_actions_do_not_receive_positive_feedback(self):
        with tempfile.TemporaryDirectory() as folder:
            with patch.dict(os.environ, {"OBSIDIAN_VAULT_DIR": folder, "OBSIDIAN_AUTO_MEMORY": "1"}):
                brain = ObsidianMemory()
                brain.record_minecraft_event(user="tester", command="mine stone", status="planner_ok",
                                             summary="Craft pronto, vou atacar", action="mine")
                state = brain._state["actions"]["mine"]
                self.assertEqual(state["ok"], 0)
                self.assertEqual(state["auto_positive"], 0)
                self.assertEqual(state["last_status"], "planner_accepted")
                brain.record_minecraft_event(user="tester", command="craft", status="command_ok",
                                             summary="Craft concluido", action="craft_tool")
                self.assertEqual(brain._state["actions"]["craft_tool"]["ok"], 1)

    def test_procedures_use_configured_vault_and_accents(self):
        with tempfile.TemporaryDirectory() as folder:
            base = Path(folder) / "Brain" / "Procedures"
            base.mkdir(parents=True)
            (base / "wood.md").write_text("---\nid: wood\ntitle: Árvore\n---\nObter madeira", encoding="utf-8")
            with patch.dict(os.environ, {"OBSIDIAN_VAULT_DIR": folder, "OBSIDIAN_MEMORY_BASE": "Brain", "MC_PROCEDURES_DIR": ""}):
                self.assertEqual(buscar_procedures("arvore")[0].id_, "wood")
                self.assertEqual(buscar_procedures("árvore", top_k=0), [])

    def test_command_terms_do_not_match_inside_words(self):
        bridge = MinecraftBridge()
        self.assertFalse(bridge._contains_any("invisivel", ["inv"]))
        self.assertTrue(bridge._contains_any("mostra inventario", ["inventario"]))

    def test_bridge_rejects_false_success_even_on_http_200(self):
        response = Mock(status_code=200)
        response.json.return_value = {"ok": False, "error": "missing materials"}
        with patch("minecraft_bridge.requests.post", return_value=response) as post:
            with self.assertRaises(requests.HTTPError):
                MinecraftBridge().send_action("craft_tool", {"item": "wooden_pickaxe"})
            self.assertGreaterEqual(post.call_args.kwargs["timeout"], 120)

    def test_plain_confirmation_and_cancellation_resolve_pending_command(self):
        # Load only the real pure command functions, avoiding main's hardware startup.
        names = {"_is_minecraft_command_message", "_is_negotiation_confirmation", "_is_negotiation_cancel",
                 "_cleanup_stale_negotiations", "_maybe_gate_minecraft_command"}
        tree = ast.parse(Path("main.py").read_text(encoding="utf-8"))
        module = ast.Module(body=[n for n in tree.body if isinstance(n, ast.FunctionDef) and n.name in names], type_ignores=[])
        from contextlib import suppress
        namespace = dict(re=re, time=time, random=random, suppress=suppress, MC_NEGOTIATION_MODE=True,
                         MC_NEGOTIATION_TTL_SEC=120, MC_NEGOTIATION_COOLDOWN_SEC=20,
                         MC_NEGOTIATION_PROB=0, mc_last_negotiation_ts=0,
                         mc_pending_negotiation_by_user={"renato": {"command": "mine stone", "ts": time.time()}})
        exec(compile(module, "main.py", "exec"), namespace)
        gate = namespace["_maybe_gate_minecraft_command"]
        self.assertEqual(gate("renato", "insisto")["override_command"], "mine stone")
        namespace["mc_pending_negotiation_by_user"]["renato"] = {"command": "mine stone", "ts": time.time()}
        self.assertTrue(gate("renato", "cancela")["blocked"])
        self.assertEqual(namespace["mc_pending_negotiation_by_user"], {})
        namespace["mc_pending_negotiation_by_user"]["renato"] = {"command": "mine stone", "ts": time.time()}
        self.assertFalse(gate("renato", "pare")["blocked"])
        self.assertEqual(namespace["mc_pending_negotiation_by_user"], {})


if __name__ == "__main__":
    unittest.main()
