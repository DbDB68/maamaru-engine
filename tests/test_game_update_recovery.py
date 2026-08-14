import unittest
from unittest.mock import patch

from touken.flows.login import LoginMixin
from touken.flows.daily import DailyMixin
from touken.maa_adapter import Point


class UpdateMaa:
    def __init__(self, line="线路一"):
        self.stage = "prompt"
        self.line = line
        self.clicks = []

    def screenshot(self, force=False):
        return object()

    def ocr_all(self, roi):
        if self.stage == "prompt":
            return [("检测到更新，请重新启动游戏进行更新", Point(640, 320))]
        return []

    def template_match(self, template, roi=None, threshold=0.7):
        if template == "通用_确定.png" and self.stage == "prompt":
            return Point(640, 468)
        if template == "登录.png" and self.stage == "login":
            return Point(640, 600)
        return None

    def exists(self, template, roi=None, threshold=0.7):
        return template == "目录.png" and self.stage == "home"

    def ocr(self, expected, roi, match_mode="exact"):
        if self.stage == "line" and expected == self.line:
            return Point(640, 420)
        return None

    def click(self, point):
        self.clicks.append(point)
        if self.stage == "prompt":
            self.stage = "login"
        elif self.stage == "login":
            self.stage = "line"
        elif self.stage == "line":
            self.stage = "home"


class UpdateFlow(LoginMixin):
    def __init__(self, maa):
        self.maa = maa
        self.current_location = None


class DailyUpdateFlow(DailyMixin, LoginMixin):
    def __init__(self, maa):
        self.maa = maa
        self.current_location = None
        self.sweeps = 0

    def _popup_sweep(self, max_rounds=30):
        self.sweeps += 1
        return True


def generator_result(generator):
    while True:
        try:
            next(generator)
        except StopIteration as stop:
            return stop.value


class GameUpdateRecoveryTests(unittest.TestCase):
    def test_prompt_guard_requires_update_and_restart_words(self):
        maa = UpdateMaa()
        flow = UpdateFlow(maa)
        self.assertTrue(flow._game_update_prompt_visible())
        maa.stage = "login"
        self.assertFalse(flow._game_update_prompt_visible())

    def test_recovers_through_login_and_primary_line(self):
        maa = UpdateMaa("线路一")
        flow = UpdateFlow(maa)
        with patch("touken.flows.login.time.sleep"):
            self.assertTrue(generator_result(flow.recover_game_update_stream()))
        self.assertEqual(len(maa.clicks), 3)
        self.assertEqual(flow.current_location, "本丸")

    def test_falls_back_to_secondary_line(self):
        maa = UpdateMaa("线路二")
        flow = UpdateFlow(maa)
        with patch("touken.flows.login.time.sleep"):
            self.assertTrue(generator_result(flow.recover_game_update_stream()))
        self.assertEqual(len(maa.clicks), 3)
        self.assertEqual(flow.current_location, "本丸")

    def test_daily_gate_recovers_before_navigation_and_cleans_popups(self):
        maa = UpdateMaa("线路一")
        flow = DailyUpdateFlow(maa)
        with patch("touken.flows.login.time.sleep"):
            self.assertTrue(generator_result(flow._daily_update_gate()))
        self.assertEqual(flow.sweeps, 1)
        self.assertEqual(flow.current_location, "本丸")


if __name__ == "__main__":
    unittest.main()
