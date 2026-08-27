# -*- coding: utf-8 -*-
"""大阪城挖地主循环的回归测试。

2026-08-26 事故：层末结算页转场慢半拍，同一画面被记成两圈；
随后层末找不到行军按钮直接整单收工，游戏被晾在选阵形画面一整夜。
"""
import unittest
from unittest.mock import patch

from touken.flows.osaka import OsakaMixin


class FakeMaa:
    def __init__(self):
        self.clicks = 0

    def screenshot(self, force=False):
        pass

    def click(self, point):
        self.clicks += 1


class OsakaFlow(OsakaMixin):
    """把主循环之外的所有依赖全部钉死，只留巡逻循环本身。"""

    def __init__(self, floor_done_seq):
        self.config = {
            "osaka": {"skip_tap": [775, 695]},
            "team_select": {"teams": {"3": [100, 100]}},
        }
        self.maa = FakeMaa()
        self.current_location = "本丸"
        self._floor_done_seq = list(floor_done_seq)
        self.wait_march_result = None   # _wait_for_osaka_march 的返回值
        self.find_march_seq = []        # _find_osaka_march 的剧本，耗尽后恒 None
        self.formation_visible = False

    # ---- 进场阶段：全部直通 ----
    def recover_game_update_stream(self):
        if False:
            yield
        return False

    def recover_network_stream(self):
        if False:
            yield
        return False

    def navigate_to_stream(self, dest):
        self.current_location = dest
        if False:
            yield

    def _open_osaka(self, cfg):
        return True

    def _wait_for_team_select(self, cfg, attempts=15, open_after=5):
        return True

    def _safe_depart_stream(self, cfg, team_no, tag, **kwargs):
        if False:
            yield
        return True, False

    def _confirm_departure(self, cfg):
        return True

    def _deny_heavy_injury_warning(self, cfg):
        return False

    # ---- 巡逻循环里的感知/操作：按剧本走 ----
    def _osaka_floor_done(self, cfg):
        if self._floor_done_seq:
            return self._floor_done_seq.pop(0)
        return False

    def _team_injury_status(self, cfg):
        return None

    def _wait_for_osaka_march(self, cfg, attempts=8):
        return self.wait_march_result

    def _find_osaka_march(self, cfg):
        if self.find_march_seq:
            return self.find_march_seq.pop(0)
        return None

    def _formation_mode_state(self, allow_auto_without_title=False):
        return "manual" if self.formation_visible else None

    def choose_formation(self, **kwargs):
        self.formation_visible = False
        return "fixed"

    def _read_drop_sword(self):
        return None

    def _click_point(self, point):
        pass

    def quick_peek(self, tag=None, force=False):
        pass


def run_flow(flow, max_floors=90):
    with patch("touken.flows.osaka.time.sleep", lambda *_: None):
        return list(flow.osaka_stream(
            max_floors=max_floors, team_no=3, select_floor=False,
            auto_equip=False, koban_science=False))


class FloorEndDebounceTests(unittest.TestCase):

    def test_same_floor_end_screen_counts_once(self):
        """层末结算页连续两拍都在（转场慢）：只记一圈，不出现幽灵圈。"""
        flow = OsakaFlow(floor_done_seq=[True, True])
        flow.wait_march_result = (1125, 592)   # 第一拍正常等到行军
        flow.find_march_seq = [(1125, 592)]    # 第二拍去重分支补点一次
        msgs = run_flow(flow)
        done = [m for m in msgs if "✓ 已完成" in m]
        self.assertEqual(len(done), 1, msgs)
        self.assertIn("1/90", done[0])

    def test_march_miss_at_floor_end_does_not_abort_run(self):
        """层末没等到行军按钮：回巡逻位继续观察，不再整单收工。"""
        flow = OsakaFlow(floor_done_seq=[True])
        flow.wait_march_result = None
        msgs = run_flow(flow)
        self.assertTrue(any("回巡逻位继续观察" in m for m in msgs), msgs)
        # 任务没有中止：一路巡逻到 idle 兜底才停
        self.assertTrue(any("连续 300 次没有识别到" in m for m in msgs), msgs)

    def test_stuck_floor_end_screen_eventually_stops(self):
        """结算页赖着不走（行军一直点不动）：去重补丁点，超时才真卡死停机。"""
        flow = OsakaFlow(floor_done_seq=[True] * 40)
        flow.wait_march_result = None
        flow.find_march_seq = []
        msgs = run_flow(flow)
        done = [m for m in msgs if "✓ 已完成" in m]
        self.assertEqual(len(done), 1, msgs)   # 也只记一圈
        self.assertTrue(any("30 秒没动静" in m for m in msgs), msgs)
        # 真卡死是终点，后面不再有巡逻兜底消息
        last = msgs[-1]
        self.assertIn("30 秒没动静", last)


if __name__ == "__main__":
    unittest.main()
