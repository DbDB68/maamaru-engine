import unittest
from unittest.mock import patch

from touken.flows.sortie import SortieMixin
from touken.maa_adapter import Point


class _Maa:
    def screenshot(self, force=False):
        pass

    def ocr(self, expected, roi, match_mode="contains"):
        return Point(1, 1) if expected in ("部队", "选择") else None

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
    """badge=True 表示当前画面有刀派立牌红徽（获得画面稀有款）；False 则没有。
    banner=True 表示掉刀预告横幅「发现了新的刀剑男士！」挂在画面上。
    tokens 可以是列表（每次一样）或列表的列表（按调用轮流出，模拟对话框晚滑入）"""

    def __init__(self, tokens, badge=True, banner=False):
        self.tokens = tokens
        self.badge = badge
        self.banner = banner
        self.calls = 0

    def ocr(self, expected, roi, match_mode="exact"):
        if expected == "刀派" and self.badge and roi.to_list() == [1105, 40, 65, 120]:
            return Point(1135, 100)
        if (expected == "新的刀剑男士" and self.banner
                and roi.to_list() == [100, 280, 1080, 180]):
            return Point(640, 370)
        return None

    def ocr_all(self, roi):
        if roi.to_list() == [0, 480, 430, 230]:  # 左下对话框名牌区（宽版）
            t = self.tokens
            if t and isinstance(t[0], list):  # 分帧剧本
                t = t[min(self.calls, len(t) - 1)]
            self.calls += 1
            return list(t)
        return []

    def screenshot(self, force=False):
        pass


class DropSwordRecognitionTests(unittest.TestCase):
    def test_plate_with_type_prefix_matches(self):
        # 名牌整条读出「短刀 毛利藤四郎」，刀种前缀+名册严格匹配接住
        flow = SortieMixin()
        flow.maa = _PlateMaa([("短刀 毛利藤四郎", Point(100, 660))])

        sword = flow._read_drop_sword()

        self.assertEqual(sword["name"], "毛利藤四郎")
        self.assertEqual(sword["sword_id"], "touken_142_mouri_toushirou")

    def test_plate_higher_layout_also_matches(self):
        # 不带立牌布局名牌偏上（2026-08-24 连拍：打刀 大和守安定），宽 ROI 罩住
        flow = SortieMixin()
        flow.maa = _PlateMaa([("打刀 大和守安定", Point(180, 530))], badge=False)

        sword = flow._read_drop_sword()

        self.assertEqual(sword["name"], "大和守安定")

    def test_split_type_and_name_tokens(self):
        # OCR 把刀种和名字拆成两条：有刀种在场，裸名也认
        flow = SortieMixin()
        flow.maa = _PlateMaa(
            [("打刀", Point(60, 530)), ("大和守安定", Point(180, 530))],
            badge=False)

        sword = flow._read_drop_sword()

        self.assertEqual(sword["name"], "大和守安定")

    def test_dialog_late_gets_retried(self):
        # 对话框晚半拍滑入：第一拍名牌区空、立牌在，重读后认到
        flow = SortieMixin()
        flow.maa = _PlateMaa(
            [[], [("短刀 毛利藤四郎", Point(100, 660))]], badge=True)

        with patch("touken.flows.sortie.time.sleep"):
            sword = flow._read_drop_sword()

        self.assertEqual(sword["name"], "毛利藤四郎")

    def test_garbage_and_school_name_never_match(self):
        # 「刀派」「粟田口」（右边刀派立牌）不是刀名，严格匹配不许乱认
        flow = SortieMixin()
        flow.maa = _PlateMaa([("刀派", Point(1, 1)), ("粟田口", Point(2, 2))])

        with patch("touken.flows.sortie.time.sleep"):
            self.assertIsNone(flow._read_drop_sword())

    def test_bare_name_on_obtain_screen_never_match(self):
        # 获得画面上名牌只读出裸名（没刀种前缀）也拒认：认错比认不到糟
        flow = SortieMixin()
        flow.maa = _PlateMaa([("大和守安定", Point(180, 530))], badge=True)

        with patch("touken.flows.sortie.time.sleep"):
            self.assertIsNone(flow._read_drop_sword())

    def test_result_screen_roster_card_is_not_a_drop(self):
        # 2026-08-24 事故：战斗结果页底部成员栏卡片落进名牌区，
        # 「之六 博多藤四郎」被逐圈误记成掉落。裸名没有刀种前缀就必须拒认。
        flow = SortieMixin()
        flow.maa = _PlateMaa(
            [("之六", Point(40, 660)), ("博多藤四郎", Point(150, 660))],
            badge=False)

        with patch("touken.flows.sortie.time.sleep"):
            self.assertIsNone(flow._read_drop_sword())

    def test_banner_waits_for_late_plate(self):
        # 掉刀预告横幅在、名牌还在转场动画里（裸立绘阶段名牌区全空）：
        # 耐心模式一直等到名牌到位，不许提前放弃让安全区点掉获得画面
        flow = SortieMixin()
        flow.maa = _PlateMaa(
            [[], [], [], [("打刀 蜂须贺虎彻", Point(180, 530))]],
            badge=False, banner=True)

        with patch("touken.flows.sortie.time.sleep"):
            sword = flow._read_drop_sword()

        self.assertIsNotNone(sword)
        self.assertEqual(sword["name"], "蜂须贺虎彻")
        self.assertEqual(flow.maa.calls, 4)  # 空拍全熬过来了

    def test_banner_but_plate_never_reads_gives_up_none(self):
        # 横幅在但名牌死活读不出来（极端情况）：耐心也有上限，认不到返回 None
        flow = SortieMixin()
        flow.maa = _PlateMaa([[]], badge=False, banner=True)

        with patch("touken.flows.sortie.time.sleep"):
            self.assertIsNone(flow._read_drop_sword())

        self.assertEqual(flow.maa.calls, 10)  # 耐心上限 10 拍

    def test_no_banner_no_badge_exits_fast(self):
        # 没横幅没立牌的普通画面（结果页/状态页）：两拍内快速退场，不拖慢行军圈
        flow = SortieMixin()
        flow.maa = _PlateMaa([[]], badge=False, banner=False)

        with patch("touken.flows.sortie.time.sleep"):
            self.assertIsNone(flow._read_drop_sword())

        self.assertEqual(flow.maa.calls, 2)  # 一拍宽限 + 一拍确认，就撤


if __name__ == "__main__":
    unittest.main()
