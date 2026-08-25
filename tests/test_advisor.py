import tempfile
import time
import unittest
from datetime import date, timedelta
from pathlib import Path

from touken import advisor


def _day(offset: int) -> str:
    return (date(2026, 8, 25) + timedelta(days=offset)).isoformat()


def _series(resource: str, deltas: list) -> list[dict]:
    """deltas: 相对 2026-08-25 的 (日偏移, total_delta)，None 表示当天没读数。"""
    return [{"date": _day(offset), "resource": resource, "total_delta": delta}
            for offset, delta in deltas]


class DailyRateTests(unittest.TestCase):
    def test_averages_only_days_with_readings(self):
        series = _series("小判", [(-3, 1000), (-2, None), (-1, 3000), (0, 2000)])
        rates = advisor.estimate_daily_rates(series, today=date(2026, 8, 25))
        self.assertEqual(rates["小判"]["daily"], 2000)
        self.assertEqual(rates["小判"]["days_observed"], 3)

    def test_days_outside_window_are_ignored(self):
        series = _series("小判", [(-30, 999999), (-1, 1000)])
        rates = advisor.estimate_daily_rates(series, today=date(2026, 8, 25))
        self.assertEqual(rates["小判"]["daily"], 1000)
        self.assertEqual(rates["小判"]["days_observed"], 1)

    def test_no_data_means_none(self):
        rates = advisor.estimate_daily_rates([], today=date(2026, 8, 25))
        self.assertIsNone(rates["小判"]["daily"])
        self.assertEqual(rates["小判"]["days_observed"], 0)


class KobanFloorYieldTests(unittest.TestCase):
    NOW = 1787700000.0  # 2026-08-25 附近

    def _event(self, delta, floors, age_days=1):
        return {"ts": self.NOW - age_days * 86400,
                "payload": {"delta": delta, "floors": floors}}

    def test_weighted_average_by_floors(self):
        events = [self._event(500, 50), self._event(100, 10)]
        result = advisor.koban_floor_yield(events, now=self.NOW)
        self.assertAlmostEqual(result["per_floor"], 600 / 60)
        self.assertEqual(result["sessions"], 2)

    def test_bad_payloads_are_skipped(self):
        events = [
            {"ts": self.NOW, "payload": {"delta": 500}},               # 没层数
            {"ts": self.NOW, "payload": {"delta": 100, "floors": 0}},  # 0 层
            {"ts": self.NOW, "payload": "not-a-dict"},
            self._event(300, 30),
        ]
        result = advisor.koban_floor_yield(events, now=self.NOW)
        self.assertAlmostEqual(result["per_floor"], 10)
        self.assertEqual(result["sessions"], 1)

    def test_no_sessions_returns_none(self):
        self.assertIsNone(advisor.koban_floor_yield([], now=self.NOW))

    def test_stale_sessions_are_ignored(self):
        # 大阪城关了一个月，旧手气不能拿来开空头支票
        events = [self._event(5000, 50, age_days=30)]
        self.assertIsNone(advisor.koban_floor_yield(events, now=self.NOW))


class EvaluateGoalTests(unittest.TestCase):
    TODAY = date(2026, 8, 25)

    def _goal(self, **overrides):
        goal = {"id": 1, "resource": "小判", "target": 10000,
                "deadline": _day(10), "note": ""}
        goal.update(overrides)
        return goal

    def test_done_when_current_reaches_target(self):
        advice = advisor.evaluate_goal(
            self._goal(), current=12000, rate_info={"daily": 100},
            floor_yield=None, today=self.TODAY)
        self.assertEqual(advice["status"], "done")

    def test_expired_after_deadline(self):
        advice = advisor.evaluate_goal(
            self._goal(deadline=_day(-1)), current=5000,
            rate_info={"daily": 100}, floor_yield=None, today=self.TODAY)
        self.assertEqual(advice["status"], "expired")
        self.assertEqual(advice["shortfall"], 5000)

    def test_unknown_without_current(self):
        advice = advisor.evaluate_goal(
            self._goal(), current=None, rate_info={"daily": 100},
            floor_yield=None, today=self.TODAY)
        self.assertEqual(advice["status"], "unknown")

    def test_unknown_without_rate(self):
        advice = advisor.evaluate_goal(
            self._goal(), current=5000, rate_info={"daily": None},
            floor_yield=None, today=self.TODAY)
        self.assertEqual(advice["status"], "unknown")

    def test_on_track(self):
        advice = advisor.evaluate_goal(
            self._goal(), current=5000, rate_info={"daily": 600},
            floor_yield=None, today=self.TODAY)
        self.assertEqual(advice["status"], "on_track")
        self.assertEqual(advice["projected"], 11000)

    def test_behind_translates_to_extra_floors(self):
        # 10 天还差 5000：每天得多攒 600-100=500，每层 25 → 每天 20 层
        advice = advisor.evaluate_goal(
            self._goal(), current=5000, rate_info={"daily": 100},
            floor_yield={"per_floor": 25.0, "sessions": 3}, today=self.TODAY)
        self.assertEqual(advice["status"], "behind")
        self.assertEqual(advice["projected"], 6000)
        self.assertEqual(advice["shortfall"], 4000)
        self.assertEqual(advice["extra_daily"], 400)
        self.assertEqual(advice["extra_floors"], 16)
        self.assertIn("大阪城", advice["message"])

    def test_behind_non_koban_has_no_floors(self):
        advice = advisor.evaluate_goal(
            self._goal(resource="砥石"), current=5000, rate_info={"daily": 100},
            floor_yield={"per_floor": 25.0, "sessions": 3}, today=self.TODAY)
        self.assertEqual(advice["status"], "behind")
        self.assertIsNone(advice["extra_floors"])


class GoalStorageTests(unittest.TestCase):
    def setUp(self):
        self._tmp = tempfile.TemporaryDirectory()
        self.path = Path(self._tmp.name) / "planning_goals.json"

    def tearDown(self):
        self._tmp.cleanup()

    def test_load_missing_file_is_empty(self):
        self.assertEqual(advisor.load_goals(self.path), [])

    def test_add_and_reload_roundtrip(self):
        goal = advisor.add_goal(self.path, resource="小判", target=300000,
                                deadline=_day(20), note="江户城门票钱")
        self.assertEqual(goal["id"], 1)
        loaded = advisor.load_goals(self.path)
        self.assertEqual(len(loaded), 1)
        self.assertEqual(loaded[0]["resource"], "小判")
        self.assertEqual(loaded[0]["note"], "江户城门票钱")
        second = advisor.add_goal(self.path, resource="砥石", target=5000,
                                  deadline=_day(5))
        self.assertEqual(second["id"], 2)

    def test_add_rejects_bad_input(self):
        with self.assertRaises(ValueError):
            advisor.add_goal(self.path, resource="钻石", target=100,
                             deadline=_day(1))
        with self.assertRaises(ValueError):
            advisor.add_goal(self.path, resource="小判", target=0,
                             deadline=_day(1))
        with self.assertRaises(ValueError):
            advisor.add_goal(self.path, resource="小判", target=100,
                             deadline="不是日期")
        with self.assertRaises(ValueError):
            advisor.add_goal(self.path, resource="小判", target=100,
                             deadline="2020-01-01")

    def test_delete_goal(self):
        goal = advisor.add_goal(self.path, resource="小判", target=100,
                                deadline=_day(1))
        self.assertFalse(advisor.delete_goal(self.path, 999))
        self.assertTrue(advisor.delete_goal(self.path, goal["id"]))
        self.assertEqual(advisor.load_goals(self.path), [])


class _FakeStore:
    def resource_ledger(self, from_ts, to_ts):
        return {
            "per_resource": [
                {"resource": "小判", "opening": 8000, "closing": 9000},
            ],
            "daily_series": _series("小判", [(-1, 500), (0, 500)]),
        }

    def recent_events(self, limit=100, event_type=None):
        assert event_type == "osaka.koban_session"
        return [{"ts": time.time(), "payload": {"delta": 250, "floors": 10}}]


class GetPlanningTests(unittest.TestCase):
    def test_end_to_end_with_fake_store(self):
        with tempfile.TemporaryDirectory() as tmp:
            path = Path(tmp) / "goals.json"
            advisor.add_goal(path, resource="小判", target=100000,
                             deadline=_day(10))
            planning = advisor.get_planning(_FakeStore(), path,
                                            today=date(2026, 8, 25))
        self.assertEqual(planning["schema_version"],
                         advisor.PLANNING_SCHEMA_VERSION)
        goal = planning["goals"][0]
        self.assertEqual(goal["current"], 9000)
        self.assertEqual(goal["rate"], 500)
        self.assertEqual(goal["status"], "behind")
        self.assertEqual(goal["extra_floors"], 344)  # 8600/天 ÷ 25/层
        self.assertEqual(planning["koban_per_floor"]["per_floor"], 25)


if __name__ == "__main__":
    unittest.main()
