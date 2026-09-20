# -*- coding: utf-8 -*-
"""仪表盘 24 小时时间轴（panel/day_timeline.py）测试。

全部依赖注入：cfg 手工构造、store 用临时库、labels/active 直接传，
不碰真实用户数据。
"""

import tempfile
import time
import unittest
from pathlib import Path
from unittest.mock import patch

from panel import day_timeline as dtl
from panel import scheduler
from touken.telemetry import TelemetryStore


def _today_at(hour, minute=0):
    return time.mktime(time.strptime(
        f"{time.strftime('%Y-%m-%d')} {hour:02d}:{minute:02d}:00",
        "%Y-%m-%d %H:%M:%S"))


_FAKE_MAPS = [
    {"code": "B3", "era": 2, "slot": 3, "name": "B3", "duration_min": 90,
     "duration_text": "1h30分"},
    {"code": "E2", "era": 5, "slot": 2, "name": "E2", "duration_min": 600,
     "duration_text": "10h00分"},
]


def _cfg(entries, *, mode="custom", enabled=True):
    return {
        "entries": entries,
        "automation": {"enabled": enabled, "mode": mode,
                       "preset": "日课三班", "teams": [2, 3, 4],
                       "start_time": "08:00"},
    }


class DayTimelineExpeditionTests(unittest.TestCase):
    def setUp(self):
        patcher = patch.object(scheduler, "map_options", lambda: _FAKE_MAPS)
        patcher.start()
        self.addCleanup(patcher.stop)

    def test_custom_entry_lands_on_axis(self):
        now = _today_at(6, 0)
        cfg = _cfg([{"time": "08:30", "team_no": 2, "map_code": "B3",
                     "enabled": True}])
        out = dtl.build_day_timeline(now, cfg=cfg, store=None,
                                     script_labels={})
        self.assertEqual(len(out["expeditions"]), 1)
        item = out["expeditions"][0]
        self.assertEqual(item["time_min"], 8 * 60 + 30)
        self.assertEqual(item["duration_min"], 90)
        self.assertEqual(item["team_no"], 2)
        self.assertEqual(item["map_code"], "B3")
        self.assertEqual(item["state"], "pending")
        self.assertTrue(item["enabled"])

    def test_disabled_entry_grayed_out(self):
        now = _today_at(6, 0)
        cfg = _cfg([{"time": "08:30", "team_no": 2, "map_code": "B3",
                     "enabled": False}])
        out = dtl.build_day_timeline(now, cfg=cfg, store=None,
                                     script_labels={})
        self.assertFalse(out["expeditions"][0]["enabled"])

    def test_mode_mismatch_grays_lane(self):
        now = _today_at(6, 0)
        cfg = _cfg([{"time": "08:30", "team_no": 2, "map_code": "B3",
                     "enabled": True}], mode="preset")
        out = dtl.build_day_timeline(now, cfg=cfg, store=None,
                                     script_labels={})
        custom = [e for e in out["expeditions"] if e["map_code"] == "B3"]
        self.assertTrue(custom)
        self.assertFalse(custom[0]["enabled"])

    def test_unknown_map_duration_zero_not_crash(self):
        now = _today_at(6, 0)
        cfg = _cfg([{"time": "08:30", "team_no": 2, "map_code": "ZZ9",
                     "enabled": True}])
        out = dtl.build_day_timeline(now, cfg=cfg, store=None,
                                     script_labels={})
        self.assertEqual(out["expeditions"][0]["duration_min"], 0)

    def test_garbage_entry_not_crash(self):
        now = _today_at(6, 0)
        cfg = _cfg([{"time": "咕咕", "team_no": 2, "map_code": "B3"}])
        out = dtl.build_day_timeline(now, cfg=cfg, store=None,
                                     script_labels={})
        self.assertEqual(len(out["expeditions"]), 1)


class DayTimelineRunTests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.store = TelemetryStore(Path(self.tmp.name) / "t.db")

    def tearDown(self):
        self.store.close()
        self.tmp.cleanup()

    def test_runs_land_with_label_and_tone(self):
        day_start = _today_at(0, 0)
        self.store.start_run("r1", "daily", started_at=day_start + 3600)
        self.store.finish_run("r1", "completed", ended_at=day_start + 5400)
        self.store.start_run("r2", "sortie", started_at=day_start + 7200)
        self.store.finish_run("r2", "failed", ended_at=day_start + 7800)
        out = dtl.build_day_timeline(
            _today_at(12, 0), cfg=_cfg([]), store=self.store,
            script_labels={"daily": "日课", "sortie": "出阵"})
        daily = next(r for r in out["runs"] if r["script"] == "daily")
        sortie = next(r for r in out["runs"] if r["script"] == "sortie")
        self.assertEqual(daily["label"], "日课")
        self.assertEqual(daily["tone"], "ok")
        self.assertEqual(sortie["tone"], "failed")
        self.assertEqual(sortie["label"], "出阵")

    def test_unknown_script_falls_back_to_key(self):
        day_start = _today_at(0, 0)
        self.store.start_run("r1", "secret_thing", started_at=day_start + 60)
        self.store.finish_run("r1", "stopped", ended_at=day_start + 600)
        out = dtl.build_day_timeline(
            _today_at(12, 0), cfg=_cfg([]), store=self.store,
            script_labels={})
        self.assertEqual(out["runs"][0]["label"], "secret_thing")
        self.assertEqual(out["runs"][0]["tone"], "stopped")

    def test_active_run_forced_running(self):
        day_start = _today_at(0, 0)
        started = day_start + 7200
        self.store.start_run("r1", "dispatch", started_at=started)
        out = dtl.build_day_timeline(
            _today_at(12, 0), cfg=_cfg([]), store=self.store,
            script_labels={"dispatch": "远征"},
            active={"script": "dispatch", "started": started})
        run = out["runs"][0]
        self.assertEqual(run["tone"], "running")
        self.assertIsNone(run["ended_at"])

    def test_old_zombie_run_is_omitted_and_today_zombie_is_stopped(self):
        """往日尸体不挤进今天零点；今日尸体也不许画成「正在跑」。"""
        day_start = _today_at(0, 0)
        self.store.start_run("z1", "osaka", started_at=day_start - 3600)
        self.store.start_run("z2", "daily", started_at=day_start + 7200)
        out = dtl.build_day_timeline(
            _today_at(12, 0), cfg=_cfg([]), store=self.store,
            script_labels={}, active=None)
        tones = {r["script"]: r["tone"] for r in out["runs"]}
        self.assertNotIn("osaka", tones)
        self.assertEqual(tones["daily"], "stopped")

    def test_active_cross_midnight_run_is_kept(self):
        day_start = _today_at(0, 0)
        started = day_start - 3600
        self.store.start_run("r1", "dispatch", started_at=started)
        out = dtl.build_day_timeline(
            _today_at(1, 0), cfg=_cfg([]), store=self.store,
            script_labels={"dispatch": "远征"},
            active={"script": "dispatch", "started": started})
        self.assertEqual(len(out["runs"]), 1)
        self.assertEqual(out["runs"][0]["tone"], "running")

    def test_cross_midnight_run_included(self):
        day_start = _today_at(0, 0)
        self.store.start_run("r1", "daily", started_at=day_start - 3600)
        self.store.finish_run("r1", "completed", ended_at=day_start + 600)
        self.store.start_run("r2", "daily", started_at=day_start - 72000)
        self.store.finish_run("r2", "completed", ended_at=day_start - 70000)
        out = dtl.build_day_timeline(
            _today_at(12, 0), cfg=_cfg([]), store=self.store,
            script_labels={})
        self.assertEqual(len(out["runs"]), 1)


class DayTimelineMiscTests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.store = TelemetryStore(Path(self.tmp.name) / "t.db")

    def tearDown(self):
        self.store.close()
        self.tmp.cleanup()

    def test_empty_inputs_not_crash(self):
        with patch.object(scheduler, "map_options", lambda: []):
            out = dtl.build_day_timeline(
                _today_at(9, 0), cfg={}, store=self.store, script_labels={})
        self.assertEqual(out["expeditions"], [])
        self.assertEqual(out["runs"], [])
        self.assertIsNone(out["hint"])

    def test_daily_reset_marker(self):
        with patch.object(scheduler, "map_options", lambda: []):
            out = dtl.build_day_timeline(
                _today_at(9, 0), cfg={}, store=self.store, script_labels={})
        marker = next(m for m in out["markers"] if m["kind"] == "daily_reset")
        self.assertEqual(marker["time_min"], 240)
        self.assertEqual(marker["label"], "日课刷新")

    def test_hint_none_when_advisor_blows_up(self):
        with patch("touken.advisor.load_event_cards",
                   side_effect=RuntimeError("boom")):
            hint = dtl._hanafuda_hint(_today_at(12, 0), self.store)
        self.assertIsNone(hint)

    def test_hint_text_when_hanafuda_active(self):
        fake_plan = {"estimated_seconds": 5400, "seconds_to_end": 99999,
                     "tama_remaining": 300}
        with patch("touken.advisor.load_event_cards",
                   return_value={"秘宝之里": {"mechanics": "hanafuda"}}), \
             patch("touken.advisor.hanafuda_plan", return_value=fake_plan):
            hint = dtl._hanafuda_hint(_today_at(12, 0), self.store)
        self.assertIsNotNone(hint)
        self.assertIn("秘宝之里", hint)

    def test_hint_none_when_event_over(self):
        fake_plan = {"estimated_seconds": 5400, "seconds_to_end": 0,
                     "tama_remaining": 300}
        with patch("touken.advisor.load_event_cards",
                   return_value={"秘宝之里": {"mechanics": "hanafuda"}}), \
             patch("touken.advisor.hanafuda_plan", return_value=fake_plan):
            hint = dtl._hanafuda_hint(_today_at(12, 0), self.store)
        self.assertIsNone(hint)


if __name__ == "__main__":
    unittest.main()
