import unittest
from unittest.mock import patch

from touken.flows.expedition import ExpeditionMixin
from touken.flows.report_judge import _is_fail
from touken.maa_adapter import Point


class ExpeditionRewardTests(unittest.TestCase):
    def test_reads_positive_resources_and_success_result(self):
        class Maa:
            def __init__(self):
                self.responses = iter([
                    [("15", Point(900, 500))],
                    [("2", Point(890, 550)), ("2", Point(905, 550))],
                    [("0", Point(900, 600))],
                    [("0", Point(900, 650))],
                    [("大成功", Point(800, 90))],
                ])

            def ocr_all(self, roi):
                return next(self.responses)

        flow = ExpeditionMixin()
        flow.maa = Maa()
        rewards, result = flow._read_settlement_rewards({})

        self.assertEqual(rewards, {"木炭": 15, "玉钢": 22})
        self.assertEqual(result, "大成功")

    def test_skips_only_the_unreadable_resource(self):
        class Maa:
            def __init__(self):
                self.responses = iter([
                    [("15", Point(900, 500))], [],
                    [("8", Point(900, 600))],
                    [("0", Point(900, 650))],
                    [("成功", Point(800, 90))],
                ])

            def ocr_all(self, roi):
                return next(self.responses)

        flow = ExpeditionMixin()
        flow.maa = Maa()
        rewards, result = flow._read_settlement_rewards({})

        self.assertEqual(rewards, {"木炭": 15, "冷却材": 8})
        self.assertEqual(result, "成功")


class DispatchVerifyTests(unittest.TestCase):
    """派遣选图验证（2026-09-07 加固）：时代卡/卡位是盲点坐标，
    选完必须全屏 OCR 看到目标图名，否则怕派错队伍不许往下走。"""

    class Maa:
        def __init__(self, map_visible=True):
            self.map_visible = map_visible
            self.ocr_clicks = []

        def screenshot(self, force=False):
            pass

        def click(self, pt):
            self.ocr_clicks.append((pt.x, pt.y))

        def ocr(self, expected, roi, match_mode="contains"):
            return Point(1, 1)

        def ocr_all(self, roi):
            if self.map_visible:
                return [("鸟羽伏见之战", Point(300, 200))]
            return [("全然无关的字", Point(300, 200))]

        def template_match(self, template, roi=None, threshold=0.7):
            return None

        def exists(self, template):
            return False

    CONFIG = {
        "expedition": {
            "eras": {"1": [100, 100]},
            "map_ocr_roi": [0, 100, 1280, 400],
            "team_ui_ocr": {"expected": "部队选择", "roi": [506, 1, 774, 77]},
            "injury_stamp": {"template": "重伤.png"},
            "start_button": {"template": "远征开始.png"},
            "start_ocr": {"expected": "远征开始", "roi": [1000, 600, 1279, 719]},
            "confirm_ocr": {"expected": "确认", "roi": [600, 400, 900, 600]},
            "running_ocr": {"expected": "远征中", "roi": [0, 100, 1280, 400]},
        },
        "team_select": {"teams": {"2": [274, 91]}},
    }

    def _flow(self, maa):
        config = dict(self.CONFIG)

        class Flow(ExpeditionMixin):
            def __init__(self):
                self.maa = maa
                self.config = config
                self.current_location = "远征"
                self.point_clicks = []

            def navigate_to_stream(self, dest):
                return iter(())

            def _click_point(self, pt):
                self.point_clicks.append(tuple(pt))

            def _find_deploy_button(self, cfg):
                return None

        return Flow()

    def test_wrong_map_selection_is_blocked(self):
        # 选完图全屏对不上名字：重选一次仍对不上 → 停，绝不点远征开始
        maa = self.Maa(map_visible=False)
        flow = self._flow(maa)
        with patch("touken.flows.expedition.time.sleep"):
            logs = list(flow.expedition_stream(era=1, map_name="鸟羽", team_no=2))

        fails = [m for m in logs if "怕派错队伍" in m]
        self.assertTrue(fails)
        self.assertTrue(_is_fail(fails[-1]))
        self.assertEqual(maa.ocr_clicks, [(1, 1), (1, 1)])  # 只有两次点小图名

    def test_confirmed_map_dispatches_normally(self):
        # 图名对得上 → 一路走到"已出发"
        maa = self.Maa(map_visible=True)
        flow = self._flow(maa)
        with patch("touken.flows.expedition.time.sleep"):
            logs = list(flow.expedition_stream(era=1, map_name="鸟羽", team_no=2))

        self.assertTrue(any("已出发" in m for m in logs))


if __name__ == "__main__":
    unittest.main()
