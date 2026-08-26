"""活动周期经验档案：期次身份、规则指纹、归档幂等、取值链优先级。"""
import json
import tempfile
import unittest
from datetime import datetime, timedelta, timezone
from pathlib import Path

from touken import advisor, event_history

_TZ = timezone(timedelta(hours=8))


def _edo_card(**overrides):
    card = {"mechanics": "edocastle", "start_date": "2026-08-27",
            "end_date": "2026-09-10", "ticket_price": 300,
            "daily_free_tickets": 12, "ticket_cap": 6,
            "keys_total": 1500, "keys_per_box": 5, "boxes": 300,
            "est_keys_per_run": None, "note": ""}
    card.update(overrides)
    return card


class _Store:
    """events: [(ts, payload)] 直接喂 edocastle.run_completed。"""

    def __init__(self, events):
        self._events = events

    def recent_events(self, limit=100, event_type=None):
        if event_type == "edocastle.run_completed":
            return [{"ts": ts, "payload": p} for ts, p in self._events]
        return []


def _ts(y, m, d, hh=12):
    return datetime(y, m, d, hh, tzinfo=_TZ).timestamp()


class PeriodIdentityTests(unittest.TestCase):
    def test_period_key_uses_start_date(self):
        self.assertEqual(event_history.period_key("江户城潜入调查", _edo_card()),
                         "江户城潜入调查@2026-08-27")
        # start_at 精确时刻也能推期次
        self.assertEqual(event_history.period_key(
            "x", {"start_at": "2027-03-01T10:00:00+08:00"}), "x@2027-03-01")
        self.assertIsNone(event_history.period_key("x", {}))

    def test_rules_fingerprint_distinguishes_rule_changes(self):
        base = event_history.rules_fingerprint(_edo_card())
        same = event_history.rules_fingerprint(_edo_card(note="别的备注"))
        changed = event_history.rules_fingerprint(_edo_card(keys_total=2000))
        self.assertEqual(base, same)
        self.assertNotEqual(base, changed)


class ArchiveTests(unittest.TestCase):
    def test_append_is_idempotent_and_backs_up(self):
        with tempfile.TemporaryDirectory() as tmp:
            period = {"event": "江户城潜入调查", "start_date": "2026-08-27",
                      "mechanics": "edocastle", "runs": 286,
                      "keys_total": 1459, "keys_per_run": 5.1,
                      "rules": {}, "closed_at": 1.0}
            self.assertTrue(event_history.append_period(Path(tmp), period))
            self.assertFalse(event_history.append_period(Path(tmp), period))
            periods = event_history.load_history(Path(tmp))
            self.assertEqual(len(periods), 1)
            self.assertEqual(periods[0]["keys_per_run"], 5.1)
            # 第二次（幂等跳过）不写文件，但第一次写了就该有备份逻辑兜着——
            # 这里验证再追加另一期时旧文件有备份
            period2 = dict(period, start_date="2027-03-01")
            self.assertTrue(event_history.append_period(Path(tmp), period2))
            backup = Path(tmp) / (event_history.HISTORY_FILENAME + ".bak")
            self.assertTrue(backup.exists())

    def test_archive_only_after_event_ends(self):
        card = _edo_card()
        store = _Store([(_ts(2026, 8, 28), {"keys": 5})])
        with tempfile.TemporaryDirectory() as tmp:
            # 进行中：不归档
            self.assertIsNone(event_history.archive_if_finished(
                store, "江户城潜入调查", card, Path(tmp),
                now=datetime(2026, 9, 1, tzinfo=_TZ)))
            # 结束后：归档
            period = event_history.archive_if_finished(
                store, "江户城潜入调查", card, Path(tmp),
                now=datetime(2026, 9, 11, tzinfo=_TZ))
            self.assertIsNotNone(period)
            self.assertEqual(period["runs"], 1)
            # 再来一遍：幂等
            self.assertIsNone(event_history.archive_if_finished(
                store, "江户城潜入调查", card, Path(tmp),
                now=datetime(2026, 9, 12, tzinfo=_TZ)))
            self.assertEqual(len(event_history.load_history(Path(tmp))), 1)


class AttributionTests(unittest.TestCase):
    def test_period_marker_wins(self):
        card = _edo_card()
        store = _Store([
            (_ts(2026, 8, 28), {"keys": 5, "period": "江户城潜入调查@2026-08-27"}),
            (_ts(2025, 3, 2), {"keys": 100, "period": "江户城潜入调查@2025-03-01"}),
        ])
        m = advisor.measured_keys_per_run(store, name="江户城潜入调查", card=card)
        self.assertEqual(m["runs"], 1)
        self.assertEqual(m["per_run"], 5)

    def test_legacy_data_attributed_by_window(self):
        card = _edo_card()
        store = _Store([
            (_ts(2026, 9, 1), {"keys": 4}),    # 窗口内，没 period → 本期
            (_ts(2026, 8, 1), {"keys": 100}),  # 窗口外 → 不算
        ])
        m = advisor.measured_keys_per_run(store, name="江户城潜入调查", card=card)
        self.assertEqual(m["runs"], 1)
        self.assertEqual(m["per_run"], 4)
        self.assertEqual(m["keys_total"], 4)

    def test_no_card_keeps_legacy_behavior(self):
        store = _Store([(_ts(2026, 8, 1), {"keys": 6}),
                        (_ts(2026, 8, 2), {"keys": 8})])
        m = advisor.measured_keys_per_run(store)
        self.assertEqual(m["per_run"], 7)


class ResolveChainTests(unittest.TestCase):
    def test_measured_beats_history_beats_estimate(self):
        card = _edo_card(est_keys_per_run=3)
        history = [{"event": "江户城潜入调查", "start_date": "2025-03-01",
                    "rules": event_history.rules_fingerprint(card),
                    "runs": 286, "keys_per_run": 5.1}]
        # 只有估计 + 上期经验 → 用上期
        r = advisor.resolve_keys_per_run(_Store([]), "江户城潜入调查",
                                         card, history)
        self.assertEqual(r["source"], "history")
        self.assertEqual(r["per_run"], 5.1)
        self.assertIn("上期", r["basis"])
        # 本期实测一来，压过上期
        store = _Store([(_ts(2026, 8, 28), {"keys": 6})])
        r = advisor.resolve_keys_per_run(store, "江户城潜入调查", card, history)
        self.assertEqual(r["source"], "measured")
        self.assertEqual(r["per_run"], 6)

    def test_rule_change_invalidates_history(self):
        card = _edo_card(keys_total=2000)  # 规则变了
        history = [{"event": "江户城潜入调查", "start_date": "2025-03-01",
                    "rules": event_history.rules_fingerprint(
                        _edo_card()),  # 旧规则指纹
                    "runs": 286, "keys_per_run": 5.1}]
        r = advisor.resolve_keys_per_run(_Store([]), "江户城潜入调查",
                                         card, history)
        self.assertIsNone(r)  # 规则不同 → 不参考，老实说没数

    def test_estimate_from_other_period_not_carried(self):
        card = _edo_card(est_keys_per_run=3,
                         est_period="江户城潜入调查@2025-03-01")
        r = advisor.resolve_keys_per_run(_Store([]), "江户城潜入调查",
                                         card, [])
        self.assertIsNone(r)
        # 当期填的估计正常用
        card2 = _edo_card(est_keys_per_run=3,
                          est_period="江户城潜入调查@2026-08-27")
        r = advisor.resolve_keys_per_run(_Store([]), "江户城潜入调查",
                                         card2, [])
        self.assertEqual(r["source"], "estimate")
        self.assertEqual(r["per_run"], 3)


class AbacusResolutionTests(unittest.TestCase):
    def test_abacus_reports_basis_and_history_source(self):
        resolution = {"per_run": 5.1, "source": "history",
                      "basis": "上期打了 286 圈"}
        abacus = advisor.event_abacus("江户城潜入调查", _edo_card(),
                                      measured=resolution,
                                      today=datetime(2026, 8, 26).date())
        self.assertEqual(abacus["keys_source"], "history")
        self.assertEqual(abacus["keys_basis"], "上期打了 286 圈")
        self.assertIn("上期经验", abacus["message"])

    def test_legacy_measured_dict_still_works(self):
        # 老调用方传 {"per_run": x, "runs": n} 不带 source，按实测对待
        abacus = advisor.event_abacus("江户城潜入调查", _edo_card(),
                                      measured={"per_run": 20.0, "runs": 3},
                                      today=datetime(2026, 8, 26).date())
        self.assertEqual(abacus["keys_source"], "measured")
        self.assertEqual(abacus["runs_needed"], 75)


if __name__ == "__main__":
    unittest.main()
