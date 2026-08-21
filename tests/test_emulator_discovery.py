import json
import tempfile
import unittest
from pathlib import Path

from touken.emulator_discovery import (
    auto_configure_emulator,
    configure_mumu_from_folder,
    discover_mumu_installation,
)


class EmulatorDiscoveryTests(unittest.TestCase):
    def _fake_install(self, root: Path):
        adb = root / "nx_device" / "12.0" / "shell" / "adb.exe"
        manager = root / "nx_main" / "MuMuManager.exe"
        adb.parent.mkdir(parents=True)
        manager.parent.mkdir(parents=True)
        adb.write_bytes(b"adb")
        manager.write_bytes(b"manager")
        return adb, manager

    def test_discovers_a_complete_mumu_installation(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp) / "MuMuPlayer"
            adb, manager = self._fake_install(root)

            found = discover_mumu_installation(
                extra_roots=[root],
                include_system=False,
            )

            self.assertEqual(found.adb_path, adb.resolve())
            self.assertEqual(found.manager_path, manager.resolve())
            self.assertEqual(found.adb_address, "127.0.0.1:16384")

    def test_first_run_fills_blank_paths_atomically(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            install = root / "MuMuPlayer"
            adb, manager = self._fake_install(install)
            config_path = root / "touken.json"
            config_path.write_text(json.dumps({
                "adb_path": "",
                "adb_address": "127.0.0.1:16384",
                "emulator_manager": "",
                "keep_me": {"value": 7},
            }), encoding="utf-8")

            found = auto_configure_emulator(
                config_path,
                extra_roots=[install],
                include_system=False,
            )
            saved = json.loads(config_path.read_text(encoding="utf-8"))

            self.assertIsNotNone(found)
            self.assertEqual(saved["adb_path"], str(adb.resolve()))
            self.assertEqual(saved["emulator_manager"], str(manager.resolve()))
            self.assertEqual(saved["keep_me"], {"value": 7})
            self.assertFalse(config_path.with_suffix(".json.tmp").exists())

    def test_never_overwrites_a_nonempty_user_choice(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            install = root / "MuMuPlayer"
            self._fake_install(install)
            config_path = root / "touken.json"
            original = {
                "adb_path": "Z:/my-emulator/adb.exe",
                "adb_address": "127.0.0.1:5555",
                "emulator_manager": "Z:/my-emulator/manager.exe",
            }
            config_path.write_text(json.dumps(original), encoding="utf-8")

            found = auto_configure_emulator(
                config_path,
                extra_roots=[install],
                include_system=False,
            )

            self.assertIsNone(found)
            self.assertEqual(
                json.loads(config_path.read_text(encoding="utf-8")),
                original,
            )

    def test_can_complete_manager_from_an_existing_adb_path(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            install = root / "MuMuPlayer"
            adb, manager = self._fake_install(install)
            config_path = root / "touken.json"
            config_path.write_text(json.dumps({
                "adb_path": str(adb),
                "adb_address": "127.0.0.1:16384",
                "emulator_manager": "",
            }), encoding="utf-8")

            auto_configure_emulator(config_path, include_system=False)
            saved = json.loads(config_path.read_text(encoding="utf-8"))

            self.assertEqual(saved["adb_path"], str(adb))
            self.assertEqual(saved["emulator_manager"], str(manager.resolve()))

    def test_partial_install_is_not_guessed(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp) / "MuMuPlayer"
            adb = root / "nx_device" / "12.0" / "shell" / "adb.exe"
            adb.parent.mkdir(parents=True)
            adb.write_bytes(b"adb")

            self.assertIsNone(discover_mumu_installation(
                extra_roots=[root],
                include_system=False,
            ))

    def test_explicit_folder_replaces_old_paths_after_validation(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            install = root / "MuMuPlayer"
            adb, manager = self._fake_install(install)
            config_path = root / "touken.json"
            config_path.write_text(json.dumps({
                "adb_path": "Z:/old/adb.exe",
                "adb_address": "127.0.0.1:16384",
                "emulator_manager": "Z:/old/manager.exe",
            }), encoding="utf-8")

            found = configure_mumu_from_folder(install / "nx_main", config_path)
            saved = json.loads(config_path.read_text(encoding="utf-8"))

            self.assertIsNotNone(found)
            self.assertEqual(saved["adb_path"], str(adb.resolve()))
            self.assertEqual(saved["emulator_manager"], str(manager.resolve()))


if __name__ == "__main__":
    unittest.main()
