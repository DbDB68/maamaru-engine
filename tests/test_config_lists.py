import asyncio
import json
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch


class _Request:
    def __init__(self, payload):
        self.payload = payload

    async def json(self):
        return self.payload


class ConfigListsTests(unittest.TestCase):
    def test_wishlist_roundtrip_preserves_other_game_config(self):
        from panel import server

        with tempfile.TemporaryDirectory() as folder:
            path = Path(folder) / "touken_config.json"
            path.write_text(json.dumps({
                "version": "keep-me",
                "repair": {"blacklist": ["三日月宗近"]},
                "dismantle": {"whitelist": ["今剑"]},
            }, ensure_ascii=False), encoding="utf-8")

            with patch.object(server, "_CONFIG_PATH", path):
                before = asyncio.run(server.api_get_config_lists())
                self.assertEqual(before["sword_wishlist"], [])

                result = asyncio.run(server.api_save_config_lists(_Request({
                    "sword_wishlist": [" 姬鹤一文字 ", "", "道誉一文字"],
                })))
                after = asyncio.run(server.api_get_config_lists())

            self.assertEqual(result, {"ok": True})
            self.assertEqual(after["sword_wishlist"], ["姬鹤一文字", "道誉一文字"])
            saved = json.loads(path.read_text(encoding="utf-8"))
            self.assertEqual(saved["version"], "keep-me")
            self.assertEqual(saved["repair"]["blacklist"], ["三日月宗近"])
            self.assertEqual(saved["dismantle"]["whitelist"], ["今剑"])


if __name__ == "__main__":
    unittest.main()
