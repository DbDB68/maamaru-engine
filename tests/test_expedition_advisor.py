# -*- coding: utf-8 -*-
"""远征建议引擎（panel/expedition_advisor.py）测试。

v3 语义：每个可丢队伍各派 N 班（rounds_per_team），班次按缺口榜轮转、
同队串行（收工+10 分钟缓冲）；点建议 = 采纳记 forced，绝不自动执行。
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


def _prefs(rounds=1, available_teams=(1, 4)):
    return {"version": 2, "rounds_per_team": rounds,
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
    """v3：每个可丢队伍各派 N 班（rounds_per_team）；班次按缺口榜轮转，
    同队多班串行（上一班收工+10 分钟收菜缓冲后起排下一班）。"""

    def _build(self, prefs, **kwargs):
        kwargs.setdefault("planning", _planning())
        kwargs.setdefault("maps", _MAPS)
        kwargs.setdefault("situation_path", Path("/nonexistent"))
        kwargs.setdefault("now_min", 600)
        return ea.build_expedition_suggestions(prefs, **kwargs)

    def test_each_team_one_shift_by_shortage_order(self):
        """可丢 [1,4]、每队 1 班 → 部队一缺口第一（砥石）、部队四缺口第二。"""
        out = self._build(_prefs(rounds=1, available_teams=(1, 4)),
                          planning=_planning(limiting=("砥石", "玉钢")))
        self.assertEqual(len(out["suggestions"]), 2)
        first, second = out["suggestions"]
        self.assertEqual((first["team_no"], first["resource"],
                          first["map_code"]), (1, "砥石", "B1"))
        self.assertEqual((second["team_no"], second["resource"],
                          second["map_code"]), (4, "玉钢", "A2"))
        # now+5 分钟起排；不同队伍同时出发是游戏常态
        self.assertEqual(first["start_min"], 605)
        self.assertEqual(second["start_min"], 605)
        self.assertEqual(first["shift_no"], 1)
        self.assertEqual(first["key"], "suggest:1:B1:605")
        self.assertIsNone(out["note"])

    def test_rounds_two_serial_shifts_per_team(self):
        """每队 2 班：同队第二班从第一班收工+10 分钟收菜缓冲后起排。"""
        out = self._build(_prefs(rounds=2, available_teams=(1,)),
                          planning=_planning(limiting=("砥石", "玉钢")))
        self.assertEqual(len(out["suggestions"]), 2)
        first, second = out["suggestions"]
        self.assertEqual((first["resource"], first["map_code"],
                          first["start_min"], first["shift_no"]),
                         ("砥石", "B1", 605, 1))
        # 605 + 90 分钟 + 10 分钟缓冲 = 705 起第二班，接缺口榜下一种资源
        self.assertEqual((second["resource"], second["map_code"],
                          second["start_min"], second["shift_no"]),
                         ("玉钢", "A2", 705, 2))
        self.assertIn("这队今天第二班", second["reason"])

    def test_rotation_walks_shortage_list_across_rounds(self):
        """轮转：各队第 1 班依次取缺口第 1、2 种，第 2 班接着往后排；
        轮到的资源没产图就顺延下一种（冷却材没图 → 顺延小判）。"""
        out = self._build(_prefs(rounds=2, available_teams=(1, 4)),
                          planning=_planning(limiting=("砥石", "玉钢")))
        got = [(s["team_no"], s["resource"], s["map_code"], s["start_min"])
               for s in out["suggestions"]]
        # 榜：[砥石, 玉钢, 木炭, 冷却材, 小判]；部队四第二班轮到冷却材，
        # 没产图顺延小判 D4（起排 675 = 605+60+10 缓冲）
        self.assertEqual(got, [(1, "砥石", "B1", 605), (4, "玉钢", "A2", 605),
                               (1, "木炭", "A1", 705), (4, "小判", "D4", 675)])
        self.assertIn("顺延补小判", out["suggestions"][3]["reason"])
        self.assertIsNone(out["note"])

    def test_committed_counts_top_up_to_n(self):
        """committed 按队计数：部队四已有一班 → 只补一班，且算今天第二班。"""
        out = self._build(_prefs(rounds=2, available_teams=(1, 4)),
                          planning=_planning(limiting=("砥石", "玉钢")),
                          committed_counts={4: 1})
        got = [(s["team_no"], s["resource"], s["shift_no"])
               for s in out["suggestions"]]
        self.assertEqual(got, [(1, "砥石", 1), (4, "玉钢", 2), (1, "木炭", 2)])

    def test_committed_shift_pushes_next_start_after_it(self):
        """已排的班占着时间：补的班从已排班收工+缓冲后起排。"""
        out = self._build(_prefs(rounds=2, available_teams=(4,)),
                          planning=_planning(limiting=("砥石",)),
                          committed_counts={4: 1},
                          team_busy_until={4: 840})  # 已有一班到 14:00
        self.assertEqual(len(out["suggestions"]), 1)
        suggestion = out["suggestions"][0]
        self.assertEqual(suggestion["shift_no"], 2)
        self.assertEqual(suggestion["start_min"], 850)  # 840 + 10 分钟缓冲

    def test_all_teams_full_gives_honest_note(self):
        out = self._build(_prefs(rounds=1, available_teams=(4,)),
                          committed_counts={4: 1})
        self.assertEqual(out["suggestions"], [])
        self.assertIn("班都排上了", out["note"])

    def test_second_shift_that_cannot_fit_is_dropped_with_note(self):
        """第一班排得下、第二班过 23:59 → 只出第一班，note 说实话。"""
        out = self._build(_prefs(rounds=2, available_teams=(1,)),
                          now_min=1340)  # 22:25 起排：B1 到 23:55 收工
        self.assertEqual(len(out["suggestions"]), 1)
        self.assertEqual(out["suggestions"][0]["map_code"], "B1")
        self.assertIn("部队一第二班", out["note"])
        self.assertIn("23:59 前排不下", out["note"])

    def test_reason_names_shortage_map_and_rank(self):
        out = self._build(_prefs(rounds=1, available_teams=(4,)))
        reason = out["suggestions"][0]["reason"]
        self.assertIn("砥石最缺（就剩3炉）", reason)
        self.assertIn("B1「湖底」", reason)
        self.assertIn("时薪正是第一", reason)
        self.assertIn("等级没核", reason)  # 没近况文件，如实标注

    def test_second_best_map_when_best_cannot_fit_today(self):
        """晚段最优图（4 小时的 D4）排不下时回退次优图 B1。"""
        planning = _planning(limiting=(), koban_available=-50)
        out = self._build(_prefs(rounds=1, available_teams=(1,)),
                          planning=planning, now_min=1200)  # 20:05 起排
        suggestion = out["suggestions"][0]
        self.assertEqual(suggestion["map_code"], "B1")
        self.assertIn("时薪第2", suggestion["reason"])

    def test_late_evening_falls_back_to_short_map(self):
        """晚段长图排不下 → 顺延能塞进今天的短图，reason 写清楚顺延。"""
        out = self._build(_prefs(rounds=1, available_teams=(1,)),
                          now_min=23 * 60)  # 23:05 起排，B1/A2 装不下，A1 行
        suggestion = out["suggestions"][0]
        self.assertEqual(suggestion["map_code"], "A1")
        self.assertIn("顺延补木炭", suggestion["reason"])

    def test_past_day_end_gives_no_suggestion_with_honest_note(self):
        out = self._build(_prefs(rounds=1, available_teams=(1,)),
                          now_min=1410)  # 23:35 起排，最短的 A1 也装不下
        self.assertEqual(out["suggestions"], [])
        self.assertIn("23:59 前排不下", out["note"])

    def test_level_gate_falls_back_to_lower_map(self):
        """D4 要等级合计 100，队伍只有 50 → 回退到门槛 20 的 B1。"""
        with tempfile.TemporaryDirectory() as folder:
            path = _write_situation(folder, [
                {"party_no": 1, "members": [{"level": 50}]},
            ])
            planning = _planning(limiting=(), koban_available=-50)
            out = self._build(_prefs(rounds=1, available_teams=(1,)),
                              planning=planning, situation_path=path)
            suggestion = out["suggestions"][0]
            self.assertEqual(suggestion["map_code"], "B1")
            self.assertIn("等级合计够格", suggestion["reason"])

    def test_all_teams_level_blocked_gives_no_suggestion(self):
        with tempfile.TemporaryDirectory() as folder:
            path = _write_situation(folder, [
                {"party_no": 4, "members": [{"level": 1}]},
            ])
            out = self._build(_prefs(rounds=1, available_teams=(4,)),
                              situation_path=path)
            self.assertEqual(out["suggestions"], [])
            self.assertIn("等级都不够", out["note"])

    def test_team_missing_from_situation_passes_gate_but_is_marked(self):
        """近况里没这队 = 等级核不了，不拦但注明。"""
        with tempfile.TemporaryDirectory() as folder:
            path = _write_situation(folder, [
                {"party_no": 2, "members": [{"level": 99}]},
            ])
            out = self._build(_prefs(rounds=1, available_teams=(4,)),
                              situation_path=path)
            self.assertEqual(len(out["suggestions"]), 1)
            self.assertIn("等级没核", out["suggestions"][0]["reason"])

    def test_full_team_gets_no_new_suggestion(self):
        out = self._build(_prefs(rounds=1, available_teams=(1, 4)),
                          committed_counts={1: 1})
        self.assertEqual([s["team_no"] for s in out["suggestions"]], [4])

    def test_partial_fill_gets_summary_note(self):
        """部队四所有对口图都被占 → 只排出部队一一班，小结 note 说实话。"""
        out = self._build(_prefs(rounds=1, available_teams=(1, 4)),
                          planning=_planning(limiting=("砥石", "玉钢")),
                          occupied_maps={"A2", "B1", "D4"})
        # 部队一顺延到木炭 A1；部队四全榜撞占用，排不出
        self.assertEqual([s["team_no"] for s in out["suggestions"]], [1])
        self.assertIn("只排得出 1 班", out["note"])
        self.assertIn("部队四第一班", out["note"])

    def test_occupied_map_falls_back_to_second_best(self):
        """小判榜首 D4 今天已有班在跑 → 建议顺移次优的 B1。"""
        planning = _planning(limiting=(), koban_available=-50)
        out = self._build(_prefs(rounds=1, available_teams=(1,)),
                          planning=planning, occupied_maps={"D4"})
        suggestion = out["suggestions"][0]
        self.assertEqual(suggestion["map_code"], "B1")
        self.assertEqual(suggestion["resource"], "小判")

    def test_all_producing_maps_occupied_gives_honest_note(self):
        """全榜对口图都被占 → 不硬塞，note 说明白。"""
        planning = _planning(limiting=(), koban_available=-50)
        out = self._build(_prefs(rounds=1, available_teams=(1,)),
                          planning=planning,
                          occupied_maps={"A1", "A2", "B1", "D4"})
        self.assertEqual(out["suggestions"], [])
        self.assertIn("都有班在跑或已点上", out["note"])

    def test_two_suggestions_never_share_one_map(self):
        """两资源时薪榜首同图时，第二条建议回退次优图（一图一班）。"""
        maps = {
            "M1": {"era": 1, "slot": 1, "name": "双产", "duration_min": 60,
                   "木炭": 120, "玉钢": 120, "冷却材": 0, "砥石": 0, "小判": 0,
                   "rules": {}},
            "M2": {"era": 1, "slot": 2, "name": "单产", "duration_min": 60,
                   "木炭": 0, "玉钢": 60, "冷却材": 0, "砥石": 0, "小判": 0,
                   "rules": {}},
        }
        planning = _planning(limiting=("木炭", "玉钢"))
        out = self._build(_prefs(rounds=1, available_teams=(1, 4)),
                          planning=planning, maps=maps)
        self.assertEqual(len(out["suggestions"]), 2)
        first, second = out["suggestions"]
        self.assertEqual((first["resource"], first["map_code"],
                          first["team_no"]), ("木炭", "M1", 1))
        # 玉钢榜首也是 M1，但已被本批建议占住 → 回退 M2
        self.assertEqual((second["resource"], second["map_code"],
                          second["team_no"]), ("玉钢", "M2", 4))

    def test_resource_without_producing_map_falls_through(self):
        """轮到的资源没产图 → 顺延下一种，reason 写清楚顺延。"""
        out = self._build(_prefs(rounds=1, available_teams=(1,)),
                          planning=_planning(limiting=("冷却材",)))
        suggestion = out["suggestions"][0]
        self.assertEqual(suggestion["resource"], "砥石")  # 榜上下一种
        self.assertIn("冷却材排不出，顺延补砥石", suggestion["reason"])

    def test_fill_tone_when_nothing_is_urgent(self):
        """四资源齐平不算「最缺」，reason 走顺手攒的 fill 口吻。"""
        planning = _planning(limiting=("木炭", "玉钢", "冷却材", "砥石"),
                             capacity=400)
        out = self._build(_prefs(rounds=1, available_teams=(4,)),
                          planning=planning)
        self.assertEqual(out["suggestions"][0]["resource"], "砥石")
        self.assertIn("顺手攒砥石", out["suggestions"][0]["reason"])

    def test_no_planning_gives_empty_advice_with_note(self):
        out = self._build(_prefs(rounds=1), planning=None)
        self.assertEqual(out["suggestions"], [])
        self.assertIn("盘点", out["note"])

    def test_empty_resource_watch_is_no_data(self):
        planning = {"resource_watch": {"forge_capacity": None,
                                       "limiting": []}}
        out = self._build(_prefs(rounds=1), planning=planning)
        self.assertEqual(out["suggestions"], [])
        self.assertIn("盘点", out["note"])

    def test_rounds_zero_means_no_advice(self):
        out = self._build(_prefs(rounds=0))
        self.assertEqual(out["suggestions"], [])
        self.assertIn("不丢队", out["note"])


# 刀种门槛测试用图：B2 要队里有打刀（老大部队四翻车现场），B1 无要求兜底，
# E4 要凑 4 种刀。收益只为排队次服务
_TYPE_MAPS = {
    "B2": {"era": 2, "slot": 2, "name": "加役方人足寄场", "duration_min": 180,
           "木炭": 0, "玉钢": 0, "冷却材": 0, "砥石": 0, "小判": 300,
           "rules": {"total_level": 60, "required_types": {"打刀": 1}}},
    "B1": {"era": 2, "slot": 1, "name": "湖底", "duration_min": 90,
           "木炭": 0, "玉钢": 0, "冷却材": 0, "砥石": 180, "小判": 90,
           "rules": {"total_level": 20, "required_types": {}}},
}
_E4_MAPS = {
    "E4": {"era": 5, "slot": 4, "name": "天下布武", "duration_min": 360,
           "木炭": 0, "玉钢": 0, "冷却材": 0, "砥石": 0, "小判": 600,
           "rules": {"total_level": 300, "required_types": {},
                     "min_distinct_types": 4}},
}


def _members(*names, level=99):
    return [{"level": level, "name": name} for name in names]


class TypeGateTests(unittest.TestCase):
    """刀种资格门：「含有」语义——至少一把该刀种在队；极化刀种不变。
    成员名单走真实名册（swords.json）解析。"""

    def _build(self, prefs, parties, maps=_TYPE_MAPS):
        folder = tempfile.TemporaryDirectory()
        self.addCleanup(folder.cleanup)
        path = _write_situation(folder.name, parties)
        planning = _planning(limiting=(), koban_available=-50)
        return ea.build_expedition_suggestions(
            prefs, planning=planning, maps=maps, situation_path=path,
            now_min=600)

    def test_all_tachi_team_skips_b2_to_second_map(self):
        """全太刀队（老大部队四翻车同款）不给 B2，顺移无门槛的 B1。"""
        out = self._build(
            _prefs(rounds=1, available_teams=(4,)),
            [{"party_no": 4, "members": _members(
                "三日月宗近", "小狐丸", "一期一振")}])
        suggestion = out["suggestions"][0]
        self.assertEqual(suggestion["map_code"], "B1")
        self.assertEqual(suggestion["team_no"], 4)

    def test_qualified_team_gets_b2_over_unqualified(self):
        """两队可丢时，B2 顺移给队里有打刀的部队一，不给全太刀的部队四。"""
        out = self._build(
            _prefs(rounds=1, available_teams=(1, 4)),
            [{"party_no": 4, "members": _members(
                "三日月宗近", "小狐丸", "一期一振")},
             {"party_no": 1, "members": _members(
                 "加州清光", "山姥切国广", "三日月宗近")}])
        suggestion = out["suggestions"][0]
        self.assertEqual((suggestion["map_code"], suggestion["team_no"]),
                         ("B2", 1))
        self.assertIn("刀种也够格", suggestion["reason"])

    def test_contains_semantics_one_uchigatana_is_enough(self):
        """「含有」不是「全是」：五把太刀里掺一把打刀就合格。"""
        out = self._build(
            _prefs(rounds=1, available_teams=(4,)),
            [{"party_no": 4, "members": _members(
                "三日月宗近", "小狐丸", "一期一振", "江雪左文字",
                "加州清光")}])
        suggestion = out["suggestions"][0]
        self.assertEqual(suggestion["map_code"], "B2")

    def test_kiwame_suffix_keeps_base_type(self):
        """极化刀种不变：「加州清光·极」仍算打刀。"""
        out = self._build(
            _prefs(rounds=1, available_teams=(4,)),
            [{"party_no": 4, "members": _members(
                "三日月宗近", "小狐丸", "一期一振", "加州清光·极")}])
        self.assertEqual(out["suggestions"][0]["map_code"], "B2")

    def test_all_teams_type_blocked_gives_human_note(self):
        """唯一可丢队全是太刀且次优图也占 → note 写人话说明卡在哪。"""
        out = self._build(
            _prefs(rounds=1, available_teams=(4,)),
            [{"party_no": 4, "members": _members(
                "三日月宗近", "小狐丸", "一期一振")}],
            maps={"B2": _TYPE_MAPS["B2"]})
        self.assertEqual(out["suggestions"], [])
        self.assertIn("刀种门槛", out["note"])
        self.assertIn("部队四全是太刀，没有打刀", out["note"])

    def test_e4_min_distinct_types_gate(self):
        """E4 要凑 4 种刀：3 种不够，补一把大太刀凑够 4 种放行。"""
        three_kinds = [{"party_no": 4, "members": _members(
            "三日月宗近", "小狐丸", "加州清光", "山姥切国广",
            "今剑", "今剑")}]  # 太刀/打刀/短刀 = 3 种
        out = self._build(_prefs(rounds=1, available_teams=(4,)),
                          three_kinds, maps=_E4_MAPS)
        self.assertEqual(out["suggestions"], [])
        self.assertIn("凑4种刀", out["note"])
        self.assertIn("只凑出3种刀", out["note"])

        four_kinds = [{"party_no": 4, "members": _members(
            "三日月宗近", "小狐丸", "加州清光", "今剑", "石切丸",
            "石切丸")}]  # 太刀/打刀/短刀/大太刀 = 4 种
        out = self._build(_prefs(rounds=1, available_teams=(4,)),
                          four_kinds, maps=_E4_MAPS)
        self.assertEqual(out["suggestions"][0]["map_code"], "E4")
        self.assertIn("凑4种刀", out["suggestions"][0]["reason"])

    def test_failed_combo_blacklisted_but_map_open_to_other_team(self):
        """同图同队今天 failed 过 → 拉黑该组合，同图换队仍可荐。"""
        folder = tempfile.TemporaryDirectory()
        self.addCleanup(folder.cleanup)
        path = _write_situation(folder.name, [
            {"party_no": 1, "members": _members("加州清光", "今剑")},
            {"party_no": 4, "members": _members("加州清光", "今剑")},
        ])
        out = ea.build_expedition_suggestions(
            _prefs(rounds=1, available_teams=(1, 4)),
            planning=_planning(limiting=(), koban_available=-50),
            maps=_TYPE_MAPS, situation_path=path, now_min=600,
            failed_combos={("B2", 4)})
        # (B2,部队四) 拉黑，B2 改荐部队一
        suggestion = out["suggestions"][0]
        self.assertEqual((suggestion["map_code"], suggestion["team_no"]),
                         ("B2", 1))

    def test_failed_combo_without_fallback_gives_note(self):
        """同组合 failed 且无队无图可换 → note 写「这班今天没派成」。"""
        folder = tempfile.TemporaryDirectory()
        self.addCleanup(folder.cleanup)
        path = _write_situation(folder.name, [
            {"party_no": 4, "members": _members("加州清光", "今剑")},
        ])
        out = ea.build_expedition_suggestions(
            _prefs(rounds=1, available_teams=(4,)),
            planning=_planning(limiting=(), koban_available=-50),
            maps={"B2": _TYPE_MAPS["B2"]}, situation_path=path, now_min=600,
            failed_combos={("B2", 4)})
        self.assertEqual(out["suggestions"], [])
        self.assertIn("这班今天没派成", out["note"])
        self.assertIn("换队/换图试试", out["note"])


class PrefsStorageTests(unittest.TestCase):
    def setUp(self):
        self.folder = tempfile.TemporaryDirectory()
        self.addCleanup(self.folder.cleanup)
        self.path = Path(self.folder.name) / "prefs.json"

    def test_missing_file_gives_defaults(self):
        prefs = ea.load_prefs(self.path)
        self.assertEqual(prefs["rounds_per_team"], 1)
        self.assertEqual(prefs["available_teams"], [1, 4, 5])

    def test_broken_file_gives_defaults(self):
        self.path.write_text("{not json", encoding="utf-8")
        prefs = ea.load_prefs(self.path)
        self.assertEqual(prefs["available_teams"], [1, 4, 5])

    def test_v1_file_migrates_teams_out_to_rounds(self):
        """v1 老偏好（teams_out=总共丢几队）读出即迁移成每队次数。"""
        self.path.write_text(json.dumps(
            {"version": 1, "teams_out": 3, "available_teams": [4]}),
            encoding="utf-8")
        prefs = ea.load_prefs(self.path)
        self.assertEqual(prefs["version"], 2)
        self.assertEqual(prefs["rounds_per_team"], 3)
        self.assertEqual(prefs["available_teams"], [4])
        # 只读迁移不落盘，下次保存才写 v2
        on_disk = json.loads(self.path.read_text(encoding="utf-8"))
        self.assertEqual(on_disk["version"], 1)

    def test_unknown_version_gives_defaults(self):
        self.path.write_text(json.dumps({"version": 3, "rounds_per_team": 3}),
                             encoding="utf-8")
        self.assertEqual(ea.load_prefs(self.path)["rounds_per_team"], 1)

    def test_partial_keys_fall_back(self):
        self.path.write_text(json.dumps({"version": 2, "rounds_per_team": 4}),
                             encoding="utf-8")
        prefs = ea.load_prefs(self.path)
        self.assertEqual(prefs["rounds_per_team"], 4)
        self.assertEqual(prefs["available_teams"], [1, 4, 5])

    def test_bad_values_normalized_not_fatal(self):
        self.path.write_text(json.dumps(
            {"version": 2, "rounds_per_team": 99,
             "available_teams": [1, 9, "x"]}),
            encoding="utf-8")
        prefs = ea.load_prefs(self.path)
        self.assertEqual(prefs["rounds_per_team"], 5)
        self.assertEqual(prefs["available_teams"], [1])

    def test_save_roundtrip_and_backup(self):
        prefs = ea.save_prefs(rounds_per_team=2, available_teams=[4, 1, 4],
                              path=self.path)
        self.assertEqual(prefs["rounds_per_team"], 2)
        self.assertEqual(prefs["available_teams"], [1, 4])
        self.assertEqual(ea.load_prefs(self.path)["available_teams"], [1, 4])
        again = ea.save_prefs(rounds_per_team=3, available_teams=[5],
                              path=self.path)
        self.assertEqual(again["available_teams"], [5])
        backup = json.loads(self.path.with_suffix(".json.bak")
                            .read_text(encoding="utf-8"))
        self.assertEqual(backup["rounds_per_team"], 2)
        # 落盘就是 v2 新字段
        on_disk = json.loads(self.path.read_text(encoding="utf-8"))
        self.assertEqual(on_disk["version"], 2)
        self.assertIn("rounds_per_team", on_disk)

    def test_save_validation(self):
        for bad in (6, -1, "3", True, 1.5):
            with self.assertRaises(ValueError, msg=repr(bad)):
                ea.save_prefs(rounds_per_team=bad, available_teams=[1],
                              path=self.path)
        for bad in ([0], [6], ["1"], [True], "14"):
            with self.assertRaises(ValueError, msg=repr(bad)):
                ea.save_prefs(rounds_per_team=1, available_teams=bad,
                              path=self.path)
        self.assertFalse(self.path.exists())


class TimelineIntegrationTests(unittest.TestCase):
    """build_day_timeline 注入偏好/账本/近况，吐出建议淡影字段（v2 现算班）。"""

    def setUp(self):
        day_timeline._planning_cache.clear()  # 别家的测试可能预填了真账本缓存
        self.addCleanup(day_timeline._planning_cache.clear)
        patcher = patch.object(scheduler, "map_options", lambda: [
            {"code": "A1", "duration_min": 30},
            {"code": "B1", "duration_min": 90},
        ])
        patcher.start()
        self.addCleanup(patcher.stop)
        # build_day_timeline 不传 maps，建议引擎走自己的 load_maps
        maps_patcher = patch.object(ea, "load_maps", lambda: _MAPS)
        maps_patcher.start()
        self.addCleanup(maps_patcher.stop)

    def _today_at(self, hour, minute=0):
        return time.mktime(time.strptime(
            f"{time.strftime('%Y-%m-%d')} {hour:02d}:{minute:02d}:00",
            "%Y-%m-%d %H:%M:%S"))

    def _build(self, now, cfg, **kwargs):
        kwargs.setdefault("store", object())
        kwargs.setdefault("script_labels", {})
        kwargs.setdefault("expedition_forced", {})
        kwargs.setdefault("expedition_records", {})
        kwargs.setdefault("situation_path", Path("/nonexistent"))
        return day_timeline.build_day_timeline(now, cfg=cfg, **kwargs)

    def test_timeline_carries_help_and_suggestions(self):
        now = self._today_at(6, 0)
        cfg = {"entries": [{"time": "10:00", "team_no": 4, "map_code": "B1",
                            "enabled": True}],
               "automation": {"enabled": False, "mode": "custom",
                              "preset": "小判", "teams": [2, 3, 4],
                              "start_time": "08:00"}}
        out = self._build(now, cfg,
                          expedition_help=_prefs(rounds=1,
                                                 available_teams=(4,)),
                          planning=_planning())
        self.assertEqual(out["expedition_help"]["rounds_per_team"], 1)
        self.assertEqual(out["expedition_help"]["available_teams"], [4])
        # v2：排班条目不再上轴，也不影响建议——引擎按缺口现算
        self.assertEqual(out["expeditions"], [])
        self.assertEqual(len(out["expedition_suggestions"]), 1)
        suggestion = out["expedition_suggestions"][0]
        self.assertEqual(suggestion["kind"], "expedition")
        self.assertEqual(suggestion["team_no"], 4)
        self.assertEqual(suggestion["map_code"], "B1")
        self.assertEqual(suggestion["start_min"], 365)  # 06:00 + 5 分钟
        self.assertEqual(suggestion["duration_min"], 90)
        self.assertEqual(suggestion["resource"], "砥石")
        self.assertEqual(suggestion["shift_no"], 1)
        self.assertTrue(suggestion["reason"])

    def test_forced_teams_get_no_new_suggestion(self):
        """已点上班的队（forced 落账）班次计满，不再给新建议。"""
        now = self._today_at(6, 0)
        cfg = {"entries": [], "automation": {"enabled": False,
                                             "mode": "custom"}}
        forced = {"k": {"team_no": 4, "map_code": "B1",
                        "planned_at": self._today_at(10, 0)}}
        out = self._build(now, cfg, expedition_forced=forced,
                          expedition_help=_prefs(rounds=1,
                                                 available_teams=(4,)),
                          planning=_planning())
        self.assertEqual(len(out["expeditions"]), 1)
        self.assertEqual(out["expedition_suggestions"], [])
        self.assertIn("班都排上了", out["expedition_advice_note"])

    def test_running_shift_counts_toward_rounds(self):
        """每队 2 班 + 在跑 1 班 → 只补 1 班，排在在跑班收工+缓冲后。"""
        now = self._today_at(6, 0)
        cfg = {"entries": [], "automation": {"enabled": False,
                                             "mode": "custom"}}
        records = {"4": {"map_code": "B1", "duration_min": 90,
                         "dispatched_at": time.strftime(
                             "%Y-%m-%d %H:%M:%S",
                             time.localtime(self._today_at(5, 0)))}}
        out = self._build(now, cfg, expedition_records=records,
                          expedition_help=_prefs(rounds=2,
                                                 available_teams=(4,)),
                          planning=_planning(limiting=(),
                                             koban_available=-50))
        suggestions = out["expedition_suggestions"]
        self.assertEqual(len(suggestions), 1)
        suggestion = suggestions[0]
        self.assertEqual(suggestion["shift_no"], 2)
        # 在跑班 05:00+90min=06:30(390) 收工 +10 分钟缓冲 → 400 起排
        self.assertEqual(suggestion["start_min"], 400)
        self.assertEqual(suggestion["map_code"], "D4")  # 小判榜首，没被占

    def test_running_team_gets_no_new_suggestion(self):
        """队伍还在外面远征（expeditions.json）时不再给新建议。"""
        now = self._today_at(6, 0)
        cfg = {"entries": [], "automation": {"enabled": False,
                                             "mode": "custom"}}
        records = {"4": {"map_code": "B1", "duration_min": 90,
                         "dispatched_at": time.strftime(
                             "%Y-%m-%d %H:%M:%S",
                             time.localtime(self._today_at(5, 0)))}}
        out = self._build(now, cfg, expedition_records=records,
                          expedition_help=_prefs(rounds=1,
                                                 available_teams=(4,)),
                          planning=_planning())
        self.assertEqual(out["expeditions"][0]["kind"], "running")
        self.assertEqual(out["expedition_suggestions"], [])

    def test_forced_shift_occupies_its_map(self):
        """已点的班（时段没过完）占住图：D4 已点 → 小判建议回退 B1。"""
        now = self._today_at(6, 0)
        cfg = {"entries": [], "automation": {"enabled": False,
                                             "mode": "custom"}}
        forced = {"k": {"team_no": 4, "map_code": "D4",
                        "planned_at": self._today_at(10, 0),
                        "start_min": 600, "duration_min": 240}}
        out = self._build(now, cfg, expedition_forced=forced,
                          expedition_help=_prefs(rounds=1,
                                                 available_teams=(4, 5)),
                          planning=_planning(limiting=(), koban_available=-50))
        suggestions = out["expedition_suggestions"]
        self.assertEqual(len(suggestions), 1)
        self.assertEqual(suggestions[0]["map_code"], "B1")
        self.assertEqual(suggestions[0]["team_no"], 5)

    def test_running_expedition_occupies_its_map(self):
        """还在跑的班占住图：D4 在跑 → 小判建议回退 B1。"""
        now = self._today_at(6, 0)
        cfg = {"entries": [], "automation": {"enabled": False,
                                             "mode": "custom"}}
        records = {"5": {"map_code": "D4", "duration_min": 240,
                         "dispatched_at": time.strftime(
                             "%Y-%m-%d %H:%M:%S",
                             time.localtime(self._today_at(5, 0)))}}
        out = self._build(now, cfg, expedition_records=records,
                          expedition_help=_prefs(rounds=1,
                                                 available_teams=(4, 5)),
                          planning=_planning(limiting=(), koban_available=-50))
        self.assertEqual(out["expeditions"][0]["state"], "running")
        suggestions = out["expedition_suggestions"]
        self.assertEqual(len(suggestions), 1)
        self.assertEqual(suggestions[0]["map_code"], "B1")
        self.assertEqual(suggestions[0]["team_no"], 4)

    def test_awaiting_collect_expedition_occupies_its_map(self):
        """跑完待收也算没完结：图仍被占，建议不往 D4 塞。"""
        now = self._today_at(6, 0)
        cfg = {"entries": [], "automation": {"enabled": False,
                                             "mode": "custom"}}
        records = {"5": {"map_code": "D4", "duration_min": 240,
                         "dispatched_at": time.strftime(
                             "%Y-%m-%d %H:%M:%S",
                             time.localtime(self._today_at(1, 0)))}}
        out = self._build(now, cfg, expedition_records=records,
                          expedition_help=_prefs(rounds=1,
                                                 available_teams=(4, 5)),
                          planning=_planning(limiting=(), koban_available=-50))
        self.assertEqual(out["expeditions"][0]["state"], "awaiting_collect")
        suggestions = out["expedition_suggestions"]
        self.assertEqual(len(suggestions), 1)
        self.assertEqual(suggestions[0]["map_code"], "B1")

    def test_expired_shift_frees_its_map(self):
        """过点作废的班不占图不计班：D4 的班 expired → 建议照常给 D4。"""
        now = self._today_at(6, 0)
        cfg = {"entries": [],
               "automation": {"enabled": False, "mode": "custom",
                              "slot_states": {"k": {"state": "expired",
                                                    "blocked_reason": ""}}}}
        forced = {"k": {"team_no": 4, "map_code": "D4",
                        "planned_at": self._today_at(10, 0),
                        "start_min": 600, "duration_min": 240}}
        out = self._build(now, cfg, expedition_forced=forced,
                          expedition_help=_prefs(rounds=1,
                                                 available_teams=(4, 5)),
                          planning=_planning(limiting=(), koban_available=-50))
        suggestions = out["expedition_suggestions"]
        # 两队都还有班次额度：部队四拿小判榜首 D4，部队五砥石 B1
        self.assertEqual(len(suggestions), 2)
        self.assertEqual((suggestions[0]["map_code"],
                          suggestions[0]["team_no"]), ("D4", 4))

    def test_failed_combo_blacklisted_map_stays_open(self):
        """确认失败的班不占图，但同图同队拉黑：部队四的小判班改落 B1，
        拉黑的事 note 如实知会。"""
        now = self._today_at(6, 0)
        cfg = {"entries": [],
               "automation": {"enabled": False, "mode": "custom",
                              "slot_states": {"k": {"state": "failed_unknown",
                                                    "blocked_reason": ""}}}}
        forced = {"k": {"team_no": 4, "map_code": "D4",
                        "planned_at": self._today_at(10, 0),
                        "start_min": 600, "duration_min": 240}}
        out = self._build(now, cfg, expedition_forced=forced,
                          expedition_help=_prefs(rounds=1,
                                                 available_teams=(4, 5)),
                          planning=_planning(limiting=(), koban_available=-50))
        suggestions = out["expedition_suggestions"]
        # (D4,部队四) 拉黑 → 部队四小判改 B1；部队五顺延玉钢 A2
        self.assertEqual([(s["map_code"], s["team_no"]) for s in suggestions],
                         [("B1", 4), ("A2", 5)])
        self.assertIn("没派成", out["expedition_advice_note"])
        self.assertIn("改排了小判", out["expedition_advice_note"])

    def test_failed_combo_without_other_team_gives_honest_note(self):
        """没派成的组合拉黑后顺延别的资源补班，note 照样说没派成的事。"""
        now = self._today_at(6, 0)
        cfg = {"entries": [],
               "automation": {"enabled": False, "mode": "custom",
                              "slot_states": {
                                  "k": {"state": "failed_unknown",
                                        "blocked_reason": ""},
                                  "k2": {"state": "failed_unknown",
                                         "blocked_reason": ""}}}}
        forced = {"k": {"team_no": 4, "map_code": "D4",
                        "planned_at": self._today_at(10, 0),
                        "start_min": 600, "duration_min": 240},
                  "k2": {"team_no": 4, "map_code": "B1",
                         "planned_at": self._today_at(15, 0),
                         "start_min": 900, "duration_min": 90}}
        out = self._build(now, cfg, expedition_forced=forced,
                          expedition_help=_prefs(rounds=1,
                                                 available_teams=(4,)),
                          planning=_planning(limiting=(), koban_available=-50))
        # 小判（D4/B1）和砥石（B1）的组合都拉黑 → 顺延玉钢 A2 补上这班
        suggestions = out["expedition_suggestions"]
        self.assertEqual([(s["map_code"], s["team_no"]) for s in suggestions],
                         [("A2", 4)])
        self.assertIn("没派成", out["expedition_advice_note"])
        self.assertIn("同图同队先拉黑", out["expedition_advice_note"])

    def test_timeline_note_when_no_planning(self):
        now = self._today_at(6, 0)
        cfg = {"entries": [], "automation": {"enabled": False,
                                             "mode": "custom"}}
        out = self._build(now, cfg, expedition_help=_prefs(rounds=1),
                          planning=None)
        self.assertEqual(out["expedition_suggestions"], [])
        self.assertIn("盘点", out["expedition_advice_note"])


class AdoptEndpointTests(unittest.TestCase):
    """PUT /api/day-timeline/expedition-adopt：采纳 = 自描述 forced 落账。"""

    def setUp(self):
        self.folder = tempfile.TemporaryDirectory()
        self.addCleanup(self.folder.cleanup)
        self.path = Path(self.folder.name) / "choices.json"
        self.day_start = time.mktime(time.strptime(
            f"{time.strftime('%Y-%m-%d')} 00:00:00", "%Y-%m-%d %H:%M:%S"))
        self.suggestion = {"kind": "expedition", "key": "suggest:4:B1",
                           "team_no": 4, "map_code": "B1", "map_name": "湖底",
                           "resource": "砥石", "duration_min": 90,
                           "start_min": 600, "reason": "砥石最缺"}
        self.timeline = {"day_start": self.day_start,
                         "expeditions": [],
                         "expedition_suggestions": [self.suggestion],
                         "expedition_help": {"rounds_per_team": 1,
                                             "available_teams": [4]},
                         "expedition_advice_note": None}

    def _put(self, payload):
        real_load = ec.load_choice_sets
        real_set = ec.set_forced_adhoc

        def load_temp(*_args, **_kwargs):
            return real_load(self.path)

        def set_temp(**kwargs):
            kwargs["path"] = self.path
            return real_set(**kwargs)

        with patch.object(server, "_day_timeline_payload",
                          return_value=self.timeline), \
             patch.object(ec, "load_choice_sets", side_effect=load_temp), \
             patch.object(ec, "set_forced_adhoc", side_effect=set_temp):
            return TestClient(server.app).put(
                "/api/day-timeline/expedition-adopt", json=payload)

    def _today(self):
        return time.strftime("%Y-%m-%d", time.localtime(self.day_start))

    def test_adopt_writes_self_describing_forced(self):
        response = self._put({"team_no": 4, "map_code": "B1",
                              "start_min": 600})
        self.assertEqual(response.status_code, 200)
        self.assertTrue(response.json()["ok"])
        skipped, forced = ec.load_choice_sets(self.path)
        self.assertEqual(skipped, {})
        key = ec.adhoc_key(self._today(), 4, 600)
        self.assertIn(key, forced)
        record = forced[key]
        # 自描述：队伍/图/时刻/时长全在记录里，不引用排班条目
        self.assertEqual(record["team_no"], 4)
        self.assertEqual(record["map_code"], "B1")
        self.assertEqual(record["start_min"], 600)
        self.assertEqual(record["duration_min"], 90)
        self.assertEqual(record["planned_at"], time.strftime(
            "%Y-%m-%dT%H:%M:%S", time.localtime(self.day_start + 600 * 60)))
        self.assertTrue(ec.is_adhoc_record(record))
        # 响应带新鲜的泳道/建议，前端不用再多拉一次
        self.assertIn("expeditions", response.json())
        self.assertIn("expedition_suggestions", response.json())

    def test_duplicate_adopt_rejected(self):
        first = self._put({"team_no": 4, "map_code": "B1", "start_min": 600})
        self.assertEqual(first.status_code, 200)
        again = self._put({"team_no": 4, "map_code": "B1", "start_min": 600})
        self.assertEqual(again.status_code, 409)
        self.assertIn("已经点上", again.json()["detail"])

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
        response = self._put({"rounds_per_team": 2, "available_teams": [1, 4]})
        self.assertEqual(response.status_code, 200)
        self.assertEqual(response.json()["expedition_help"]
                         ["rounds_per_team"], 2)
        self.assertEqual(ea.load_prefs(self.path)["available_teams"], [1, 4])

    def test_legacy_teams_out_field_still_accepted(self):
        """旧前端/旧脚本只认 teams_out：兜底读作每队次数。"""
        response = self._put({"teams_out": 3, "available_teams": [4]})
        self.assertEqual(response.status_code, 200)
        self.assertEqual(response.json()["expedition_help"]
                         ["rounds_per_team"], 3)

    def test_validation_error_400(self):
        response = self._put({"rounds_per_team": 9, "available_teams": [1]})
        self.assertEqual(response.status_code, 400)
        self.assertFalse(self.path.exists())

    def test_bad_shape_400(self):
        response = self._put({"rounds_per_team": 1, "available_teams": "14"})
        self.assertEqual(response.status_code, 400)
        self.assertFalse(self.path.exists())


class ExpeditionMapsDataTests(unittest.TestCase):
    """touken/data/expedition_maps.json 刀种要求校验。

    刀种数据来源：4399 远征攻略（2026-09-30 转录），B2~B4 与游戏内截图
    核对一致；等级合计沿用 TapTap 白月魔女统计表（2026-07-26 转录）。
    """

    KNOWN_LEVELS = {"A1": 5, "A2": 10, "A3": 20, "A4": 30,
                    "B1": 50, "B2": 60, "B3": 80, "B4": 100,
                    "C1": 110, "C2": 120, "C3": 130, "C4": 140,
                    "D1": 150, "D2": 180, "D3": 200, "D4": 220,
                    "E1": 240, "E2": 260, "E3": 280, "E4": 300}
    KNOWN_TYPES = {"A2": {"短刀": 1}, "A3": {"胁差": 1},
                   "A4": {"短刀": 1, "胁差": 1},
                   "B2": {"打刀": 1}, "B3": {"太刀": 1},
                   "B4": {"打刀": 1, "太刀": 1},
                   "C2": {"大太刀": 1}, "E2": {"枪": 1}, "E3": {"薙刀": 1}}
    FREE_MAPS = {"A1", "B1", "C1", "C3", "C4",
                 "D1", "D2", "D3", "D4", "E1", "E4"}

    def setUp(self):
        self.maps = ea.load_maps()

    def test_all_20_maps_have_known_type_rules(self):
        """每张图 required_types 必须查实（含「确认自由」={}），不许 null。"""
        self.assertEqual(len(self.maps), 20)
        for code, meta in self.maps.items():
            rules = meta.get("rules") or {}
            with self.subTest(map=code):
                self.assertIsInstance(rules.get("required_types"), dict)
                self.assertNotIn("required_types",
                                 rules.get("unknown_aspects") or [])
                self.assertIn("min_distinct_types", rules)

    def test_levels_match_known_table(self):
        for code, total in self.KNOWN_LEVELS.items():
            with self.subTest(map=code):
                self.assertEqual(self.maps[code]["rules"]["total_level"],
                                 total)
                self.assertEqual(self.maps[code]["level_req"], total)

    def test_type_requirements_match_known_table(self):
        for code in self.maps:
            with self.subTest(map=code):
                self.assertEqual(self.maps[code]["rules"]["required_types"],
                                 self.KNOWN_TYPES.get(code, {}))
                expected_distinct = 4 if code == "E4" else None
                self.assertEqual(
                    self.maps[code]["rules"]["min_distinct_types"],
                    expected_distinct)
        self.assertEqual(self.FREE_MAPS,
                         {c for c in self.maps if c not in self.KNOWN_TYPES})


if __name__ == "__main__":
    unittest.main()
