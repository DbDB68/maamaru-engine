import json
import tempfile
import time
import unittest
from datetime import date, datetime, timedelta
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

    def test_event_days_excluded_from_normal_rate(self):
        series = _series("小判", [(-2, 9000), (-1, 1000), (0, 1000)])
        rates = advisor.estimate_daily_rates(series, today=date(2026, 8, 25),
                                             exclude_dates={_day(-2)})
        self.assertEqual(rates["小判"]["daily"], 1000)
        self.assertEqual(rates["小判"]["days_observed"], 2)


class EventRateTests(unittest.TestCase):
    TODAY = date(2026, 8, 25)

    def _ts(self, offset: int) -> float:
        from datetime import datetime
        return datetime(2026, 8, 25, 12, tzinfo=advisor._TZ).timestamp() \
            + offset * 86400

    def test_event_day_dates_from_attributions(self):
        attributions = [
            {"ts": self._ts(-2), "source": "osaka.koban_session"},
            {"ts": self._ts(-2), "source": "edocastle.run_completed"},
            {"ts": self._ts(-1), "source": "expedition.dispatched"},  # 平常来源不算
            {"ts": self._ts(0), "source": "raid.round_completed"},
            {"ts": self._ts(-90), "source": "osaka.koban_session"},   # 超出回望窗口
        ]
        dates = advisor.event_day_dates(attributions, today=self.TODAY)
        self.assertEqual(dates, {_day(-2), _day(0)})

    def test_event_rates_average_only_event_days(self):
        series = _series("小判", [(-2, 9000), (-1, 1000), (0, 3000)])
        rates = advisor.estimate_event_rates(series, {_day(-2), _day(0)},
                                             today=self.TODAY)
        self.assertEqual(rates["小判"]["daily"], 6000)
        self.assertEqual(rates["小判"]["days_observed"], 2)

    def test_event_rates_none_without_event_days(self):
        series = _series("小判", [(-1, 1000)])
        rates = advisor.estimate_event_rates(series, set(), today=self.TODAY)
        self.assertIsNone(rates["小判"]["daily"])


class SplitGoalDaysTests(unittest.TestCase):
    TODAY = date(2026, 8, 25)

    def test_event_window_splits_days(self):
        windows = [{"name": "江户城潜入调查", "start_date": _day(2),
                    "end_date": _day(7)}]
        normal, event, names = advisor._split_goal_days(self.TODAY, _day(10), windows)
        self.assertEqual((normal, event), (4, 6))
        self.assertEqual(names, ["江户城潜入调查"])

    def test_window_clamped_to_goal_range(self):
        windows = [{"name": "联队战", "start_date": _day(-5),
                    "end_date": _day(99)}]
        normal, event, _ = advisor._split_goal_days(self.TODAY, _day(10), windows)
        self.assertEqual((normal, event), (0, 10))

    def test_overlapping_windows_counted_once(self):
        windows = [{"name": "A", "start_date": _day(2), "end_date": _day(6)},
                   {"name": "B", "start_date": _day(4), "end_date": _day(8)}]
        normal, event, _ = advisor._split_goal_days(self.TODAY, _day(10), windows)
        self.assertEqual((normal, event), (3, 7))

    def test_window_missing_dates_ignored(self):
        windows = [{"name": "无名", "start_date": None, "end_date": _day(5)}]
        normal, event, _ = advisor._split_goal_days(self.TODAY, _day(10), windows)
        self.assertEqual((normal, event), (10, 0))


class EvaluateGoalEventWindowTests(unittest.TestCase):
    TODAY = date(2026, 8, 25)
    WINDOW = [{"name": "江户城潜入调查", "start_date": _day(2),
               "end_date": _day(7)}]  # 6 天活动期

    def _goal(self, **overrides):
        goal = {"id": 1, "resource": "小判", "target": 10000,
                "deadline": _day(10), "note": ""}
        goal.update(overrides)
        return goal

    def test_event_days_use_event_rate(self):
        # 4 平常天 × 100 + 6 活动天 × 1000 = 6400 → 5000 + 6400 = 11400
        advice = advisor.evaluate_goal(
            self._goal(), current=5000,
            rate_info={"daily": 100, "event_daily": 1000},
            floor_yield=None, today=self.TODAY, event_windows=self.WINDOW)
        self.assertEqual(advice["status"], "on_track")
        self.assertEqual(advice["projected"], 11400)
        self.assertEqual(advice["event_days"], 6)
        self.assertIn("活动期", advice["message"])

    def test_event_days_fall_back_to_normal_rate_when_unmeasured(self):
        # 活动收益没实测：全程按平常 100 估，文案明说兜底
        advice = advisor.evaluate_goal(
            self._goal(), current=5000,
            rate_info={"daily": 100, "event_daily": None},
            floor_yield=None, today=self.TODAY, event_windows=self.WINDOW)
        self.assertEqual(advice["status"], "behind")
        self.assertEqual(advice["projected"], 6000)
        self.assertIn("还没实测", advice["message"])

    def test_no_event_window_keeps_plain_message(self):
        advice = advisor.evaluate_goal(
            self._goal(), current=5000,
            rate_info={"daily": 600, "event_daily": 9999},
            floor_yield=None, today=self.TODAY)
        self.assertEqual(advice["projected"], 11000)
        self.assertEqual(advice["event_days"], 0)
        self.assertIn("平常每天", advice["message"])


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
                                deadline=(date.today() + timedelta(days=1)).isoformat())
        self.assertFalse(advisor.delete_goal(self.path, 999))
        self.assertTrue(advisor.delete_goal(self.path, goal["id"]))
        self.assertEqual(advisor.load_goals(self.path), [])

    def _write_v1(self, goals):
        self.path.write_text(json.dumps(goals, ensure_ascii=False),
                             encoding="utf-8")

    def test_v1_file_loads_with_resource_kind(self):
        # v1 纯数组：老目标一律按攒钱目标读（牛评审：格式升级不许丢老数据）
        self._write_v1([{"id": 1, "resource": "小判", "target": 300000,
                         "deadline": _day(20), "note": "老目标"}])
        loaded = advisor.load_goals(self.path)
        self.assertEqual(len(loaded), 1)
        self.assertEqual(loaded[0]["kind"], "resource")
        self.assertEqual(loaded[0]["note"], "老目标")

    def test_v1_to_v2_migration_backs_up_and_preserves(self):
        v1 = [{"id": 1, "resource": "小判", "target": 300000,
               "deadline": _day(20), "note": "老目标"}]
        self._write_v1(v1)
        advisor.add_goal(self.path, resource="砥石", target=5000,
                         deadline=_day(5))
        # 新文件是 v2 信封，新老目标都在
        data = json.loads(self.path.read_text(encoding="utf-8"))
        self.assertEqual(data["schema_version"], advisor.GOALS_SCHEMA_VERSION)
        self.assertEqual(len(data["goals"]), 2)
        self.assertEqual(data["goals"][0]["note"], "老目标")
        # 旧格式有备份，真要回滚有得捡
        backup = self.path.with_name(self.path.name + ".v1.bak")
        self.assertEqual(json.loads(backup.read_text(encoding="utf-8")), v1)
        # 再写一次还是 v2，不重复备份
        advisor.add_goal(self.path, resource="小判", target=100,
                         deadline=_day(3))
        data = json.loads(self.path.read_text(encoding="utf-8"))
        self.assertEqual(len(data["goals"]), 3)

    def test_v2_file_roundtrip(self):
        advisor.add_goal(self.path, resource="小判", target=100,
                         deadline=_day(3))
        data = json.loads(self.path.read_text(encoding="utf-8"))
        self.assertEqual(data["schema_version"], advisor.GOALS_SCHEMA_VERSION)
        self.assertFalse(self.path.with_name(self.path.name + ".v1.bak")
                         .exists())  # 全新文件没有可备份的旧格式


class _FakeStore:
    def resource_ledger(self, from_ts, to_ts):
        return {
            "per_resource": [
                {"resource": "小判", "opening": 8000, "closing": 9000},
            ],
            "daily_series": _series("小判", [(-1, 500), (0, 500)]),
        }

    def recent_events(self, limit=100, event_type=None):
        if event_type == "osaka.koban_session":
            return [{"ts": time.time(), "payload": {"delta": 250, "floors": 10}}]
        return []  # edocastle.run_completed 等其它事件一律没数据


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
        # 本期大阪城已进入知识卡窗口，预测会把窗口净收益一并算进去。
        self.assertEqual(goal["extra_floors"], 345)
        self.assertEqual(planning["koban_per_floor"]["per_floor"], 25)
        # 仓库默认活动卡（江户城）也应出现在算盘里，没实测就保持「还没数」
        abacus = planning["events"][0]
        self.assertEqual(abacus["event"], "江户城潜入调查")
        self.assertIsNone(abacus["keys_source"])
        # 预算判定字段由服务端给出；还没数时是 None，不许前端自己拼
        self.assertEqual(abacus["available_now"], 9000)
        self.assertIsNone(abacus["sufficient"])
        self.assertIsNone(abacus["shortfall"])


class EventGoalTests(unittest.TestCase):
    """牛评审：活动攒钱目标的语义是「预算 vs 家底」，
    不是旧前端的「家底 + 预算」（那等于让人多攒一倍）。"""

    def _setup(self, tmp: str, balance: int):
        # 日期跟着真实今天走，免得活动一过测试自己过期
        start = date.today() + timedelta(days=1)
        end = date.today() + timedelta(days=15)
        card = {"start_date": start.isoformat(), "end_date": end.isoformat(),
                "start_at": f"{start.isoformat()}T10:00:00+08:00",
                "end_at": f"{end.isoformat()}T05:00:00+08:00",
                "ticket_price": 300, "ticket_cap": 6, "refill_hours": [5, 17],
                "refill_amount": 3,
                "keys_total": 1500, "keys_per_box": 5, "boxes": 300,
                "est_keys_per_run": 5}
        patch = {"江户城潜入调查": card}
        (Path(tmp) / advisor.EVENTS_META_LOCAL).write_text(
            json.dumps(patch, ensure_ascii=False), encoding="utf-8")

        class _Store:
            def resource_ledger(self, from_ts, to_ts):
                return {"per_resource": [{"resource": "小判", "opening": balance,
                                          "closing": balance}],
                        "daily_series": []}

            def recent_events(self, limit=100, event_type=None):
                return []
        return _Store(), card

    def test_shortfall_creates_goal_with_budget_as_target(self):
        with tempfile.TemporaryDirectory() as tmp:
            store, card = self._setup(tmp, 9000)
            path = Path(tmp) / "planning_goals.json"
            result = advisor.add_event_goal(store, path, "江户城潜入调查")
            self.assertFalse(result["sufficient"])
            expected = advisor.event_abacus("江户城潜入调查", card,
                                            measured=None)["koban_cost"]
            goal = result["goal"]
            self.assertEqual(goal["target"], expected)  # 目标是预算本身
            self.assertNotEqual(goal["target"], 9000 + expected)  # 旧错法
            self.assertEqual(goal["resource"], "小判")
            self.assertEqual(goal["deadline"], card["start_date"])
            self.assertEqual(result["shortfall"], expected - 9000)
            self.assertEqual(advisor.load_goals(path), [goal])

    def test_sufficient_balance_creates_no_goal(self):
        with tempfile.TemporaryDirectory() as tmp:
            store, _ = self._setup(tmp, 90_000_000)
            path = Path(tmp) / "planning_goals.json"
            result = advisor.add_event_goal(store, path, "江户城潜入调查")
            self.assertTrue(result["sufficient"])
            self.assertIsNone(result["goal"])
            self.assertEqual(advisor.load_goals(path), [])

    def test_repeated_request_updates_the_same_event_goal(self):
        with tempfile.TemporaryDirectory() as tmp:
            store, _ = self._setup(tmp, 0)
            path = Path(tmp) / "planning_goals.json"
            first = advisor.add_event_goal(store, path, "江户城潜入调查")
            second = advisor.add_event_goal(store, path, "江户城潜入调查")
            goals = advisor.load_goals(path)
            self.assertEqual(len(goals), 1)
            self.assertEqual(first["goal"]["id"], second["goal"]["id"])
            self.assertEqual(goals[0]["kind"], "event")
            self.assertEqual(goals[0]["event"], "江户城潜入调查")

    def test_event_goal_uses_the_supplied_real_time(self):
        with tempfile.TemporaryDirectory() as tmp:
            store, card = self._setup(tmp, 0)
            path = Path(tmp) / "planning_goals.json"
            start = date.fromisoformat(card["start_date"])
            evening = datetime.combine(start, datetime.min.time(),
                                         tzinfo=advisor._TZ) + timedelta(hours=18)
            result = advisor.add_event_goal(
                store, path, "江户城潜入调查", today=start, now=evening)
            expected = advisor.event_abacus(
                "江户城潜入调查", card, measured=None,
                today=start, now=evening)["koban_cost"]
            self.assertEqual(result["koban_cost"], expected)
            self.assertEqual(result["goal"]["target"], expected)
            self.assertEqual(result["goal"]["deadline"], card["end_date"])

    def test_unknown_event_rejected(self):
        with tempfile.TemporaryDirectory() as tmp:
            store, _ = self._setup(tmp, 9000)
            with self.assertRaises(ValueError):
                advisor.add_event_goal(store, Path(tmp) / "g.json", "南瓜大作战")


class OsakaStockGoalTests(unittest.TestCase):
    NOW = datetime(2026, 8, 26, 12, tzinfo=advisor._TZ)

    def _setup(self, tmp: str, balance: int = 9000):
        card = {
            "start_date": "2026-08-13", "end_date": "2026-08-27",
            "start_at": "2026-08-13T10:00:00+08:00",
            "end_at": "2026-08-27T05:00:00+08:00",
            "mechanics": "osaka",
        }
        (Path(tmp) / advisor.EVENTS_META_LOCAL).write_text(
            json.dumps({"大阪城": card}, ensure_ascii=False), encoding="utf-8")

        class _Store:
            def resource_ledger(self, from_ts, to_ts):
                return {"per_resource": [{"resource": "小判",
                                           "opening": balance,
                                           "closing": balance}],
                        "daily_series": []}

            def recent_events(self, limit=100, event_type=None):
                if event_type == "osaka.koban_session":
                    return [{"ts": OsakaStockGoalTests.NOW.timestamp(),
                             "payload": {"delta": 250, "floors": 10}}]
                return []

            def recent_run_summaries(self, **kwargs):
                return [{"started_at": OsakaStockGoalTests.NOW.timestamp() - 3600,
                         "loops": 16, "average_loop_seconds": 300}]
        return _Store(), card

    def test_creates_final_stock_goal_with_precise_deadline(self):
        with tempfile.TemporaryDirectory() as tmp:
            store, card = self._setup(tmp)
            path = Path(tmp) / "planning_goals.json"
            result = advisor.add_event_goal(
                store, path, "大阪城", target=10000,
                today=self.NOW.date(), now=self.NOW)
            self.assertEqual(result["shortfall"], 1000)
            self.assertEqual(result["goal_mode"], "stock_target")
            self.assertEqual(result["goal"]["target"], 10000)
            self.assertEqual(result["goal"]["deadline"], card["end_date"])
            self.assertEqual(result["goal"]["deadline_at"], card["end_at"])
            self.assertEqual(result["goal"]["note"], "大阪城收摊目标")

    def test_repeated_request_updates_same_goal(self):
        with tempfile.TemporaryDirectory() as tmp:
            store, _ = self._setup(tmp)
            path = Path(tmp) / "planning_goals.json"
            first = advisor.add_event_goal(
                store, path, "大阪城", target=10000,
                today=self.NOW.date(), now=self.NOW)
            second = advisor.add_event_goal(
                store, path, "大阪城", target=12000,
                today=self.NOW.date(), now=self.NOW)
            goals = advisor.load_goals(path)
            self.assertEqual(len(goals), 1)
            self.assertEqual(first["goal"]["id"], second["goal"]["id"])
            self.assertEqual(goals[0]["target"], 12000)

    def test_planning_connects_latest_floor_speed_to_stock_goal(self):
        with tempfile.TemporaryDirectory() as tmp:
            store, _ = self._setup(tmp)
            path = Path(tmp) / "planning_goals.json"
            advisor.add_event_goal(
                store, path, "大阪城", target=10000,
                today=self.NOW.date(), now=self.NOW)
            planning = advisor.get_planning(
                store, path, today=self.NOW.date(), now=self.NOW)
        self.assertEqual(planning["osaka_floor_speed"]["seconds_per_floor"], 300)
        self.assertEqual(planning["goals"][0]["estimated_seconds"], 12000)
        self.assertTrue(planning["goals"][0]["can_finish"])

    def test_missing_target_and_closed_activity_are_rejected(self):
        with tempfile.TemporaryDirectory() as tmp:
            store, _ = self._setup(tmp)
            path = Path(tmp) / "planning_goals.json"
            with self.assertRaises(ValueError):
                advisor.add_event_goal(store, path, "大阪城", now=self.NOW)
            with self.assertRaises(ValueError):
                advisor.add_event_goal(
                    store, path, "大阪城", target=10000,
                    now=datetime(2026, 8, 27, 5, tzinfo=advisor._TZ))

    def test_evaluation_uses_measured_floor_yield_and_exact_closing_time(self):
        goal = {
            "id": 1, "kind": "event", "event": "大阪城",
            "goal_mode": "stock_target", "resource": "小判",
            "target": 10000, "deadline": "2026-08-27",
            "deadline_at": "2026-08-27T05:00:00+08:00",
        }
        advice = advisor.evaluate_goal(
            goal, current=9000, rate_info={},
            floor_yield={"per_floor": 25, "sessions": 3},
            floor_speed={"seconds_per_floor": 300, "floors": 16},
            now=self.NOW)
        self.assertEqual(advice["status"], "active")
        self.assertEqual(advice["floors_needed"], 40)
        self.assertEqual(advice["floors_per_day"], 40)
        self.assertEqual(advice["seconds_per_floor"], 300)
        self.assertEqual(advice["speed_sample_floors"], 16)
        self.assertEqual(advice["estimated_seconds"], 12000)
        self.assertEqual(advice["remaining_seconds"], 61200)
        self.assertEqual(advice["time_margin_seconds"], 49200)
        self.assertTrue(advice["can_finish"])
        self.assertNotIn("每天", advice["message"])
        expired = advisor.evaluate_goal(
            goal, current=9000, rate_info={},
            floor_yield={"per_floor": 25, "sessions": 3},
            now=datetime(2026, 8, 27, 5, tzinfo=advisor._TZ))
        self.assertEqual(expired["status"], "expired")

    def test_evaluation_says_when_measured_pace_cannot_finish(self):
        goal = {
            "id": 1, "kind": "event", "event": "大阪城",
            "goal_mode": "stock_target", "resource": "小判",
            "target": 10000, "deadline": "2026-08-27",
            "deadline_at": "2026-08-27T05:00:00+08:00",
        }
        advice = advisor.evaluate_goal(
            goal, current=9000, rate_info={},
            floor_yield={"per_floor": 25, "sessions": 3},
            floor_speed={"seconds_per_floor": 1800, "floors": 4},
            now=self.NOW)
        self.assertFalse(advice["can_finish"])
        self.assertEqual(advice["estimated_seconds"], 72000)
        self.assertEqual(advice["time_margin_seconds"], -10800)


class OsakaFloorSpeedTests(unittest.TestCase):
    def test_uses_latest_valid_recent_osaka_run(self):
        class _Store:
            def recent_run_summaries(self, **kwargs):
                self.kwargs = kwargs
                return [
                    {"started_at": 3, "loops": 0, "average_loop_seconds": None},
                    {"started_at": 2, "loops": 16, "average_loop_seconds": 359.4},
                    {"started_at": 1, "loops": 25, "average_loop_seconds": 298.0},
                ]
        store = _Store()
        result = advisor.latest_osaka_floor_speed(store, now=1000000)
        self.assertEqual(result, {"seconds_per_floor": 359.4, "floors": 16,
                                  "run_started_at": 2})
        self.assertEqual(store.kwargs["script"], "osaka")

    def test_store_without_run_summaries_has_no_speed(self):
        self.assertIsNone(advisor.latest_osaka_floor_speed(object()))


if __name__ == "__main__":
    unittest.main()


def _edo_card(**overrides):
    card = {"mechanics": "edocastle",
            "start_at": "2026-08-27T10:00:00+08:00",
            "end_at": "2026-09-10T05:00:00+08:00",
            "ticket_price": 300, "daily_free_tickets": 6,
            "ticket_cap": 6, "refill_hours": [5, 17], "refill_amount": 3,
            "keys_total": 1500, "keys_per_box": 5, "boxes": 300,
            "est_keys_per_run": None, "note": ""}
    card.update(overrides)
    return card


class EventAbacusTests(unittest.TestCase):
    TODAY = date(2026, 8, 25)

    def test_no_keys_data_means_learning(self):
        abacus = advisor.event_abacus("江户城潜入调查", _edo_card(),
                                      measured=None, today=self.TODAY)
        self.assertIsNone(abacus["runs_needed"])
        self.assertIsNone(abacus["keys_source"])
        self.assertIn("还没数", abacus["message"])

    def test_estimate_without_end_date_gives_worst_case(self):
        abacus = advisor.event_abacus(
            "江户城潜入调查",
            _edo_card(est_keys_per_run=10, start_at=None, end_at=None),
            measured=None, today=self.TODAY)
        self.assertEqual(abacus["runs_needed"], 150)
        self.assertEqual(abacus["koban_cost"], 45000)  # 150 圈 × 300
        self.assertEqual(abacus["keys_source"], "estimate")

    def test_free_tickets_can_cover_everything(self):
        # 精确口径：开场 6 + 窗口内 27 次回票 × 3 = 87 张白票
        abacus = advisor.event_abacus(
            "江户城潜入调查",
            _edo_card(est_keys_per_run=20),
            measured=None, today=self.TODAY)
        self.assertEqual(abacus["days_left"], 15)
        self.assertEqual(abacus["free_runs"], 87)
        self.assertEqual(abacus["paid_tickets"], 0)
        self.assertEqual(abacus["koban_cost"], 0)
        self.assertIn("一个小判都不用花", abacus["message"])

    def test_paid_tickets_and_cost(self):
        abacus = advisor.event_abacus(
            "江户城潜入调查",
            _edo_card(est_keys_per_run=5),
            measured=None, today=self.TODAY)
        self.assertEqual(abacus["runs_needed"], 300)
        self.assertEqual(abacus["free_runs"], 87)
        self.assertEqual(abacus["paid_tickets"], 213)
        self.assertEqual(abacus["koban_cost"], 63900)

    def test_measured_overrides_estimate(self):
        measured = {"per_run": 20.0, "runs": 3}
        abacus = advisor.event_abacus(
            "江户城潜入调查", _edo_card(est_keys_per_run=10),
            measured=measured, today=self.TODAY)
        self.assertEqual(abacus["runs_needed"], 75)
        self.assertEqual(abacus["keys_source"], "measured")


class MeasuredKeysTests(unittest.TestCase):
    def test_averages_payload_keys(self):
        class _Store:
            def recent_events(self, limit=100, event_type=None):
                assert event_type == "edocastle.run_completed"
                return [{"payload": {"keys": 10}}, {"payload": {"keys": 20}},
                        {"payload": {"keys": 0}}, {"payload": "脏数据"}]
        result = advisor.measured_keys_per_run(_Store())
        self.assertEqual(result["per_run"], 15)
        self.assertEqual(result["runs"], 2)

    def test_no_data_returns_none(self):
        class _Store:
            def recent_events(self, limit=100, event_type=None):
                return []
        self.assertIsNone(advisor.measured_keys_per_run(_Store()))


class EventCardStorageTests(unittest.TestCase):
    def setUp(self):
        self._tmp = tempfile.TemporaryDirectory()
        self.dir = Path(self._tmp.name)

    def tearDown(self):
        self._tmp.cleanup()

    def test_default_card_loads_from_repo(self):
        cards = advisor.load_event_cards(self.dir)
        self.assertIn("江户城潜入调查", cards)
        self.assertEqual(cards["江户城潜入调查"]["ticket_price"], 300)

    def test_save_estimate_roundtrip_and_override(self):
        advisor.save_key_estimate(self.dir, "江户城潜入调查", 12)
        cards = advisor.load_event_cards(self.dir)
        self.assertEqual(cards["江户城潜入调查"]["est_keys_per_run"], 12)

    def test_save_estimate_rejects_bad_input(self):
        with self.assertRaises(ValueError):
            advisor.save_key_estimate(self.dir, "不存在的活动", 10)
        with self.assertRaises(ValueError):
            advisor.save_key_estimate(self.dir, "江户城潜入调查", 0)
        with self.assertRaises(ValueError):
            advisor.save_key_estimate(self.dir, "江户城潜入调查", "不是数")


class WindowImpactTests(unittest.TestCase):
    """§25 活动感知规划：知识卡机理算盘直接算窗口净影响。"""

    TODAY = date(2026, 8, 26)  # 江户城开打前一天
    EDO_CARD = {
        "mechanics": "edocastle",
        "start_at": "2026-08-27T10:00:00+08:00",
        "end_at": "2026-09-10T05:00:00+08:00",
        "ticket_price": 300, "daily_free_tickets": 6,
        "ticket_cap": 6, "refill_hours": [5, 17], "refill_amount": 3,
        "keys_total": 1500, "keys_per_box": 5, "boxes": 300,
        "est_keys_per_run": 5,
    }

    def test_edocastle_impact_is_negative_ticket_cost(self):
        # 场均 5 把 → 300 圈；白票 87 → 补 213 张 ≈ -63900
        impact = advisor.window_impact("江户城潜入调查", self.EDO_CARD,
                                       today=self.TODAY)
        self.assertEqual(impact["resource"], "小判")
        self.assertEqual(impact["delta"], -63900)

    def test_edocastle_free_tickets_cover_all_means_zero_cost(self):
        card = {**self.EDO_CARD, "est_keys_per_run": 20}  # 75 圈 ≤ 87 白票
        impact = advisor.window_impact("江户城潜入调查", card, today=self.TODAY)
        self.assertEqual(impact["delta"], 0)

    def test_edocastle_without_keys_data_returns_none(self):
        card = {**self.EDO_CARD, "est_keys_per_run": None}
        self.assertIsNone(advisor.window_impact("江户城潜入调查", card,
                                                today=self.TODAY))

    def test_measured_keys_override_estimate(self):
        # 实测场均 10 → 150 圈；白票 87 → 补 63 张 ≈ -18900
        impact = advisor.window_impact(
            "江户城潜入调查", dict(self.EDO_CARD),
            measured_keys={"per_run": 10, "runs": 3}, today=self.TODAY)
        self.assertEqual(impact["delta"], -18900)

    def test_osaka_impact_is_positive(self):
        card = {"mechanics": "osaka", "start_date": "2026-08-27",
                "end_date": "2026-09-02",  # 开打后起 7 天
                "hours_per_night": 6, "lap_minutes": 5}
        impact = advisor.window_impact("大阪城", card,
                                       floor_yield={"per_floor": 400},
                                       today=self.TODAY)
        # 每晚 72 层 × 7 天 × 400 = 201600
        self.assertEqual(impact["delta"], 201600)

    def test_osaka_without_yield_or_dates_returns_none(self):
        card = {"mechanics": "osaka", "start_date": "2026-08-27",
                "end_date": "2026-09-02"}
        self.assertIsNone(advisor.window_impact("大阪城", card,
                                                floor_yield=None,
                                                today=self.TODAY))
        self.assertIsNone(advisor.window_impact(
            "大阪城", {"mechanics": "osaka"},
            floor_yield={"per_floor": 400}, today=self.TODAY))

    def test_unknown_mechanics_returns_none(self):
        self.assertIsNone(advisor.window_impact(
            "神秘活动", {"mechanics": "???"}, today=self.TODAY))


class ModeledWindowGoalTests(unittest.TestCase):
    """有知识卡模型的活动窗口参与目标预测（§25.5 步骤 2）。"""

    TODAY = date(2026, 8, 26)
    WINDOW = [{"name": "江户城潜入调查", "start_date": "2026-08-27",
               "end_date": "2026-09-10"}]  # 目标期内 15 天活动
    IMPACT = {"江户城潜入调查": {"resource": "小判", "delta": -36000}}

    def _goal(self, deadline="2026-09-10"):
        return {"id": 1, "resource": "小判", "target": 90000,
                "deadline": deadline, "note": ""}

    def test_modeled_window_replaces_rate_guess(self):
        # 全程在活动期：平常 0 天 + 门票影响 -36000，活动段不吃速率
        advice = advisor.evaluate_goal(
            self._goal(), current=80000,
            rate_info={"daily": 100, "event_daily": None},
            floor_yield=None, today=self.TODAY, event_windows=self.WINDOW,
            window_impacts=self.IMPACT)
        self.assertEqual(advice["projected"], 44000)
        self.assertEqual(advice["status"], "behind")
        self.assertTrue(advice["event_modeled"])
        self.assertIn("知识卡", advice["message"])
        self.assertNotIn("还没实测", advice["message"])

    def test_unmodeled_window_still_uses_rate_fallback(self):
        # 没模型：15 活动天按平常 100 兜底 → 80000 + 1500
        advice = advisor.evaluate_goal(
            self._goal(), current=80000,
            rate_info={"daily": 100, "event_daily": None},
            floor_yield=None, today=self.TODAY, event_windows=self.WINDOW,
            window_impacts={})
        self.assertEqual(advice["projected"], 81500)
        self.assertIn("还没实测", advice["message"])

    def test_deadline_mid_window_scales_impact(self):
        # 截止 9-01：窗口只覆盖 8-27..9-01 = 6 天，影响按 6/15 折算 -14400
        advice = advisor.evaluate_goal(
            self._goal(deadline="2026-09-01"), current=80000,
            rate_info={"daily": 100, "event_daily": None},
            floor_yield=None, today=self.TODAY, event_windows=self.WINDOW,
            window_impacts=self.IMPACT)
        self.assertEqual(advice["projected"], 65600)

    def test_impact_for_other_resource_ignored(self):
        impact = {"江户城潜入调查": {"resource": "冷却材", "delta": -5000}}
        advice = advisor.evaluate_goal(
            self._goal(), current=80000,
            rate_info={"daily": 100, "event_daily": None},
            floor_yield=None, today=self.TODAY, event_windows=self.WINDOW,
            window_impacts=impact)
        self.assertEqual(advice["projected"], 81500)
        self.assertFalse(advice["event_modeled"])


class PreciseWindowAbacusTests(unittest.TestCase):
    """带时刻的活动卡：新模型是开场 cap + 严格落在窗口内的回票点 × refill_amount。

    江户城 8-27 10:00 开、9-10 05:00 收：开场 6 + 窗口内 27 次回票 × 3 = 87 张。
    """

    NOW = datetime(2026, 8, 26, 12, tzinfo=advisor._TZ)  # 开打前一天中午

    def _card(self, **overrides):
        card = {
            "mechanics": "edocastle",
            "start_at": "2026-08-27T10:00:00+08:00",
            "end_at": "2026-09-10T05:00:00+08:00",
            "ticket_price": 300, "daily_free_tickets": 6,
            "ticket_cap": 6, "refill_hours": [5, 17], "refill_amount": 3,
            "keys_total": 1500, "keys_per_box": 5, "boxes": 300,
            "est_keys_per_run": 5,
        }
        card.update(overrides)
        return card

    def test_free_tickets_counted_by_refill_overlap(self):
        abacus = advisor.event_abacus("江户城潜入调查", self._card(),
                                      measured=None, today=date(2026, 8, 26),
                                      now=self.NOW)
        self.assertEqual(abacus["free_runs"], 87)  # 6 + 27 × 3
        self.assertEqual(abacus["runs_needed"], 300)
        self.assertEqual(abacus["paid_tickets"], 213)
        self.assertEqual(abacus["koban_cost"], 63900)

    def test_mid_event_check_excludes_past_refills(self):
        # 9-05 中午再看：9-05 05:00 已过去，窗口内剩余 9 次回票
        # cap 6 + 9 × 3 = 33 张
        abacus = advisor.event_abacus(
            "江户城潜入调查", self._card(), measured=None,
            today=date(2026, 9, 5),
            now=datetime(2026, 9, 5, 12, tzinfo=advisor._TZ))
        self.assertEqual(abacus["free_runs"], 33)

    def test_precise_window_impact_uses_refill_counting(self):
        impact = advisor.window_impact("江户城潜入调查", self._card(),
                                       today=date(2026, 8, 26))
        self.assertEqual(impact["delta"], -63900)

    def test_end_refill_at_closing_instant_not_counted(self):
        # 收摊改到 17:00：9-10 05:00 回票落在窗口内（+3），
        # 9-10 17:00 收摊瞬间的回满不算
        abacus = advisor.event_abacus(
            "江户城潜入调查",
            self._card(end_at="2026-09-10T17:00:00+08:00"),
            measured=None, today=date(2026, 8, 26), now=self.NOW)
        self.assertEqual(abacus["free_runs"], 90)  # 6 + 28 × 3

    def test_start_refill_before_open_not_counted(self):
        # 窗口内没有回票点：8-27 05:00 在开场前，8-27 17:00 在收摊后
        # 只算开场 cap
        abacus = advisor.event_abacus(
            "江户城潜入调查",
            self._card(start_at="2026-08-27T11:00:00+08:00",
                       end_at="2026-08-27T16:00:00+08:00"),
            measured=None, today=date(2026, 8, 26), now=self.NOW)
        self.assertEqual(abacus["free_runs"], 6)

    def test_legacy_card_without_refill_amount_keeps_old_logic(self):
        # 无 refill_amount 的老卡维持旧 12 小时回满交集逻辑
        card = {k: v for k, v in self._card().items() if k != "refill_amount"}
        card["daily_free_tickets"] = 12
        abacus = advisor.event_abacus("江户城潜入调查", card,
                                      measured=None, today=date(2026, 8, 26),
                                      now=self.NOW)
        self.assertEqual(abacus["free_runs"], 168)
