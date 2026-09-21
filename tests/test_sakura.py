# -*- coding: utf-8 -*-
"""刷花与出阵自动换队长的纯逻辑测试（假 MAA，不碰真机）。"""

import unittest

from touken.flows.sakura import SakuraMixin, _parse_fatigue_text
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


# 部队选择页实测的疲劳行 y（2026-09-21 模板工坊帧校准，行距 ~94.5px）
_FY = {1: 199, 2: 293, 3: 388, 4: 483, 5: 577, 6: 672}


class Maa:
    """整列 OCR 假实现：疲劳列一把全给（带 y），名字列按 fy-32 归位；
    swipe 后切换成 after_rows/after_names 模拟拖动结果。"""

    def __init__(self, rows, after_rows=None, names=None, after_names=None):
        self.rows = rows
        self.after_rows = after_rows
        self.names = names or {}
        self.after_names = after_names
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
        if self.after_names is not None:
            self.names = self.after_names

    def ocr_all(self, roi):
        if roi.x == 285:  # 疲劳整列：一把全给
            return [(f"疲劳 {v}/100", Point(300, _FY[s]))
                    for s, v in sorted(self.rows.items())]
        if roi.x == 100:  # 名字列：roi.y = 疲劳行y - 32
            for slot, fy in _FY.items():
                if abs(roi.y - (fy - 32)) <= 2:
                    name = self.names.get(slot)
                    return [(name, Point(120, roi.y))] if name else []
            return []


def _flow(maa):
    flow = SakuraMixin()
    flow.maa = maa
    return flow


FULL = {1: 80, 2: 60, 3: 90, 4: 30, 5: 70, 6: 85}


def _rotate(maa, margin=10):
    from unittest.mock import patch
    with patch("touken.flows.sakura.time.sleep"):
        return list(_flow(maa)._rotate_captain_here(margin=margin))


class RotateCaptainTests(unittest.TestCase):
    def test_lowest_fatigue_is_dragged_to_captain(self):
        maa = Maa(dict(FULL), after_rows={**FULL, 1: 30}, names={4: "小狐丸"})
        messages = _rotate(maa)

        # 从 4 号位（fy=483 → 行心 447）拖到队长位（fy=199 → 行心 163）
        self.assertEqual(maa.swipes, [(200, 447, 200, 163, 1000)])
        self.assertTrue(any("小狐丸" in m and "上任队长" in m for m in messages))
        self.assertTrue(any("全队疲劳" in m for m in messages))

    def test_captain_already_lowest_does_nothing(self):
        maa = Maa({**FULL, 1: 20})
        messages = _rotate(maa)

        self.assertEqual(maa.swipes, [])
        self.assertTrue(any("位置没毛病" in m for m in messages))

    def test_gap_below_margin_is_not_worth_it(self):
        maa = Maa({**FULL, 1: 40, 4: 35})
        messages = _rotate(maa)

        self.assertEqual(maa.swipes, [])
        self.assertTrue(any("不值得折腾" in m for m in messages))

    def test_missing_first_row_is_rejected(self):
        # 首行漏读会让全队错号：顶 anchor 直接拒读，宁可不换也不拖错人
        rows = dict(FULL)
        del rows[1]
        maa = Maa(rows)
        messages = _rotate(maa)

        self.assertEqual(maa.swipes, [])
        self.assertTrue(any("读不齐" in m for m in messages))

    def test_missing_middle_row_is_rejected(self):
        # 中间漏行会留下倍距空洞，同样拒读
        rows = dict(FULL)
        del rows[3]
        maa = Maa(rows)
        messages = _rotate(maa)

        self.assertEqual(maa.swipes, [])
        self.assertTrue(any("读不齐" in m for m in messages))

    def test_all_unreadable_stops(self):
        messages = _rotate(Maa({}))

        self.assertTrue(any("读不齐" in m for m in messages))

    def test_swallowed_drag_is_retried_then_reported(self):
        # 拖完队长位还是原值 → 手势被吞，按现位置再拖一次，仍不行就如实汇报
        maa = Maa(dict(FULL), after_rows=dict(FULL))
        messages = _rotate(maa)

        self.assertEqual(maa.swipes, [(200, 447, 200, 163, 1000),
                                      (200, 447, 200, 163, 1500)])
        self.assertTrue(any("再拖一次" in m for m in messages))
        self.assertTrue(any("拖动可能没生效" in m for m in messages))
        self.assertFalse(any("上任队长" in m for m in messages))

    def test_misread_fatigue_is_verified_by_captain_name(self):
        # 疲劳复读 OCR 错字（30 认成 36）但队长位名字对得上 → 算换好了
        maa = Maa(dict(FULL), after_rows={**FULL, 1: 36},
                  names={4: "小狐丸"}, after_names={1: "小狐丸"})
        messages = _rotate(maa)

        self.assertEqual(len(maa.swipes), 1)
        self.assertTrue(any("换好了" in m and "小狐丸" in m for m in messages))
        self.assertFalse(any("拖动可能没生效" in m for m in messages))

class SortieRotateHookTests(unittest.TestCase):
    """出阵流程的换队长钩子：开了才换，且每圈在部队选择步之后触发。"""

    class Maa:
        def screenshot(self, force=False):
            pass

        def click(self, point):
            pass

        def ocr(self, expected, roi, match_mode="contains"):
            return Point(1, 1) if expected in ("部队", "选择") else None

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
        host._expedition_takeover_requested = lambda now=None: False
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
