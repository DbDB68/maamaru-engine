# -*- coding: utf-8 -*-
"""海联新增配置在老安装中只补缺口，保留玩家现有设置。"""

import json
import tempfile
import unittest
from pathlib import Path

from touken.runtime_paths import _fill_missing_config_keys
from touken.flows.raid import _departure_config


EXAMPLE = Path(__file__).resolve().parent.parent / "touken_config.example.json"


class RaidConfigMigrationTests(unittest.TestCase):
    def test_hailian_uses_shared_slider_refill_without_changing_old_config(self):
        config = json.loads(EXAMPLE.read_text(encoding="utf-8-sig"))
        raid = config["raid"]
        before = json.loads(json.dumps(raid))
        departure = _departure_config(raid, "hailian", config)
        self.assertEqual(departure["ticket_recover"], config["hanafuda"]["ticket_recover"])
        self.assertNotIn("recover_button", departure["ticket_recover"])
        self.assertEqual(departure["confirm_button"], raid["confirm_button_hailian"])
        self.assertEqual(raid, before)
        self.assertEqual(_departure_config(raid, "lulian", config)["ticket_recover"],
                         raid["ticket_recover"])

    def test_existing_install_keeps_old_raid_keys_but_uses_shared_refill(self):
        template = json.loads(EXAMPLE.read_text(encoding="utf-8-sig"))
        old = json.loads(json.dumps(template))
        old["hanafuda"].pop("ticket_recover")
        with tempfile.TemporaryDirectory() as tmp:
            target = Path(tmp) / "touken_config.json"
            target.write_text(json.dumps(old), encoding="utf-8")
            _fill_missing_config_keys(EXAMPLE, target, Path(tmp) / "backups")
            merged = json.loads(target.read_text(encoding="utf-8"))
            self.assertEqual(merged["raid"], old["raid"])
            self.assertNotIn("recover_button", _departure_config(
                merged["raid"], "hailian", merged)["ticket_recover"])
            self.assertEqual(len(list((Path(tmp) / "backups").glob("*.json"))), 1)

    def test_old_raid_config_gets_new_fields_with_backup(self):
        template = json.loads(EXAMPLE.read_text(encoding="utf-8-sig"))
        old = json.loads(json.dumps(template))
        new_keys = ("confirm_button_hailian",
                    "fish_basket3", "auto_march", "shells_total_ocr",
                    "injury_deny_button", "injury_stamps",
                    "injury_stamp_roi", "injury_status_roi")
        for key in new_keys:
            old["raid"].pop(key)
        old["raid"]["confirm_ui_hailian"] = {
            "template": "lulian/ui海联确认.png"}
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
            self.assertIn("raid.confirm_ui_hailian.ocr", added)
            self.assertEqual(merged["raid"]["confirm_ui_hailian"]["ocr"]["expected"], "出阵")
            self.assertEqual(merged["raid"]["confirm_ui_hailian"]["template"],
                             "lulian/ui海联确认.png")
            self.assertEqual(len(list(backup_dir.glob("*.json"))), 1)
            before = json.loads(next(backup_dir.glob("*.json"))
                                .read_text(encoding="utf-8"))
            self.assertNotIn("auto_march", before["raid"])


if __name__ == "__main__":
    unittest.main()


class InjuryCheckConfigMigrationTests(unittest.TestCase):
    def test_old_config_gets_injury_check_key(self):
        """老安装没有 injury_check：补键后默认开启日志验伤，且保留备份。"""
        template = json.loads(EXAMPLE.read_text(encoding="utf-8-sig"))
        old = json.loads(json.dumps(template))
        old.pop("injury_check")
        with tempfile.TemporaryDirectory() as tmp:
            target = Path(tmp) / "touken_config.json"
            backup_dir = Path(tmp) / "backups"
            target.write_text(json.dumps(old, ensure_ascii=False),
                              encoding="utf-8")
            added = _fill_missing_config_keys(EXAMPLE, target, backup_dir)
            merged = json.loads(target.read_text(encoding="utf-8"))
            self.assertIn("injury_check", added)
            self.assertTrue(merged["injury_check"]["use_youzu_log"])
            self.assertEqual(merged["injury_check"]["max_age_sec"], 600)
            self.assertEqual(len(list(backup_dir.glob("*.json"))), 1)
