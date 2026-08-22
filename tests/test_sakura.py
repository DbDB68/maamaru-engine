# -*- coding: utf-8 -*-
"""刷花与出阵自动换队长的纯逻辑测试（假 MAA，不碰真机）。"""

import unittest

from touken.flows.sakura import SakuraMixin, _ROW_CY, _parse_fatigue_text
from touken.maa_adapter import Point


class ParseFatigueTests(unittest.TestCase):
    def test_denominator_100_wins_over_survival_line(self):
        # roi 蹭到上面"生存 xx/xx"那行时，分母 100 的才是疲劳
        self.assertEqual(_parse_fatigue_text("生存 55/60 疲劳 88/100"), 88)

    def test_plain_fatigue(self):
        self.assertEqual(_parse_fatigue_text("疲劳 100/100"), 100)

    def test_no_100_denominator_falls_back_to_first_pair(self):
        self.assertEqual(_parse_fatigue_text("12/34"), 12)

    def test_garbage_is_none(self):
        self.assertIsNone(_parse_fatigue_text("啥也没有"))


class Maa:
    """按 roi 分行回答疲劳/名字 OCR；swipe 后切换成 after_rows 模拟拖动结果。"""

    def __init__(self, rows, after_rows=None, names=None):
        self.rows = rows
        self.after_rows = after_rows
        self.names = names or {}
        self.swipes = []
        self.clicks = []

    def screenshot(self, force=False):
        pass

    def click(self, point):
        self.clicks.append(point)

    def swipe(self, x1, y1, x2, y2, duration_ms=400):
        self.swipes.append((x1, y1, x2, y2, duration_ms))
        if self.after_rows is not None:
            self.rows = self.after_rows

    def ocr_all(self, roi):
        if roi.x == 290:  # 疲劳列：roi.y = cy + 28
            slot = _ROW_CY.index(roi.y - 28) + 1
            value = self.rows.get(slot)
            return [(f"疲劳 {value}/100", Point(300, roi.y))] if value is not None else []
        if roi.x == 100:  # 名字列：roi.y = cy + 8
            slot = _ROW_CY.index(roi.y - 8) + 1
            name = self.names.get(slot)
            return [(name, Point(120, roi.y))] if name else []
        return []


def _flow(maa):
    flow = SakuraMixin()
    flow.maa = maa
    return flow


FULL = {1: 80, 2: 60, 3: 90, 4: 30, 5: 70, 6: 85}


class RotateCaptainTests(unittest.TestCase):
    def test_lowest_fatigue_is_dragged_to_captain(self):
        maa = Maa(dict(FULL), after_rows={**FULL, 1: 30}, names={4: "小狐丸"})
        messages = list(_flow(maa)._rotate_captain_here(margin=10))

        # 从 4 号位（cy=455）拖到队长位（cy=160）
        self.assertEqual(maa.swipes, [(200, 455, 200, 160, 1000)])
        self.assertTrue(any("小狐丸" in m and "上任队长" in m for m in messages))
        self.assertTrue(any("全队疲劳" in m for m in messages))

    def test_captain_already_lowest_does_nothing(self):
        maa = Maa({**FULL, 1: 20})
        messages = list(_flow(maa)._rotate_captain_here(margin=10))

        self.assertEqual(maa.swipes, [])
        self.assertTrue(any("位置没毛病" in m for m in messages))

    def test_gap_below_margin_is_not_worth_it(self):
        maa = Maa({**FULL, 1: 40, 4: 35})
        messages = list(_flow(maa)._rotate_captain_here(margin=10))

        self.assertEqual(maa.swipes, [])
        self.assertTrue(any("不值得折腾" in m for m in messages))

    def test_unreadable_captain_stops(self):
        rows = dict(FULL)
        del rows[1]  # 队长位读不到（空位/OCR 瞎了）
        messages = list(_flow(Maa(rows))._rotate_captain_here())

        self.assertTrue(any("队长位读不到疲劳" in m for m in messages))

    def test_all_unreadable_stops(self):
        messages = list(_flow(Maa({}))._rotate_captain_here())

        self.assertTrue(any("全队都读不到疲劳" in m for m in messages))

    def test_swallowed_drag_is_reported(self):
        # 拖完队长位还是原值 → 手势被吞，如实汇报
        maa = Maa(dict(FULL), after_rows=dict(FULL))
        messages = list(_flow(maa)._rotate_captain_here(margin=10))

        self.assertEqual(len(maa.swipes), 1)
        self.assertTrue(any("拖动可能没生效" in m for m in messages))
        self.assertFalse(any("上任队长" in m for m in messages))

class SortieRotateHookTests(unittest.TestCase):
    """出阵流程的换队长钩子：开了才换，且每圈在部队选择步之后触发。"""

    class Maa:
        def screenshot(self, force=False):
            pass

        def click(self, point):
            pass

        def template_match(self, template, roi=None, threshold=0.7):
            # 只放行"小图页"地标，其它一律不命中，把流程快进到部队选择
            return Point(1, 1) if template == "area.png" else None

    def _host(self):
        from touken.flows.sortie import SortieMixin

        host = SortieMixin()
        host.maa = self.Maa()
        host.config = {
            "sortie": {"decide_button": {"template": "decide.png"},
                       "area_select_ui": {"template": "area.png"},
                       "depart_button": {"template": "depart.png"}},
            "map_select": {"合战场": {"chapters": {"1": [1, 2]},
                                      "maps": {"1": [3, 4]}}},
            "team_select": {"teams": {"3": [5, 6]}},
        }
        host.current_location = "本丸"

        def fake_nav(location):
            host.current_location = location  # 导航必然成功
            return iter(())

        host.navigate_to_stream = fake_nav
        host._click_point = lambda point: None
        host._wait_for_team_select = lambda cfg, attempts=12, open_after=2: True
        host._pick_team = lambda team_no: True
        host._team_injury_status = lambda cfg: None
        host.saved_records = []
        host._save_team_record = lambda cfg, record_no=1: (
            host.saved_records.append(record_no) or True)
        host._click_depart = lambda cfg: False  # 换完队长就收场，别真出阵
        host.rotations = []
        host._rotate_captain_here = \
            lambda margin=10: iter([host.rotations.append(margin) or "rot"])
        return host

    def test_rotate_runs_each_loop_after_team_pick(self):
        host = self._host()
        from unittest.mock import patch
        with patch("touken.flows.sortie.time.sleep"):
            messages = list(host.sortie_stream(chapter=1, map_no=1, team_no=3,
                                               auto_equip=False, auto_march=False,
                                               rotate_captain=True,
                                               rotate_captain_margin=20))

        self.assertEqual(host.rotations, [20])
        self.assertIn("rot", messages)
        self.assertIn("[出阵] 找不到即刻出阵按钮（队长重伤会变灰？），停", messages)

    def test_rotate_off_by_default(self):
        host = self._host()
        from unittest.mock import patch
        with patch("touken.flows.sortie.time.sleep"):
            list(host.sortie_stream(chapter=1, map_no=1, team_no=3, auto_equip=False, auto_march=False))

        self.assertEqual(host.rotations, [])

    def test_auto_equip_stays_active_when_injury_action_will_stop(self):
        host = self._host()
        from unittest.mock import patch
        with patch("touken.flows.sortie.time.sleep"):
            list(host.sortie_stream(
                chapter=1, map_no=1, team_no=3,
                auto_equip=True, auto_march=False,
                injury_action="repair_stop"))

        self.assertEqual(host.saved_records, [1])


class SortieBuilderTests(unittest.TestCase):
    """面板 builder 把自动换队长开关和阈值透传给出阵/异去。"""

    class AgentStub:
        def sortie_stream(self, **kw):
            self.kw = kw
            return iter(())

        def yosari_stream(self, **kw):
            self.kw = kw
            return iter(())

    def test_build_sortie_passes_rotate_captain(self):
        from panel.server import _build_sortie, _build_yosari

        agent = self.AgentStub()
        list(_build_sortie(agent, "cfg", {
            "rotate_captain": True,
            "rotate_captain_margin": "20",
        }))
        self.assertIs(agent.kw["rotate_captain"], True)
        self.assertEqual(agent.kw["rotate_captain_margin"], 20)

        agent = self.AgentStub()
        list(_build_yosari(agent, "cfg", {
            "rotate_captain": True,
            "rotate_captain_margin": "5",
        }))
        self.assertIs(agent.kw["rotate_captain"], True)
        self.assertEqual(agent.kw["rotate_captain_margin"], 5)

        agent = self.AgentStub()
        list(_build_sortie(agent, "cfg", {}))
        self.assertIs(agent.kw["rotate_captain"], False)
        self.assertEqual(agent.kw["rotate_captain_margin"], 10)

    def test_battle_forms_only_show_margin_when_rotation_is_enabled(self):
        from panel.script_runner import _SCRIPTS
        import panel.server  # noqa: F401  # import 即注册脚本

        for script in ("sortie", "yosari"):
            fields = {field["key"]: field for field in _SCRIPTS[script]["params"]}
            self.assertIn("rotate_captain", fields)
            self.assertEqual(
                fields["rotate_captain_margin"]["visibleWhen"],
                {"key": "rotate_captain", "is": True})

    def test_auto_equip_is_independent_from_injury_action_in_battle_forms(self):
        from panel.script_runner import _SCRIPTS
        import panel.server  # noqa: F401  # import 即注册脚本

        for script in ("sortie", "yosari"):
            fields = {field["key"]: field for field in _SCRIPTS[script]["params"]}
            self.assertNotIn("visibleWhen", fields["auto_equip"])


if __name__ == "__main__":
    unittest.main()
