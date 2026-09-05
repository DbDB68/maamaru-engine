import unittest
from unittest.mock import patch

from touken.flows.sugar import SugarMixin


class Game:
    """Two same-name bodies: first needs two feeds, second needs one."""
    def __init__(self, timeout=False):
        self.state = "list"
        self.remaining = [2, 1]
        self.body = 0
        self.picks = 0
        self.feeds = 0
        self.timeout = timeout

    def screenshot(self, **kwargs):
        pass

    def template_match(self, name, *args, **kwargs):
        if name == "习合.png":
            return "tab"
        if name == "选择png.png" and self.state == "list" and self.body < 2:
            return "body"
        if name == "一键选择.png" and self.state == "materials" and self.remaining[self.body]:
            return "select"
        if name == "习合开始.png" and self.state == "selected":
            return "go"
        return None

    def ocr(self, text, *args):
        if text == "是否确认":
            return self.state == "confirm"
        return self.state == "materials"

    def click(self, target):
        if target == "tab":
            return
        if target == "body":
            self.picks += 1
            self.state = "materials"
        elif target == "select":
            self.state = "selected"
        elif target == "go":
            self.state = "confirm"
        elif self.state == "confirm":
            self.remaining[self.body] -= 1
            self.feeds += 1
            self.state = "animation" if self.timeout else "materials"
        elif self.state == "materials":
            self.body += 1
            self.state = "list"


class Flow(SugarMixin):
    def __init__(self, timeout=False):
        self.maa = Game(timeout)
        self.current_location = "强化"

    def navigate_to_stream(self, target):
        yield "navigate"


class SugarFlowTests(unittest.TestCase):
    @patch("touken.flows.sugar.time.sleep")
    def test_feed_current_body_then_pick_next_without_name_filter(self, sleep):
        flow = Flow()
        messages = list(flow._shugo_loop_stream(False))
        self.assertEqual(flow.maa.feeds, 3)
        self.assertEqual(flow.maa.picks, 2)
        self.assertIn("炼了 3 轮", messages[-1])

    @patch("touken.flows.sugar.time.sleep")
    def test_animation_timeout_does_not_count_success(self, sleep):
        flow = Flow(timeout=True)
        messages = []
        with self.assertRaisesRegex(RuntimeError, "超时"):
            for message in flow._shugo_loop_stream(False):
                messages.append(message)
        self.assertFalse(any("完成第" in message for message in messages))

    @patch("touken.flows.sugar.time.sleep")
    def test_dry_run_does_not_feed(self, sleep):
        flow = Flow()
        list(flow._shugo_loop_stream(True))
        self.assertEqual(flow.maa.feeds, 0)

    @patch("touken.flows.sugar.time.sleep")
    def test_progress_runs_past_sixty_feeds(self, sleep):
        flow = Flow()
        flow.maa.remaining = [80, 1]
        list(flow._shugo_loop_stream(False))
        self.assertEqual(flow.maa.feeds, 81)

    @patch("touken.flows.sugar.time.sleep")
    def test_repeated_unfeedable_body_stops(self, sleep):
        flow = Flow()
        flow.maa.remaining = [0, 0]
        original_click = flow.maa.click
        def click(target):
            original_click(target)
            if flow.maa.state == "list":
                flow.maa.body = 0
        flow.maa.click = click
        with self.assertRaisesRegex(RuntimeError, "持续没有进展"):
            list(flow._shugo_loop_stream(False))
        self.assertEqual(flow.maa.picks, 3)
