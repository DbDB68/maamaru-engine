import unittest
from datetime import datetime
from unittest.mock import Mock
from touken.gameplay_planning import estimate

class GameplayPlanningTests(unittest.TestCase):
    def setUp(self):
        self.store = Mock()
        self.store.recent_events.return_value = []
        self.now = datetime.fromisoformat("2026-09-05T10:00:00+08:00")

    def test_time_and_budget_both_limit_runs(self):
        result = estimate(self.store, {"minutes_per_run": 5, "hours_per_day": 2, "budget": 1000, "free_runs": 3}, self.now)
        self.assertEqual(result["runs"], 5)
        self.assertEqual(result["cost"], 1000)

    def test_target_cost_and_time(self):
        result = estimate(self.store, {"mode": "runs", "runs": 200, "minutes_per_run": 3, "free_runs": 10}, self.now)
        self.assertEqual(result["hours"], 10)
        self.assertEqual(result["cost"], 95000)
        self.assertFalse(result["can_finish"])

    def test_unknown_speed_is_not_zero(self):
        self.assertIsNone(estimate(self.store, {}, self.now)["runs"])

    def test_expired_time_has_no_capacity(self):
        self.assertEqual(estimate(self.store, {"minutes_per_run": 1, "deadline": "2026-09-01T10:00"}, self.now)["runs"], 0)

    def test_samples_do_not_cross_runs_or_maps(self):
        def event(ts, run, seq, map_no):
            return {"ts": ts, "run_id": run, "payload": {"mode": "yosari", "sequence": seq, "map_no": map_no}}
        self.store.recent_events.return_value = [event(1, "a", 1, 1), event(121, "a", 2, 1), event(200, "b", 1, 1), event(400, "a", 3, 2)]
        result = estimate(self.store, {}, self.now)
        self.assertEqual(result["sample_count"], 1)
        self.assertEqual(result["seconds_per_run"], 120)
        self.assertIn("连续圈实测", result["speed_source"])

    # ---- 精确圈速：payload.duration_seconds 优先，绝不和近似口径混算 ----

    @staticmethod
    def _precise(ts, run, map_no, duration, outcome="completed"):
        return {"ts": ts, "run_id": run,
                "payload": {"mode": "yosari", "map_no": map_no,
                            "sequence": 1, "attempt": 1, "outcome": outcome,
                            "duration_seconds": duration}}

    def test_single_precise_sample_is_enough(self):
        # 验收样本同构：异去 1-4 一条精确计时就要能用起来
        self.store.recent_events.return_value = [self._precise(100, "a", 4, 84.3)]
        result = estimate(self.store, {"map_no": 4}, self.now)
        self.assertEqual(result["seconds_per_run"], 84.3)
        self.assertEqual(result["sample_count"], 1)
        self.assertIn("精确", result["speed_source"])

    def test_precise_median_ignores_bad_samples(self):
        self.store.recent_events.return_value = [
            self._precise(100, "a", 4, 84.0),
            self._precise(200, "a", 4, 86.0),
            self._precise(300, "a", 4, 90.0),
            self._precise(400, "b", 1, 10.0),      # 其他地图
            self._precise(500, "c", 4, 0),          # 非正数
            self._precise(600, "d", 4, -5.0),       # 负数
            self._precise(700, "e", 4, 99999),      # 异常长耗时
            self._precise(800, "f", 4, 60, outcome="unknown"),
            self._precise(900, "g", 4, 60, outcome="interrupted"),
        ]
        result = estimate(self.store, {"map_no": 4}, self.now)
        self.assertEqual(result["sample_count"], 3)
        self.assertEqual(result["seconds_per_run"], 86.0)

    def test_precise_never_mixes_with_adjacent_intervals(self):
        # 有精确样本时，旧的相邻间隔口径整体让位，不许凑进同一个中位数
        events = [self._precise(100, "a", 4, 84.3),
                  {"ts": 200, "run_id": "b", "payload": {"mode": "yosari", "sequence": 1, "map_no": 4}},
                  {"ts": 320, "run_id": "b", "payload": {"mode": "yosari", "sequence": 2, "map_no": 4}}]
        self.store.recent_events.return_value = events
        result = estimate(self.store, {"map_no": 4}, self.now)
        self.assertEqual(result["sample_count"], 1)
        self.assertEqual(result["seconds_per_run"], 84.3)

    def test_falls_back_to_adjacent_intervals_without_precise(self):
        self.store.recent_events.return_value = [
            {"ts": 1, "run_id": "a", "payload": {"mode": "yosari", "sequence": 1, "map_no": 4}},
            {"ts": 121, "run_id": "a", "payload": {"mode": "yosari", "sequence": 2, "map_no": 4}},
        ]
        result = estimate(self.store, {"map_no": 4}, self.now)
        self.assertEqual(result["seconds_per_run"], 120)
        self.assertIn("连续圈实测", result["speed_source"])

    def test_nonfinite_values_rejected(self):
        for value in ("nan", "inf", -1):
            with self.assertRaises(ValueError):
                estimate(self.store, {"budget": value}, self.now)

    def test_campaign_and_price_come_from_card(self):
        from touken.gameplay_planning import load_gameplay_card
        card = load_gameplay_card()
        self.assertTrue(card["campaign"]["end_at"])
        result = estimate(self.store, {"minutes_per_run": 1}, self.now)
        self.assertEqual(result["campaign"], card["campaign"])
        # 数据卡门票价 500：预算 1000 只够 2 圈
        self.assertEqual(estimate(self.store, {"minutes_per_run": 1, "budget": 1000, "free_runs": 0}, self.now)["runs"], 2)

    def test_missing_card_falls_back(self):
        from unittest.mock import patch
        from touken import gameplay_planning
        with patch.object(gameplay_planning, "load_gameplay_card", return_value={}):
            result = estimate(self.store, {"minutes_per_run": 1}, self.now)
        self.assertEqual(result["campaign"], gameplay_planning._FALLBACK_CAMPAIGN)

    def test_auto_free_uses_only_complete_future_days(self):
        result = estimate(self.store, {"minutes_per_run": 3, "current_free": 2}, self.now)
        self.assertEqual(result["free_days"], 4)
        self.assertEqual(result["free_runs"], 14)

    def test_manual_free_overrides_auto(self):
        result = estimate(self.store, {"minutes_per_run": 3, "free_runs": 1}, self.now)
        self.assertEqual(result["free_runs"], 1)

    def test_same_day_has_no_assumed_refill(self):
        result = estimate(self.store, {"minutes_per_run": 3, "deadline": "2026-09-05T23:59"}, self.now)
        self.assertEqual(result["free_runs"], 0)

    def test_card_price_used_for_blank_input(self):
        result = estimate(self.store, {"price": "", "minutes_per_run": 3}, self.now)
        self.assertEqual(result["price"], 500)
