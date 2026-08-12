import hashlib
import json
import tempfile
import unittest
from pathlib import Path

from touken.runtime_paths import DATA_SCHEMA_VERSION, ensure_runtime_data


class RuntimePathsTests(unittest.TestCase):
    @staticmethod
    def _snapshot(root: Path) -> dict[str, str]:
        return {
            path.relative_to(root).as_posix(): hashlib.sha256(path.read_bytes()).hexdigest()
            for path in root.rglob("*")
            if path.is_file()
        }

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

    def test_v014_flat_user_directory_migrates_completely_and_is_repeatable(self):
        """Model the writable files produced beside data in the v0.1.4 release."""
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            bundle = self._bundle(root)
            old = root / "v0.1.4-user-data"
            old.mkdir()

            fixtures = {
                "touken_config.json": b'{"version":"1.0","adb_path":"D:/MuMu/adb.exe"}',
                "panel_config.json": b'{"ai":{"api_key":"private-test-key"}}',
                "expedition_schedule.json": b'{"entries":[{"team":3}]}',
                "launcher.log": "旧启动日志".encode(),
                "status/daily_flags.json": b'{"forge":"2026-08-11"}',
                "status/expeditions.json": b'{"3":{"map":"5-4"}}',
                "status/inventory.json": '{"木炭":12345}'.encode(),
                "status/session_state.json": b'{"messages":[]}',
                "status/maamaru_logs.db": b"SQLite format 3\x00test-db",
                "debug/maa.log": b"debug-log",
                "debug/last-screen.png": b"fake-png",
                "profiles/custom_head.png": b"custom-profile",
            }
            for relative, content in fixtures.items():
                path = old / relative
                path.parent.mkdir(parents=True, exist_ok=True)
                path.write_bytes(content)

            original = self._snapshot(old)
            first = ensure_runtime_data(old, bundle, legacy_roots=[old])

            expected = {
                "touken_config.json": "config/touken.json",
                "panel_config.json": "config/panel.json",
                "expedition_schedule.json": "config/expedition.json",
                "launcher.log": "logs/launcher.log",
                "status/daily_flags.json": "state/daily_flags.json",
                "status/expeditions.json": "state/expeditions.json",
                "status/inventory.json": "state/inventory.json",
                "status/session_state.json": "state/session_state.json",
                "status/maamaru_logs.db": "logs/maamaru_logs.db",
                "debug/maa.log": "debug/maa.log",
                "debug/last-screen.png": "debug/last-screen.png",
                "profiles/custom_head.png": "profiles/overrides/custom_head.png",
            }
            for source, target in expected.items():
                self.assertEqual((old / target).read_bytes(), fixtures[source], target)
            for source, digest in original.items():
                self.assertEqual(hashlib.sha256((old / source).read_bytes()).hexdigest(), digest)

            backup = Path(first["backup"])
            self.assertTrue(backup.is_dir())
            for source, target in expected.items():
                if source.startswith("debug/"):
                    continue  # v0.1.4 and v1 use the same debug/ location
                backup_target = source if source.startswith("profiles/") else target
                self.assertEqual((backup / backup_target).read_bytes(), fixtures[source], backup_target)

            after_first = self._snapshot(old)
            second = ensure_runtime_data(old, bundle, legacy_roots=[old])
            after_second = self._snapshot(old)
            self.assertEqual(second, first)
            self.assertEqual(after_second, after_first)


if __name__ == "__main__":
    unittest.main()
