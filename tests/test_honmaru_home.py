import json
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

from fastapi import FastAPI
from fastapi.testclient import TestClient

from panel.honmaru_home import HomeStore, create_home_router


class HonmaruHomeTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.path = Path(self.temp.name) / "status" / "honmaru_home.json"
        self.store = HomeStore(self.path)

    def test_old_install_opens_without_migrating_or_touching_settings(self):
        self.path.parent.mkdir()
        settings = self.path.parent / "panel_settings.json"
        original = b'{"theme":"pixel","params":{"daily":{"runs":5}}}'
        settings.write_bytes(original)
        self.assertEqual(self.store.read()["profile"], {})
        self.assertFalse(self.path.exists())
        self.store.save_profile({"attendant": "压切长谷部"})
        self.assertEqual(settings.read_bytes(), original)
        self.assertEqual(HomeStore(self.path).read()["profile"]["attendant"], "压切长谷部")

    def test_partial_profile_edit_keeps_notes_and_other_profile_fields(self):
        self.store.save_profile({"honmaru_name": "花见本丸", "joined_on": "2017-06-03"})
        note = self.store.save_note("终于等到你了。")
        self.store.save_profile({"attendant": "加州清光"})
        current = self.store.read()
        self.assertEqual(current["notes"][0], note)
        self.assertEqual(current["profile"]["honmaru_name"], "花见本丸")
        self.assertEqual(json.loads(self.path.with_suffix(".json.bak").read_text(encoding="utf-8"))["notes"][0], note)

    def test_note_correction_preserves_identity_and_creation_date(self):
        note = self.store.save_note("旧内容")
        edited = self.store.save_note("新内容", note["id"])
        self.assertEqual(edited["id"], note["id"])
        self.assertEqual(edited["created_at"], note["created_at"])
        self.assertEqual(len(self.store.read()["notes"]), 1)
        self.assertEqual(edited["body"], "新内容")

    def test_failed_atomic_replace_preserves_original_and_backup(self):
        self.store.save_note("不能丢掉的记录")
        original = self.path.read_bytes()
        with patch.object(Path, "replace", side_effect=OSError("disk unavailable")):
            with self.assertRaises(OSError):
                self.store.save_profile({"attendant": "加州清光"})
        self.assertEqual(self.path.read_bytes(), original)
        self.assertEqual(self.path.with_suffix(".json.bak").read_bytes(), original)

    def test_corrupt_or_newer_data_cannot_be_overwritten(self):
        self.path.parent.mkdir()
        for original in ['{broken', '{"schema_version":2,"profile":{},"notes":[]}']:
            self.path.write_text(original, encoding="utf-8")
            with self.assertRaises(ValueError):
                self.store.save_profile({"attendant": "加州清光"})
            self.assertEqual(self.path.read_text(encoding="utf-8"), original)

    def test_api_validation_and_reload(self):
        app = FastAPI()
        app.include_router(create_home_router(self.path))
        with TestClient(app) as client:
            self.assertEqual(client.get("/api/honmaru-home").status_code, 200)
            for data in [{"joined_on": "9999-01-01"}, {"joined_on": "2026-02-30"}, {"avatar": "https://example.com/avatar.png"}, {"attendant": 123}, {"params": {}}]:
                self.assertEqual(client.put("/api/honmaru-home/profile", json=data).status_code, 400)
            self.assertFalse(self.path.exists())
            self.assertEqual(client.put("/api/honmaru-home/profile", json={"attendant": "压切长谷部"}).status_code, 200)
            self.assertEqual(client.post("/api/honmaru-home/notes", json={"body": " "}).status_code, 400)
            self.assertEqual(client.put("/api/honmaru-home/notes/missing", json={"body": "小记"}).status_code, 404)
            self.assertEqual(client.get("/api/honmaru-home").json()["profile"]["attendant"], "压切长谷部")


if __name__ == "__main__":
    unittest.main()
