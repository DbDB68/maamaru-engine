# -*- coding: utf-8 -*-
"""海联新增配置在老安装中只补缺口，保留玩家现有设置。"""

import json
import tempfile
import unittest
from pathlib import Path

from touken.runtime_paths import _fill_missing_config_keys


EXAMPLE = Path(__file__).resolve().parent.parent / "touken_config.example.json"


class RaidConfigMigrationTests(unittest.TestCase):
    def test_old_raid_config_gets_new_fields_with_backup(self):
        template = json.loads(EXAMPLE.read_text(encoding="utf-8-sig"))
        old = json.loads(json.dumps(template))
        new_keys = ("confirm_ui_hailian", "confirm_button_hailian",
                    "fish_basket3", "auto_march", "shells_total_ocr",
                    "injury_deny_button", "injury_stamps",
                    "injury_stamp_roi", "injury_status_roi")
        for key in new_keys:
            old["raid"].pop(key)
        old["raid"]["team_no"] = 4
        with tempfile.TemporaryDirectory() as tmp:
            target = Path(tmp) / "touken_config.json"
            backup_dir = Path(tmp) / "backups"
            target.write_text(json.dumps(old, ensure_ascii=False),
                              encoding="utf-8")
            added = _fill_missing_config_keys(EXAMPLE, target, backup_dir)
            merged = json.loads(target.read_text(encoding="utf-8"))
            self.assertEqual(merged["raid"]["team_no"], 4)
            self.assertTrue(all(f"raid.{key}" in added for key in new_keys))
            self.assertEqual(len(list(backup_dir.glob("*.json"))), 1)
            before = json.loads(next(backup_dir.glob("*.json"))
                                .read_text(encoding="utf-8"))
            self.assertNotIn("auto_march", before["raid"])


if __name__ == "__main__":
    unittest.main()
