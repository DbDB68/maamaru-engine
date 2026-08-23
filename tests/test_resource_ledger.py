import asyncio
import json
import tempfile
import unittest
from datetime import datetime, timedelta, timezone
from pathlib import Path
from unittest.mock import patch

from touken.telemetry import LEDGER_RESOURCES, TelemetryStore

# Asia/Shanghai 无夏令时，测试里用固定 +8 拼时间戳
SH = timezone(timedelta(hours=8))


def sh(text: str) -> float:
    return datetime.strptime(text, "%Y-%m-%d %H:%M:%S").replace(tzinfo=SH).timestamp()


class ResourceLedgerTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.store = TelemetryStore(Path(self.temp.name) / "telemetry.db")

    def tearDown(self):
        self.store.close()
        self.temp.cleanup()

    def _event(self, ts, event_type, payload, run_id="run-1", script="osaka"):
        cursor = self.store._conn().execute(
            "INSERT INTO events(ts, run_id, script, event_type, payload) "
            "VALUES (?, ?, ?, ?, ?)",
            (ts, run_id, script, event_type, json.dumps(payload, ensure_ascii=False)))
        self.store._conn().commit()
        return cursor.lastrowid

    def _captured(self, ts, resources, phase=None, run_id="run-1", script="daily"):
        return self._event(ts, "inventory.captured",
                           {"captured_at": "", "phase": phase, "resources": resources,
                            "doko": None, "furnaces": []}, run_id=run_id, script=script)

    @staticmethod
    def _res(ledger, name):
        return next(r for r in ledger["per_resource"] if r["resource"] == name)

    @staticmethod
    def _day(ledger, date, resource):
        return next((d for d in ledger["daily_series"]
                     if d["date"] == date and d["resource"] == resource), None)

    def test_koban_session_reconciles_against_captured(self):
        # 8/20 实例：captured 745056 → 挖地收场 788506（session 开工 745656）
        t0 = sh("2026-08-20 09:00:00")
        self._captured(t0, {"小判": 745056, "木炭": 5000}, phase="before", run_id="run-a")
        self._event(t0 + 600, "osaka.koban_session",
                    {"before": 745656, "after": 788506, "delta": 42850,
                     "floors": 10, "target_floor": 99}, run_id="run-b")

        ledger = self.store.resource_ledger(t0 - 60, t0 + 3600)

        koban = self._res(ledger, "小判")
        self.assertEqual(koban["total_delta"], 43450)
        self.assertEqual(koban["attributed_delta"], 42850)
        self.assertEqual(koban["unattributed_delta"], 600)
        self.assertEqual(koban["observation_count"], 3)
        self.assertEqual(koban["confidence"], "high")

    def test_negative_unattributed_is_not_clamped(self):
        # confirmed +100、净变化 +10 → 未归因 -90，负残差保留符号
        t0 = sh("2026-08-20 09:00:00")
        self._captured(t0, {"小判": 1000}, phase="before", run_id="run-a")
        self._event(t0 + 600, "osaka.koban_session",
                    {"before": 1000, "after": 1100, "delta": 100,
                     "floors": 1, "target_floor": 99}, run_id="run-b")
        self._captured(t0 + 1200, {"小判": 1010}, phase="after", run_id="run-b")

        koban = self._res(self.store.resource_ledger(t0 - 60, t0 + 1800), "小判")

        self.assertEqual(koban["total_delta"], 10)
        self.assertEqual(koban["attributed_delta"], 100)
        self.assertEqual(koban["unattributed_delta"], -90)

    def test_confirmed_attribution_survives_missing_observations(self):
        # 有 confirmed 支出但加速符零观察：total 是 None 不是 0，明细仍在
        t0 = sh("2026-08-20 09:00:00")
        self._event(t0, "repair.session_completed",
                    {"repaired": 2, "speedups": 3}, script="repair")

        ledger = self.store.resource_ledger(t0 - 60, t0 + 600)

        speedup = self._res(ledger, "加速符")
        self.assertIsNone(speedup["total_delta"])
        self.assertEqual(speedup["attributed_delta"], -3)
        self.assertIsNone(speedup["unattributed_delta"])
        self.assertEqual(speedup["confidence"], "low")
        attr = next(a for a in ledger["attributions"] if a["resource"] == "加速符")
        self.assertEqual(attr["delta"], -3)
        self.assertEqual(attr["confidence"], "confirmed")
        day = self._day(ledger, "2026-08-20", "加速符")
        self.assertIsNone(day["total_delta"])
        self.assertEqual(day["attributed_delta"], -3)

    def test_cross_midnight_run_booked_by_observation_day(self):
        # 跨日 run：收益按观察发生日记账，首日只有单点观察无法结账
        t0 = sh("2026-08-20 23:30:00")
        t1 = sh("2026-08-21 01:00:00")
        self._captured(t0, {"小判": 1000}, phase="before")
        self._captured(t1, {"小判": 1300}, phase="after")

        ledger = self.store.resource_ledger(t0 - 60, t1 + 60)

        first = self._day(ledger, "2026-08-20", "小判")
        second = self._day(ledger, "2026-08-21", "小判")
        self.assertIsNone(first["total_delta"])
        self.assertEqual(second["opening"], 1000)
        self.assertEqual(second["closing"], 1300)
        self.assertEqual(second["total_delta"], 300)
        # 窗口级仍按首末观察结总账
        self.assertEqual(self._res(ledger, "小判")["total_delta"], 300)

    def test_peek_never_touches_koban(self):
        # peek 只认顶栏五资源：即使脏 payload 带了小判也不许污染小判观察链
        t0 = sh("2026-08-20 09:00:00")
        self._captured(t0, {"小判": 1000, "木炭": 5000}, phase="before")
        self._event(t0 + 300, "inventory.peek",
                    {"tag": "raid", "木炭": 5100, "玉钢": 200, "冷却材": 300,
                     "砥石": 400, "甲州金": 50, "小判": 99999}, script="raid")
        self._captured(t0 + 600, {"小判": 1100, "木炭": 5150}, phase="after")

        ledger = self.store.resource_ledger(t0 - 60, t0 + 900)

        koban = self._res(ledger, "小判")
        self.assertEqual(koban["total_delta"], 100)
        self.assertEqual(koban["observation_count"], 2)
        charcoal = self._res(ledger, "木炭")
        self.assertEqual(charcoal["total_delta"], 150)
        self.assertEqual(charcoal["observation_count"], 3)

    def test_duplicate_closing_value_is_deduped(self):
        # koban_session.after 与紧随的 captured 同值同刻：只算一次观察、一次收益
        t0 = sh("2026-08-20 09:00:00")
        t1 = t0 + 600
        self._captured(t0, {"小判": 745056}, phase="before", run_id="run-a")
        self._event(t1, "osaka.koban_session",
                    {"before": 745656, "after": 788506, "delta": 42850,
                     "floors": 10, "target_floor": 99}, run_id="run-b")
        self._captured(t1 + 2, {"小判": 788506}, phase="after", run_id="run-b")

        ledger = self.store.resource_ledger(t0 - 60, t1 + 900)

        koban = self._res(ledger, "小判")
        self.assertEqual(koban["observation_count"], 3)
        self.assertEqual(koban["total_delta"], 43450)
        self.assertEqual(koban["attributed_delta"], 42850)
        koban_attrs = [a for a in ledger["attributions"] if a["resource"] == "小判"]
        self.assertEqual(len(koban_attrs), 1)

    def test_resource_change_before_after_feeds_observation_chain(self):
        # 2026-08-23 事故：异去补充提灯的 resource.change 带了精确 before/after，
        # 却只算归因不进观察链 → 次日日榜 opening 跳过整条补充链，
        # -8000 支出漏成次日「不知道谁干的」。修后补充链必须接住日界。
        d1 = sh("2026-08-21 10:00:00")
        d2 = sh("2026-08-22 14:00:00")
        d3 = sh("2026-08-23 06:00:00")
        self._event(d1, "osaka.koban_session",
                    {"before": 900, "after": 1000, "delta": 100,
                     "floors": 2, "target_floor": 99}, run_id="run-d1")
        self._event(d2, "resource.change",
                    {"resource": "小判", "delta": -300, "before": 1050, "after": 750,
                     "source": "yosari.ticket_refill", "attribution": "confirmed",
                     "evidence": "purchase_preview_balances", "note": "异去归城提灯补充"},
                    run_id="run-d2", script="yosari")
        self._event(d3, "osaka.koban_session",
                    {"before": 750, "after": 850, "delta": 100,
                     "floors": 2, "target_floor": 99}, run_id="run-d3")

        ledger = self.store.resource_ledger(d1 - 60, d3 + 600)

        koban = self._res(ledger, "小判")
        self.assertEqual(koban["observation_count"], 6)
        self.assertEqual(koban["total_delta"], -50)
        self.assertEqual(koban["attributed_delta"], -100)
        self.assertEqual(koban["unattributed_delta"], 50)
        # 补充当天：opening 接窗前基线 1000，closing 是补充后余额 750，
        # 未归因只剩补充前真实多出来的 +50
        day2 = self._day(ledger, "2026-08-22", "小判")
        self.assertEqual(day2["opening"], 1000)
        self.assertEqual(day2["closing"], 750)
        self.assertEqual(day2["total_delta"], -250)
        self.assertEqual(day2["attributed_delta"], -300)
        self.assertEqual(day2["unattributed_delta"], 50)
        # 次日：opening 必须接补充链末尾 750，不再用前天的旧值
        day3 = self._day(ledger, "2026-08-23", "小判")
        self.assertEqual(day3["opening"], 750)
        self.assertEqual(day3["closing"], 850)
        self.assertEqual(day3["total_delta"], 100)
        self.assertEqual(day3["unattributed_delta"], 0)
        self.assertEqual(day3["confidence"], "high")

    def test_resource_change_baseline_scans_back_for_balances(self):
        # 窗前基线：resource.change 不是每条都带 before/after（锻刀等没有），
        # 基线要向前翻找最近一条带余额的，而不是抓到无余额的就放弃
        t0 = sh("2026-08-20 09:00:00")
        self._event(t0, "resource.change",
                    {"resource": "小判", "delta": -500, "before": 1000, "after": 500,
                     "source": "yosari.ticket_refill", "attribution": "confirmed"},
                    script="yosari")
        self._event(t0 + 10, "resource.change",
                    {"resource": "木炭", "delta": -700, "source": "forge.started",
                     "attribution": "confirmed"}, script="forge")
        self._captured(t0 + 3600, {"小判": 800}, phase="after", run_id="run-b")

        koban = self._res(self.store.resource_ledger(t0 + 1800, t0 + 7200), "小判")

        self.assertEqual(koban["opening"], 500)
        self.assertEqual(koban["closing"], 800)
        self.assertEqual(koban["total_delta"], 300)

    def test_resource_change_shadows_legacy_event(self):
        # 双写兼容：resource.change 用 source_event_id 指向旧事件，旧的那份不重复聚合
        t0 = sh("2026-08-20 09:00:00")
        legacy_id = self._event(t0, "osaka.koban_session",
                                {"before": 745656, "after": 788506, "delta": 42850,
                                 "floors": 10, "target_floor": 99})
        self._event(t0 + 1, "resource.change",
                    {"resource": "小判", "delta": 42850, "before": 745656,
                     "after": 788506, "source": "osaka.koban_session",
                     "source_event_id": legacy_id, "attribution": "confirmed",
                     "evidence": "direct_before_after"})

        ledger = self.store.resource_ledger(t0 - 60, t0 + 600)

        koban_attrs = [a for a in ledger["attributions"] if a["resource"] == "小判"]
        self.assertEqual(len(koban_attrs), 1)
        self.assertEqual(koban_attrs[0]["source"], "osaka.koban_session")
        self.assertNotEqual(koban_attrs[0]["event_id"], legacy_id)
        koban = self._res(ledger, "小判")
        self.assertEqual(koban["attributed_delta"], 42850)
        self.assertEqual(koban["unattributed_delta"], 0)

    def test_large_window_is_not_capped_by_recent_events_limit(self):
        # 30 天 1440 条 peek（超过 recent_events 的 1000 上限）仍完整聚合
        base = sh("2026-07-22 00:00:00")
        rows = [(base + i * 1800, "run-x", "raid", "inventory.peek",
                 json.dumps({"tag": "raid", "木炭": 1000 + i}, ensure_ascii=False))
                for i in range(1440)]
        self.store._conn().executemany(
            "INSERT INTO events(ts, run_id, script, event_type, payload) "
            "VALUES (?, ?, ?, ?, ?)", rows)
        self.store._conn().commit()

        ledger = self.store.resource_ledger(base - 10, base + 1440 * 1800 + 10)

        charcoal = self._res(ledger, "木炭")
        self.assertEqual(charcoal["observation_count"], 1440)
        self.assertEqual(charcoal["total_delta"], 1439)
        self.assertEqual(ledger["window"]["days"], 30.0)

    def test_shanghai_day_boundary(self):
        # UTC 16:00 = 上海次日 00:00：分桶按上海日期，不按 UTC
        t1 = datetime(2026, 8, 20, 15, 30, tzinfo=timezone.utc).timestamp()
        t2 = datetime(2026, 8, 20, 16, 30, tzinfo=timezone.utc).timestamp()
        self._captured(t1, {"小判": 100}, phase="before")
        self._captured(t2, {"小判": 200}, phase="after")

        ledger = self.store.resource_ledger(t1 - 60, t2 + 60)

        self.assertEqual(ledger["window"]["timezone"], "Asia/Shanghai")
        first = self._day(ledger, "2026-08-20", "小判")
        second = self._day(ledger, "2026-08-21", "小判")
        self.assertEqual(first["observation_count"], 1)
        self.assertIsNone(first["total_delta"])
        self.assertEqual(second["total_delta"], 100)

    def test_human_report_lowers_confidence_without_rewriting_inventory(self):
        # 人工报备只降置信度，库存数值照旧
        t0 = sh("2026-08-20 09:00:00")
        self._captured(t0, {"小判": 1000}, phase="before")
        self._captured(t0 + 3600, {"小判": 1200}, phase="after")

        before_report = self.store.resource_ledger(t0 - 60, t0 + 7200)
        self.assertEqual(self._res(before_report, "小判")["confidence"], "medium")

        report = self.store.add_human_report(
            occurred_at=t0 + 1800, activities=["领邮箱", "手动打了一轮"])
        after_report = self.store.resource_ledger(t0 - 60, t0 + 7200)

        koban = self._res(after_report, "小判")
        self.assertEqual(koban["total_delta"], 200)
        self.assertEqual(koban["confidence"], "low")
        gap = next(g for g in after_report["gaps"] if g["reason"] == "human_reported")
        self.assertEqual(gap["human_report_ids"], [report["id"]])

    def test_cross_run_gap_links_human_report(self):
        # 跨 run 快照差值 = no_observation 缺口；报备按时间/gap_key 挂上，不改数值
        t0 = sh("2026-08-20 09:00:00")
        self._captured(t0, {"小判": 1000, "木炭": 500}, phase="after", run_id="run-a")
        self._captured(t0 + 3600, {"小判": 1200, "木炭": 480},
                       phase="before", run_id="run-b")

        ledger = self.store.resource_ledger(t0 - 60, t0 + 7200)
        gap = next(g for g in ledger["gaps"] if g["reason"] == "no_observation")
        self.assertEqual(gap["resources"], {"小判": 200, "木炭": -20})
        self.assertEqual(gap["human_report_ids"], [])

        report = self.store.add_human_report(
            occurred_at=t0 + 1800, activities=["领了任务奖励"])
        ledger = self.store.resource_ledger(t0 - 60, t0 + 7200)
        gap = next(g for g in ledger["gaps"] if g["reason"] == "no_observation")
        self.assertEqual(gap["human_report_ids"], [report["id"]])
        self.assertEqual(self._res(ledger, "小判")["total_delta"], 200)
        self.assertEqual(self._res(ledger, "小判")["confidence"], "low")

    def test_window_baseline_comes_from_before_window(self):
        # 窗前最近一次观察当 opening 基线：窗口内没有首观察也能结账
        t0 = sh("2026-08-19 09:00:00")
        t1 = sh("2026-08-20 09:00:00")
        self._captured(t0, {"小判": 900}, phase="after", run_id="run-a")
        self._captured(t1, {"小判": 950}, phase="after", run_id="run-b")

        ledger = self.store.resource_ledger(t1 - 3600, t1 + 600)

        koban = self._res(ledger, "小判")
        self.assertEqual(koban["opening"], 900)
        self.assertEqual(koban["closing"], 950)
        self.assertEqual(koban["total_delta"], 50)

    def test_api_endpoint_aggregates_server_side(self):
        from panel.server import api_data_resource_ledger

        t0 = sh("2026-08-20 09:00:00")
        self._captured(t0, {"小判": 1000}, phase="before")
        self._captured(t0 + 600, {"小判": 1100}, phase="after")

        with patch("touken.telemetry._store", self.store):
            by_from_to = asyncio.run(
                api_data_resource_ledger(days=7, from_ts=t0 - 60, to=t0 + 900))
            by_days = asyncio.run(api_data_resource_ledger(days=7, from_ts=None, to=None))

        self.assertEqual(by_from_to["schema_version"], 1)
        self.assertEqual(by_from_to["window"]["from"], t0 - 60)
        self.assertEqual(by_from_to["window"]["to"], t0 + 900)
        self.assertEqual([r["resource"] for r in by_from_to["per_resource"]],
                         list(LEDGER_RESOURCES))
        self.assertEqual(self._res(by_from_to, "小判")["total_delta"], 100)
        # days 分支：窗口 7 天、八资源齐全（空窗期也返回完整结构）
        self.assertEqual(by_days["window"]["days"], 7.0)
        self.assertEqual(len(by_days["per_resource"]), 8)


if __name__ == "__main__":
    unittest.main()
