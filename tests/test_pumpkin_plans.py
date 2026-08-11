import unittest
from unittest.mock import patch

from panel.server import _build_daily, _build_pumpkin


class FakeAgent:
    def __init__(self):
        self.daily_args = None
        self.pumpkin_args = None

    def daily_stream(self, **kwargs):
        self.daily_args = kwargs
        yield "daily"

    def pumpkin_stream(self, **kwargs):
        self.pumpkin_args = kwargs
        yield "pumpkin"


class PumpkinPlanTests(unittest.TestCase):
    def test_daily_pumpkin_is_always_four_without_watch_list(self):
        agent = FakeAgent()
        params = {
            "sortie_mode": "pumpkin",
            "team_no": "2",
            "pumpkin_watch": "旧名单不应读取",
            "pumpkin_max_skips": 99,
        }
        with patch("panel.server._make_agent", return_value=agent), patch(
            "panel.server._load_panel_settings", return_value={}
        ):
            list(_build_daily("config.json", params))

        plan = agent.daily_args["sortie_override"]
        self.assertEqual(plan["team_no"], 2)
        self.assertEqual(plan["watch_names"], [])
        self.assertEqual(plan["max_skips"], 4)

    def test_standalone_daily_plan_ignores_farm_targets(self):
        agent = FakeAgent()
        with patch("panel.server._make_agent", return_value=agent):
            list(_build_pumpkin("config.json", {
                "run_mode": "daily", "watch": "三日月宗近", "team_no": "3"
            }))

        self.assertIsNone(agent.pumpkin_args["watch_names"])
        self.assertEqual(agent.pumpkin_args["max_skips"], 4)

    def test_standalone_farm_plan_uses_targets_and_99_tokens(self):
        agent = FakeAgent()
        with patch("panel.server._make_agent", return_value=agent):
            list(_build_pumpkin("config.json", {
                "run_mode": "farm", "watch": "三日月宗近， 小狐丸", "team_no": "3"
            }))

        self.assertEqual(agent.pumpkin_args["watch_names"], ["三日月宗近", "小狐丸"])
        self.assertEqual(agent.pumpkin_args["max_skips"], 99)


if __name__ == "__main__":
    unittest.main()
