"""今天单班选择真正影响派遣，并能随时还原当天未来班次。"""

import json
import tempfile
import time
import unittest
from pathlib import Path
from unittest.mock import patch

from fastapi.testclient import TestClient

from panel import day_timeline, scheduler
from panel.expedition_choices import is_skipped, load_choices, set_skipped


def _today_at(hour, minute=0):
    return time.mktime(time.strptime(
        f"{time.strftime('%Y-%m-%d')} {hour:02d}:{minute:02d}:00",
        "%Y-%m-%d %H:%M:%S"))


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
        from panel import server

        slot = {"key": "today:custom:0:10:00", "team_no": 2,
                "map_code": "B3", "planned_at": _today_at(10),
                "toggleable": True}
        timeline = {"expeditions": [slot]}
        client = TestClient(server.app)
        with patch.object(server, "_day_timeline_payload", return_value=timeline), \
             patch("panel.expedition_choices.set_skipped") as writer:
            response = client.put("/api/day-timeline/expedition-slot",
                                  json={"key": slot["key"], "enabled": False})
            self.assertEqual(response.status_code, 200)
            writer.assert_called_once_with(
                key=slot["key"], team_no=2, map_code="B3",
                planned_at=slot["planned_at"], skipped=True)
            slot["toggleable"] = False
            blocked = client.put("/api/day-timeline/expedition-slot",
                                 json={"key": slot["key"], "enabled": True})
            self.assertEqual(blocked.status_code, 409)
            self.assertEqual(writer.call_count, 1)


if __name__ == "__main__":
    unittest.main()
