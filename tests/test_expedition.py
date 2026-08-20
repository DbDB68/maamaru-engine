import unittest

from touken.flows.expedition import ExpeditionMixin
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


if __name__ == "__main__":
    unittest.main()
