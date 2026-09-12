# -*- coding: utf-8 -*-
"""每圈出阵事实记录（sortie.loop_started / completed / interrupted /
retreated_before_boss 的扩展 payload）与旧数据兼容的测试。

帧驱动假 MAA：screenshot(force=True) 推进一帧，帧是画面标记集合
（"formation" 阵形页、"result" 战斗结算页、"march" 行军按钮、
"home" 本丸、"march_stop" 自动行军停止横幅、"drop" 掉刀获得画面）。
"""

import os
import tempfile
import time
import unittest
from pathlib import Path
from unittest.mock import patch

from touken.flows.sortie import SortieMixin
from touken.maa_adapter import Point
from touken.telemetry import TelemetryStore


class _FrameMaa:
    def __init__(self, frames):
        self.frames = list(frames)
        self.frame = set()

    def screenshot(self, force=False):
        if force and self.frames:
            self.frame = set(self.frames.pop(0))
        return None

    def template_match(self, template, roi=None, threshold=0.7):
        if template == "home.png" and "home" in self.frame:
            return Point(1, 1)
        if template == "battle/ui战斗结果.png" and "result" in self.frame:
            return Point(640, 100)
        return None

    def ocr(self, expected, roi=None, match_mode="contains"):
        if expected == "自动行军停止" and "march_stop" in self.frame:
            return Point(1, 1)
        return None

    def ocr_all(self, roi, image=None):
        return []

    def click(self, point):
        return True


class _LoopHost(SortieMixin):
    """能把 _map_sortie_stream 开进行军监控主循环的最小宿主。"""

    def __init__(self, frames, *, drop_id=None, injuries=()):
        self.config = {
            "sortie": {
                "decide_button": {"template": "decide.png"},
                "home_ui": {"template": "home.png"},
                "skip_tap": [5, 5],
                "march_stop_ocr": {"expected": "自动行军停止",
                                   "roi": [0, 0, 100, 50]},
            },
            "map_select": {"合战场": {"chapters": {"1": [10, 10]},
                                      "maps": {"1": [20, 20]}}},
            "team_select": {"teams": {"3": [30, 30]}},
        }
        self.current_location = "出阵"
        self.maa = _FrameMaa(frames)
        self.events = []
        self._drop_id = drop_id
        self._injuries = list(injuries)

    def record_event(self, event_type, **payload):
        self.events.append({"ts": time.time(), "event_type": event_type,
                            "payload": dict(payload)})

    def navigate_to_stream(self, dest):
        self.current_location = dest
        yield f"nav→{dest}"

    def _click_point(self, pt):
        pass

    def _wait_for_team_select(self, cfg, attempts=12, open_after=2):
        return True

    def _pick_team(self, team_no):
        pass

    def _team_injury_status(self, cfg):
        return self._injuries.pop(0) if self._injuries else None

    def _injury_reaches_threshold(self, injury, threshold):
        return True

    def _enable_auto_march(self):
        return True

    def _click_depart(self, cfg):
        return True

    def _cancel_equip_warning(self, cfg):
        return None

    def _deny_heavy_injury_warning(self, cfg):
        return False

    def _formation_mode_state(self, allow_auto_without_title=False):
        return "manual" if "formation" in self.maa.frame else None

    def choose_formation(self, formation_name="鱼鳞阵", enable_auto=False):
        return "fixed"

    def _find_march_continue(self, cfg):
        return Point(1100, 600) if "march" in self.maa.frame else None

    def _read_drop_sword(self):
        if self._drop_id is not None and "drop" in self.maa.frame:
            return {"sword_id": self._drop_id,
                    "name": "厚藤四郎", "name_jp": "厚藤四郎"}
        return None

    def _return_home_from_march(self, cfg):
        return True

    def by_type(self, event_type):
        return [e for e in self.events if e["event_type"] == event_type]


def _run(host, **kwargs):
    kwargs.setdefault("auto_equip", False)
    with patch("touken.flows.sortie.time.sleep"), \
         patch("touken.flows.sortie.find_deploy_button",
               return_value=Point(1, 1)):
        return list(host.sortie_stream(chapter=1, map_no=1, team_no=3,
                                       **kwargs))


# 每圈出发前固定消耗 3 帧：章节页确认、重伤检查、出阵后确认
PRE = [{}, {}, {}]


class LoopFactTests(unittest.TestCase):
    def test_two_loops_first_loop_has_duration_and_battles(self):
        frames = (PRE
                  + [{"formation"}, {"formation"}, {},
                     {"result", "march"}, {},
                     {"formation"}, {},
                     {"result", "march"}, {"home"}]
                  + PRE
                  + [{"result", "march"}, {}, {"home"}])
        host = _LoopHost(frames)
        _run(host, auto_march=False, max_loops=2)

        started = host.by_type("sortie.loop_started")
        completed = host.by_type("sortie.completed")
        self.assertEqual([e["payload"]["sequence"] for e in started], [1, 2])
        self.assertEqual([e["payload"]["sequence"] for e in completed], [1, 2])
        for event in started:
            self.assertEqual(event["payload"]["march_mode"], "script")
            self.assertEqual(event["payload"]["attempt"], 1)
        self.assertEqual([e["payload"]["battle_count"] for e in completed],
                         [2, 1])
        for begin, end in zip(started, completed):
            payload = end["payload"]
            self.assertEqual(payload["outcome"], "completed")
            self.assertEqual(payload["mode"], "sortie")
            self.assertEqual(payload["map_no"], 1)
            self.assertEqual(payload["team_no"], 3)
            self.assertEqual(payload["drop_observation"], "confirmed_none")
            self.assertEqual(payload["drops_recognized"], 0)
            # duration 就是「出发 → 回本」的纯游戏流程耗时，第一圈也有
            self.assertIsNotNone(payload["duration_seconds"])
            self.assertGreaterEqual(payload["duration_seconds"], 0)
            self.assertAlmostEqual(payload["duration_seconds"],
                                   end["ts"] - begin["ts"], delta=1.0)

    def test_retreat_before_boss_records_own_outcome(self):
        frames = PRE + [{"result", "march"}, {"march"}]
        host = _LoopHost(frames)
        with patch("touken.flows.sortie.CV2_AVAILABLE", True), \
             patch("touken.flows.sortie.boss_distance_from_image",
                   side_effect=[2, 1]):
            _run(host, auto_march=True, max_loops=1, retreat_before_boss=True)

        retreated = host.by_type("sortie.retreated_before_boss")
        self.assertEqual(len(retreated), 1)
        payload = retreated[0]["payload"]
        self.assertEqual(payload["outcome"], "retreated_before_boss")
        self.assertEqual(payload["battle_count"], 1)
        self.assertEqual(payload["drop_observation"], "confirmed_none")
        self.assertIsNotNone(payload["duration_seconds"])
        self.assertEqual(host.by_type("sortie.completed"), [])

    def test_interruption_then_retry_same_sequence(self):
        frames = (PRE
                  + [{"result"}, {"march_stop"}]
                  + PRE
                  + [{"result"}, {}, {"home"}])
        host = _LoopHost(frames, injuries=[None, "中伤", None])
        _run(host, auto_march=True, max_loops=1)

        types = [e["event_type"] for e in host.events]
        self.assertEqual(types, ["sortie.loop_started", "sortie.interrupted",
                                 "sortie.loop_started", "sortie.completed"])
        interrupted = host.by_type("sortie.interrupted")[0]["payload"]
        self.assertEqual(interrupted["outcome"], "interrupted")
        self.assertEqual(interrupted["interrupt_reason"], "auto_march_stopped")
        self.assertEqual(interrupted["battle_count"], 1)
        self.assertEqual(interrupted["attempt"], 1)
        # 委托自动行军：游戏跳过获得动画，掉落只能记「没观察到」
        self.assertEqual(interrupted["drop_observation"], "not_observed")
        self.assertEqual(interrupted["drop_observation_reason"],
                         "auto_march_skips_obtain_animation")
        completed = host.by_type("sortie.completed")[0]["payload"]
        self.assertEqual(completed["sequence"], 1)
        self.assertEqual(completed["attempt"], 2)
        self.assertEqual(completed["battle_count"], 1)
        self.assertEqual(completed["drop_observation"], "not_observed")

    def test_drop_recognized_and_deduped(self):
        frames = (PRE
                  + [{"drop"}, {"drop"}, {"result", "march"}, {}, {"home"}])
        host = _LoopHost(frames, drop_id=130)
        _run(host, auto_march=False, max_loops=1)

        obtained = host.by_type("sword.obtained")
        self.assertEqual(len(obtained), 1)  # 获得画面连帧只记一次
        self.assertEqual(obtained[0]["payload"]["sword_id"], 130)
        self.assertEqual(obtained[0]["payload"]["source"], "sortie.drop")
        self.assertEqual(obtained[0]["payload"]["sequence"], 1)
        completed = host.by_type("sortie.completed")[0]["payload"]
        self.assertEqual(completed["drop_observation"], "recognized")
        self.assertEqual(completed["drops_recognized"], 1)

    def test_result_page_repeated_frames_count_once(self):
        frames = (PRE
                  + [{"result"}, {"result"}, {"result"}, {},
                     {"result"}, {"result"}, {"home"}])
        host = _LoopHost(frames)
        _run(host, auto_march=False, max_loops=1)
        payload = host.by_type("sortie.completed")[0]["payload"]
        self.assertEqual(payload["battle_count"], 2)

    def test_completed_loop_without_any_result_page_is_unknown_not_zero(self):
        # 正常完成必有王点结算页；0 场只可能是锚点失明，不许拿 0 交账
        frames = PRE + [{}, {"home"}]
        host = _LoopHost(frames)
        _run(host, auto_march=False, max_loops=1)
        payload = host.by_type("sortie.completed")[0]["payload"]
        self.assertIsNone(payload["battle_count"])
        self.assertIn("battle_count_note", payload)

    def test_monitor_timeout_records_unknown_not_task_status(self):
        frames = PRE + [{}]  # 帧耗尽后停在空画面，300 拍后触发安全上限
        host = _LoopHost(frames)
        logs = _run(host, auto_march=False, max_loops=1)
        self.assertTrue(any("安全上限" in msg for msg in logs))
        interrupted = host.by_type("sortie.interrupted")
        self.assertEqual(len(interrupted), 1)
        payload = interrupted[0]["payload"]
        self.assertEqual(payload["outcome"], "unknown")
        self.assertEqual(payload["interrupt_reason"], "monitor_timeout")
        self.assertEqual(payload["drop_observation"], "not_observed")
        self.assertEqual(payload["drop_observation_reason"],
                         "observation_lost")


class OldDataCompatTests(unittest.TestCase):
    """旧版 telemetry 事件（没有新字段）必须照常聚合，新字段不顶坏老读者。"""

    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.store = TelemetryStore(Path(self.tmp.name) / "telemetry.db")
        self.env = patch.dict(os.environ, {"MAAMARU_RUN_ID": "run-1",
                                           "MAAMARU_SCRIPT": "sortie"})
        self.env.start()
        self.store.start_run("run-1", "sortie", started_at=time.time() - 600)

    def tearDown(self):
        self.env.stop()
        self.store.close()
        self.tmp.cleanup()

    def test_old_style_events_still_drive_run_summary(self):
        # 旧 payload 只有 mode/chapter/map_no/team_no/sequence
        self.store.record_event("sortie.completed",
                                {"mode": "sortie", "chapter": 5, "map_no": 4,
                                 "team_no": 3, "sequence": 1})
        time.sleep(0.01)
        self.store.record_event("sortie.completed",
                                {"mode": "sortie", "chapter": 5, "map_no": 4,
                                 "team_no": 3, "sequence": 2})
        self.store.finish_run("run-1", "completed")
        summary = self.store.run_summary("run-1")
        self.assertEqual(summary["loops"], 2)
        self.assertIsNotNone(summary["average_loop_seconds"])

    def test_new_fields_do_not_break_loop_aggregation(self):
        self.store.record_event("sortie.loop_started",
                                {"mode": "yosari", "sequence": 1})
        self.store.record_event(
            "sortie.completed",
            {"mode": "yosari", "chapter": 1, "map_no": 2, "team_no": 3,
             "sequence": 1, "attempt": 1, "outcome": "completed",
             "duration_seconds": 301.5, "march_mode": "delegated",
             "battle_count": 4, "battle_count_basis": "battle_result_page_edges",
             "drop_observation": "not_observed", "drops_recognized": 0})
        # 中断不算完成圈，不进圈速分母
        self.store.record_event(
            "sortie.interrupted",
            {"mode": "yosari", "chapter": 1, "map_no": 2, "team_no": 3,
             "sequence": 2, "attempt": 1, "outcome": "interrupted",
             "interrupt_reason": "auto_march_stopped",
             "duration_seconds": 122.0, "march_mode": "delegated",
             "battle_count": 2, "drop_observation": "not_observed",
             "drops_recognized": 0})
        self.store.finish_run("run-1", "completed")
        summary = self.store.run_summary("run-1")
        self.assertEqual(summary["loops"], 1)

    def test_drop_links_to_loop_by_run_and_sequence(self):
        self.store.record_event(
            "sortie.completed",
            {"mode": "sortie", "chapter": 5, "map_no": 4, "team_no": 3,
             "sequence": 1, "outcome": "completed",
             "drop_observation": "recognized", "drops_recognized": 1})
        self.store.record_event("sword.obtained",
                                {"sword_id": 130, "name": "厚藤四郎",
                                 "source": "sortie.drop", "chapter": 5,
                                 "map_no": 4, "sequence": 1})
        events = self.store.recent_events(limit=10)
        obtained = next(e for e in events
                        if e["event_type"] == "sword.obtained")
        completed = next(e for e in events
                         if e["event_type"] == "sortie.completed")
        self.assertEqual(obtained["run_id"], "run-1")
        self.assertEqual(obtained["run_id"], completed["run_id"])
        self.assertEqual(obtained["payload"]["sequence"],
                         completed["payload"]["sequence"])


if __name__ == "__main__":
    unittest.main()
