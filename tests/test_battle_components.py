import unittest
from unittest.mock import patch

from touken.flows.battle import BattleMixin
from touken.flows.sortie import SortieMixin
from touken.flows.osaka import OsakaMixin
from touken.maa_adapter import Point


class FakeMaa:
    def __init__(self, ocr_results=None, templates=None):
        self.ocr_results = iter(ocr_results or [])
        self.templates = dict(templates or {})
        self.clicks = []
        self.ocr_calls = []
        self.template_calls = []
        self.template_thresholds = []

    def screenshot(self, force=False):
        return None

    def ocr(self, expected, roi):
        self.ocr_calls.append(expected)
        return next(self.ocr_results, False)

    def template_match(self, template, roi=None, threshold=0.7):
        self.template_calls.append((template, roi))
        self.template_thresholds.append((template, threshold))
        return self.templates.get(template)

    def click(self, point):
        self.clicks.append(point)


class Flow(BattleMixin):
    def __init__(self, maa):
        self.maa = maa
        self.config = {
            "team_select": {
                "teams": {"3": [394, 91]},
            },
        }
        self.points = []

    def _click_point(self, point):
        self.points.append(point)


class BattleComponentTests(unittest.TestCase):
    @staticmethod
    def _record_flow(start="team", save_auto_return=True, yes_template=True):
        points = {
            "record": Point(1200, 145), "save": Point(480, 85),
            "load": Point(740, 85), "yes": Point(784, 510),
            "warning": Point(780, 510), "prepare": Point(500, 510),
        }

        class Maa:
            def __init__(self):
                self.state = start
                self.clicked = []

            def screenshot(self, force=False):
                return object()

            def template_match(self, template, roi=None, threshold=0.7):
                if template == "team/继续出阵.png" and self.state == "warning":
                    return points["warning"]
                if template == "team/整备刀装.png" and self.state == "warning":
                    return points["prepare"]
                if template == "team/部队记录.png" and self.state in ("team", "formation"):
                    return points["record"]
                if template == "team/进行记录.png" and self.state == "record":
                    return points["save"]
                if template == "team/使用记录.png" and self.state == "record":
                    return points["load"]
                if (template == "team/是.png" and yes_template
                        and self.state.startswith("confirm")):
                    return points["yes"]
                return None

            def ocr_all(self, roi):
                if self.state == "confirm_save":
                    return [("部队记录", Point(640, 170)),
                            ("是否记录到记录部队一中", Point(640, 340))]
                if self.state == "confirm_load":
                    return [("部队记录", Point(640, 170)),
                            ("是否使用记录部队一", Point(640, 340))]
                return []

            def click(self, point):
                self.clicked.append(point)
                if point == points["prepare"]:
                    self.state = "formation"
                elif point == points["record"]:
                    self.state = "record"
                elif point == points["save"]:
                    self.state = "confirm_save"
                elif point == points["load"]:
                    self.state = "confirm_load"
                elif point == points["yes"]:
                    self.state = ("team" if self.state == "confirm_load"
                                  or save_auto_return else "record")
                elif point == Point(73, 31) and self.state == "record":
                    self.state = "team"
                return True

            def ocr(self, expected, roi, match_mode="contains"):
                return Point(640, 30) if self.state == "team" else None

        class RecordFlow(BattleMixin):
            def __init__(self):
                self.maa = Maa()
                self.config = {"team_select": {"team_record": {
                    "button": {"template": "team/部队记录.png"},
                    "records": {"1": [1225, 179]},
                    "save_confirm": {"template": "team/进行记录.png"},
                    "load_confirm": {"template": "team/使用记录.png"},
                    "yes_button": {"template": "team/是.png"},
                }}}

            def _click_template_config(self, config):
                point = self.maa.template_match(config.get("template"))
                return self.maa.click(point) if point else False

            def _click_point(self, target):
                return self.maa.click(Point(*target))

        return RecordFlow()

    def test_saves_current_team_to_record_one_and_returns_to_team_select(self):
        flow = self._record_flow("team")
        cfg = {"team_ui_ocr": {"expected": "部队选择", "roi": [0, 0, 10, 10]}}
        with patch("touken.flows.battle.time.sleep"):
            self.assertTrue(flow._save_team_record(cfg, record_no=1))
        self.assertEqual(flow.maa.state, "team")
        self.assertIn(Point(1225, 179), flow.maa.clicked)

    def test_warning_restores_record_one_through_formation_screen(self):
        flow = self._record_flow("warning")
        cfg = {
            "equip_warning_button": {"template": "team/继续出阵.png"},
            "team_ui_ocr": {"expected": "部队选择", "roi": [0, 0, 10, 10]},
        }
        with patch("touken.flows.battle.time.sleep"):
            self.assertTrue(flow._restore_equipment_from_warning(cfg, record_no=1))
        self.assertEqual(flow.maa.state, "team")
        self.assertIn(Point(500, 510), flow.maa.clicked)
        self.assertIn(Point(740, 85), flow.maa.clicked)

    def test_save_uses_back_when_record_page_does_not_close_itself(self):
        flow = self._record_flow("team", save_auto_return=False)
        cfg = {"team_ui_ocr": {"expected": "部队选择", "roi": [0, 0, 10, 10]}}
        with patch("touken.flows.battle.time.sleep"):
            self.assertTrue(flow._save_team_record(cfg, record_no=1))
        self.assertEqual(flow.maa.state, "team")
        self.assertIn(Point(73, 31), flow.maa.clicked)

    def test_record_confirmation_uses_guarded_fallback_when_yes_template_changes(self):
        flow = self._record_flow("team", yes_template=False)
        cfg = {"team_ui_ocr": {"expected": "部队选择", "roi": [0, 0, 10, 10]}}
        with patch("touken.flows.battle.time.sleep"):
            self.assertTrue(flow._save_team_record(cfg, record_no=1))
        self.assertEqual(flow.maa.state, "team")
        self.assertIn(Point(784, 510), flow.maa.clicked)

    def test_injury_templates_are_restricted_to_our_team_side(self):
        flow = Flow(FakeMaa(templates={"battle/轻伤.png": Point(200, 150)}))
        cfg = {
            "injury_stamps": {
                "重伤": {"template": "battle/ui重伤.png"},
                "中伤": {"template": "battle/中伤.png"},
                "轻伤": {"template": "battle/轻伤.png"},
            },
            "injury_status_roi": [0, 90, 570, 690],
        }
        self.assertEqual(flow._team_injury_status(cfg), "轻伤")
        self.assertTrue(flow.maa.template_calls)
        for _, roi in flow.maa.template_calls:
            self.assertEqual((roi.x, roi.y, roi.w, roi.h),
                             (220, 90, 120, 600))
        self.assertTrue(all(threshold == 0.88
                            for _, threshold in flow.maa.template_thresholds))

    def test_partial_injury_ocr_never_promotes_hurt_to_heavy(self):
        class Maa(FakeMaa):
            def ocr_all(self, roi):
                return [("伤", Point(290, 153))]

        flow = Flow(Maa())
        self.assertIsNone(flow._team_injury_status({"injury_stamps": {}}))

    def test_medium_stamp_cannot_be_claimed_by_low_score_heavy_template(self):
        class Maa(FakeMaa):
            scores = {
                "battle/ui重伤.png": 0.704,
                "battle/中伤.png": 0.96,
                "battle/轻伤.png": 0.80,
            }

            def template_match(self, template, roi=None, threshold=0.7):
                self.template_thresholds.append((template, threshold))
                return Point(282, 147) if self.scores[template] >= threshold else None

            def ocr_all(self, roi):
                return []

        cfg = {"injury_stamps": {
            "重伤": {"template": "battle/ui重伤.png"},
            "中伤": {"template": "battle/中伤.png"},
            "轻伤": {"template": "battle/轻伤.png"},
        }}
        flow = Flow(Maa())

        self.assertEqual(flow._team_injury_status(cfg), "中伤")
        self.assertEqual(flow.maa.template_thresholds[:2], [
            ("battle/ui重伤.png", 0.88),
            ("battle/中伤.png", 0.88),
        ])

    def test_heavy_march_warning_always_chooses_no_in_scoped_roi(self):
        deny = Point(500, 520)
        flow = Flow(FakeMaa(templates={"否.png": deny}))
        with patch("touken.flows.battle.time.sleep"):
            self.assertTrue(flow._deny_heavy_injury_warning({
                "injury_deny_button": {"template": "否.png"},
            }))
        self.assertEqual(flow.maa.clicks, [deny])
        template, roi = flow.maa.template_calls[-1]
        self.assertEqual(template, "否.png")
        self.assertEqual((roi.x, roi.y, roi.w, roi.h), (330, 400, 320, 220))
        self.assertEqual(flow.maa.template_thresholds[-1], ("否.png", 0.75))

    def test_full_injury_ocr_keeps_medium_injury_as_medium(self):
        class Maa(FakeMaa):
            def ocr_all(self, roi):
                return [("米中伤", Point(290, 153))]

        flow = Flow(Maa())
        self.assertEqual(
            flow._team_injury_status({"injury_stamps": {}}), "中伤")

    def test_formation_state_uses_the_two_status_templates(self):
        auto = Point(910, 32)
        title = Point(640, 24)
        flow = Flow(FakeMaa(templates={
            "battle/ui阵形选择.png": title,
            "battle/阵形选择自动.png": auto,
        }))
        flow.config["formation"] = {"auto_mode": {}}
        self.assertEqual(flow._formation_mode_state(), "auto")

        manual = Point(910, 32)
        flow = Flow(FakeMaa(templates={
            "battle/ui阵形选择.png": title,
            "battle/阵形选择手动.png": manual,
        }))
        flow.config["formation"] = {"auto_mode": {}}
        self.assertEqual(flow._formation_mode_state(), "manual")

    def test_manual_formation_switches_from_auto_then_selects_fixed(self):
        flow = Flow(FakeMaa(templates={
            "battle/ui阵形选择.png": Point(640, 24),
            "battle/阵形选择自动.png": Point(910, 32),
        }))
        flow.config["formation"] = {
            "auto_mode": {"toggle": [910, 32]},
            "formations": {"逆行阵": [1034, 420]},
            "double_click": True,
        }
        with patch("touken.flows.battle.time.sleep"):
            self.assertEqual(flow.choose_formation(
                formation_name="逆行阵", enable_auto=False), "fixed")
        self.assertEqual(flow.points, [[910, 32], [1034, 420], [1034, 420]])

    def test_auto_formation_switches_from_manual_without_clicking_fixed(self):
        flow = Flow(FakeMaa(templates={
            "battle/ui阵形选择.png": Point(640, 24),
            "battle/阵形选择手动.png": Point(910, 32),
        }))
        flow.config["formation"] = {
            "auto_mode": {"toggle": [910, 32]},
            "formations": {"逆行阵": [1034, 420]},
        }
        with patch("touken.flows.battle.time.sleep"):
            self.assertEqual(flow.choose_formation(
                formation_name="逆行阵", enable_auto=True), "auto")
        self.assertEqual(flow.points, [[910, 32]])

    def test_formation_status_alone_during_battle_is_not_a_selection_screen(self):
        flow = Flow(FakeMaa(templates={
            "battle/阵形选择手动.png": Point(910, 32),
        }))
        flow.config["formation"] = {"auto_mode": {}}

        self.assertIsNone(flow._formation_mode_state())
        self.assertEqual(flow.points, [])

    def test_auto_status_without_title_can_only_be_used_to_switch_to_manual(self):
        flow = Flow(FakeMaa(templates={
            "battle/阵形选择自动.png": Point(910, 32),
        }))
        flow.config["formation"] = {"auto_mode": {}}

        self.assertEqual(
            flow._formation_mode_state(allow_auto_without_title=True), "auto")
        self.assertIsNone(flow._formation_mode_state())
        self.assertIn(("battle/阵形选择自动.png", 0.9),
                      flow.maa.template_thresholds)

    def test_wait_for_team_select_can_open_the_panel(self):
        deploy = Point(100, 200)
        maa = FakeMaa(
            ocr_results=[False, False, True],
            templates={"team/部队选择.png": deploy},
        )
        flow = Flow(maa)
        cfg = {
            "team_ui_ocr": {"expected": "部队选择", "roi": [0, 0, 10, 10]},
            "deploy_button": {"template": "team/部队选择.png"},
        }

        self.assertTrue(flow._wait_for_team_select(cfg, attempts=3, open_after=1))
        self.assertEqual(maa.clicks, [deploy])

    def test_pick_team_uses_the_shared_team_coordinates(self):
        flow = Flow(FakeMaa())

        self.assertTrue(flow._pick_team(3))
        self.assertEqual(flow.points, [[394, 91], [394, 91]])
        self.assertFalse(flow._pick_team(5))

    def test_depart_requires_the_button_to_be_visible(self):
        depart = Point(1198, 625)
        flow = Flow(FakeMaa(templates={"team/即刻出阵.png": depart}))

        self.assertTrue(flow._click_depart({
            "depart_button": {"template": "team/即刻出阵.png"},
        }))
        self.assertEqual(flow.maa.clicks, [depart])
        self.assertFalse(flow._click_depart({"depart_button": {}}))

    def test_ticket_refill_is_a_shared_three_step_flow(self):
        refill = Point(100, 100)
        recover = Point(200, 200)
        confirm = Point(300, 300)
        flow = Flow(FakeMaa(templates={
            "补充.png": refill,
            "恢复一个.png": recover,
            "确定.png": confirm,
        }))
        cfg = {"ticket_recover": {
            "popup_button": {"template": "补充.png"},
            "recover_button": {"template": "恢复一个.png"},
            "confirm_button": {"template": "确定.png"},
        }}
        with patch("touken.flows.battle.time.sleep"):
            messages = list(flow._recover_ticket_stream(cfg, tag="[异去]"))
        self.assertTrue(flow._recover_ok)
        self.assertEqual(flow.maa.clicks, [refill, recover, confirm])
        self.assertEqual(messages, ["[异去] 手形补充完成"])


class YosariRouteTests(unittest.TestCase):
    @staticmethod
    def _drain(generator):
        messages = []
        while True:
            try:
                messages.append(next(generator))
            except StopIteration as done:
                return messages, done.value

    def test_yosari_reuses_the_map_sortie_pipeline(self):
        class Route(SortieMixin):
            def _map_sortie_stream(self, **kwargs):
                self.route = kwargs
                yield "route"

        flow = Route()
        self.assertEqual(list(flow.yosari_stream(map_no=4, team_no=2)), ["route"])
        self.assertEqual(flow.route["map_type"], "异去")
        self.assertEqual(flow.route["cfg_key"], "yosari")
        self.assertEqual(flow.route["chapter"], 1)
        self.assertEqual(flow.route["map_no"], 4)
        self.assertEqual(flow.route["team_no"], 2)

    def test_round_ends_only_when_title_and_team_button_are_both_visible(self):
        class Route(SortieMixin):
            pass

        cfg = {
            "entry": {"expected": "归城提灯", "verify_roi": [0, 0, 10, 10]},
            "deploy_button": {"template": "team/部队选择.png"},
        }
        flow = Route()
        flow.maa = FakeMaa(
            ocr_results=[True],
            templates={"team/部队选择.png": Point(1200, 640)},
        )
        self.assertTrue(flow._yosari_round_done(cfg))

        flow.maa = FakeMaa(ocr_results=[True])
        self.assertFalse(flow._yosari_round_done(cfg))

    def test_manual_march_uses_the_button_template_not_partial_ocr(self):
        class Route(SortieMixin):
            pass

        button = Point(1146, 617)
        flow = Route()
        flow.maa = FakeMaa(templates={"battle/行军.png": button})
        self.assertEqual(flow._find_march_continue({}), button)

    def test_yosari_new_refill_flow_confirms_four_dialogs(self):
        class Route(SortieMixin):
            def __init__(self):
                self.maa = FakeMaa(ocr_results=[True, True, True, True])
                self.points = []

            def _click_point(self, point):
                self.points.append(point)

        flow = Route()
        with patch("touken.flows.sortie.time.sleep"):
            messages, result = self._drain(flow._confirm_yosari_departure(
                {"departure_confirm": {}}, auto_refill=True))
        self.assertEqual(result, "refilled")
        self.assertEqual(flow.points, [[640, 603], [638, 611], [784, 604], [638, 511]])
        self.assertIn("[异去] 归城提灯补充完成，已回到部队选择", messages)

    def test_yosari_refill_off_closes_before_spending_koban(self):
        class Route(SortieMixin):
            def __init__(self):
                self.maa = FakeMaa(ocr_results=[True, True])
                self.points = []

            def _click_point(self, point):
                self.points.append(point)

        flow = Route()
        with patch("touken.flows.sortie.time.sleep"):
            messages, result = self._drain(flow._confirm_yosari_departure(
                {"departure_confirm": {}}, auto_refill=False))
        self.assertFalse(result)
        self.assertEqual(flow.points, [[640, 603], [1040, 48]])
        self.assertIn("[异去] 归城提灯不足；自动补充已关闭，不消耗小判，收工", messages)


class OsakaRouteTests(unittest.TestCase):
    def test_floor_reader_uses_the_full_activity_title(self):
        class Maa(FakeMaa):
            def ocr_all(self, roi):
                return [("大阪城地下", Point(150, 190)),
                        ("81层", Point(300, 190))]

        flow = OsakaMixin()
        flow.maa = Maa()
        self.assertEqual(flow._read_osaka_floor({}), 81)

    def test_floor_selector_rereads_after_every_arrow_click(self):
        class Route(OsakaMixin):
            def __init__(self):
                self.maa = FakeMaa()
                self.readings = iter([99, 89, 88, 87, 86, 85, 84, 83, 82, 81])
                self.points = []

            def _read_osaka_floor(self, cfg):
                return next(self.readings)

            def _click_point(self, point):
                self.points.append(point)

        flow = Route()
        with patch("touken.flows.osaka.time.sleep"):
            self.assertEqual(flow._select_osaka_floor({}, 81), 81)
        self.assertEqual(flow.points[0], [1014, 420])
        self.assertEqual(flow.points[1:], [[1084, 420]] * 8)

    def test_floor_selector_stops_when_a_grey_arrow_does_not_change_floor(self):
        class Route(OsakaMixin):
            def __init__(self):
                self.maa = FakeMaa()
                self.readings = iter([29, 29])
                self.points = []

            def _read_osaka_floor(self, cfg):
                return next(self.readings)

            def _click_point(self, point):
                self.points.append(point)

        flow = Route()
        with patch("touken.flows.osaka.time.sleep"):
            self.assertEqual(flow._select_osaka_floor({}, 39), 29)
        self.assertEqual(flow.points, [[1014, 284]])

    def test_osaka_injury_thresholds_match_the_panel_choices(self):
        self.assertFalse(BattleMixin._injury_reaches_threshold("轻伤", "medium"))
        self.assertTrue(BattleMixin._injury_reaches_threshold("中伤", "medium"))
        self.assertFalse(BattleMixin._injury_reaches_threshold("中伤", "heavy"))
        self.assertTrue(BattleMixin._injury_reaches_threshold("重伤", "heavy"))

    def test_floor_end_uses_stable_label_and_result_witness(self):
        flow = OsakaMixin()
        flow.maa = FakeMaa(ocr_results=[True, True])

        self.assertTrue(flow._osaka_floor_done({}))
        self.assertEqual(flow.maa.ocr_calls, ["当前层数", "传送凭证"])

    def test_route_buttons_never_participate_in_floor_end_detection(self):
        flow = OsakaMixin()
        flow.maa = FakeMaa(
            ocr_results=[False],
            templates={
                "battle/行军.png": Point(1130, 610),
                "battle/返回本丸.png": Point(1200, 440),
                "team/部队恢复.png": Point(1040, 440),
            },
        )

        self.assertFalse(flow._osaka_floor_done({}))
        self.assertEqual(flow.maa.ocr_calls, ["当前层数"])

        flow.maa = FakeMaa(ocr_results=[True, False])
        self.assertFalse(flow._osaka_floor_done({}))

    def test_floor_end_does_not_depend_on_the_changing_floor_number(self):
        flow = OsakaMixin()
        flow.maa = FakeMaa(ocr_results=[False])

        self.assertFalse(flow._osaka_floor_done({
            "floor_end_ocr": {"expected": "当前层数", "roi": [0, 0, 10, 10]},
        }))

    def test_osaka_march_is_limited_to_the_bottom_right_button(self):
        button = Point(1130, 610)
        flow = OsakaMixin()
        flow.maa = FakeMaa(templates={"battle/行军.png": button})

        self.assertEqual(flow._find_osaka_march({}), button)

    def test_floor_end_waits_for_a_late_march_button(self):
        button = Point(1130, 610)

        class Maa(FakeMaa):
            def __init__(self):
                super().__init__()
                self.results = iter([None, None, button])

            def template_match(self, template, roi=None, threshold=0.7):
                return next(self.results)

        flow = OsakaMixin()
        flow.maa = Maa()
        with patch("touken.flows.osaka.time.sleep"):
            self.assertEqual(flow._wait_for_osaka_march({}, attempts=4), button)


if __name__ == "__main__":
    unittest.main()
