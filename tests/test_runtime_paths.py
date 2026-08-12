import json
import tempfile
import unittest
from pathlib import Path

from touken.runtime_paths import DATA_SCHEMA_VERSION, ensure_runtime_data


class RuntimePathsTests(unittest.TestCase):
    def _bundle(self, root: Path) -> Path:
        bundle = root / "program"
        (bundle / "panel").mkdir(parents=True)
        (bundle / "profiles").mkdir()
        (bundle / "profiles" / "official_head.png").write_bytes(b"official")
        (bundle / "touken_config.example.json").write_text('{"default": true}', encoding="utf-8")
        (bundle / "panel" / "panel_config.example.json").write_text('{"panel": true}', encoding="utf-8")
        (bundle / "panel" / "expedition_schedule.json").write_text('{"entries": []}', encoding="utf-8")
        return bundle

    def test_first_start_creates_separated_layout_from_templates(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            bundle = self._bundle(root)
            data = root / "user-data"

            result = ensure_runtime_data(data, bundle, legacy_roots=[])

            self.assertEqual(result["data_schema"], DATA_SCHEMA_VERSION)
            self.assertEqual(json.loads((data / "config" / "touken.json").read_text()), {"default": True})
            self.assertTrue((data / "config" / "panel.json").is_file())
            self.assertTrue((data / "config" / "expedition.json").is_file())
            for directory in ("state", "logs", "debug", "backups", "updates", "profiles/overrides"):
                self.assertTrue((data / directory).is_dir(), directory)
            self.assertFalse((data / "profiles" / "overrides" / "official_head.png").exists())

    def test_legacy_migration_copies_backs_up_and_never_deletes(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            bundle = self._bundle(root)
            data = root / "user-data"
            legacy = root / "legacy"
            (legacy / "status").mkdir(parents=True)
            (legacy / "profiles").mkdir()
            (legacy / "touken_config.json").write_text('{"mine": true}', encoding="utf-8")
            (legacy / "status" / "daily_flags.json").write_text('{"done": true}', encoding="utf-8")
            (legacy / "status" / "maamaru_logs.db").write_bytes(b"sqlite")
            (legacy / "profiles" / "custom_head.png").write_bytes(b"png")

            result = ensure_runtime_data(data, bundle, legacy_roots=[legacy])

            self.assertGreaterEqual(result["copied"], 4)
            self.assertEqual(json.loads((data / "config" / "touken.json").read_text()), {"mine": True})
            self.assertTrue((data / "state" / "daily_flags.json").is_file())
            self.assertFalse((data / "state" / "maamaru_logs.db").exists())
            self.assertEqual((data / "logs" / "maamaru_logs.db").read_bytes(), b"sqlite")
            self.assertTrue((data / "profiles" / "overrides" / "custom_head.png").is_file())
            self.assertTrue(Path(result["backup"]).is_dir())
            self.assertTrue((legacy / "touken_config.json").is_file())

            second = ensure_runtime_data(data, bundle, legacy_roots=[legacy])
            self.assertEqual(second, result)

    def test_existing_new_config_wins_over_legacy_and_template(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            bundle = self._bundle(root)
            data = root / "user-data"
            legacy = root / "legacy"
            (data / "config").mkdir(parents=True)
            (legacy).mkdir()
            target = data / "config" / "touken.json"
            target.write_text('{"new": true}', encoding="utf-8")
            (legacy / "touken_config.json").write_text('{"old": true}', encoding="utf-8")

            ensure_runtime_data(data, bundle, legacy_roots=[legacy])

            self.assertEqual(json.loads(target.read_text()), {"new": True})


if __name__ == "__main__":
    unittest.main()
