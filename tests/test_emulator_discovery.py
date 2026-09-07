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


class ResolveAdbAddressTests(unittest.TestCase):
    """无头 MuMu 备胎地址（2026-09-07：窗口消失后 16384 拒连，工作流三趟全灭）"""

    def _run_with(self, monkeypatch, devices_out, alive):
        import touken.emulator as emu

        class R:
            def __init__(self, stdout):
                self.stdout = stdout
                self.stderr = ""
                self.returncode = 0

        def fake_run(cmd, timeout=30):
            if cmd[1:2] == ["devices"]:
                return R(devices_out)
            return R("")
        monkeypatch.setattr(emu, "_run", fake_run)
        monkeypatch.setattr(emu, "adb_alive",
                            lambda adb_path, address: alive(address))
        return emu

    def test_configured_address_alive_stays(self):
        import pytest
        mp = pytest.MonkeyPatch()
        emu = self._run_with(mp, "", alive=lambda a: True)
        try:
            self.assertEqual(
                emu.resolve_adb_address("adb", "127.0.0.1:16384",
                                        emit=lambda m: None),
                "127.0.0.1:16384")
        finally:
            mp.undo()

    def test_single_headless_emulator_becomes_fallback(self):
        import pytest
        # 用 monkeypatch 保证还原
        mp = pytest.MonkeyPatch()
        emu = self._run_with(mp, "List of devices attached\nemulator-5554\tdevice\n",
                             alive=lambda a: a == "emulator-5554")
        try:
            self.assertEqual(
                emu.resolve_adb_address("adb", "127.0.0.1:16384",
                                        emit=lambda m: None),
                "emulator-5554")
        finally:
            mp.undo()

    def test_multiple_emulators_never_guessed(self):
        import pytest
        mp = pytest.MonkeyPatch()
        emu = self._run_with(mp, "emulator-5554\tdevice\nemulator-5556\tdevice\n",
                             alive=lambda a: False)
        try:
            self.assertEqual(
                emu.resolve_adb_address("adb", "127.0.0.1:16384",
                                        emit=lambda m: None),
                "127.0.0.1:16384")
        finally:
            mp.undo()


if __name__ == "__main__":
    unittest.main()
