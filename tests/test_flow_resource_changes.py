import json
import tempfile
import unittest
from pathlib import Path

from touken.flows.repair import RepairMixin
from touken.flows.rewards import RewardsMixin
from touken.flows.smith import SmithMixin
from touken.maa_adapter import Point, roi_4to4
from touken.telemetry import TelemetryStore

_REPAIR_CFG = {
    "select_btn_x": 1065,
    "select_offset_y": -28,
    "speedup_checkbox": [1162, 251],
    "start_button": {"template": "修复开始.png"},
    "cost_rois": [
        [288, 404, 378, 436],
        [288, 475, 378, 507],
        [288, 546, 378, 578],
        [288, 617, 378, 649],
    ],
}


class _Host(SmithMixin, RepairMixin, RewardsMixin):
    """最小宿主：config + record_event 收集（可选写入真 TelemetryStore）"""

    def __init__(self, config, store=None):
        self.config = config
        self.store = store
        self.events = []
        self.maa = None

    def record_event(self, event_type, **payload):
        self.events.append((event_type, payload))
        if self.store is not None:
            return self.store.record_event(event_type, payload)
        return len(self.events)


class _RepairFakeMaa:
    """_repair_one 用：成本 OCR 按 ROI 出数，修复开始模板给点，确认弹窗没有"""

    def __init__(self, cost_tokens):
        self.cost_tokens = cost_tokens  # {tuple(roi): [(text, point), ...]}
        self.clicked = []

    def click(self, pt):
        self.clicked.append((pt.x, pt.y))
        return True

    def screenshot(self, force=False):
        return None

    def ocr_all(self, roi):
        return self.cost_tokens.get(tuple(roi.to_list()), [])

    def template_match(self, template, roi=None, threshold=0.8):
        if template == "修复开始.png":
            return Point(1150, 600)
        return None


class _RewardFakeMaa:
    """报酬弹窗用：标题命中；格子按 cells 配置出图标匹配和数量文本"""

    def __init__(self, cells, title_found=True):
        self.cells = cells  # {格号: (匹配模板 or None, 数量文本 or None)}
        self.title_found = title_found

    def screenshot(self, force=False):
        return None

    def ocr(self, expected, roi, match_mode="exact"):
        return Point(640, 70) if self.title_found else None

    def template_match(self, template, roi=None, threshold=0.8):
        # 从 icon_roi 的 x 反推格号：x = 311 + i*110
        if roi is None:
            return None
        x1 = roi.to_list()[0]
        i = round((x1 - 311) / 110)
        cell = self.cells.get(i)
        if cell and cell[0] == template:
            return Point(x1 + 50, 200)
        return None

    def ocr_all(self, roi):
        x1, y1 = roi.to_list()[:2]
        i = round((x1 - 311) / 110)
        cell = self.cells.get(i)
        if cell and cell[1] is not None and y1 == 260:
            return [(cell[1], Point(x1 + 50, 278))]
        return []


class ForgeResourceChangeTests(unittest.TestCase):
    def test_recipe_from_config_and_fallback(self):
        host = _Host({"forge": {"recipe": [950, 950, 950, 950]}})
        self.assertEqual(host._forge_recipe(), [950, 950, 950, 950])
        self.assertEqual(_Host({})._forge_recipe(), [700, 700, 700, 700])
        self.assertEqual(_Host({"forge": {"recipe": [1, 2]}})._forge_recipe(),
                         [700, 700, 700, 700])

    def test_forge_emits_five_confirmed_changes(self):
        host = _Host({"forge": {"recipe": [700, 700, 700, 700]}})
        host._emit_forge_costs(started_event_id=42)

        changes = [p for t, p in host.events if t == "resource.change"]
        self.assertEqual(len(changes), 5)
        by_res = {p["resource"]: p for p in changes}
        for name in ("木炭", "玉钢", "冷却材", "砥石"):
            self.assertEqual(by_res[name]["delta"], -700)
        self.assertEqual(by_res["委托符"]["delta"], -1)
        for p in changes:
            self.assertEqual(p["source"], "forge.started")
            self.assertEqual(p["attribution"], "confirmed")
            self.assertEqual(p["evidence"], "known_recipe")
            self.assertEqual(p["source_event_id"], 42)

    def test_forge_recipe_change_follows_config(self):
        host = _Host({"forge": {"recipe": [350, 350, 350, 350]}})
        host._emit_forge_costs(started_event_id=None)
        by_res = {p["resource"]: p for t, p in host.events
                  if t == "resource.change"}
        self.assertEqual(by_res["木炭"]["delta"], -350)
        self.assertNotIn("source_event_id", by_res["木炭"])


class RepairResourceChangeTests(unittest.TestCase):
    def _run_repair_one(self, cost_tokens, need_speed=False):
        host = _Host({"repair": _REPAIR_CFG})
        host.maa = _RepairFakeMaa(cost_tokens)
        messages = list(host._repair_one(_REPAIR_CFG, name_y=200,
                                         need_speed=need_speed))
        return host, messages

    def test_ocr_success_emits_confirmed_costs(self):
        tokens = {tuple(roi_4to4(*roi).to_list()): [(text, Point(330, 420))]
                  for roi, text in zip(_REPAIR_CFG["cost_rois"],
                                       ("264", "429", "429", "198"))}
        host, messages = self._run_repair_one(tokens, need_speed=True)

        self.assertIn("[手入] 已开工", messages)
        changes = [p for t, p in host.events if t == "resource.change"]
        self.assertEqual(len(changes), 5)
        by_res = {p["resource"]: p for p in changes}
        self.assertEqual(by_res["木炭"]["delta"], -264)
        self.assertEqual(by_res["玉钢"]["delta"], -429)
        self.assertEqual(by_res["砥石"]["delta"], -198)
        self.assertEqual(by_res["加速符"]["delta"], -1)
        for name in ("木炭", "玉钢", "冷却材", "砥石"):
            self.assertEqual(by_res[name]["attribution"], "confirmed")
            self.assertEqual(by_res[name]["evidence"], "repair_confirm_ocr")
            self.assertEqual(by_res[name]["source"], "repair.confirm_screen")
        self.assertEqual(by_res["加速符"]["attribution"], "confirmed")

    def test_ocr_partial_failure_marks_unknown(self):
        tokens = {tuple(roi_4to4(*_REPAIR_CFG["cost_rois"][0]).to_list()):
                  [("264", Point(330, 420))],
                  tuple(roi_4to4(*_REPAIR_CFG["cost_rois"][1]).to_list()):
                  [("429", Point(330, 484))],
                  # 冷却材 OCR 出乱码，砥石读空
                  tuple(roi_4to4(*_REPAIR_CFG["cost_rois"][2]).to_list()):
                  [("---", Point(330, 548))]}
        host, messages = self._run_repair_one(tokens)

        self.assertIn("[手入] 已开工", messages)
        by_res = {p["resource"]: p for t, p in host.events
                  if t == "resource.change"}
        self.assertEqual(by_res["木炭"]["delta"], -264)
        for name in ("冷却材", "砥石"):
            self.assertIsNone(by_res[name]["delta"])
            self.assertEqual(by_res[name]["attribution"], "unknown")
            self.assertIn("读取失败", by_res[name]["note"])
        self.assertNotIn("加速符", by_res)

    def test_no_cost_rois_no_bookkeeping(self):
        cfg = {k: v for k, v in _REPAIR_CFG.items() if k != "cost_rois"}
        host = _Host({"repair": cfg})
        host.maa = _RepairFakeMaa({})
        messages = list(host._repair_one(cfg, name_y=200, need_speed=False))
        self.assertIn("[手入] 已开工", messages)
        self.assertEqual(host.events, [])

    def test_start_button_missing_no_bookkeeping(self):
        host = _Host({"repair": _REPAIR_CFG})
        host.maa = _RepairFakeMaa({})
        host.maa.template_match = lambda *a, **k: None
        messages = list(host._repair_one(_REPAIR_CFG, name_y=200,
                                         need_speed=False))
        self.assertNotIn("[手入] 已开工", messages)
        self.assertEqual(host.events, [])


class RewardPopupTests(unittest.TestCase):
    def test_popup_items_and_unknown_icon_skip(self):
        cells = {
            0: ("资源/icon木炭.png", "1,050"),
            1: ("资源/icon小判.png", "650"),
            2: (None, "300"),  # 图标不认识但数量在 → 跳过并记 note
            # 第 3 格起什么都没有 → 扫描停止
        }
        host = _Host({})
        host.maa = _RewardFakeMaa(cells)

        items, notes = host._read_reward_popup()

        self.assertEqual(items, [("木炭", 1050), ("小判", 650)])
        self.assertEqual(len(notes), 1)
        self.assertIn("图标不认识", notes[0])

    def test_popup_absent_returns_none(self):
        host = _Host({})
        host.maa = _RewardFakeMaa({}, title_found=False)
        self.assertIsNone(host._read_reward_popup())

    def test_emit_changes_link_claimed_event(self):
        host = _Host({})
        host._emit_reward_popup_changes([("木炭", 1050), ("委托符", 2)],
                                        claimed_event_id=77)
        changes = [p for t, p in host.events if t == "resource.change"]
        self.assertEqual(len(changes), 2)
        for p in changes:
            self.assertEqual(p["source"], "task_rewards.reward_popup")
            self.assertEqual(p["attribution"], "confirmed")
            self.assertEqual(p["evidence"], "reward_popup_ocr")
            self.assertEqual(p["source_event_id"], 77)
        self.assertEqual(changes[0]["delta"], 1050)
        self.assertEqual(changes[1]["resource"], "委托符")


class LedgerAggregationTests(unittest.TestCase):
    """三流程的 resource.change 能被 TelemetryStore.resource_ledger 正确聚合"""

    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.store = TelemetryStore(Path(self.temp.name) / "telemetry.db")

    def tearDown(self):
        self.store.close()
        self.temp.cleanup()

    def test_flow_changes_aggregated_into_attributions(self):
        host = _Host({"forge": {"recipe": [700, 700, 700, 700]}},
                     store=self.store)

        started_id = self.store.record_event("forge.started", {"slot": 1})
        host._emit_forge_costs(started_event_id=started_id)

        host.events.clear()
        tokens = {tuple(roi_4to4(*roi).to_list()): [(text, Point(330, 420))]
                  for roi, text in zip(_REPAIR_CFG["cost_rois"],
                                       ("264", "429", "429", "198"))}
        host.config = {"repair": _REPAIR_CFG}
        host.maa = _RepairFakeMaa(tokens)
        list(host._repair_one(_REPAIR_CFG, name_y=200, need_speed=True))

        claimed_id = self.store.record_event("task_rewards.claimed",
                                             {"tab": "日常"})
        host._emit_reward_popup_changes([("木炭", 1050), ("小判", 650)],
                                        claimed_event_id=claimed_id)

        ledger = self.store.resource_ledger(0, 9999999999)
        attrs = ledger["attributions"]

        charcoal = [a for a in attrs if a["resource"] == "木炭"]
        # 锻刀 -700、手入 -264、任务 +1050
        self.assertEqual(sorted(a["delta"] for a in charcoal),
                         [-700, -264, 1050])
        self.assertTrue(all(a["confidence"] == "confirmed" for a in attrs))
        sources = {a["source"] for a in attrs}
        self.assertEqual(sources, {"forge.started", "repair.confirm_screen",
                                   "task_rewards.reward_popup"})
        ticket = next(a for a in attrs if a["resource"] == "委托符")
        self.assertEqual(ticket["delta"], -1)
        koban = next(a for a in attrs if a["resource"] == "小判")
        self.assertEqual(koban["delta"], 650)
        # 每资源 attributed_delta 汇总正确
        per = {r["resource"]: r for r in ledger["per_resource"]}
        self.assertEqual(per["木炭"]["attributed_delta"], -700 - 264 + 1050)
        self.assertEqual(per["加速符"]["attributed_delta"], -1)

    def test_unknown_null_delta_stays_out_of_attributions(self):
        # delta=null 的 unknown 记账保留事实但不进聚合明细
        host = _Host({}, store=self.store)
        host.record_event("resource.change", resource="砥石", delta=None,
                          source="repair.confirm_screen", script="repair",
                          attribution="unknown", evidence="repair_confirm_ocr",
                          note="发生了修理消耗但数值读取失败")

        ledger = self.store.resource_ledger(0, 9999999999)

        self.assertEqual(ledger["attributions"], [])
        # 事件本身仍在 events 表里可查
        rows = self.store.recent_events(event_type="resource.change")
        self.assertEqual(len(rows), 1)
        self.assertIsNone(rows[0]["payload"]["delta"])
        self.assertEqual(rows[0]["payload"]["attribution"], "unknown")


class SpeedupDedupTests(unittest.TestCase):
    """加速符去重：同 run 有逐笔记账时 session_completed 的汇总让位，老数据照常"""

    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.store = TelemetryStore(Path(self.temp.name) / "telemetry.db")

    def tearDown(self):
        self.store.close()
        self.temp.cleanup()

    def _event(self, ts, event_type, payload, run_id=None, script="repair"):
        cursor = self.store._conn().execute(
            "INSERT INTO events(ts, run_id, script, event_type, payload) "
            "VALUES (?, ?, ?, ?, ?)",
            (ts, run_id, script, event_type,
             json.dumps(payload, ensure_ascii=False)))
        self.store._conn().commit()
        return cursor.lastrowid

    def _per_repair(self, ts, run_id=None):
        return self._event(ts, "resource.change",
                           {"resource": "加速符", "delta": -1,
                            "source": "repair.confirm_screen", "script": "repair",
                            "attribution": "confirmed", "evidence": "known_recipe"},
                           run_id=run_id)

    def _speedup_attrs(self, ledger):
        return [a for a in ledger["attributions"] if a["resource"] == "加速符"]

    def test_same_run_session_completed_yields_to_per_repair(self):
        t0 = 1786600000.0
        for i in range(3):
            self._per_repair(t0 + i, run_id="run-a")
        self._event(t0 + 10, "repair.session_completed",
                    {"repaired": 3, "speedups": 3, "source": "osaka"},
                    run_id="run-a", script="osaka")

        attrs = self._speedup_attrs(self.store.resource_ledger(0, 9999999999))

        # 只算逐笔的 3 条，session_completed 的 -3 不再计入
        self.assertEqual(len(attrs), 3)
        self.assertTrue(all(a["delta"] == -1 for a in attrs))
        self.assertTrue(all(a["source"] == "repair.confirm_screen" for a in attrs))
        per = {r["resource"]: r for r in
               self.store.resource_ledger(0, 9999999999)["per_resource"]}
        self.assertEqual(per["加速符"]["attributed_delta"], -3)

    def test_legacy_session_completed_still_counted(self):
        # 没有逐笔记账的老数据：照常靠 session_completed 归因
        t0 = 1786600000.0
        self._event(t0, "repair.session_completed",
                    {"repaired": 2, "speedups": 3, "source": "osaka"},
                    run_id="run-old", script="osaka")

        attrs = self._speedup_attrs(self.store.resource_ledger(0, 9999999999))

        self.assertEqual(len(attrs), 1)
        self.assertEqual(attrs[0]["delta"], -3)
        self.assertEqual(attrs[0]["source"], "repair.session_completed")

    def test_cross_run_does_not_shadow(self):
        # run-a 有逐笔，run-b 只有 session_completed：各算各的
        t0 = 1786600000.0
        self._per_repair(t0, run_id="run-a")
        self._event(t0 + 10, "repair.session_completed",
                    {"repaired": 1, "speedups": 2, "source": "osaka"},
                    run_id="run-b", script="osaka")

        attrs = self._speedup_attrs(self.store.resource_ledger(0, 9999999999))

        self.assertEqual(sorted(a["delta"] for a in attrs), [-2, -1])

    def test_null_run_id_falls_back_to_window_presence(self):
        # run_id 缺失的兜底：窗内有逐笔记录就跳过 session_completed
        t0 = 1786600000.0
        self._per_repair(t0, run_id=None)
        self._event(t0 + 10, "repair.session_completed",
                    {"repaired": 1, "speedups": 1, "source": "osaka"},
                    run_id=None, script="osaka")

        attrs = self._speedup_attrs(self.store.resource_ledger(0, 9999999999))

        self.assertEqual(len(attrs), 1)
        self.assertEqual(attrs[0]["source"], "repair.confirm_screen")


if __name__ == "__main__":
    unittest.main()
