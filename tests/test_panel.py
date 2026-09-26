import asyncio
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

import iara_panel


class PanelConfigTests(unittest.TestCase):
    def test_config_preserves_secret_when_masked(self):
        with tempfile.TemporaryDirectory() as tmp:
            env_file = Path(tmp) / ".env"
            env_file.write_text("IARA_API_KEY=segredo\nAI_API_URL=http://old\n", encoding="utf-8")
            with patch.object(iara_panel, "ENV_FILE", env_file):
                panel = iara_panel.Panel()
                self.assertEqual(panel.config()["IARA_API_KEY"], "configured")
                asyncio.run(panel.config_post(_Request({"IARA_API_KEY": "configured", "AI_API_URL": "http://new"})))
                self.assertIn("IARA_API_KEY=segredo", env_file.read_text(encoding="utf-8"))
                self.assertIn("AI_API_URL=http://new", env_file.read_text(encoding="utf-8"))


class _Request:
    def __init__(self, data): self.data = data
    async def json(self): return self.data


if __name__ == "__main__": unittest.main()
