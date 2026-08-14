import unittest
from unittest.mock import patch

from panel.server import _build_daily, _build_osaka, _build_pumpkin, _build_raid, list_scripts


class FakeAgent:
    def __init__(self):
        self.daily_args = None
        self.pumpkin_args = None
        self.raid_args = None
        self.yosari_args = None
        self.osaka_args = None

    def daily_stream(self, **kwargs):
        self.daily_args = kwargs
        yield "daily"

    def pumpkin_stream(self, **kwargs):
        self.pumpkin_args = kwargs
        yield "pumpkin"

    def raid_stream(self, **kwargs):
        self.raid_args = kwargs
        yield "raid"

    def yosari_stream(self, **kwargs):
        self.yosari_args = kwargs
        yield "yosari"

    def osaka_stream(self, **kwargs):
        self.osaka_args = kwargs
        yield "osaka"


class PumpkinPlanTests(unittest.TestCase):
    def test_osaka_formation_mode_matches_the_sortie_panel_semantics(self):
        fields = list_scripts()["osaka"]["params"]
        by_key = {field["key"]: field for field in fields}
        self.assertEqual(by_key["formation_mode"]["options"],
                         [["manual", "手动阵形"], ["auto", "自动阵形"]])
        self.assertEqual(by_key["formation_strategy"]["visibleWhen"],
                         {"key": "formation_mode", "is": "manual"})
        self.assertEqual(by_key["formation"]["visibleWhen"],
                         {"key": "formation_mode", "is": "manual"})
        self.assertEqual(by_key["repair_threshold"]["options"],
                         [["light", "轻伤时停止"],
                          ["medium", "中伤时停止"],
                          ["heavy", "重伤时停止"]])
        self.assertEqual(by_key["repair_on_injury"]["options"][-1],
                         ["stop", "返回本丸，不进行手入"])
        self.assertTrue(by_key["auto_equip"]["default"])
        self.assertEqual(by_key["auto_equip"]["visibleWhen"],
                         {"key": "repair_on_injury", "is": "continue"})

        agent = FakeAgent()
        with patch("panel.server._make_agent", return_value=agent):
            list(_build_osaka("config.json", {
                "team_no": "3", "runs": "2", "formation_mode": "auto",
                "formation_strategy": "fixed", "formation": "逆行阵",
                "repair_threshold": "medium", "repair_on_injury": "repair_stop",
            }))
        self.assertEqual(agent.osaka_args["formation_mode"], "auto")
        self.assertEqual(agent.osaka_args["repair_threshold"], "medium")
        self.assertEqual(agent.osaka_args["injury_action"], "repair_stop")
        self.assertTrue(agent.osaka_args["auto_equip"])

    def test_four_sortie_forms_share_one_quantity_key(self):
        scripts = list_scripts()
        for name in ("raid", "pumpkin", "sortie", "yosari"):
            keys = [field.get("key") for field in scripts[name]["params"]]
            self.assertIn("runs", keys, name)
        for name in ("raid", "pumpkin"):
            keys = [field.get("key") for field in scripts[name]["params"]]
            self.assertNotIn("auto_march", keys, name)
            self.assertNotIn("repair_threshold", keys, name)
        for name in ("sortie", "yosari"):
            keys = [field.get("key") for field in scripts[name]["params"]]
            self.assertIn("auto_march", keys, name)
            self.assertIn("repair_threshold", keys, name)
            self.assertIn("auto_equip", keys, name)

    def test_yosari_uses_chapter_and_map_fields_like_sortie(self):
        fields = list_scripts()["yosari"]["params"]
        chapter = next(field for field in fields if field.get("key") == "chapter")
        map_no = next(field for field in fields if field.get("key") == "map_no")
        self.assertEqual(chapter["options"], [["1", "1章"]])
        self.assertEqual(map_no["options"],
                         [["1", "1图"], ["2", "2图"], ["3", "3图"], ["4", "4图"]])

    def test_sortie_forms_put_map_before_team_and_runs(self):
        scripts = list_scripts()
        expected = {
            "raid": ["map_no", "team_no", "runs", "auto_refill"],
            "pumpkin": ["difficulty", "team_no", "runs", "auto_refill"],
            "sortie": ["chapter", "map_no", "team_no", "runs"],
            "yosari": ["chapter", "map_no", "team_no", "runs"],
        }
        for name, prefix in expected.items():
            keys = [field.get("key") for field in scripts[name]["params"]]
            self.assertEqual(keys[:len(prefix)], prefix, name)
        self.assertNotIn("watch", [field.get("key") for field in scripts["pumpkin"]["params"]])

    def test_raid_selected_map_reaches_flow(self):
        agent = FakeAgent()
        with patch("panel.server._make_agent", return_value=agent):
            list(_build_raid("config.json", {"map_no": "2", "runs": "5", "team_no": "4"}))
        self.assertEqual(agent.raid_args["difficulty_no"], 2)
        self.assertEqual(agent.raid_args["max_rounds"], 5)
        self.assertEqual(agent.raid_args["team_no"], 4)
        self.assertFalse(agent.raid_args["auto_buy_ticket"])

    def test_standalone_form_uses_shared_run_count_field(self):
        fields = list_scripts()["pumpkin"]["params"]
        difficulty = next(field for field in fields if field.get("key") == "difficulty")
        budget = next(field for field in fields if field.get("key") == "runs")
        self.assertEqual(difficulty["default"], "1")
        self.assertEqual(budget["label"], "出阵次数")
        refill = next(field for field in fields if field.get("key") == "auto_refill")
        self.assertFalse(refill["default"])
        self.assertFalse(any(field.get("key") == "run_mode" for field in fields))

    def test_daily_pumpkin_plan_is_independent(self):
        agent = FakeAgent()
        params = {"sortie_mode": "pumpkin", "team_no": "2",
                  "pumpkin_difficulty": "2", "pumpkin_runs": "6",
                  "pumpkin_watch": ["三日月宗近"]}
        with patch("panel.server._make_agent", return_value=agent), patch(
            "panel.server._load_panel_settings", return_value={}
        ):
            list(_build_daily("config.json", params))

        plan = agent.daily_args["sortie_override"]
        self.assertEqual(plan, {"mode": "pumpkin", "difficulty": 2,
                                "team_no": 2, "watch_names": ["三日月宗近"],
                                "max_skips": 6})
        daily_modes = next(field for field in list_scripts()["daily"]["params"]
                           if field.get("key") == "sortie_mode")
        self.assertIn("pumpkin", [value for value, _ in daily_modes["options"]])
        self.assertEqual(daily_modes["default"], "none")

    def test_daily_can_schedule_yosari(self):
        agent = FakeAgent()
        params = {"sortie_mode": "yosari", "team_no": "4",
                  "yosari_map_no": "3", "yosari_runs": "8",
                  "yosari_auto_refill": True}
        saved = {"params": {"yosari": {"auto_march": False,
                                          "repair_threshold": "medium"}}}
        with patch("panel.server._make_agent", return_value=agent), patch(
            "panel.server._load_panel_settings", return_value=saved
        ):
            list(_build_daily("config.json", params))
        plan = agent.daily_args["sortie_override"]
        self.assertEqual(plan["mode"], "yosari")
        self.assertEqual(plan["map_no"], 3)
        self.assertEqual(plan["team_no"], 4)
        self.assertEqual(plan["loops"], 8)
        self.assertTrue(plan["auto_refill"])
        self.assertFalse(plan["auto_march"])
        self.assertEqual(plan["repair_threshold"], "medium")

    def test_standalone_plan_uses_targets_and_selected_handshape_budget(self):
        agent = FakeAgent()
        with patch("panel.server._make_agent", return_value=agent):
            list(_build_pumpkin("config.json", {
                "watch": "三日月宗近， 小狐丸", "team_no": "3", "runs": "12"
            }))

        self.assertEqual(agent.pumpkin_args["watch_names"], ["三日月宗近", "小狐丸"])
        self.assertEqual(agent.pumpkin_args["max_skips"], 12)
        self.assertFalse(agent.pumpkin_args["auto_refill"])

    def test_ticket_refill_choice_reaches_raid_but_pumpkin_stays_safe(self):
        agent = FakeAgent()
        with patch("panel.server._make_agent", return_value=agent):
            list(_build_raid("config.json", {"runs": "99", "auto_refill": True}))
            list(_build_pumpkin("config.json", {"runs": "99", "auto_refill": True}))
        self.assertTrue(agent.raid_args["auto_buy_ticket"])
        self.assertFalse(agent.pumpkin_args["auto_refill"])

    def test_old_token_budget_is_still_read(self):
        agent = FakeAgent()
        with patch("panel.server._make_agent", return_value=agent):
            list(_build_pumpkin("config.json", {"max_skips": "7"}))
        self.assertEqual(agent.pumpkin_args["max_skips"], 7)


if __name__ == "__main__":
    unittest.main()
