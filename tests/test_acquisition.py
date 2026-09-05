import unittest

from touken import acquisition, advisor


class ExpeditionRankingTests(unittest.TestCase):
    def test_per_hour_and_tiebreak(self):
        # 木炭三张 90/h 的图并列，短图（周转快）排前面
        ranking = acquisition.expedition_ranking("木炭")
        self.assertEqual([e["map"] for e in ranking], ["A1", "A3", "B3"])
        for entry in ranking:
            self.assertEqual(entry["per_hour"], 90)
        self.assertEqual(ranking[0]["label"], "1-1")
        self.assertEqual(ranking[0]["name"], "鸟羽·伏见之战")

    def test_ticket_maps_and_level_tiebreak(self):
        # 委托符 B3/D1 同为 120min 1 张，等级要求低的排前面
        ranking = acquisition.expedition_ranking("委托符")
        self.assertEqual([e["map"] for e in ranking[:2]], ["B3", "D1"])
        self.assertEqual(ranking[0]["amount"], 1)
        self.assertEqual(ranking[0]["per_hour"], 0.5)

    def test_no_expedition_source_returns_empty(self):
        # 甲州金没有任何远征产出，不许硬编
        self.assertEqual(acquisition.expedition_ranking("甲州金"), [])

    def test_top_limit(self):
        self.assertLessEqual(len(acquisition.expedition_ranking("小判")), 3)
        self.assertEqual(len(acquisition.expedition_ranking("小判", top=1)), 1)


class ResourceGuideTests(unittest.TestCase):
    def test_guide_merges_static_card(self):
        guide = acquisition.resource_guide("委托符")
        self.assertIsNotNone(guide)
        self.assertTrue(guide["expeditions"])
        self.assertIn("委托符", guide["mission"])
        self.assertTrue(guide["expedition_caveat"])

    def test_premium_currency_is_honest(self):
        guide = acquisition.resource_guide("甲州金")
        self.assertEqual(guide["expeditions"], [])
        self.assertIsNone(guide["expedition_caveat"])
        self.assertTrue(guide["note"])  # 没渠道就要把丑话说前头

    def test_unknown_resource_returns_none(self):
        self.assertIsNone(acquisition.resource_guide("钻石"))


class _FakeStore:
    def resource_ledger(self, from_ts, to_ts):
        return {"per_resource": [], "daily_series": [], "attributions": []}

    def recent_events(self, limit=100, event_type=None):
        return []


class FragmentCatalogTests(unittest.TestCase):
    def test_ranks_maps_by_rate(self):
        catalog = acquisition.fragment_catalog()
        # 曜变天目只在 1-4 出
        guide = catalog["曜变天目"]
        self.assertEqual(guide["best_map"]["map_no"], 4)
        self.assertAlmostEqual(guide["best_map"]["rate"], 0.04)
        # 狮子螺钿鞍：1-2（0.07）压过 1-4（0.02）
        self.assertEqual(catalog["狮子螺钿鞍"]["best_map"]["map_no"], 2)

    def test_notes_carry_source_and_milestones(self):
        notes = acquisition.fragment_notes()
        self.assertTrue(notes["rate_source"])
        self.assertTrue(notes["milestones"])
        self.assertIn("active", notes["campaign"])


class PlanningPayloadTests(unittest.TestCase):
    def test_planning_includes_acquisition(self):
        import tempfile
        from datetime import date
        from pathlib import Path
        with tempfile.TemporaryDirectory() as tmp:
            planning = advisor.get_planning(_FakeStore(), Path(tmp) / "goals.json",
                                            today=date(2026, 8, 25))
        guides = planning["acquisition"]
        self.assertEqual(set(guides), set(advisor.LEDGER_RESOURCES))
        self.assertTrue(guides["砥石"]["expeditions"])
        self.assertEqual(guides["甲州金"]["expeditions"], [])


if __name__ == "__main__":
    unittest.main()
