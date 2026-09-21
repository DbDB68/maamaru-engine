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

    def test_workflow_uses_name_snapshot_from_run(self):
        day_start = _today_at(0, 0)
        self.store.start_run(
            "wf1", "workflow", started_at=day_start + 7200,
            label="活动+异去")
        self.store.finish_run("wf1", "completed", ended_at=day_start + 9000)
        out = dtl.build_day_timeline(
            _today_at(12, 0), cfg=_cfg([]), store=self.store,
            script_labels={"workflow": "自定义工作流"})
        self.assertEqual(out["runs"][0]["label"], "活动+异去")

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
            plan = dtl._hanafuda_active_plan(_today_at(12, 0), self.store)
        self.assertIsNone(plan)
        self.assertIsNone(dtl._hanafuda_hint(plan))

    def test_hint_text_when_hanafuda_active(self):
        fake_plan = {"estimated_seconds": 5400, "seconds_to_end": 99999,
                     "tama_remaining": 300}
        with patch("touken.advisor.load_event_cards",
                   return_value={"秘宝之里": {"mechanics": "hanafuda"}}), \
             patch("touken.advisor.hanafuda_plan", return_value=fake_plan):
            plan = dtl._hanafuda_active_plan(_today_at(12, 0), self.store)
        self.assertEqual(plan, fake_plan)
        self.assertIn("秘宝之里", dtl._hanafuda_hint(plan))

    def test_hint_none_when_event_over(self):
        fake_plan = {"estimated_seconds": 5400, "seconds_to_end": 0,
                     "tama_remaining": 300}
        with patch("touken.advisor.load_event_cards",
                   return_value={"秘宝之里": {"mechanics": "hanafuda"}}), \
             patch("touken.advisor.hanafuda_plan", return_value=fake_plan):
            plan = dtl._hanafuda_active_plan(_today_at(12, 0), self.store)
        self.assertIsNone(plan)


class DayTimelineSuggestWindowsTests(unittest.TestCase):
    """suggest_windows 纯函数：占用段手工注入。"""

    def test_fills_earliest_free_window(self):
        blocks, shortfall = dtl.suggest_windows(480, [], 3600)
        self.assertEqual(shortfall, 0)
        self.assertEqual(blocks, [{"start_min": 480, "duration_min": 60,
                                   "note": ""}])

    def test_avoids_action_window_and_splits(self):
        occupied = [{"start_min": 540, "end_min": 547,
                     "label": "10:00 部队二派遣"}]
        blocks, shortfall = dtl.suggest_windows(480, occupied, 90 * 60)
        self.assertEqual(shortfall, 0)
        self.assertEqual(len(blocks), 2)
        self.assertEqual((blocks[0]["start_min"], blocks[0]["duration_min"]),
                         (480, 60))
        self.assertIn("部队二派遣", blocks[0]["note"])
        self.assertEqual((blocks[1]["start_min"], blocks[1]["duration_min"]),
                         (547, 30))

    def test_fragment_shorter_than_30min_skipped(self):
        occupied = [{"start_min": 480, "end_min": 605, "label": "a"},
                    {"start_min": 630, "end_min": 1440, "label": "b"}]
        blocks, shortfall = dtl.suggest_windows(480, occupied, 3600)
        self.assertEqual(blocks, [])
        self.assertEqual(shortfall, 3600)

    def test_max_two_blocks_then_shortfall(self):
        occupied = [{"start_min": 60, "end_min": 120, "label": "a"},
                    {"start_min": 300, "end_min": 360, "label": "b"}]
        blocks, shortfall = dtl.suggest_windows(0, occupied, 10 * 3600)
        self.assertEqual(len(blocks), 2)
        self.assertEqual((blocks[0]["start_min"], blocks[0]["duration_min"]), (0, 60))
        self.assertEqual((blocks[1]["start_min"], blocks[1]["duration_min"]), (120, 180))
        self.assertGreater(shortfall, 0)

    def test_shortfall_honest_when_no_room(self):
        blocks, shortfall = dtl.suggest_windows(23 * 60, [], 2 * 3600)
        self.assertEqual(len(blocks), 1)
        self.assertEqual(shortfall, 3600)

    def test_zero_needed_no_blocks(self):
        blocks, shortfall = dtl.suggest_windows(480, [], 0)
        self.assertEqual(blocks, [])
        self.assertEqual(shortfall, 0)


class DayTimelineSuggestionIntegrationTests(unittest.TestCase):
    """build_day_timeline 的建议层：占用段组装 + 每日配额口径。"""

    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.store = TelemetryStore(Path(self.tmp.name) / "t.db")
        patcher = patch.object(scheduler, "map_options", lambda: _FAKE_MAPS)
        patcher.start()
        self.addCleanup(patcher.stop)

    def tearDown(self):
        self.store.close()
        self.tmp.cleanup()

    @staticmethod
    def _plan(estimated, seconds_to_end):
        return {"estimated_seconds": estimated,
                "seconds_to_end": seconds_to_end,
                "tama_remaining": 300}

    def _build(self, now, cfg, plan, team_no=None):
        with patch.object(dtl, "_hanafuda_active_plan", return_value=plan):
            return dtl.build_day_timeline(now, cfg=cfg, store=self.store,
                                          script_labels={},
                                          hanafuda_team_no=team_no)

    def test_daily_quota_spread_over_days_left(self):
        """口径：estimated_seconds 按剩余天数平摊（和活动卡前端一致）。"""
        plan = self._plan(7200, 2 * 86400)  # 摊 2 天 → 今天 1 小时
        out = self._build(_today_at(8, 0), _cfg([]), plan)
        self.assertEqual(out["shortfall_seconds"], 0)
        self.assertEqual(out["suggestions"],
                         [{"start_min": 480, "duration_min": 60, "note": ""}])

    def test_quota_capped_by_estimated_seconds(self):
        plan = self._plan(7200, 12 * 3600)  # 只剩半天 → 平摊超标，卡回 7200
        out = self._build(_today_at(8, 0), _cfg([]), plan)
        self.assertEqual(sum(b["duration_min"] for b in out["suggestions"]), 120)

    def test_no_plan_no_suggestions(self):
        out = self._build(_today_at(8, 0), _cfg([]), None)
        self.assertIsNone(out["suggestions"])
        self.assertIsNone(out["shortfall_seconds"])

    def test_skips_daily_reset_window(self):
        plan = self._plan(3600, 86400)
        out = self._build(_today_at(3, 30), _cfg([]), plan)
        # 03:30→03:50 只有 20 分钟碎片，跳过；建议从 04:10 开始
        self.assertEqual(out["suggestions"][0]["start_min"], 250)

    def test_managed_hanafuda_team_blocks_whole_shift(self):
        """活动队在排班管理内：它的远征时段整段避让，不只是动作窗口。"""
        cfg = _cfg([{"time": "10:00", "team_no": 3, "map_code": "B3",
                     "enabled": True}])  # B3 = 90 分钟
        plan = self._plan(4 * 3600, 86400)
        out = self._build(_today_at(8, 0), cfg, plan, team_no=3)
        blocks = out["suggestions"]
        self.assertEqual(out["shortfall_seconds"], 0)
        self.assertEqual(len(blocks), 2)
        self.assertEqual((blocks[0]["start_min"], blocks[0]["duration_min"]),
                         (480, 118))  # 08:00 → 09:58 动作窗口前
        # 只避让动作窗口的话第二块会从 10:05 开始；整段避让必须等 11:30
        self.assertEqual(blocks[1]["start_min"], 690)

    def test_unmanaged_hanafuda_team_only_action_window(self):
        """活动队不在排班管理内：只占动作窗口。"""
        cfg = _cfg([{"time": "10:00", "team_no": 3, "map_code": "B3",
                     "enabled": True}])
        plan = self._plan(4 * 3600, 86400)
        out = self._build(_today_at(8, 0), cfg, plan, team_no=4)
        blocks = out["suggestions"]
        self.assertEqual(blocks[1]["start_min"], 605)  # 10:05 就能续

    def test_disabled_shift_not_avoided(self):
        cfg = _cfg([{"time": "10:00", "team_no": 3, "map_code": "B3",
                     "enabled": False}])
        plan = self._plan(2 * 3600, 86400)
        out = self._build(_today_at(8, 0), cfg, plan, team_no=3)
        self.assertEqual(out["suggestions"],
                         [{"start_min": 480, "duration_min": 120, "note": ""}])


if __name__ == "__main__":
    unittest.main()
