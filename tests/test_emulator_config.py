import json
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

from fastapi.testclient import TestClient

from panel import server


class EmulatorConfigTests(unittest.TestCase):
    def _config_file(self, tmp: str, data: dict) -> Path:
        config_path = Path(tmp) / "touken_config.json"
        config_path.write_text(json.dumps(data, ensure_ascii=False), encoding="utf-8")
        return config_path

    def test_get_returns_current_address(self):
        with tempfile.TemporaryDirectory() as tmp:
            config_path = self._config_file(tmp, {"adb_address": "127.0.0.1:16384"})
            with patch.object(server, "_CONFIG_PATH", config_path):
                client = TestClient(server.app)
                data = client.get("/api/emulator-config").json()
                self.assertEqual(data["adb_address"], "127.0.0.1:16384")
                self.assertEqual(data["default_address"], server._DEFAULT_ADB_ADDR)

    def test_save_manual_address(self):
        with tempfile.TemporaryDirectory() as tmp:
            config_path = self._config_file(tmp, {"adb_path": "x"})
            with patch.object(server, "_CONFIG_PATH", config_path):
                client = TestClient(server.app)
                resp = client.post("/api/emulator-config", json={"adb_address": "127.0.0.1:16416"})
                self.assertTrue(resp.json()["ok"])
                saved = json.loads(config_path.read_text("utf-8"))
                self.assertEqual(saved["adb_address"], "127.0.0.1:16416")
                self.assertEqual(saved["adb_path"], "x")  # 别的键不动

    def test_emulator_serial_address_accepted(self):
        with tempfile.TemporaryDirectory() as tmp:
            config_path = self._config_file(tmp, {})
            with patch.object(server, "_CONFIG_PATH", config_path):
                client = TestClient(server.app)
                resp = client.post("/api/emulator-config", json={"adb_address": "emulator-5554"})
                self.assertEqual(resp.status_code, 200)
                saved = json.loads(config_path.read_text("utf-8"))
                self.assertEqual(saved["adb_address"], "emulator-5554")

    def test_blank_address_restores_autodiscovery(self):
        with tempfile.TemporaryDirectory() as tmp:
            config_path = self._config_file(tmp, {"adb_address": "127.0.0.1:16416"})
            with patch.object(server, "_CONFIG_PATH", config_path):
                client = TestClient(server.app)
                resp = client.post("/api/emulator-config", json={"adb_address": "  "})
                self.assertTrue(resp.json()["ok"])
                saved = json.loads(config_path.read_text("utf-8"))
                self.assertNotIn("adb_address", saved)

    def test_invalid_address_rejected(self):
        with tempfile.TemporaryDirectory() as tmp:
            config_path = self._config_file(tmp, {"adb_address": "127.0.0.1:16384"})
            with patch.object(server, "_CONFIG_PATH", config_path):
                client = TestClient(server.app)
                for bad in ("abc", "127.0.0.1:", "127.0.0.1:99999", "127.0.0.1:16384; rm -rf /"):
                    resp = client.post("/api/emulator-config", json={"adb_address": bad})
                    self.assertEqual(resp.status_code, 400, bad)
                saved = json.loads(config_path.read_text("utf-8"))
                self.assertEqual(saved["adb_address"], "127.0.0.1:16384")


if __name__ == "__main__":
    unittest.main()
