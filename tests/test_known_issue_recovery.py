import unittest
from unittest.mock import patch

from touken.flows.battle import BattleMixin
from touken.flows.daily import (
    DailyMixin,
    _equip_warning_status,
    _is_fail,
    _shop_report_status,
)
from touken.flows.rewards import RewardsMixin
from touken.maa_adapter import Point, _ocr_text_matches


class FakeMaa:
    def __init__(self, matches):
        self.matches = {name: list(values) for name, values in matches.items()}
        self.clicked = []
        self.screenshots = 0
        self.ocr_results = []

    def template_match(self, template):
        values = self.matches.get(template, [])
        return values.pop(0) if values else None

    def click(self, point):
        self.clicked.append(point)

    def screenshot(self, force=False):
        self.screenshots += 1

    def ocr(self, expected, roi):
        return self.ocr_results.pop(0) if self.ocr_results else None


class EquipWarningTests(unittest.TestCase):
    def test_warning_uses_prepare_and_returns_to_team_select(self):
        flow = BattleMixin()
        prepare = Point(420, 500)
        flow.maa = FakeMaa({
            "team/继续出阵.png": [Point(850, 500)],
            "team/整备刀装.png": [prepare],
        })
        flow.maa.ocr_results = [Point(640, 29)]

        with patch("touken.flows.battle.time.sleep"):
            result = flow._cancel_equip_warning({
                "equip_warning_button": {"template": "team/继续出阵.png"},
                "team_ui_ocr": {
                    "expected": "部队选择",
                    "roi": [506, 1, 774, 77],
                },
            })

        self.assertTrue(result)
        self.assertEqual(flow.maa.clicked, [prepare])

    def test_no_warning_does_nothing(self):
        flow = BattleMixin()
        flow.maa = FakeMaa({})
        result = flow._cancel_equip_warning({
            "equip_warning_button": {"template": "team/继续出阵.png"}
        })
        self.assertIsNone(result)
        self.assertEqual(flow.maa.clicked, [])


class DailyReportTests(unittest.TestCase):
    def test_equip_warning_is_not_green(self):
        msg = "[出阵] ⚠️ 刀装未满警告；已取消出阵并返回部队选择，本次跳过"
        self.assertTrue(_is_fail(msg))
        self.assertEqual(
            _equip_warning_status(msg),
            "⚠ 刀装未满，已取消出阵并跳过",
        )

    def test_failed_cancel_is_reported_as_failure(self):
        msg = "[出阵] ⚠️ 刀装未满警告；没能安全取消整备，本次出阵停止"
        self.assertEqual(
            _equip_warning_status(msg),
            "✗ 刀装未满，取消整备失败，出阵停止",
        )

    def test_daily_sortie_step_keeps_detailed_skip_reason(self):
        flow = DailyMixin()
        flow.raid_stream = lambda **kwargs: iter([
            "[RAID] ⚠️ 刀装未满警告；已取消出阵并返回部队选择，本次跳过"
        ])
        report = []

        list(flow._sortie_step({"sortie": {"mode": "raid"}}, report))

        self.assertEqual(report, [
            ("出阵(活动)", "⚠ 刀装未满，已取消出阵并跳过")
        ])

    def test_shop_sold_out_is_a_detailed_success(self):
        msg = "[SHOP] 今日暖心礼包已售罄，说明此前已经领取，跳过"
        self.assertFalse(_is_fail(msg))
        self.assertEqual(_shop_report_status(msg), "✓ 此前已领取（售罄）")

    def test_shop_recognition_failure_is_not_green(self):
        msg = "[SHOP] 暖心礼包未售罄，但未识别到领取按钮，本次未点击"
        self.assertTrue(_is_fail(msg))
        self.assertEqual(
            _shop_report_status(msg),
            "✗ 未识别到领取按钮，未点击",
        )


class ShopGiftTests(unittest.TestCase):
    def test_claim_button_roi_is_anchored_to_warm_gift_card(self):
        class Maa:
            def __init__(self):
                self.template_rois = []

            def screenshot(self, force=False):
                pass

            def ocr(self, expected, roi, match_mode="contains"):
                if expected == "暖心":
                    return Point(145, 145)
                return None

            def template_match(self, template, roi=None, threshold=0.7):
                self.template_rois.append((template, roi))
                return None

        class Flow(RewardsMixin):
            def __init__(self):
                self.current_location = "万屋"
                self.maa = Maa()
                self.config = {"shop": {"free_gift": {
                    "find_text": {"expected": "暖心", "roi": [0, 100, 700, 650]},
                    "claim_button": {"template": "领取.png"},
                    "sold_out": {"template": "售罄.png"},
                }}}

            def navigate_to_stream(self, location):
                return iter(())

        flow = Flow()
        list(flow.claim_free_gift_stream())
        rois = [roi for template, roi in flow.maa.template_rois
                if template == "领取.png"]
        self.assertTrue(rois)
        for roi in rois:
            self.assertEqual((roi.x, roi.y, roi.w, roi.h), (350, 265, 330, 95))
            self.assertLessEqual(roi.y + roi.h, 360)


class OcrMatchingTests(unittest.TestCase):
    def test_empty_ocr_result_never_matches(self):
        self.assertFalse(_ocr_text_matches("", "重伤", "contains"))
        self.assertFalse(_ocr_text_matches("   ", "重伤", "contains"))

    def test_existing_partial_match_behavior_is_preserved(self):
        self.assertTrue(_ocr_text_matches("暖心礼包", "暖心", "contains"))
        self.assertTrue(_ocr_text_matches("万", "万屋", "contains"))


if __name__ == "__main__":
    unittest.main()
