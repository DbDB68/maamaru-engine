# -*- coding: utf-8 -*-
"""远征建议引擎（panel/expedition_advisor.py）测试。

建议只投排班投影里已有的班：采纳 = 记 forced，绝不自动执行。
全部依赖注入：maps / planning / 偏好 / 近况文件都用临时件，不碰真实数据。
"""

import json
import tempfile
import time
import unittest
from pathlib import Path
from unittest.mock import patch

from fastapi.testclient import TestClient

from panel import day_timeline, scheduler
from panel import expedition_advisor as ea
from panel import expedition_choices as ec
from panel import server


# 假图数据：时薪都是 120/小时，靠 total_level / 资源种类区分
_MAPS = {
    "A1": {"era": 1, "slot": 1, "name": "练习场", "duration_min": 30,
           "木炭": 60, "玉钢": 0, "冷却材": 0, "砥石": 0, "小判": 0,
           "level_req": 5, "rules": {"total_level": 10}},
    "A2": {"era": 1, "slot": 2, "name": "矿山", "duration_min": 60,
           "木炭": 0, "玉钢": 120, "冷却材": 0, "砥石": 0, "小判": 0,
           "level_req": 50, "rules": {"total_level": 200}},
    "B1": {"era": 2, "slot": 1, "name": "湖底", "duration_min": 90,
           "木炭": 0, "玉钢": 0, "冷却材": 0, "砥石": 180, "小判": 90,
           "level_req": 10, "rules": {"total_level": 20}},
    "D4": {"era": 4, "slot": 4, "name": "大坂", "duration_min": 240,
           "木炭": 0, "玉钢": 0, "冷却材": 0, "砥石": 0, "小判": 400,
           "level_req": 30, "rules": {"total_level": 100}},
}


def _planning(*, limiting=("砥石",), capacity=3, koban_available=1000,
              goals=(), events=()):
    return {
        "resource_watch": {
            "resources": [
                {"resource": "木炭", "forge_capacity": capacity + 5},
                {"resource": "玉钢", "forge_capacity": capacity + 2},
                {"resource": "冷却材", "forge_capacity": capacity + 8},
                {"resource": "砥石", "forge_capacity": capacity},
                {"resource": "委托符", "forge_capacity": 12},
            ],
            "forge_capacity": capacity,
            "limiting": list(limiting),
        },
        "koban_watch": {"available": koban_available},
        "goals": list(goals),
        "events": list(events),
    }


def _slot(key, team, map_code, time_min, *, toggleable=True, will_run=False,
          duration=90):
    return {"key": key, "team_no": team, "map_code": map_code,
            "time_min": time_min, "duration_min": duration,
            "toggleable": toggleable, "will_run": will_run,
            "planned_at": float(time_min)}


def _timeline(*slots):
    return {"expeditions": list(slots)}


def _prefs(teams_out=2, available_teams=(1, 4)):
    return {"version": 1, "teams_out": teams_out,
            "available_teams": list(available_teams)}


def _write_situation(folder, parties):
    path = Path(folder) / "situation.json"
    path.write_text(json.dumps({"schema": 1, "parties": parties},
                               ensure_ascii=False), encoding="utf-8")
    return path


class ShortageOrderTests(unittest.TestCase):
    def test_limiting_drives_order_then_capacity_fill(self):
        order = ea.shortage_order(_planning(limiting=("砥石", "玉钢")), 3)
        self.assertEqual(order[0], ("砥石", "limiting"))
        self.assertEqual(order[1], ("玉钢", "limiting"))
        # 第三名按锻刀余量从少到多补：capacity+2 的玉钢已上榜，下一个是木炭
        self.assertEqual(order[2], ("木炭", "fill"))

    def test_koban_appended_when_short(self):
        planning = _planning(limiting=("砥石",), koban_available=-50)
        order = ea.shortage_order(planning, 2)
        self.assertEqual(order[1], ("小判", "koban"))

    def test_koban_goal_counts_as_short(self):
        planning = _planning(limiting=("砥石",),
                             goals=[{"resource": "小判", "status": "active"}])
        self.assertEqual(ea.shortage_order(planning, 2)[1], ("小判", "koban"))

    def test_all_four_tied_is_not_a_crisis(self):
        """四资源齐平不算「最缺」，走 fill 口吻按余量兜底。"""
        planning = _planning(limiting=("木炭", "玉钢", "冷却材", "砥石"),
                             capacity=400)
        order = ea.shortage_order(planning, 2)
        self.assertTrue(all(tag == "fill" for _, tag in order))
        self.assertEqual(order[0], ("砥石", "fill"))  # capacity 400 最少

    def test_pad_to_n_with_koban(self):
        order = ea.shortage_order(_planning(limiting=("砥石",)), 6)
        self.assertEqual(len(order), 6)
        self.assertEqual(order[-1], ("小判", "fill"))


class SuggestionBuildTests(unittest.TestCase):
    def test_n_teams_get_n_suggestions_in_team_order(self):
        timeline = _timeline(
            _slot("k1", 4, "B1", 600),
            _slot("k2", 1, "A1", 700, duration=30),
        )
        out = ea.build_expedition_suggestions(
            timeline, _prefs(teams_out=2, available_teams=(4, 1)),
            planning=_planning(limiting=("砥石", "玉钢")), maps=_MAPS,
            situation_path=Path("/nonexistent"))
        self.assertEqual(len(out["suggestions"]), 2)
        first, second = out["suggestions"]
        # 队号序：部队一先挑缺口第一（砥石），部队四拿缺口第二（玉钢）
        self.assertEqual((first["team_no"], first["resource"]), (1, "砥石"))
        self.assertEqual((second["team_no"], second["resource"]), (4, "玉钢"))
        self.assertEqual(first["map_code"], "A1")
        self.assertEqual(first["start_min"], 700)
        self.assertEqual(first["duration_min"], 30)
        self.assertIsNone(out["note"])

    def test_best_map_for_shortage_picked_among_team_slots(self):
        """同一队有多班时挑最对口资源的，不是最早那班。"""
        timeline = _timeline(
            _slot("k1", 4, "A1", 600),   # 木炭 120/h
            _slot("k2", 4, "B1", 900),   # 砥石 120/h ← 缺口对口
        )
        out = ea.build_expedition_suggestions(
            timeline, _prefs(teams_out=1), planning=_planning(), maps=_MAPS,
            situation_path=Path("/nonexistent"))
        self.assertEqual(out["suggestions"][0]["map_code"], "B1")
        self.assertEqual(out["suggestions"][0]["start_min"], 900)
        self.assertIn("时薪第一", out["suggestions"][0]["reason"])

    def test_rank_one_reason_when_globally_best(self):
        timeline = _timeline(_slot("k1", 4, "B1", 600))
        out = ea.build_expedition_suggestions(
            timeline, _prefs(teams_out=1), planning=_planning(), maps=_MAPS,
            situation_path=Path("/nonexistent"))
        self.assertIn("砥石", out["suggestions"][0]["reason"])
        self.assertIn("时薪第一", out["suggestions"][0]["reason"])

    def test_zero_yield_slot_still_suggested_with_honest_reason(self):
        timeline = _timeline(_slot("k1", 1, "A2", 600))  # A2 只产玉钢
        out = ea.build_expedition_suggestions(
            timeline, _prefs(teams_out=1), planning=_planning(), maps=_MAPS,
            situation_path=Path("/nonexistent"))
        suggestion = out["suggestions"][0]
        self.assertEqual(suggestion["map_code"], "A2")
        self.assertIn("不产砥石", suggestion["reason"])

    def test_running_or_untoggleable_slots_not_suggested(self):
        timeline = _timeline(
            _slot("k1", 4, "B1", 600, will_run=True),
            _slot("k2", 4, "B1", 900, toggleable=False),
        )
        out = ea.build_expedition_suggestions(
            timeline, _prefs(teams_out=1), planning=_planning(), maps=_MAPS,
            situation_path=Path("/nonexistent"))
        self.assertEqual(out["suggestions"], [])
        self.assertIn("没有能点的班", out["note"])

    def test_available_team_without_slots_counts_against_quota(self):
        timeline = _timeline(_slot("k1", 1, "A1", 600))
        out = ea.build_expedition_suggestions(
            timeline, _prefs(teams_out=2, available_teams=(1, 4)),
            planning=_planning(), maps=_MAPS,
            situation_path=Path("/nonexistent"))
        self.assertEqual(len(out["suggestions"]), 1)
        self.assertIn("想丢 2 队", out["note"])

    def test_level_gate_filters_high_maps(self):
        """队伍等级和不够 total_level 的图被滤掉，挑剩下的。"""
        with tempfile.TemporaryDirectory() as folder:
            path = _write_situation(folder, [
                {"party_no": 1, "members": [{"level": 6}, {"level": 4}]},
            ])
            timeline = _timeline(
                _slot("k1", 1, "A2", 600),  # total_level 200，滤掉
                _slot("k2", 1, "A1", 700),  # total_level 10，过
            )
            out = ea.build_expedition_suggestions(
                timeline, _prefs(teams_out=1), planning=_planning(),
                maps=_MAPS, situation_path=path)
            self.assertEqual(out["suggestions"][0]["map_code"], "A1")
            self.assertNotIn("等级没核", out["suggestions"][0]["reason"])

    def test_all_slots_level_blocked_gives_no_suggestion(self):
        with tempfile.TemporaryDirectory() as folder:
            path = _write_situation(folder, [
                {"party_no": 4, "members": [{"level": 1}]},
            ])
            timeline = _timeline(_slot("k1", 4, "B1", 600))
            out = ea.build_expedition_suggestions(
                timeline, _prefs(teams_out=1), planning=_planning(),
                maps=_MAPS, situation_path=path)
            self.assertEqual(out["suggestions"], [])
            self.assertIn("没有能点的班", out["note"])

    def test_no_situation_annotates_reason(self):
        timeline = _timeline(_slot("k1", 4, "B1", 600))
        out = ea.build_expedition_suggestions(
            timeline, _prefs(teams_out=1), planning=_planning(), maps=_MAPS,
            situation_path=Path("/nonexistent"))
        self.assertIn("等级没核", out["suggestions"][0]["reason"])

    def test_no_planning_gives_empty_advice_with_note(self):
        timeline = _timeline(_slot("k1", 4, "B1", 600))
        out = ea.build_expedition_suggestions(
            timeline, _prefs(teams_out=1), planning=None, maps=_MAPS,
            situation_path=Path("/nonexistent"))
        self.assertEqual(out["suggestions"], [])
        self.assertIn("盘点", out["note"])

    def test_empty_resource_watch_is_no_data(self):
        timeline = _timeline(_slot("k1", 4, "B1", 600))
        planning = {"resource_watch": {"forge_capacity": None,
                                       "limiting": []}}
        out = ea.build_expedition_suggestions(
            timeline, _prefs(teams_out=1), planning=planning, maps=_MAPS,
            situation_path=Path("/nonexistent"))
        self.assertEqual(out["suggestions"], [])
        self.assertIsNotNone(out["note"])

    def test_teams_out_zero_means_no_advice(self):
        timeline = _timeline(_slot("k1", 4, "B1", 600))
        out = ea.build_expedition_suggestions(
            timeline, _prefs(teams_out=0), planning=_planning(), maps=_MAPS,
            situation_path=Path("/nonexistent"))
        self.assertEqual(out["suggestions"], [])
        self.assertIsNone(out["note"])


class PrefsStorageTests(unittest.TestCase):
    def setUp(self):
        self.folder = tempfile.TemporaryDirectory()
        self.addCleanup(self.folder.cleanup)
        self.path = Path(self.folder.name) / "prefs.json"

    def test_missing_file_gives_defaults(self):
        prefs = ea.load_prefs(self.path)
        self.assertEqual(prefs["teams_out"], 1)
        self.assertEqual(prefs["available_teams"], [1, 4, 5])

    def test_broken_file_gives_defaults(self):
        self.path.write_text("{not json", encoding="utf-8")
        prefs = ea.load_prefs(self.path)
        self.assertEqual(prefs["available_teams"], [1, 4, 5])

    def test_wrong_version_gives_defaults(self):
        self.path.write_text(json.dumps({"version": 2, "teams_out": 3}),
                             encoding="utf-8")
        self.assertEqual(ea.load_prefs(self.path)["teams_out"], 1)

    def test_partial_keys_fall_back(self):
        self.path.write_text(json.dumps({"version": 1, "teams_out": 4}),
                             encoding="utf-8")
        prefs = ea.load_prefs(self.path)
        self.assertEqual(prefs["teams_out"], 4)
        self.assertEqual(prefs["available_teams"], [1, 4, 5])

    def test_bad_values_normalized_not_fatal(self):
        self.path.write_text(json.dumps(
            {"version": 1, "teams_out": 99, "available_teams": [1, 9, "x"]}),
            encoding="utf-8")
        prefs = ea.load_prefs(self.path)
        self.assertEqual(prefs["teams_out"], 5)
        self.assertEqual(prefs["available_teams"], [1])

    def test_save_roundtrip_and_backup(self):
        prefs = ea.save_prefs(teams_out=2, available_teams=[4, 1, 4],
                              path=self.path)
        self.assertEqual(prefs["teams_out"], 2)
        self.assertEqual(prefs["available_teams"], [1, 4])
        self.assertEqual(ea.load_prefs(self.path)["available_teams"], [1, 4])
        again = ea.save_prefs(teams_out=3, available_teams=[5], path=self.path)
        self.assertEqual(again["available_teams"], [5])
        backup = json.loads(self.path.with_suffix(".json.bak")
                            .read_text(encoding="utf-8"))
        self.assertEqual(backup["teams_out"], 2)

    def test_save_validation(self):
        for bad in (6, -1, "3", True, 1.5):
            with self.assertRaises(ValueError, msg=repr(bad)):
                ea.save_prefs(teams_out=bad, available_teams=[1],
                              path=self.path)
        for bad in ([0], [6], ["1"], [True], "14"):
            with self.assertRaises(ValueError, msg=repr(bad)):
                ea.save_prefs(teams_out=1, available_teams=bad,
                              path=self.path)
        self.assertFalse(self.path.exists())


class TimelineIntegrationTests(unittest.TestCase):
    """build_day_timeline 注入偏好/账本/近况，吐出建议淡影字段。"""

    def setUp(self):
        day_timeline._planning_cache.clear()  # 别家的测试可能预填了真账本缓存
        self.addCleanup(day_timeline._planning_cache.clear)
        patcher = patch.object(scheduler, "map_options", lambda: [
            {"code": "A1", "duration_min": 30},
            {"code": "B1", "duration_min": 90},
        ])
        patcher.start()
        self.addCleanup(patcher.stop)

    def _build(self, now, cfg, **kwargs):
        kwargs.setdefault("store", object())
        kwargs.setdefault("script_labels", {})
        return day_timeline.build_day_timeline(now, cfg=cfg, **kwargs)

    def test_timeline_carries_help_and_suggestions(self):
        now = time.mktime(time.strptime(
            f"{time.strftime('%Y-%m-%d')} 06:00:00", "%Y-%m-%d %H:%M:%S"))
        cfg = {"entries": [{"time": "10:00", "team_no": 4, "map_code": "B1",
                            "enabled": True}],
               "automation": {"enabled": False, "mode": "custom",
                              "preset": "小判", "teams": [2, 3, 4],
                              "start_time": "08:00"}}
        out = self._build(now, cfg,
                          expedition_help=_prefs(teams_out=1,
                                                 available_teams=(4,)),
                          planning=_planning(),
                          situation_path=Path("/nonexistent"))
        self.assertEqual(out["expedition_help"]["teams_out"], 1)
        self.assertEqual(out["expedition_help"]["available_teams"], [4])
        self.assertEqual(len(out["expedition_suggestions"]), 1)
        suggestion = out["expedition_suggestions"][0]
        self.assertEqual(suggestion["kind"], "expedition")
        self.assertEqual(suggestion["team_no"], 4)
        self.assertEqual(suggestion["map_code"], "B1")
        self.assertEqual(suggestion["start_min"], 600)
        self.assertEqual(suggestion["resource"], "砥石")
        self.assertTrue(suggestion["reason"])

    def test_timeline_note_when_no_planning(self):
        now = time.mktime(time.strptime(
            f"{time.strftime('%Y-%m-%d')} 06:00:00", "%Y-%m-%d %H:%M:%S"))
        cfg = {"entries": [], "automation": {"enabled": False,
                                             "mode": "custom"}}
        out = self._build(now, cfg, expedition_help=_prefs(teams_out=1),
                          planning=None, situation_path=Path("/nonexistent"))
        self.assertEqual(out["expedition_suggestions"], [])
        self.assertIn("盘点", out["expedition_advice_note"])


class AdoptEndpointTests(unittest.TestCase):
    """PUT /api/day-timeline/expedition-adopt：采纳 = forced 落账。"""

    def setUp(self):
        self.folder = tempfile.TemporaryDirectory()
        self.addCleanup(self.folder.cleanup)
        self.path = Path(self.folder.name) / "choices.json"
        self.slot = {"key": "today:custom:0:10:00", "team_no": 4,
                     "map_code": "B1", "planned_at": 1759094400.0,
                     "time_min": 600, "duration_min": 90,
                     "toggleable": True, "base_enabled": False,
                     "entry_enabled": True}
        self.suggestion = {"kind": "expedition", "key": self.slot["key"],
                           "team_no": 4, "map_code": "B1", "resource": "砥石",
                           "duration_min": 90, "start_min": 600,
                           "reason": "砥石最缺"}
        self.timeline = {"expeditions": [self.slot],
                         "expedition_suggestions": [self.suggestion],
                         "expedition_help": {"teams_out": 1,
                                             "available_teams": [4]}}

    def _put(self, payload):
        real = ec.set_slot_intention

        def to_temp(**kwargs):
            kwargs["path"] = self.path
            return real(**kwargs)

        with patch.object(server, "_day_timeline_payload",
                          return_value=self.timeline), \
             patch.object(ec, "set_slot_intention", side_effect=to_temp):
            return TestClient(server.app).put(
                "/api/day-timeline/expedition-adopt", json=payload)

    def test_adopt_records_forced_when_schedule_off(self):
        response = self._put({"team_no": 4, "map_code": "B1",
                              "start_min": 600})
        self.assertEqual(response.status_code, 200)
        self.assertTrue(response.json()["ok"])
        skipped, forced = ec.load_choice_sets(self.path)
        self.assertEqual(skipped, {})
        self.assertIn(self.slot["key"], forced)
        self.assertEqual(forced[self.slot["key"]]["map_code"], "B1")

    def test_stale_suggestion_rejected(self):
        response = self._put({"team_no": 4, "map_code": "B1",
                              "start_min": 601})
        self.assertEqual(response.status_code, 409)
        self.assertFalse(self.path.exists())

    def test_unknown_team_rejected(self):
        response = self._put({"team_no": 9, "map_code": "B1",
                              "start_min": 600})
        self.assertEqual(response.status_code, 400)
        self.assertFalse(self.path.exists())

    def test_untoggleable_slot_rejected(self):
        self.slot["toggleable"] = False
        response = self._put({"team_no": 4, "map_code": "B1",
                              "start_min": 600})
        self.assertEqual(response.status_code, 409)
        self.assertFalse(self.path.exists())


class HelpPrefsEndpointTests(unittest.TestCase):
    """PUT /api/expedition-help-prefs：校验落盘，GET 并进时间轴。"""

    def setUp(self):
        self.folder = tempfile.TemporaryDirectory()
        self.addCleanup(self.folder.cleanup)
        self.path = Path(self.folder.name) / "prefs.json"

    def _put(self, payload):
        real = ea.save_prefs

        def to_temp(**kwargs):
            kwargs["path"] = self.path
            return real(**kwargs)

        with patch.object(ea, "save_prefs", side_effect=to_temp):
            return TestClient(server.app).put("/api/expedition-help-prefs",
                                              json=payload)

    def test_save_and_read_back(self):
        response = self._put({"teams_out": 2, "available_teams": [1, 4]})
        self.assertEqual(response.status_code, 200)
        self.assertEqual(response.json()["expedition_help"]["teams_out"], 2)
        self.assertEqual(ea.load_prefs(self.path)["available_teams"], [1, 4])

    def test_validation_error_400(self):
        response = self._put({"teams_out": 9, "available_teams": [1]})
        self.assertEqual(response.status_code, 400)
        self.assertFalse(self.path.exists())

    def test_bad_shape_400(self):
        response = self._put({"teams_out": 1, "available_teams": "14"})
        self.assertEqual(response.status_code, 400)
        self.assertFalse(self.path.exists())


if __name__ == "__main__":
    unittest.main()
