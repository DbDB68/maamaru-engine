# -*- coding: utf-8 -*-
"""共用编队执行器（formation_editor）契约测试。

假 MAA 是点击/滑动驱动的页面状态机：
  - 外壳（部队编成/部队选择）只看标题 OCR，不含任何主题色信息——
    两种外壳走同一条执行器路径本测试直接钉死；
  - click(替换) 开"刀剑男士选择"列表；swipe 翻页；click(决定) 按剧本
    应用换人或模拟禁用/未生效；
  - 编队槽观察不走真 OCR：host 覆写 _formation_read_team/_formation_row_label
    注入缝喂剧本槽位（team_roster 自己的读取有 test_team_roster 守着）。

全程断言：永不点击出发按钮坐标（FORBIDDEN_DEPART_CLICKS）、
template_match 永远不碰即刻出阵/继续出阵类模板。
"""

import copy
import unittest
from unittest.mock import patch

from touken.flows.formation_editor import (
    FormationEditorMixin, decide_match, normalize_target, parse_selection_rows,
    row_conflicts_target, slot_matches_target,
    FORBIDDEN_DEPART_CLICKS, ALREADY_CORRECT, AMBIGUOUS, CHANGED,
    INVALID_REQUEST, NOT_FOUND, SCREEN_UNRECOGNIZED, UNAVAILABLE,
    VERIFICATION_FAILED, _DECIDE_X, _ROW_CY, _SWAP_X, _TEAM_TAB)

HASEBE = "touken_118_heshikiri_hasebe"   # 压切长谷部（打刀）
MIKA = "touken_003_mikazuki_munechika"   # 三日月宗近（太刀）
KOGI = "touken_005_kogitsune_maru"       # 小狐丸（太刀）
MAEDA = "touken_039_maeda_toushirou"     # 前田藤四郎（短刀）


class _P:
    def __init__(self, x, y):
        self.x, self.y = x, y


def _slot(slot, catalog=MIKA, name="三日月宗近", level=99, kiwame="normal",
          status="occupied"):
    return {"slot": slot, "slot_status": status, "name_raw": name, "name": name,
            "name_status": "recognized" if name else None,
            "sword_catalog_id": catalog, "sword_type": "太刀",
            "rarity_base": 4, "level": level, "fatigue": 100, "survival": 50,
            "survival_max": 50, "injury": "none",
            "badge": {"type": "太刀", "flowers": None},
            "kiwame_status": kiwame, "kiwame_evidence": [],
            "tactical_roles": [], "unknown_fields": []}


def _six(catalog=MIKA, name="三日月宗近", level=99):
    return [_slot(i, catalog=catalog, name=name, level=level)
            for i in range(1, 7)]


def _target(catalog=HASEBE, name="压切长谷部", level=35, form="normal",
            observation_id="9:12"):
    return {"observation_id": observation_id, "sword_catalog_id": catalog,
            "name": name, "form": form, "level": level}


def _row(name, y, level=None, fatigue=None, becomes=None, disabled=False,
         popup=False):
    return {"name": name, "y": y, "level": level, "fatigue": fatigue,
            "becomes": becomes, "disabled": disabled, "popup": popup}


class _FakeMaa:
    """编队执行器状态机假 MAA（无图像，全靠剧本与坐标约定）。"""

    def __init__(self, shell="formation", current_tab=1, pages=None):
        self.shell = shell                  # formation/team_select/None
        self.current_tab = current_tab
        self.pages = pages or []            # 选择列表分页剧本
        self.in_list = False
        self.list_page = 0
        self.pending_slot = None
        self.list_opens = True
        self.decide_works = True            # False=点了决定列表不关闭
        self.swallow_tabs = set()           # 首次点这些队标签被吞
        self._swallowed = set()
        self.popup = False
        self.on_decide = None
        self.clicks = []
        self.swipes = []
        self.templates_seen = []

    # ---- 识别 ----

    def screenshot(self, force=False):
        return None

    def ocr(self, expected, roi, match_mode="contains"):
        if expected == "刀剑男士选择":
            return _P(640, 40) if self.in_list else None
        if expected == "部队编成":
            return _P(640, 30) if (self.shell == "formation"
                                   and not self.in_list) else None
        if expected == "部队选择":
            return _P(640, 30) if (self.shell == "team_select"
                                   and not self.in_list) else None
        return None

    def ocr_all(self, roi, image=None):
        if not self.in_list or not (roi.x == 60 and roi.y == 100):
            return []
        if not self.pages:
            return []
        tokens = []
        for row in self.pages[self.list_page]:
            tokens.append((row["name"], _P(150, row["y"])))
            if row.get("level") is not None:
                tokens.append((f"{row['level']}级", _P(380, row["y"])))
            if row.get("fatigue") is not None:
                tokens.append((f"疲劳 {row['fatigue']}/100",
                               _P(520, row["y"])))
        return tokens

    def template_match(self, template, roi=None, threshold=0.7):
        self.templates_seen.append(template)
        if template == "通用_确定.png" and self.popup:
            return _P(640, 500)
        return None

    # ---- 交互 ----

    def click(self, point):
        x, y = point.x, point.y
        self.clicks.append((x, y))
        for team, (tx, ty) in _TEAM_TAB.items():
            if (x, y) == (tx, ty):
                if team in self.swallow_tabs and team not in self._swallowed:
                    self._swallowed.add(team)   # 第一次被吞
                    return
                self.current_tab = team
                return
        if (x, y) == (640, 500) and self.popup:
            self.popup = False
            return
        if x == _SWAP_X:
            if y in _ROW_CY:
                self.pending_slot = _ROW_CY.index(y) + 1
            if self.list_opens:
                self.in_list = True
                self.list_page = 0
            return
        if x == _DECIDE_X and self.in_list:
            for row in self.pages[self.list_page]:
                if abs((row["y"] - 22) - y) <= 3:
                    if row.get("disabled") or not self.decide_works:
                        return      # 游戏不响应：列表不关闭
                    if self.on_decide:
                        self.on_decide(self.pending_slot, row)
                    if row.get("popup"):
                        self.popup = True
                    self.in_list = False
                    return
            return

    def swipe(self, x1, y1, x2, y2, duration_ms=400):
        self.swipes.append((x1, y1, x2, y2, duration_ms))
        if not self.in_list or not self.pages:
            return
        if y2 < y1:
            self.list_page = min(self.list_page + 1, len(self.pages) - 1)
        else:
            self.list_page = max(self.list_page - 1, 0)


class _EditorHost(FormationEditorMixin):
    def __init__(self, maa, teams):
        self.maa = maa
        self.config = {}
        self.current_location = None
        self.events = []
        self.teams = teams                    # {team_no: [slot×6]}
        maa.on_decide = self._apply_decide

    def _apply_decide(self, slot_no, row):
        if slot_no and row.get("becomes") is not None:
            self.teams[self.maa.current_tab][slot_no - 1] = copy.deepcopy(
                row["becomes"])

    def record_event(self, event_type, **payload):
        self.events.append({"event_type": event_type, "payload": payload})

    def navigate_to_stream(self, dest):
        if dest == "编队":
            self.maa.shell = "formation"
        self.current_location = dest
        yield f"nav→{dest}"

    def _formation_read_team(self):
        return copy.deepcopy(self.teams[self.maa.current_tab])

    def _formation_row_label(self, cy):
        return self.maa.current_tab


def _run(host, team_no=2, slot_no=3, target=None, **kw):
    with patch("touken.flows.formation_editor.time.sleep", lambda *_: None):
        return host.ensure_team_member(team_no, slot_no,
                                       target or _target(), **kw)


def _std_setup(shell="formation", pages=None, team_no=2, slot_no=3):
    """部队 team_no 的 slot_no 是小狐丸，目标是压切长谷部 Lv35。"""
    teams = {team_no: _six()}
    teams[team_no][slot_no - 1] = _slot(slot_no, catalog=KOGI, name="小狐丸")
    maa = _FakeMaa(shell=shell, pages=pages or [])
    return maa, _EditorHost(maa, teams)


def _assert_never_departs(tc, maa):
    for click in maa.clicks:
        tc.assertNotIn(click, FORBIDDEN_DEPART_CLICKS,
                       f"出发按钮被点击: {click}")
    for tpl in maa.templates_seen:
        for word in ("即刻出阵", "继续出阵", "演练"):
            tc.assertNotIn(word, tpl)


# ==================== 纯函数 ====================

class PureFunctionTests(unittest.TestCase):

    def test_normalize_target_from_pool_entry(self):
        entry = {"observation_id": "9:12", "sword_catalog_id": HASEBE,
                 "name_zh": "压切长谷部", "level": 35, "kiwame_date": None}
        tgt, err = normalize_target(entry)
        self.assertIsNone(err)
        self.assertEqual(tgt["form"], "normal")       # 无显现日期 → 普通
        entry["kiwame_date"] = "2024-01-01"
        tgt, _ = normalize_target(entry)
        self.assertEqual(tgt["form"], "kiwame")
        bare = {"sword_catalog_id": HASEBE}           # 没给 kiwame_date 键
        tgt, _ = normalize_target(bare)
        self.assertIsNone(tgt["form"])                # 不硬猜
        tgt, err = normalize_target({"level": 35})
        self.assertIsNotNone(err)

    def test_parse_rows_merges_fragments_and_attaches(self):
        tokens = [("压切", _P(150, 148)), ("长谷部", _P(200, 152)),
                  ("35级", _P(380, 150)), ("疲劳 85/100", _P(520, 150)),
                  ("小狐丸", _P(150, 300)), ("疲劳 20/100", _P(520, 300))]
        rows, unreadable = parse_selection_rows(tokens)
        self.assertEqual(unreadable, 0)
        self.assertEqual(len(rows), 2)
        r0 = rows[0]
        self.assertEqual(r0["sword_catalog_id"], HASEBE)
        self.assertEqual(r0["level"], 35)
        self.assertEqual(r0["fatigue"], 85)
        self.assertIsNone(r0["form"])                 # 页面无形态通道
        self.assertIn("form", r0["unknown_fields"])
        self.assertEqual(rows[1]["sword_catalog_id"], KOGI)
        self.assertIn("level", rows[1]["unknown_fields"])

    def test_parse_rows_unreadable_counted(self):
        rows, unreadable = parse_selection_rows([("@@乱码@@", _P(150, 150))])
        self.assertEqual(unreadable, 1)
        self.assertIsNone(rows[0]["sword_catalog_id"])

    def test_decide_unique_with_form_evidence(self):
        # 同名普通/极化：页面给出可靠形态证据时选对（row form 由未来
        # 真机校准通道提供，这里直接构造证明判定逻辑）
        tgt, _ = normalize_target(_target(form="kiwame", level=99))
        rows = [{"y": 150, "name_raw": "压切长谷部", "name": "压切长谷部",
                 "sword_catalog_id": HASEBE, "level": 99, "fatigue": 50,
                 "form": "normal", "unknown_fields": []},
                {"y": 300, "name_raw": "压切长谷部", "name": "压切长谷部",
                 "sword_catalog_id": HASEBE, "level": 99, "fatigue": 60,
                 "form": "kiwame", "unknown_fields": []}]
        v = decide_match([rows], tgt)
        self.assertEqual(v["status"], "unique")
        self.assertEqual(v["row"]["y"], 300)

    def test_decide_ambiguous_identical_rows(self):
        tgt, _ = normalize_target(_target(level=35))
        row = {"y": 150, "name_raw": "压切长谷部", "name": "压切长谷部",
               "sword_catalog_id": HASEBE, "level": 35, "fatigue": 50,
               "form": None, "unknown_fields": ["form"]}
        pages = [[dict(row)], [dict(row, y=160)]]
        v = decide_match(pages, tgt)
        self.assertEqual(v["status"], "ambiguous")
        self.assertEqual(len(v["candidates"]), 2)

    def test_decide_ambiguous_when_unreadable_rows_exist(self):
        tgt, _ = normalize_target(_target(level=35))
        rows = [{"y": 150, "name_raw": "压切长谷部", "name": "压切长谷部",
                 "sword_catalog_id": HASEBE, "level": 35, "fatigue": None,
                 "form": None, "unknown_fields": []}]
        v = decide_match([rows], tgt, unreadable_rows=1)
        self.assertEqual(v["status"], "ambiguous")

    def test_decide_not_found(self):
        tgt, _ = normalize_target(_target(level=35))
        rows = [{"y": 150, "name_raw": "小狐丸", "name": "小狐丸",
                 "sword_catalog_id": KOGI, "level": 99, "fatigue": 50,
                 "form": None, "unknown_fields": []}]
        v = decide_match([rows], tgt)
        self.assertEqual(v["status"], "not_found")

    def test_level_conflict_excludes_row(self):
        tgt, _ = normalize_target(_target(level=35))
        row = {"sword_catalog_id": HASEBE, "level": 99, "fatigue": 50,
               "form": None}
        self.assertTrue(row_conflicts_target(row, tgt, ("name", "level")))
        self.assertFalse(row_conflicts_target(
            {"sword_catalog_id": HASEBE, "level": None}, tgt,
            ("name", "level")))   # 缺值不冲突

    def test_slot_matches_target(self):
        tgt, _ = normalize_target(_target(level=35, form="normal"))
        self.assertTrue(slot_matches_target(
            _slot(1, catalog=HASEBE, name="压切长谷部", level=35), tgt))
        self.assertFalse(slot_matches_target(_slot(1), tgt))      # 别的刀
        self.assertFalse(slot_matches_target(                     # 形态冲突
            _slot(1, catalog=HASEBE, name="压切长谷部", kiwame="kiwame"),
            tgt))
        self.assertFalse(slot_matches_target(
            _slot(1, status="empty", catalog=None, name=None), tgt))
        self.assertIsNone(slot_matches_target(
            _slot(1, status="unknown", catalog=None, name=None), tgt))


# ==================== 执行器流程 ====================

class ExecutorFlowTests(unittest.TestCase):

    def test_formation_shell_change_first_page(self):
        target_becomes = _slot(3, catalog=HASEBE, name="压切长谷部", level=35)
        pages = [[_row("三日月宗近", 150, level=99, fatigue=100),
                  _row("压切长谷部", 300, level=35, fatigue=60,
                       becomes=target_becomes),
                  _row("前田藤四郎", 450, level=80, fatigue=90)]]
        maa, host = _std_setup(pages=pages)
        result = _run(host)
        self.assertEqual(result["result"], CHANGED)
        self.assertEqual(result["entry_shell"], "formation")
        self.assertEqual(result["before"]["sword_catalog_id"], KOGI)
        self.assertEqual(result["after"]["sword_catalog_id"], HASEBE)
        self.assertEqual(len(result["team_before"]), 6)
        self.assertEqual(len(result["team_after"]), 6)
        self.assertIn((_DECIDE_X, 300 - 22), maa.clicks)
        self.assertEqual(maa.shell, "formation")   # 保持原入口上下文
        ev = host.events[-1]
        self.assertEqual(ev["event_type"], "formation.member_ensured")
        self.assertEqual(ev["payload"]["result"], CHANGED)
        _assert_never_departs(self, maa)

    def test_team_select_shell_same_path(self):
        """部队选择外壳走同一执行器：识别只看标题，没有颜色通道可依赖。"""
        target_becomes = _slot(3, catalog=HASEBE, name="压切长谷部", level=35)
        pages = [[_row("压切长谷部", 300, level=35, fatigue=60,
                       becomes=target_becomes)]]
        maa, host = _std_setup(shell="team_select", pages=pages)
        result = _run(host, entry_context="team_select")
        self.assertEqual(result["result"], CHANGED)
        self.assertEqual(result["entry_shell"], "team_select")
        self.assertIn((_SWAP_X, _ROW_CY[2]), maa.clicks)
        _assert_never_departs(self, maa)

    def test_standalone_wrapper_navigates_to_formation(self):
        target_becomes = _slot(3, catalog=HASEBE, name="压切长谷部", level=35)
        pages = [[_row("压切长谷部", 300, level=35, fatigue=60,
                       becomes=target_becomes)]]
        maa, host = _std_setup(shell=None, pages=pages)
        with patch("touken.flows.formation_editor.time.sleep",
                   lambda *_: None):
            gen = host.ensure_team_member_from_honmaru_stream(2, 3, _target())
            while True:
                try:
                    next(gen)
                except StopIteration as stop:
                    result = stop.value
                    break
        self.assertEqual(result["result"], CHANGED)
        self.assertEqual(host.current_location, "编队")
        _assert_never_departs(self, maa)

    def test_already_correct_zero_swap_clicks(self):
        maa, host = _std_setup(pages=[])
        host.teams[2][2] = _slot(3, catalog=HASEBE, name="压切长谷部",
                                 level=35)
        result = _run(host)
        self.assertEqual(result["result"], ALREADY_CORRECT)
        swap_clicks = [c for c in maa.clicks if c[0] == _SWAP_X]
        decide_clicks = [c for c in maa.clicks if c[0] == _DECIDE_X]
        self.assertEqual(swap_clicks, [])
        self.assertEqual(decide_clicks, [])
        _assert_never_departs(self, maa)

    def test_target_on_first_page_of_three_navigates_back(self):
        """目标在首页，扫完全表后按指纹翻回首页再点决定。"""
        target_becomes = _slot(3, catalog=HASEBE, name="压切长谷部", level=35)
        pages = [[_row("压切长谷部", 300, level=35, fatigue=60,
                       becomes=target_becomes)],
                 [_row("三日月宗近", 200, level=99, fatigue=100)],
                 [_row("前田藤四郎", 400, level=80, fatigue=90)]]
        maa, host = _std_setup(pages=pages)
        result = _run(host)
        self.assertEqual(result["result"], CHANGED)
        self.assertEqual(result["pages_scanned"], 3)
        # 既有正向翻页也有反向回翻
        forward = [s for s in maa.swipes if s[3] < s[1]]
        backward = [s for s in maa.swipes if s[3] > s[1]]
        self.assertTrue(forward)
        self.assertTrue(backward)
        _assert_never_departs(self, maa)

    def test_scan_terminates_and_reports_not_found(self):
        pages = [[_row("三日月宗近", 150, level=99, fatigue=100)],
                 [_row("小狐丸", 300, level=99, fatigue=50)]]
        maa, host = _std_setup(pages=pages)
        result = _run(host)
        self.assertEqual(result["result"], NOT_FOUND)
        self.assertIn("隐藏", result["reason"])
        decide_clicks = [c for c in maa.clicks if c[0] == _DECIDE_X]
        self.assertEqual(decide_clicks, [])
        self.assertLessEqual(len([s for s in maa.swipes]), 10)  # 有上限
        _assert_never_departs(self, maa)

    def test_ambiguous_same_name_never_clicks_first(self):
        pages = [[_row("压切长谷部", 200, level=35, fatigue=60),
                  _row("压切长谷部", 400, level=35, fatigue=80)]]
        maa, host = _std_setup(pages=pages)
        result = _run(host)
        self.assertEqual(result["result"], AMBIGUOUS)
        self.assertEqual(len(result["candidates"]), 2)
        decide_clicks = [c for c in maa.clicks if c[0] == _DECIDE_X]
        self.assertEqual(decide_clicks, [])     # 绝不点第一条
        _assert_never_departs(self, maa)

    def test_catalog_alone_cannot_claim_unique(self):
        """只有 observation_id/sword_catalog_id 的目标遇同名多振 → ambiguous。"""
        pages = [[_row("压切长谷部", 200, level=35, fatigue=60),
                  _row("压切长谷部", 400, level=99, fatigue=80)]]
        maa, host = _std_setup(pages=pages)
        target = {"observation_id": "9:12", "sword_catalog_id": HASEBE,
                  "name": "压切长谷部"}   # form/level 都没有
        result = _run(host, target=target)
        self.assertEqual(result["result"], AMBIGUOUS)
        decide_clicks = [c for c in maa.clicks if c[0] == _DECIDE_X]
        self.assertEqual(decide_clicks, [])

    def test_list_never_opens_is_screen_unrecognized(self):
        maa, host = _std_setup(pages=[])
        maa.list_opens = False
        result = _run(host)
        self.assertEqual(result["result"], SCREEN_UNRECOGNIZED)
        _assert_never_departs(self, maa)

    def test_decide_no_effect_is_unavailable(self):
        """目标被游戏禁用（决定点了列表不关闭）→ unavailable，不盲试。"""
        pages = [[_row("压切长谷部", 300, level=35, fatigue=60,
                       disabled=True)]]
        maa, host = _std_setup(pages=pages)
        result = _run(host)
        self.assertEqual(result["result"], UNAVAILABLE)
        self.assertIn("不可选", result["reason"])
        _assert_never_departs(self, maa)

    def test_verification_failed_on_wrong_readback(self):
        """决定生效但回读是别的刀 → verification_failed，明说队伍可能已变。"""
        wrong = _slot(3, catalog=MAEDA, name="前田藤四郎", level=80)
        pages = [[_row("压切长谷部", 300, level=35, fatigue=60,
                       becomes=wrong)]]
        maa, host = _std_setup(pages=pages)
        result = _run(host)
        self.assertEqual(result["result"], VERIFICATION_FAILED)
        self.assertIn("可能已发生变化", result["reason"])
        self.assertEqual(result["after"]["sword_catalog_id"], MAEDA)
        _assert_never_departs(self, maa)

    def test_verification_failed_on_unreadable_slot(self):
        target_becomes = _slot(3, catalog=HASEBE, name="压切长谷部", level=35)
        pages = [[_row("压切长谷部", 300, level=35, fatigue=60,
                       becomes=target_becomes)]]
        maa, host = _std_setup(pages=pages)
        original = host._formation_read_team
        state = {"decided": False}
        real_apply = host._apply_decide

        def apply(slot_no, row):
            state["decided"] = True
            real_apply(slot_no, row)
        maa.on_decide = apply

        def read_team():
            team = original()
            if state["decided"]:
                team[2] = _slot(3, status="unknown", catalog=None, name=None)
            return team
        host._formation_read_team = read_team
        result = _run(host)
        self.assertEqual(result["result"], VERIFICATION_FAILED)

    def test_shell_unrecognized_and_no_wandering(self):
        maa, host = _std_setup(shell=None, pages=[])
        result = _run(host, entry_context="team_select")
        self.assertEqual(result["result"], SCREEN_UNRECOGNIZED)
        self.assertEqual(maa.clicks, [])     # 指定外壳不在场：不乱逛
        # auto 模式不在任何编队表面 → 导航去编队
        maa2, host2 = _std_setup(shell=None, pages=[
            [_row("压切长谷部", 300, level=35, fatigue=60,
                  becomes=_slot(3, catalog=HASEBE, name="压切长谷部",
                                level=35))]])
        result2 = _run(host2, entry_context="auto")
        self.assertEqual(result2["result"], CHANGED)
        self.assertEqual(result2["entry_shell"], "formation")

    def test_tab_click_swallowed_retries(self):
        target_becomes = _slot(3, catalog=HASEBE, name="压切长谷部", level=35)
        pages = [[_row("压切长谷部", 300, level=35, fatigue=60,
                       becomes=target_becomes)]]
        maa, host = _std_setup(pages=pages)
        maa.swallow_tabs.add(2)              # 第一次切队被吞
        result = _run(host)
        self.assertEqual(result["result"], CHANGED)
        tab_clicks = [c for c in maa.clicks if c == _TEAM_TAB[2]]
        self.assertGreaterEqual(len(tab_clicks), 2)

    def test_invalid_request(self):
        maa, host = _std_setup()
        result = _run(host, team_no=9)
        self.assertEqual(result["result"], INVALID_REQUEST)
        result = _run(host, target={"level": 35})
        self.assertEqual(result["result"], INVALID_REQUEST)
        self.assertEqual(maa.clicks, [])

    def test_confirm_popup_handled_after_decide(self):
        target_becomes = _slot(3, catalog=HASEBE, name="压切长谷部", level=35)
        pages = [[_row("压切长谷部", 300, level=35, fatigue=60,
                       becomes=target_becomes, popup=True)]]
        maa, host = _std_setup(pages=pages)
        result = _run(host)
        self.assertEqual(result["result"], CHANGED)
        self.assertIn((640, 500), maa.clicks)      # 通用_确定 被点掉
        _assert_never_departs(self, maa)


if __name__ == "__main__":
    unittest.main()
