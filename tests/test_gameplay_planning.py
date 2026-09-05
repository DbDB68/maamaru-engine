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

    def test_nonfinite_values_rejected(self):
        for value in ("nan", "inf", -1):
            with self.assertRaises(ValueError):
                estimate(self.store, {"budget": value}, self.now)
