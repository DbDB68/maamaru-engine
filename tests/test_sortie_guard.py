import unittest
from unittest.mock import patch

from touken.flows.sortie import SortieMixin
from touken.maa_adapter import Point


class _Maa:
    def screenshot(self, force=False):
        pass

    def template_match(self, template, roi=None, threshold=0.8):
        if template == "area.png":
            return Point(1, 1)
        return None


class _Host(SortieMixin):
    """最小出阵宿主：走到「即刻出阵」就停，侦察 _enable_auto_march 有没有被叫"""

    def __init__(self):
        self.config = {
            "sortie": {"decide_button": {"template": "decide.png"},
                       "area_select_ui": {"template": "area.png"}},
            "map_select": {"合战场": {"chapters": {"1": [10, 10]},
                                      "maps": {"1": [20, 20]}}},
            "team_select": {"teams": {"3": [30, 30]}},
        }
        self.current_location = "出阵"
        self.maa = _Maa()
        self.march_calls = 0

    def navigate_to_stream(self, dest):
        yield f"nav→{dest}"

    def _click_point(self, pt):
        pass

    def _wait_for_team_select(self, cfg, attempts=12, open_after=2):
        return True

    def _pick_team(self, team_no):
        pass

    def _team_injury_status(self, cfg):
        return None

    def _save_team_record(self, cfg, record_no=1):
        return True

    def _enable_auto_march(self):
        self.march_calls += 1
        return True

    def _click_depart(self, cfg):
        return False


def _run(host, **kwargs):
    with patch("touken.flows.sortie.time.sleep"):
        return list(host.sortie_stream(chapter=1, map_no=1, team_no=3, **kwargs))


class RetreatAutoMarchGuardTests(unittest.TestCase):
    def test_retreat_forces_manual_march(self):
        # 面板只是隐藏开关不是清空：retreat=true 和 auto_march=true 可能同时
        # 到达引擎。撤退必须脚本盯小地图，委托一旦挂上撤退就静默失效。
        host = _Host()
        logs = _run(host, auto_march=True, retreat_before_boss=True)

        self.assertTrue(any("二选一" in msg for msg in logs))
        self.assertEqual(host.march_calls, 0)

    def test_without_retreat_delegates_normally(self):
        host = _Host()
        logs = _run(host, auto_march=True, retreat_before_boss=False)

        self.assertFalse(any("二选一" in msg for msg in logs))
        self.assertEqual(host.march_calls, 1)


class _PlateMaa:
    """badge=True 表示当前画面有刀派立牌（获得画面）；False 则没有"""

    def __init__(self, tokens, badge=True):
        self.tokens = tokens
        self.badge = badge

    def ocr(self, expected, roi, match_mode="exact"):
        if expected == "刀派" and self.badge and roi.to_list() == [1105, 40, 65, 120]:
            return Point(1135, 100)
        return None

    def ocr_all(self, roi):
        if roi.to_list() == [20, 630, 360, 75]:  # 左下对话框名牌区
            return list(self.tokens)
        return []


class DropSwordRecognitionTests(unittest.TestCase):
    def test_plate_with_type_prefix_matches(self):
        # 名牌整条读出「短刀 毛利藤四郎」，包含匹配接住名字
        flow = SortieMixin()
        flow.maa = _PlateMaa([("短刀 毛利藤四郎", Point(100, 660))])

        sword = flow._read_drop_sword()

        self.assertEqual(sword["name"], "毛利藤四郎")
        self.assertEqual(sword["sword_id"], "touken_142_mouri_toushirou")

    def test_garbage_and_school_name_never_match(self):
        # 「刀派」「粟田口」（右边刀派立牌）不是刀名，严格匹配不许乱认
        flow = SortieMixin()
        flow.maa = _PlateMaa([("刀派", Point(1, 1)), ("粟田口", Point(2, 2))])

        self.assertIsNone(flow._read_drop_sword())

    def test_result_screen_roster_card_is_not_a_drop(self):
        # 2026-08-24 事故：战斗结果页底部成员栏末位卡片落进名牌 ROI，
        # 「之六 博多藤四郎」被逐圈误记成掉落。没有刀派立牌就必须拒认。
        flow = SortieMixin()
        flow.maa = _PlateMaa(
            [("之六", Point(40, 660)), ("博多藤四郎", Point(150, 660))],
            badge=False)

        self.assertIsNone(flow._read_drop_sword())


if __name__ == "__main__":
    unittest.main()
