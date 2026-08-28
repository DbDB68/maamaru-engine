# -*- coding: utf-8 -*-
"""江户城潜入调查：巡游决策与地图档案测试。"""

import json
import unittest
from pathlib import Path
from unittest.mock import patch

from touken.edo_route import (
    EDOCASTLE_TOUR,
    bfs_distance,
    bfs_path,
    build_graph,
    decide_next,
    load_archive,
)
from touken.flows.edocastle import EdocastleMixin


ARCHIVE_PATH = Path(__file__).resolve().parent.parent / "resource" / "base" / "maps" / "edocastle-4.json"


class EdocastleRouteTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.archive = load_archive(ARCHIVE_PATH)
        cls.graph = build_graph(cls.archive)

    # ── 老大的实例场景，必须逐字复现 ──

    def test_16_with_4_steps_goes_11(self):
        """16 剩 4 步 → 11（tour），9/8 已被踩过。"""
        visited = set(EDOCASTLE_TOUR[:EDOCASTLE_TOUR.index(16)]) | {9, 8, 16}
        nxt, mode = decide_next(self.archive, EDOCASTLE_TOUR, 16, visited, 4)
        self.assertEqual(nxt, 11)
        self.assertEqual(mode, "tour")

    def test_11_after_step_refill_goes_8(self):
        """11 步数回后 → 8（tour），12 已被踩过所以 target 是 1，BFS 走 8。"""
        visited = set(EDOCASTLE_TOUR[:EDOCASTLE_TOUR.index(11)]) | {12, 11}
        nxt, mode = decide_next(self.archive, EDOCASTLE_TOUR, 11, visited, 5)
        self.assertEqual(nxt, 8)
        self.assertEqual(mode, "tour")

    def test_19_desperate_rushes_via_17(self):
        """19 烂透 → 沿 BFS 奔王点，第一步是 17。"""
        visited = {21, 20, 19}
        nxt, mode = decide_next(self.archive, EDOCASTLE_TOUR, 19, visited, 2)
        self.assertEqual(nxt, 17)
        self.assertEqual(mode, "rush")

    def test_opening_20_with_5_steps_goes_19(self):
        """开局 20 剩 5 步 → 19。"""
        visited = {21, 20}
        nxt, mode = decide_next(self.archive, EDOCASTLE_TOUR, 20, visited, 5)
        self.assertEqual(nxt, 19)
        self.assertEqual(mode, "tour")

    # ── 边界 ──

    def test_exact_steps_to_boss_rushes(self):
        """步数正好等于到王点距离时，继续巡游的不变量会失败，应 rush。"""
        # cur=7 距王点 1 步；target=1（若 1 未访问）dist(1,2)=2，steps-1=0 < 2
        visited = {21, 20, 19, 17, 18, 6, 4, 10, 14, 13, 15, 16, 9, 8, 11, 12, 7}
        nxt, mode = decide_next(self.archive, EDOCASTLE_TOUR, 7, visited, 1)
        self.assertEqual(nxt, 2)
        self.assertEqual(mode, "rush")

    def test_cur_not_in_tour_rushes(self):
        """cur 不在巡游序上（节点 3）直接 BFS 奔王点。"""
        nxt, mode = decide_next(self.archive, EDOCASTLE_TOUR, 3, {3}, 5)
        self.assertEqual(mode, "rush")
        # 3 的邻边是 4/7，到王点最短第一步是 7
        self.assertEqual(nxt, 7)

    def test_visited_skips_already_visited(self):
        """巡游序上已访问的节点会被跳过，从 20 出发只认 21/20 已访问时 target 是 19。"""
        nxt, mode = decide_next(self.archive, EDOCASTLE_TOUR, 20, {21, 20}, 5)
        self.assertEqual(nxt, 19)

    def test_all_visited_rushes_to_boss(self):
        """巡游序全访问完直奔王点。"""
        visited = set(EDOCASTLE_TOUR)  # 含王点 2
        nxt, mode = decide_next(self.archive, EDOCASTLE_TOUR, 16, visited, 10)
        self.assertEqual(mode, "rush")
        self.assertEqual(nxt, 11)  # 16→11→12→7→2 第一步


class EdocastleArchiveTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.archive = load_archive(ARCHIVE_PATH)
        cls.graph = build_graph(cls.archive)

    def test_archive_verified_flag(self):
        self.assertTrue(self.archive.get("verified", False))

    def test_all_tour_edges_exist(self):
        """巡游序中相邻节点必须能在档案里直接走到（或经 BFS 一步）。"""
        for i in range(len(EDOCASTLE_TOUR) - 1):
            a, b = EDOCASTLE_TOUR[i], EDOCASTLE_TOUR[i + 1]
            if b not in self.graph.get(a, set()):
                self.fail(f"巡游边 {a}→{b} 在档案里不是直接相邻边")

    def test_entry_reaches_boss(self):
        entry = self.archive.get("entry", 21)
        boss = self.archive.get("boss", 2)
        dist = bfs_distance(self.graph, entry, boss)
        self.assertIsNotNone(dist)
        self.assertEqual(dist, 5)  # 踩点记录：入口→王点最短 5 步

    def test_graph_is_connected(self):
        """全图连通，任意节点可达王点。"""
        boss = self.archive.get("boss", 2)
        for node in self.archive["nodes"]:
            dist = bfs_distance(self.graph, node["id"], boss)
            self.assertIsNotNone(
                dist, f"节点 {node['id']} 不可达王点"
            )

    def test_boss_is_node_2(self):
        self.assertEqual(self.archive.get("boss"), 2)

    def test_bfs_path_to_boss(self):
        path = bfs_path(self.graph, 20, 2)
        self.assertIsNotNone(path)
        self.assertEqual(path[0], 20)
        self.assertEqual(path[-1], 2)
        self.assertEqual(len(path) - 1, bfs_distance(self.graph, 20, 2))

    def test_no_node_id_zero_or_five_in_archive(self):
        """终审删除了 0/5 两个美术假点。"""
        ids = {node["id"] for node in self.archive["nodes"]}
        self.assertNotIn(0, ids)
        self.assertNotIn(5, ids)


class EdocastleConfigTests(unittest.TestCase):
    def test_example_config_has_edocastle_section(self):
        example_path = Path(__file__).resolve().parent.parent / "touken_config.example.json"
        cfg = json.loads(example_path.read_text(encoding="utf-8-sig"))
        self.assertIn("edocastle", cfg)
        edo = cfg["edocastle"]
        self.assertEqual(edo["difficulty"], 4)
        self.assertEqual(edo["map_archive"], "resource/base/maps/edocastle-4.json")
        self.assertEqual(edo["tour"], EDOCASTLE_TOUR)
        self.assertIn("team_ui_ocr", edo)
        self.assertIn("hud_step_ocr", edo)
        self.assertIn("ticket_refill", edo)  # 弹窗补票（模板待踩点，留空即不认）
        self.assertNotIn("tokens", edo)  # 数令牌格已拆除，票尽走游戏补票弹窗
        # 通用安全出阵链依赖的键必须在配置契约里
        self.assertEqual(edo["repair_threshold"], "heavy")  # 虚拟伤害，中伤照跑
        self.assertIn("auto_equip", edo)
        for key in ("injury_deny_button", "injury_stamps",
                    "injury_stamp_roi", "injury_status_roi"):
            self.assertIn(key, edo, f"example 配置缺 edocastle.{key}")


class _MapRunHost(EdocastleMixin):
    """_map_run_stream 的最小宿主：节点全是空点，OCR 读数按剧本给。"""

    def __init__(self, step_reads):
        import tempfile
        from types import SimpleNamespace
        self.maa = SimpleNamespace(
            screenshot=lambda force=False: None,
            ocr_all=lambda roi, image=None: [],
            template_match=lambda *a, **k: None,
            save_screenshot=lambda path: True,
            click=lambda p: True,
        )
        self._root = tempfile.mkdtemp()
        self._step_reads = iter(step_reads)
        self.clicked = []

    def _click_point(self, point):
        self.clicked.append(list(point) if not isinstance(point, list) else point)

    def _read_hud_steps(self, cfg):
        return next(self._step_reads, None)

    def _wait_formation_page(self, cfg, timeout_s=5.0, skip_point=None,
                             formation_mode="manual"):
        return False  # 全是空点，没有战斗

    def _wait_map_landmark(self, cfg, timeout_s=15.0):
        return True

    def _wait_round_end(self, cfg, skip_point, timeout_s=30.0):
        return True

    def skip_safe(self, times, interval=0.8, point=None):
        pass


def _run_map(flow):
    """驱动 _map_run_stream 生成器，返回 (消息列表, 返回值)。"""
    from touken.edo_route import load_archive
    archive = load_archive(ARCHIVE_PATH)
    gen = flow._map_run_stream(
        {}, archive, EDOCASTLE_TOUR, archive.get("boss", 2), [775, 695],
        "manual", "fixed", "鱼鳞阵",
    )
    msgs = []
    while True:
        try:
            msgs.append(next(gen))
        except StopIteration as stop:
            return msgs, stop.value


class EdocastleOcrFallbackTests(unittest.TestCase):
    def test_ocr_miss_falls_back_to_pessimistic_estimate(self):
        """读不出步数时按"没回步"悲观估算继续走，最终打到王点收工。"""
        # 开局 6；19 后瞎一次(估 5)；17 后读出 3；13 后瞎(估 2)；
        # 7 后读出 1；点王点后瞎一次(估 0)——王点判定在读数之后，正常收工
        flow = _MapRunHost([6, None, 3, None, 1, None])
        msgs, result = _run_map(flow)
        self.assertEqual(result, (0, True))
        est_msgs = [m for m in msgs if "悲观估算" in m]
        self.assertEqual(len(est_msgs), 3)
        self.assertFalse(any("太瞎了" in m for m in msgs))

    def test_three_consecutive_ocr_misses_stops(self):
        """连续 3 次读不出步数：太瞎了，停。"""
        flow = _MapRunHost([6, None, None, None])
        msgs, result = _run_map(flow)
        self.assertEqual(result, (0, False))
        self.assertTrue(any("太瞎了" in m for m in msgs))


class _BattleGateMaa:
    def __init__(self, frames):
        self.frames = iter(frames)
        self.frame = set()

    def screenshot(self, force=False):
        self.frame = set(next(self.frames, self.frame))

    def template_match(self, template, roi=None, threshold=0.7):
        return template if template in self.frame else None


class _BattleGateHost(EdocastleMixin):
    def __init__(self, frames):
        self.maa = _BattleGateMaa(frames)
        self.clicked = []
        self.config = {}

    def _click_point(self, point):
        self.clicked.append(point)


class EdocastleBattleGateTests(unittest.TestCase):
    @patch("touken.flows.edocastle.time.sleep")
    def test_does_not_tap_until_battle_result_then_stops_on_map(self, _sleep):
        flow = _BattleGateHost([
            set(), set(), {"battle/ui战斗结果.png"},
            {"江户城/获得钥匙.png"}, {"江户城/地图难度标签.png"},
        ])
        ok = flow._wait_after_battle(
            "江户城/地图难度标签.png", [775, 695], timeout_s=10)
        self.assertTrue(ok)
        self.assertEqual(flow.clicked, [[775, 695], [775, 695]])

    @patch("touken.flows.edocastle.time.sleep")
    def test_round_end_banner_is_returned_without_extra_tap(self, _sleep):
        flow = _BattleGateHost([
            set(), {"battle/ui战斗结果.png"}, {"江户城/调查完了.png"},
        ])
        ok = flow._wait_after_battle(
            "江户城/调查完了.png", [775, 695], timeout_s=10)
        self.assertTrue(ok)
        self.assertEqual(flow.clicked, [[775, 695]])


if __name__ == "__main__":
    unittest.main()
