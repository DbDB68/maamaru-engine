# -*- coding: utf-8 -*-
"""今天单班选择真正影响派遣，并能随时还原当天未来班次。

skipped：今天这班别跑。forced：今天这班一定要跑——排班总开关关着也单独
走状态机派出（排班开着时等价于「不跳过」）。两者互斥，后写的赢；
forced 不 lifted 自定义排班里被关掉的条目。
"""

import json
import tempfile
import time
import unittest
from pathlib import Path
from unittest.mock import patch

from fastapi.testclient import TestClient

from panel import day_timeline, scheduler
from panel import expedition_choices as ec
from panel import server
from panel.expedition_choices import is_skipped, load_choices, set_skipped


def _today_at(hour, minute=0):
    return time.mktime(time.strptime(
        f"{time.strftime('%Y-%m-%d')} {hour:02d}:{minute:02d}:00",
        "%Y-%m-%d %H:%M:%S"))


def _key():
    return "2026-09-29:custom:0:08:00"


class ExpeditionChoiceTests(unittest.TestCase):
    def test_custom_skip_prevents_due_and_restore_reenables(self):
        cfg = scheduler._defaults()
        cfg["automation"].update(enabled=True, mode="custom")
        cfg["entries"] = [{"time": "10:00", "team_no": 2,
                           "map_code": "B3", "enabled": True}]
        today = time.strftime("%Y-%m-%d")
        job = scheduler._custom_due(cfg, 600, today)[0]
        projected = scheduler.today_projection(cfg, now=_today_at(9, 0))["custom"][0]
        with tempfile.TemporaryDirectory() as folder:
            path = Path(folder) / "choices.json"
            set_skipped(key=projected["key"], team_no=2, map_code="B3",
                        planned_at=projected["planned_at"], skipped=True, path=path)
            choices = load_choices(path)
            self.assertEqual(scheduler._custom_due(cfg, 600, today, choices), [])
            self.assertEqual(scheduler.today_projection(
                cfg, now=_today_at(9, 0), choices=choices)["custom"][0]["state"], "skipped")
            self.assertTrue(is_skipped(choices, key=job["key"], team_no=2,
                                       map_code="B3", planned_at=projected["planned_at"]))
            self.assertTrue(is_skipped(choices, key=job["key"], team_no=2,
                                       map_code="B3", planned_at=projected["planned_at"] + 1200))
            self.assertFalse(is_skipped(choices, key=job["key"], team_no=3,
                                        map_code="B3", planned_at=projected["planned_at"]))
            set_skipped(key=projected["key"], team_no=2, map_code="B3",
                        planned_at=projected["planned_at"], skipped=False, path=path)
            self.assertEqual(load_choices(path), {})
            self.assertIn(projected["key"], json.loads(
                path.with_suffix(".json.bak").read_text(encoding="utf-8"))["skipped"])
            self.assertEqual(len(scheduler._custom_due(cfg, 600, today, load_choices(path))), 1)

    def test_unknown_choice_version_is_preserved_as_backup(self):
        with tempfile.TemporaryDirectory() as folder:
            path = Path(folder) / "choices.json"
            path.write_text('{"version":0,"old":"kept"}', encoding="utf-8")
            self.assertEqual(load_choices(path), {})
            set_skipped(key="today:custom:0:10:00", team_no=2,
                        map_code="B3", planned_at=123, skipped=True, path=path)
            self.assertEqual(json.loads(path.with_suffix(".json.bak").read_text(
                encoding="utf-8"))["old"], "kept")

    def test_preset_skip_only_affects_same_shift(self):
        cfg = scheduler._defaults()
        cfg["automation"].update(enabled=True, mode="preset", start_time="08:00",
                                 preset="试排", teams=[2, 3, 4])
        preset = {"试排": {"lanes": [[{"offset_min": 0, "map_code": "B3",
                                          "duration_min": 90},
                                         {"offset_min": 90, "map_code": "B4",
                                          "duration_min": 90}]]}}
        with patch.object(scheduler, "preset_payload", return_value=preset):
            first = scheduler.today_projection(cfg, now=_today_at(8, 0))["preset"][0]
            choices = {first["key"]: {"team_no": 2, "map_code": "B3",
                                       "planned_at": first["planned_at"]}}
            self.assertEqual(scheduler._preset_due(cfg, 480, time.strftime("%Y-%m-%d"), choices), [])
            later = scheduler._preset_due(cfg, 570, time.strftime("%Y-%m-%d"), choices)
            self.assertEqual(len(later), 1)
            self.assertEqual(later[0]["map_code"], "B4")

    def test_timeline_shows_both_sides_of_midnight_preset(self):
        cfg = scheduler._defaults()
        cfg["automation"].update(enabled=False, mode="preset", start_time="20:00",
                                 preset="跨日", teams=[2, 3, 4])
        preset = {"跨日": {"lanes": [[{"offset_min": 0, "map_code": "B3",
                                          "duration_min": 90},
                                         {"offset_min": 300, "map_code": "B4",
                                          "duration_min": 90}]]}}
        with patch.object(scheduler, "preset_payload", return_value=preset), \
             patch.object(scheduler, "map_options", return_value=[
                 {"code": "B3", "duration_min": 90},
                 {"code": "B4", "duration_min": 90}]):
            timeline = day_timeline.build_day_timeline(
                _today_at(12), cfg=cfg, store=object())
        self.assertEqual([(item["time_min"], item["map_code"])
                          for item in timeline["expeditions"]],
                         [(60, "B4"), (1200, "B3")])
        self.assertFalse(any(item["enabled"] for item in timeline["expeditions"]))

    def test_skipping_shift_changes_raid_window(self):
        cfg = scheduler._defaults()
        cfg["automation"].update(enabled=True, mode="custom")
        cfg["entries"] = [{"time": "10:00", "team_no": 3,
                           "map_code": "B3", "enabled": True}]
        maps = [{"code": "B3", "duration_min": 90}]
        plan = {"runs_needed": 36, "seconds_per_loop": 420,
                "seconds_to_end": 2 * 86400, "tama_remaining": 10000}
        now = _today_at(8, 0)
        with patch.object(scheduler, "map_options", return_value=maps), \
             patch.object(day_timeline, "_raid_active_plan", return_value=plan), \
             patch.object(day_timeline, "_hanafuda_active_plan", return_value=None):
            before = day_timeline.build_day_timeline(now, cfg=cfg, store=object(),
                                                     raid_team_no=3)
            slot = before["expeditions"][0]
            choices = {slot["key"]: {"team_no": 3, "map_code": "B3",
                                      "planned_at": slot["planned_at"]}}
            after = day_timeline.build_day_timeline(
                now, cfg=cfg, store=object(), raid_team_no=3,
                expedition_choices=choices)
        self.assertEqual(len(before["suggestions"]), 2)
        self.assertEqual([(b["start_min"], b["runs"]) for b in after["suggestions"]],
                         [(480, 18)])
        self.assertFalse(after["expeditions"][0]["enabled"])

    def test_api_checks_live_slot_before_changing_it(self):
        """端点先核对实时班次再落盘；body 用目标态 will_run（新契约：
        排班开着点「不跑」记 skipped，关着点「跑」记 forced）。"""
        slot = {"key": "today:custom:0:10:00", "team_no": 2,
                "map_code": "B3", "planned_at": _today_at(10),
                "toggleable": True, "base_enabled": True,
                "entry_enabled": True}
        timeline = {"expeditions": [slot]}
        client = TestClient(server.app)
        with patch.object(server, "_day_timeline_payload", return_value=timeline), \
             patch.object(ec, "set_slot_intention") as writer:
            response = client.put("/api/day-timeline/expedition-slot",
                                  json={"key": slot["key"], "will_run": False})
            self.assertEqual(response.status_code, 200)
            writer.assert_called_once_with(
                key=slot["key"], team_no=2, map_code="B3",
                planned_at=slot["planned_at"], will_run=False,
                base_enabled=True)
            slot["toggleable"] = False
            blocked = client.put("/api/day-timeline/expedition-slot",
                                 json={"key": slot["key"], "will_run": True})
            self.assertEqual(blocked.status_code, 409)
            self.assertEqual(writer.call_count, 1)


class ChoiceSetTests(unittest.TestCase):
    def setUp(self):
        self.folder = tempfile.TemporaryDirectory()
        self.addCleanup(self.folder.cleanup)
        self.path = Path(self.folder.name) / "choices.json"

    def test_forced_roundtrip(self):
        ec.set_forced(key=_key(), team_no=2, map_code="B1", planned_at=1,
                      forced=True, path=self.path)
        skipped, forced = ec.load_choice_sets(self.path)
        self.assertEqual(skipped, {})
        self.assertTrue(ec.is_forced(forced, key=_key(), team_no=2, map_code="B1"))
        self.assertFalse(ec.is_forced(forced, key=_key(), team_no=3, map_code="B1"))

    def test_skipped_and_forced_are_mutually_exclusive(self):
        ec.set_skipped(key=_key(), team_no=2, map_code="B1", planned_at=1,
                       skipped=True, path=self.path)
        ec.set_forced(key=_key(), team_no=2, map_code="B1", planned_at=1,
                      forced=True, path=self.path)
        skipped, forced = ec.load_choice_sets(self.path)
        self.assertEqual(skipped, {})
        self.assertIn(_key(), forced)
        # 反过来再记跳过，强制被清掉
        ec.set_skipped(key=_key(), team_no=2, map_code="B1", planned_at=1,
                       skipped=True, path=self.path)
        skipped, forced = ec.load_choice_sets(self.path)
        self.assertIn(_key(), skipped)
        self.assertEqual(forced, {})

    def test_legacy_file_without_forced_key(self):
        self.path.write_text(
            '{"version":1,"skipped":{"k":{"team_no":2,"map_code":"B1",'
            '"planned_at":1}}}', encoding="utf-8")
        skipped, forced = ec.load_choice_sets(self.path)
        self.assertIn("k", skipped)
        self.assertEqual(forced, {})
        self.assertEqual(ec.load_choices(self.path), skipped)

    def test_set_slot_intention_by_base_state(self):
        # 排班开着点「会跑」：只清选择，不记 forced
        out = ec.set_slot_intention(key=_key(), team_no=2, map_code="B1",
                                    planned_at=1, will_run=True,
                                    base_enabled=True, path=self.path)
        self.assertEqual(out["skipped"], {})
        self.assertEqual(out["forced"], {})
        # 排班关着点「会跑」：记 forced
        out = ec.set_slot_intention(key=_key(), team_no=2, map_code="B1",
                                    planned_at=1, will_run=True,
                                    base_enabled=False, path=self.path)
        self.assertIn(_key(), out["forced"])
        # 点「不跑」：清 forced 记 skipped
        out = ec.set_slot_intention(key=_key(), team_no=2, map_code="B1",
                                    planned_at=1, will_run=False,
                                    base_enabled=False, path=self.path)
        self.assertIn(_key(), out["skipped"])
        self.assertEqual(out["forced"], {})


class ExpeditionSlotEndpointTests(unittest.TestCase):
    """PUT /api/day-timeline/expedition-slot：will_run 目标态三态落盘。"""

    def setUp(self):
        self.folder = tempfile.TemporaryDirectory()
        self.addCleanup(self.folder.cleanup)
        self.path = Path(self.folder.name) / "choices.json"
        self.slot = {"key": _key(), "team_no": 2, "map_code": "B1",
                     "planned_at": 1759094400.0, "toggleable": True,
                     "base_enabled": True, "entry_enabled": True}

    def _put(self, payload):
        real = ec.set_slot_intention

        def to_temp(**kwargs):
            kwargs["path"] = self.path
            return real(**kwargs)

        with patch.object(server, "_day_timeline_payload",
                          return_value={"expeditions": [self.slot]}), \
             patch.object(ec, "set_slot_intention", side_effect=to_temp):
            return TestClient(server.app).put("/api/day-timeline/expedition-slot",
                                              json=payload)

    def test_will_run_false_records_skip(self):
        response = self._put({"key": _key(), "will_run": False})
        self.assertEqual(response.status_code, 200)
        skipped, forced = ec.load_choice_sets(self.path)
        self.assertIn(_key(), skipped)
        self.assertEqual(forced, {})

    def test_will_run_true_with_automation_off_records_force(self):
        self.slot["base_enabled"] = False
        response = self._put({"key": _key(), "will_run": True})
        self.assertEqual(response.status_code, 200)
        skipped, forced = ec.load_choice_sets(self.path)
        self.assertEqual(skipped, {})
        self.assertIn(_key(), forced)

    def test_will_run_true_with_automation_on_clears_both(self):
        response = self._put({"key": _key(), "will_run": True})
        self.assertEqual(response.status_code, 200)
        skipped, forced = ec.load_choice_sets(self.path)
        self.assertEqual(skipped, {})
        self.assertEqual(forced, {})

    def test_untoggleable_slot_rejected(self):
        self.slot["toggleable"] = False
        response = self._put({"key": _key(), "will_run": False})
        self.assertEqual(response.status_code, 409)
        self.assertFalse(self.path.exists())

    def test_entry_disabled_cannot_be_forced(self):
        self.slot["base_enabled"] = False
        self.slot["entry_enabled"] = False
        response = self._put({"key": _key(), "will_run": True})
        self.assertEqual(response.status_code, 409)
        self.assertFalse(self.path.exists())


if __name__ == "__main__":
    unittest.main()
