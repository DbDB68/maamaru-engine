import unittest
from unittest.mock import patch

from touken.flows.battle import BattleMixin
from touken.flows.daily import (
    DailyMixin,
    _equip_warning_status,
    _is_fail,
    _is_success_status,
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

    def test_detailed_shop_success_is_green_in_final_report(self):
        self.assertTrue(_is_success_status("✓ 本次领取成功"))
        self.assertTrue(_is_success_status("✓ 此前已领取（售罄）"))
        self.assertFalse(_is_success_status("✗ 未识别到领取按钮，未点击"))
        self.assertFalse(_is_success_status("⚠ 刀装未满，已取消出阵并跳过"))

    def test_shop_recognition_failure_is_not_green(self):
        msg = "[SHOP] 暖心礼包未售罄，但未识别到领取按钮，本次未点击"
        self.assertTrue(_is_fail(msg))
        self.assertEqual(
            _shop_report_status(msg),
            "✗ 未识别到领取按钮，未点击",
        )

    def test_daily_expedition_dispatches_idle_teams_from_common_plan(self):
        flow = DailyMixin()
        flow.collect_expedition_stream = lambda redispatch=None: iter(["collected"])
        dispatched = []
        flow.expedition_stream = lambda **kwargs: (
            dispatched.append(kwargs) or iter(["dispatched"]))
        routes = [{"team_no": 2, "map_code": "B2", "map_name": "测试图",
                   "era": 2, "map_slot": 2}]

        with patch("touken.flows.expedition._load_exp_record", return_value={}):
            messages = list(flow._daily_expedition_step(routes))

        self.assertEqual(dispatched, [{"era": 2, "map_slot": 2, "team_no": 2}])
        self.assertIn("collected", messages)

    def test_daily_expedition_does_not_touch_team_still_away(self):
        flow = DailyMixin()
        flow.collect_expedition_stream = lambda redispatch=None: iter(())
        dispatched = []
        flow.expedition_stream = lambda **kwargs: (
            dispatched.append(kwargs) or iter(()))
        routes = [{"team_no": 2, "map_code": "B2", "map_name": "测试图",
                   "era": 2, "map_slot": 2}]
        future_record = {"2": {
            "dispatched_at": "2099-01-01 00:00:00", "duration_min": 60,
        }}

        with patch("touken.flows.expedition._load_exp_record",
                   return_value=future_record):
            messages = list(flow._daily_expedition_step(routes))

        self.assertFalse(dispatched)
        self.assertTrue(any("仍在外面" in message for message in messages))


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


class TaskRewardTests(unittest.TestCase):
    class Maa:
        def __init__(self, active_first=False, inactive=False):
            self.active_first = active_first
            self.inactive = inactive
            self.active_calls = 0
            self.clicked = []

        def screenshot(self, force=False):
            pass

        def template_match(self, template, roi=None, threshold=0.7):
            if template == "一键领取.png":
                self.active_calls += 1
                return Point(1165, 620) if self.active_first and self.active_calls == 1 else None
            if template == "一键领取_灰.png":
                return Point(1165, 620) if self.inactive else None
            return None

        def exists(self, template):
            return False

        def click(self, point):
            self.clicked.append(point)

    def _flow(self, maa):
        flow = RewardsMixin()
        flow.maa = maa
        flow.current_location = "任务"
        flow.config = {"task_reward": {
            "tabs": {"日常": [48, 204]},
            "claim_button": {"template": "一键领取.png"},
        }}
        flow.navigate_to_stream = lambda location: iter(())
        flow._click_point = lambda point: None
        flow.events = []
        flow.record_event = lambda kind, **payload: flow.events.append((kind, payload))
        return flow

    def test_claim_is_counted_only_after_button_turns_gray(self):
        flow = self._flow(self.Maa(active_first=True, inactive=True))
        with patch("touken.flows.rewards.time.sleep"):
            messages = list(flow.claim_task_rewards_stream())

        self.assertIn(("task_rewards.claimed", {"tab": "日常"}), flow.events)
        self.assertTrue(any("已确认按钮变灰" in msg for msg in messages))

    def test_gray_button_records_no_reward_without_counting_claim(self):
        flow = self._flow(self.Maa(inactive=True))
        with patch("touken.flows.rewards.time.sleep"):
            messages = list(flow.claim_task_rewards_stream())

        self.assertEqual(flow.events, [("task_rewards.none", {"tab": "日常"})])
        self.assertTrue(any("已确认没有可领奖励" in msg for msg in messages))

    def test_reward_popup_confirms_claim_when_gray_button_is_late(self):
        flow = self._flow(self.Maa(active_first=True, inactive=False))
        flow._read_reward_popup = lambda: ([("木炭", 1050)], [])
        flow._emit_reward_popup_changes = lambda items, event_id: flow.events.append(
            ("popup.resources", {"items": items}))
        with patch("touken.flows.rewards.time.sleep"):
            messages = list(flow.claim_task_rewards_stream())

        self.assertIn(("task_rewards.claimed", {"tab": "日常"}), flow.events)
        self.assertIn(("popup.resources", {"items": [("木炭", 1050)]}), flow.events)
        self.assertTrue(any("已确认报酬弹窗" in msg for msg in messages))

    def test_late_reward_popup_still_confirms_claim(self):
        """弹窗比首次读取慢（安装版实测月常/活动）：等待窗口里弹出来也算领到。"""
        maa = self.Maa(active_first=True, inactive=False)
        maa.exists = lambda template: template == "ui完成任务.png"
        flow = self._flow(maa)
        reads = []

        def fake_read():
            reads.append(1)
            # 首次读时弹窗还没弹；等待窗口里二次读才有
            return None if len(reads) == 1 else ([("玉钢", 800)], [])

        flow._read_reward_popup = fake_read
        with patch("touken.flows.rewards.time.sleep"):
            messages = list(flow.claim_task_rewards_stream())

        self.assertIn(("task_rewards.claimed", {"tab": "日常"}), flow.events)
        self.assertTrue(any("已确认报酬弹窗" in msg for msg in messages))
        self.assertFalse(any("未确认领取成功" in msg for msg in messages))

    def test_unknown_button_state_is_not_clicked_or_counted(self):
        maa = self.Maa()
        flow = self._flow(maa)
        with patch("touken.flows.rewards.time.sleep"):
            messages = list(flow.claim_task_rewards_stream())

        self.assertEqual(flow.events, [("task_rewards.unconfirmed", {
            "tab": "日常", "stage": "before_click",
        })])
        self.assertFalse(maa.clicked)
        self.assertTrue(any("不点击也不计成绩" in msg for msg in messages))


class OcrMatchingTests(unittest.TestCase):
    def test_empty_ocr_result_never_matches(self):
        self.assertFalse(_ocr_text_matches("", "重伤", "contains"))
        self.assertFalse(_ocr_text_matches("   ", "重伤", "contains"))

    def test_existing_partial_match_behavior_is_preserved(self):
        self.assertTrue(_ocr_text_matches("暖心礼包", "暖心", "contains"))
        self.assertTrue(_ocr_text_matches("万", "万屋", "contains"))


if __name__ == "__main__":
    unittest.main()
