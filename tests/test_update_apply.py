import hashlib
import json
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

from launcher import update_apply


class UpdateApplyTests(unittest.TestCase):
    def _plan(self, root: Path):
        updates = root / "updates"
        installer = updates / "0.1.6" / "maamaru-setup-v0.1.6.exe"
        installer.parent.mkdir(parents=True)
        installer.write_bytes(b"installer")
        program = root / "Programs" / "Maamaru"
        program.mkdir(parents=True)
        (program / "まあ丸启动器.exe").write_bytes(b"old")
        return {
            "version": "0.1.6", "installer": str(installer),
            "sha256": hashlib.sha256(b"installer").hexdigest(),
            "program_dir": str(program), "backup_dir": str(updates / "backups" / "before-0.1.6"),
            "previous_executable": str(program / "まあ丸启动器.exe"), "parent_pid": 1,
            "data_root": str(root / "data"),
        }, updates

    def test_failed_installer_restores_exact_program_snapshot(self):
        with tempfile.TemporaryDirectory() as tmp:
            plan, updates = self._plan(Path(tmp))
            plan_path = updates / "plan.json"
            plan_path.write_text(json.dumps(plan), encoding="utf-8")
            class Failed:
                returncode = 7
            with patch.object(update_apply, "UPDATES_DIR", updates), \
                    patch.object(update_apply, "DATA_ROOT", Path(plan["data_root"])), \
                    patch.object(update_apply, "RESULT_PATH", updates / "result.json"), \
                    patch.object(update_apply, "_program_dir", return_value=Path(plan["program_dir"])), \
                    patch.object(update_apply, "_wait_for_process"), \
                    patch.object(update_apply.subprocess, "run", return_value=Failed()), \
                    patch.object(update_apply, "_restart"):
                self.assertEqual(update_apply.run_plan(plan_path), 7)
            program = Path(plan["program_dir"])
            self.assertEqual((program / "まあ丸启动器.exe").read_bytes(), b"old")
            result = json.loads((updates / "result.json").read_text(encoding="utf-8"))
            self.assertTrue(result["rolled_back"])

    def test_plan_cannot_put_program_inside_user_data(self):
        with tempfile.TemporaryDirectory() as tmp:
            plan, updates = self._plan(Path(tmp))
            plan["program_dir"] = str(Path(plan["data_root"]) / "program")
            with patch.object(update_apply, "UPDATES_DIR", updates), \
                    patch.object(update_apply, "DATA_ROOT", Path(plan["data_root"])), \
                    patch.object(update_apply, "_program_dir", return_value=Path(plan["program_dir"])):
                with self.assertRaises(update_apply.ApplyError):
                    update_apply._validate_plan(plan)


if __name__ == "__main__":
    unittest.main()
