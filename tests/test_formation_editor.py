# -*- coding: utf-8 -*-
"""共用编队执行器（formation_editor）契约测试。

假 MAA 是点击/滑动驱动的页面状态机：
  - 外壳（部队编成/部队选择）只看标题 OCR，不含任何主题色信息——
    两种外壳走同一条执行器路径本测试直接钉死；
  - click(替换) 开"刀剑男士选择"列表；swipe 翻页（wrap=True 时模拟
    末页后绕回首页的异常页序）；click(决定) 按剧本应用换人或模拟
    禁用/未生效；
  - 页面行证据（形态等）经 host 的 _parse_selection_rows 注入缝喂入，
    与真机未来校准通道同一位置；默认页面给不出形态（form=None）；
  - 编队槽观察不走真 OCR：host 覆写 _formation_read_team/_formation_row_label
    注入缝喂剧本槽位（team_roster 自己的读取有 test_team_roster 守着）。

全程断言：永不点击出发按钮坐标（FORBIDDEN_DEPART_CLICKS）、
template_match 永远不碰即刻出阵/继续出阵类模板。
"""

import copy
import unittest
from unittest.mock import patch

import numpy as np

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


def _row(name, y, level=None, fatigue=None, form=None, becomes=None,
         disabled=False, popup=False):
    """选择列表行剧本。form 为该行的形态证据（None=页面给不出，默认）。"""
    return {"name": name, "y": y, "level": level, "fatigue": fatigue,
            "form": form, "becomes": becomes, "disabled": disabled,
            "popup": popup}


class _FakeMaa:
    """编队执行器状态机假 MAA（无图像，全靠剧本与坐标约定）。"""

    def __init__(self, shell="formation", current_tab=1, pages=None,
                 wrap=False, swallow_swipes=False):
        self.shell = shell                  # formation/team_select/None
        self.current_tab = current_tab
        self.pages = pages or []            # 选择列表分页剧本
        self.wrap = wrap                    # True=末页后再翻绕回首页（异常页序）
        self.swallow_swipes = swallow_swipes  # True=滑动全被模拟器吞掉
        self.swallow_forward = set()        # 被吞的前滑序号（1 起）
        self._forward_count = 0
        self.form_map = {(r["name"], r.get("level")): r["form"]
                         for page in self.pages for r in page
                         if r.get("form") is not None}
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

    def end_sighted(self):
        """剧本末端视觉证据（滚动条到底）：当前页就是最后一页才为真——
        与滑动是否被执行无关的绝对位置证据。"""
        return bool(self.in_list and self.pages
                    and self.list_page == len(self.pages) - 1)

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
        if not self.in_list or not self.pages or self.swallow_swipes:
            return
        if y2 < y1:
            self._forward_count += 1
            if self._forward_count in self.swallow_forward:
                return                      # 这一次前滑被模拟器吞掉
            if self.list_page + 1 >= len(self.pages) and self.wrap:
                self.list_page = 0          # 异常：末页后绕回首页
            else:
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

    def _list_end_sighted(self):
        """注入缝：剧本滚动条证据（生产通道=右缘滑轨滑块贴底）。"""
        return self.maa.end_sighted()

    def _parse_selection_rows(self, tokens):
        """注入缝：给行补上剧本里的形态证据（未来真机形态通道的位置）。"""
        rows, bad = parse_selection_rows(tokens)
        for r in rows:
            form = self.maa.form_map.get((r["name_raw"], r["level"]))
            if form is not None:
                r["form"] = form
                r["unknown_fields"] = [f for f in r["unknown_fields"]
                                       if f != "form"]
        return rows, bad


def _run(host, team_no=2, slot_no=3, target=None, **kw):
    with patch("touken.flows.formation_editor.time.sleep", lambda *_: None):
        return host.ensure_team_member(team_no, slot_no,
                                       target or _target(), **kw)


def _std_setup(shell="formation", pages=None, team_no=2, slot_no=3,
               wrap=False, swallow_swipes=False):
    """部队 team_no 的 slot_no 是小狐丸，目标是压切长谷部 Lv35 普通。"""
    teams = {team_no: _six()}
    teams[team_no][slot_no - 1] = _slot(slot_no, catalog=KOGI, name="小狐丸")
    maa = _FakeMaa(shell=shell, pages=pages or [], wrap=wrap,
                   swallow_swipes=swallow_swipes)
    return maa, _EditorHost(maa, teams)


def _assert_never_departs(tc, maa):
    for click in maa.clicks:
        tc.assertNotIn(click, FORBIDDEN_DEPART_CLICKS,
                       f"出发按钮被点击: {click}")
    for tpl in maa.templates_seen:
        for word in ("即刻出阵", "继续出阵", "演练"):
            tc.assertNotIn(word, tpl)


def _ok_row(y=300, **kw):
    """一行证据齐全的目标（形态证据经注入缝给出）。"""
    kw.setdefault("becomes", _slot(3, catalog=HASEBE, name="压切长谷部",
                                   level=35))
    return _row("压切长谷部", y, level=35, fatigue=60, form="normal", **kw)


# ==================== 纯函数 ====================

class PureFunctionTests(unittest.TestCase):

    def test_normalize_target_from_pool_entry(self):
        """反例钉死（2026-09-15 P0）：kiwame_date 是显现日期，每振都有，
        永远推不出形态；form 只认显式 form 或档案 form_status 结论。"""
        entry = {"observation_id": "9:12", "sword_catalog_id": HASEBE,
                 "name_zh": "压切长谷部", "level": 35, "kiwame_date": None}
        tgt, err = normalize_target(entry)
        self.assertIsNone(err)
        self.assertIsNone(tgt["form"])                # 无证据 → None
        entry["kiwame_date"] = "2024-01-01"           # 显现日期 ≠ 极化
        tgt, _ = normalize_target(entry)
        self.assertIsNone(tgt["form"])                # 不许再推 kiwame
        entry["form_status"] = "ambiguous"            # 分不清 → None
        tgt, _ = normalize_target(entry)
        self.assertIsNone(tgt["form"])
        entry["form_status"] = "kiwame"               # 档案确认极 → kiwame
        tgt, _ = normalize_target(entry)
        self.assertEqual(tgt["form"], "kiwame")
        entry["form"] = "normal"                      # 显式 form 优先
        tgt, _ = normalize_target(entry)
        self.assertEqual(tgt["form"], "normal")
        bare = {"sword_catalog_id": HASEBE}
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
        self.assertEqual(r0["name_raw"], "压切长谷部")
        self.assertEqual(r0["level"], 35)
        self.assertEqual(r0["fatigue"], 85)
        self.assertIsNone(r0["form"])                 # 页面无形态通道
        self.assertIn("form", r0["unknown_fields"])
        self.assertEqual(rows[1]["sword_catalog_id"], KOGI)
        self.assertIn("level", rows[1]["unknown_fields"])

    def test_position_markers_never_pollute_name_band(self):
        """真机布局：名字左侧的"N之M"位置标记/锁图标不算读不清的名字。"""
        for mx, my, mark in ((60, 300, "二之六"),      # 同 y，标记区
                             (250, 310, "四之二"),      # 近 y，落进姓名带
                             (120, 500, "四之"),        # 分离 y，OCR 残缺
                             (75, 148, "一之五")):      # 同 y（目标行）
            tokens = [("压切长谷部", _P(150, 150)), (mark, _P(mx, my))]
            rows, unreadable = parse_selection_rows(tokens)
            self.assertEqual(unreadable, 0, f"{mark}@({mx},{my}) 不应算乱码")
            self.assertEqual(len(rows), 1)
            self.assertEqual(rows[0]["name_raw"], "压切长谷部")
            self.assertEqual(rows[0]["sword_catalog_id"], HASEBE)

    def test_garbage_in_name_band_still_blocks(self):
        """姓名带里的真乱码仍保守阻断（unreadable 防线不取消）。"""
        rows, unreadable = parse_selection_rows(
            [("压切长谷部", _P(150, 150)), ("@@乱码@@", _P(150, 300))])
        self.assertEqual(unreadable, 1)

    def test_decide_unique_requires_sufficient_evidence(self):
        """字段齐全（零冲突+零缺口+无读不清）才 unique。"""
        tgt, _ = normalize_target(_target(form="kiwame", level=99))
        row = {"y": 300, "name_raw": "压切长谷部", "name": "压切长谷部",
               "sword_catalog_id": HASEBE, "level": 99, "fatigue": 60,
               "form": "kiwame", "unknown_fields": []}
        v = decide_match([[row]], tgt)
        self.assertEqual(v["status"], "unique")
        self.assertEqual(v["evidence_gaps"], [])

    def test_decide_single_row_missing_form_and_level_not_unique(self):
        """牛老师复现的反例：唯一同名行但 form+level 都缺 → 不放行。"""
        tgt, _ = normalize_target(_target(form="kiwame", level=99))
        row = {"y": 300, "name_raw": "压切长谷部", "name": "压切长谷部",
               "sword_catalog_id": HASEBE, "level": None, "fatigue": 60,
               "form": None, "unknown_fields": ["level", "form"]}
        v = decide_match([[row]], tgt)
        self.assertEqual(v["status"], "ambiguous")
        self.assertEqual(v["missing_evidence"], ["form", "level"])
        self.assertIn("缺身份证据", v["reason"])

    def test_decide_missing_form_only_blocks(self):
        tgt, _ = normalize_target(_target(form="kiwame", level=99))
        row = {"y": 300, "name_raw": "压切长谷部", "name": "压切长谷部",
               "sword_catalog_id": HASEBE, "level": 99, "fatigue": 60,
               "form": None, "unknown_fields": ["form"]}
        v = decide_match([[row]], tgt)
        self.assertEqual(v["status"], "ambiguous")
        self.assertEqual(v["missing_evidence"], ["form"])

    def test_decide_missing_level_only_blocks(self):
        tgt, _ = normalize_target(_target(form="kiwame", level=99))
        row = {"y": 300, "name_raw": "压切长谷部", "name": "压切长谷部",
               "sword_catalog_id": HASEBE, "level": None, "fatigue": 60,
               "form": "kiwame", "unknown_fields": ["level"]}
        v = decide_match([[row]], tgt)
        self.assertEqual(v["status"], "ambiguous")
        self.assertEqual(v["missing_evidence"], ["level"])

    def test_decide_confirmed_plus_unconfirmed_is_ambiguous(self):
        """一条证据充分 + 一条缺证据同名行：不能排除后者 → ambiguous。"""
        tgt, _ = normalize_target(_target(form="normal", level=35))
        good = {"y": 200, "name_raw": "压切长谷部", "name": "压切长谷部",
                "sword_catalog_id": HASEBE, "level": 35, "fatigue": 60,
                "form": "normal", "unknown_fields": []}
        weak = {"y": 400, "name_raw": "压切长谷部", "name": "压切长谷部",
                "sword_catalog_id": HASEBE, "level": None, "fatigue": 80,
                "form": None, "unknown_fields": ["level", "form"]}
        v = decide_match([[good, weak]], tgt)
        self.assertEqual(v["status"], "ambiguous")
        self.assertEqual(len(v["candidates"]), 2)

    def test_decide_unique_with_form_evidence(self):
        """同名普通/极化：页面给出可靠形态证据时选对。"""
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
        tgt, _ = normalize_target(_target(level=35, form=None))
        row = {"y": 150, "name_raw": "压切长谷部", "name": "压切长谷部",
               "sword_catalog_id": HASEBE, "level": 35, "fatigue": 50,
               "form": None, "unknown_fields": ["form"]}
        pages = [[dict(row)], [dict(row, y=160)]]
        v = decide_match(pages, tgt)
        self.assertEqual(v["status"], "ambiguous")
        self.assertEqual(len(v["candidates"]), 2)

    def test_decide_ambiguous_when_unreadable_rows_exist(self):
        tgt, _ = normalize_target(_target(level=35, form=None))
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
            ("name", "level")))   # 缺值不冲突（但证据充分性另算）

    def test_slot_matches_target_three_states(self):
        """三态：确认匹配 / 确认不匹配 / 证据不足。形态未知绝不通过。"""
        tgt, _ = normalize_target(_target(level=35, form="normal"))
        self.assertTrue(slot_matches_target(
            _slot(1, catalog=HASEBE, name="压切长谷部", level=35), tgt))
        self.assertFalse(slot_matches_target(_slot(1), tgt))      # 别的刀
        self.assertFalse(slot_matches_target(                     # 形态冲突
            _slot(1, catalog=HASEBE, name="压切长谷部", kiwame="kiwame"),
            tgt))
        self.assertFalse(slot_matches_target(                     # 等级冲突
            _slot(1, catalog=HASEBE, name="压切长谷部", level=99), tgt))
        self.assertIsNone(slot_matches_target(                    # 形态读不出
            _slot(1, catalog=HASEBE, name="压切长谷部", level=35,
                  kiwame="unknown"), tgt))
        self.assertIsNone(slot_matches_target(                    # 等级读不出
            _slot(1, catalog=HASEBE, name="压切长谷部", level=None), tgt))
        self.assertFalse(slot_matches_target(
            _slot(1, status="empty", catalog=None, name=None), tgt))
        self.assertIsNone(slot_matches_target(
            _slot(1, status="unknown", catalog=None, name=None), tgt))


# ==================== 执行器流程 ====================


_DECOY_PAGE = [_row("三日月宗近", 200, level=99, fatigue=100)]


class ExecutorFlowTests(unittest.TestCase):

    def test_formation_shell_change_first_page(self):
        pages = [[_row("三日月宗近", 150, level=99, fatigue=100),
                  _ok_row(300),
                  _row("前田藤四郎", 450, level=80, fatigue=90)],
                 _DECOY_PAGE]
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
        ev = [e for e in host.events
              if e["event_type"] == "formation.member_ensured"][-1]
        self.assertEqual(ev["payload"]["result"], CHANGED)
        # 换后整队回读要落成新事实，本丸档案编队层只认这类事件
        self.assertEqual(host.events[-1]["event_type"], "team_roster.observed")
        _assert_never_departs(self, maa)

    def test_team_select_shell_same_path(self):
        """部队选择外壳走同一执行器：识别只看标题，没有颜色通道可依赖。"""
        pages = [[_ok_row(300)], _DECOY_PAGE]
        maa, host = _std_setup(shell="team_select", pages=pages)
        result = _run(host, entry_context="team_select")
        self.assertEqual(result["result"], CHANGED)
        self.assertEqual(result["entry_shell"], "team_select")
        self.assertIn((_SWAP_X, _ROW_CY[2]), maa.clicks)
        _assert_never_departs(self, maa)

    def test_standalone_wrapper_navigates_to_formation(self):
        pages = [[_ok_row(300)], _DECOY_PAGE]
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

    def test_already_correct_requires_proven_form(self):
        """槽位同名但形态读不出：不能零点击宣称正确（去名单找证据）。"""
        pages = [[_ok_row(300)], _DECOY_PAGE]
        maa, host = _std_setup(pages=pages)
        host.teams[2][2] = _slot(3, catalog=HASEBE, name="压切长谷部",
                                 level=35, kiwame="unknown")
        result = _run(host)
        self.assertNotEqual(result["result"], ALREADY_CORRECT)
        swap_clicks = [c for c in maa.clicks if c[0] == _SWAP_X]
        self.assertTrue(swap_clicks)     # 开了名单，没偷懒宣称正确

    def test_target_on_first_page_of_three_navigates_back(self):
        """目标在首页，扫完全表后按指纹翻回首页再点决定。"""
        pages = [[_ok_row(300)],
                 [_row("三日月宗近", 200, level=99, fatigue=100)],
                 [_row("前田藤四郎", 400, level=80, fatigue=90)]]
        maa, host = _std_setup(pages=pages)
        result = _run(host)
        self.assertEqual(result["result"], CHANGED)
        self.assertEqual(result["pages_scanned"], 3)
        forward = [s for s in maa.swipes if s[3] < s[1]]
        backward = [s for s in maa.swipes if s[3] > s[1]]
        self.assertTrue(forward)
        self.assertTrue(backward)
        _assert_never_departs(self, maa)

    def test_scan_terminates_and_reports_not_found(self):
        """两页短名单，回翻复归证明到底 → complete，确定 not_found。"""
        pages = [[_row("三日月宗近", 150, level=99, fatigue=100)],
                 [_row("小狐丸", 300, level=99, fatigue=50)]]
        maa, host = _std_setup(pages=pages)
        result = _run(host)
        self.assertEqual(result["result"], NOT_FOUND)
        self.assertIn("隐藏", result["reason"])
        decide_clicks = [c for c in maa.clicks if c[0] == _DECIDE_X]
        self.assertEqual(decide_clicks, [])
        self.assertLessEqual(len([s for s in maa.swipes]), 70)  # 有上限
        _assert_never_departs(self, maa)

    def test_ambiguous_same_name_never_clicks_first(self):
        pages = [[_row("压切长谷部", 200, level=35, fatigue=60,
                       form="normal"),
                  _row("压切长谷部", 400, level=35, fatigue=80,
                       form="normal")],
                 _DECOY_PAGE]
        maa, host = _std_setup(pages=pages)
        result = _run(host)
        self.assertEqual(result["result"], AMBIGUOUS)
        self.assertEqual(len(result["candidates"]), 2)
        decide_clicks = [c for c in maa.clicks if c[0] == _DECIDE_X]
        self.assertEqual(decide_clicks, [])     # 绝不点第一条
        _assert_never_departs(self, maa)

    def test_single_row_missing_evidence_never_clicked(self):
        """流程级反例：唯一同名行但页面给不出形态证据 → ambiguous 停住。"""
        pages = [[_row("压切长谷部", 300, level=35, fatigue=60,
                       form=None)],            # 页面无形态通道
                 _DECOY_PAGE]
        maa, host = _std_setup(pages=pages)
        result = _run(host)
        self.assertEqual(result["result"], AMBIGUOUS)
        self.assertIn("form", result["missing_evidence"])
        decide_clicks = [c for c in maa.clicks if c[0] == _DECIDE_X]
        self.assertEqual(decide_clicks, [])

    def test_catalog_alone_cannot_claim_unique(self):
        """只有 observation_id/sword_catalog_id 的目标遇同名多振 → ambiguous。"""
        pages = [[_row("压切长谷部", 200, level=35, fatigue=60),
                  _row("压切长谷部", 400, level=99, fatigue=80)],
                 _DECOY_PAGE]
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
                       form="normal", disabled=True)],
                 _DECOY_PAGE]
        maa, host = _std_setup(pages=pages)
        result = _run(host)
        self.assertEqual(result["result"], UNAVAILABLE)
        self.assertIn("不可选", result["reason"])
        _assert_never_departs(self, maa)

    def test_verification_failed_on_wrong_readback(self):
        """决定生效但回读是别的刀 → verification_failed，明说队伍可能已变。"""
        wrong = _slot(3, catalog=MAEDA, name="前田藤四郎", level=80)
        pages = [[_row("压切长谷部", 300, level=35, fatigue=60,
                       form="normal", becomes=wrong)],
                 _DECOY_PAGE]
        maa, host = _std_setup(pages=pages)
        result = _run(host)
        self.assertEqual(result["result"], VERIFICATION_FAILED)
        self.assertIn("可能已发生变化", result["reason"])
        self.assertEqual(result["after"]["sword_catalog_id"], MAEDA)
        _assert_never_departs(self, maa)

    def test_verification_failed_on_insufficient_readback(self):
        """回读同名但形态未知 → 证据不足也绝不报 changed。"""
        weak = _slot(3, catalog=HASEBE, name="压切长谷部", level=35,
                     kiwame="unknown")
        pages = [[_row("压切长谷部", 300, level=35, fatigue=60,
                       form="normal", becomes=weak)],
                 _DECOY_PAGE]
        maa, host = _std_setup(pages=pages)
        result = _run(host)
        self.assertEqual(result["result"], VERIFICATION_FAILED)
        self.assertIn("证据不足", result["reason"])
        self.assertIn("可能已发生变化", result["reason"])

    def test_verification_failed_on_unreadable_slot(self):
        pages = [[_ok_row(300)], _DECOY_PAGE]
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
        maa2, host2 = _std_setup(shell=None,
                                 pages=[[_ok_row(300)], _DECOY_PAGE])
        result2 = _run(host2, entry_context="auto")
        self.assertEqual(result2["result"], CHANGED)
        self.assertEqual(result2["entry_shell"], "formation")

    def test_tab_click_swallowed_retries(self):
        pages = [[_ok_row(300)], _DECOY_PAGE]
        maa, host = _std_setup(pages=pages)
        maa.swallow_tabs.add(2)              # 第一次切队被吞
        result = _run(host)
        self.assertEqual(result["result"], CHANGED)
        tab_clicks = [c for c in maa.clicks if c == _TEAM_TAB[2]]
        self.assertEqual(len(tab_clicks) >= 2, True)

    def test_invalid_request(self):
        maa, host = _std_setup()
        result = _run(host, team_no=9)
        self.assertEqual(result["result"], INVALID_REQUEST)
        result = _run(host, target={"level": 35})
        self.assertEqual(result["result"], INVALID_REQUEST)
        self.assertEqual(maa.clicks, [])

    def test_confirm_popup_handled_after_decide(self):
        pages = [[_ok_row(300, popup=True)], _DECOY_PAGE]
        maa, host = _std_setup(pages=pages)
        result = _run(host)
        self.assertEqual(result["result"], CHANGED)
        self.assertIn((640, 500), maa.clicks)      # 通用_确定 被点掉
        _assert_never_departs(self, maa)


# ==================== 扫描完整度契约 ====================

class ScanCompletenessTests(unittest.TestCase):

    @staticmethod
    def _many_pages(target_page, extra_target=False, total=9):
        """total 页名单：target_page 页放目标（extra_target=True 时第 9 页
        再放一振 identical 同名）。"""
        pages = []
        for i in range(total):
            if i == target_page:
                pages.append([_ok_row(300)])
            elif extra_target and i == total - 1:
                pages.append([_row("压切长谷部", 300, level=35, fatigue=70,
                                   form="normal")])
            else:
                pages.append([_row("前田藤四郎", 200 + i, level=80 + i,
                                   fatigue=90)])
        return pages

    def test_target_on_page_9_full_scan_finds_it(self):
        """大库存：目标在第 9 页，默认上限足够扫到底 → 正常换入。"""
        pages = self._many_pages(8)
        maa, host = _std_setup(pages=pages)
        result = _run(host)
        self.assertEqual(result["result"], CHANGED)
        self.assertEqual(result["pages_scanned"], 9)
        _assert_never_departs(self, maa)

    def test_second_copy_on_page_9_makes_ambiguous(self):
        """同名第二振在第 9 页：扫到底后 ambiguous，绝不点第一条。"""
        pages = self._many_pages(0, extra_target=True)
        maa, host = _std_setup(pages=pages)
        result = _run(host)
        self.assertEqual(result["result"], AMBIGUOUS)
        self.assertEqual(len(result["candidates"]), 2)
        decide_clicks = [c for c in maa.clicks if c[0] == _DECIDE_X]
        self.assertEqual(decide_clicks, [])

    def test_truncated_scan_never_clicks(self):
        """安全上限 8 页而名单有 9 页：截断不裁决、不点击。"""
        pages = self._many_pages(8)
        maa, host = _std_setup(pages=pages)
        result = _run(host, max_pages=8)
        self.assertEqual(result["result"], SCREEN_UNRECOGNIZED)
        self.assertEqual(result["scan_status"], "truncated")
        self.assertIn("scan_incomplete", result["reason"])
        decide_clicks = [c for c in maa.clicks if c[0] == _DECIDE_X]
        self.assertEqual(decide_clicks, [])
        _assert_never_departs(self, maa)

    def test_truncated_scan_cannot_prove_not_found(self):
        """目标不在前 8 页：截断名单连 not_found 也不许确定。"""
        pages = self._many_pages(8)
        maa, host = _std_setup(pages=pages)
        result = _run(host, max_pages=8)
        self.assertNotIn(result["result"], (NOT_FOUND, CHANGED, AMBIGUOUS))

    def test_real_end_at_page_3_still_decides(self):
        """真正第 3 页到底（回翻复归验证通过）：unique 照常工作。"""
        pages = [[_row("三日月宗近", 200, level=99, fatigue=100)],
                 [_ok_row(300)],
                 [_row("前田藤四郎", 400, level=80, fatigue=90)]]
        maa, host = _std_setup(pages=pages)
        result = _run(host)
        self.assertEqual(result["result"], CHANGED)
        self.assertEqual(result["pages_scanned"], 3)

    def test_loop_is_not_reached_end(self):
        """末页后绕回首页（异常页序）：loop ≠ 到底，拒绝裁决。"""
        pages = self._many_pages(2, total=3)
        maa, host = _std_setup(pages=pages, wrap=True)
        result = _run(host, max_pages=10)
        self.assertEqual(result["result"], SCREEN_UNRECOGNIZED)
        self.assertEqual(result["scan_status"], "loop")
        decide_clicks = [c for c in maa.clicks if c[0] == _DECIDE_X]
        self.assertEqual(decide_clicks, [])


# ==================== 「滑不动」≠「确认到底」 ====================

class BottomProofTests(unittest.TestCase):
    """停滞只是"没翻动"，不是"到底"。OCR 行数不足不是独立到底证据
    （满页整行漏识与真短末页不可区分）；独立证据 = 多阶段回翻复归+向前探测。"""

    @staticmethod
    def _full_page(page_idx, rows=6):
        """一页满行（6 行真实刀名，等级错开保证页指纹唯一）。"""
        names = ["三日月宗近", "小狐丸", "前田藤四郎", "压切长谷部",
                 "加州清光", "歌仙兼定"]
        return [_row(n, 120 + i * 90, level=page_idx * 10 + i, fatigue=90)
                for i, n in enumerate(names[:rows])]

    def test_exact_combo_counterexample_is_stalled(self):
        """牛老师精确反例：首屏实际满页但 OCR 只解析 5 行 + 滑动全吞
        + 目标在后页 → stalled，绝不 not_found/unique/点击。"""
        page0 = [_row("三日月宗近", 120, level=1, fatigue=90),
                 _row("小狐丸", 210, level=2, fatigue=90),
                 _row("前田藤四郎", 300, level=3, fatigue=90),
                 _row("加州清光", 390, level=4, fatigue=90),
                 _row("歌仙兼定", 480, level=5, fatigue=90)]
        # 实际第 6 行被 OCR 整行漏掉（根本没出现在 tokens 里）
        pages = [page0, [_ok_row(300)]]
        maa, host = _std_setup(pages=pages, swallow_swipes=True)
        result = _run(host)
        self.assertEqual(result["result"], SCREEN_UNRECOGNIZED)
        self.assertEqual(result["scan_status"], "stalled")
        self.assertEqual(result["pages_scanned"], 1)
        decide_clicks = [c for c in maa.clicks if c[0] == _DECIDE_X]
        self.assertEqual(decide_clicks, [])
        _assert_never_departs(self, maa)

    def test_swallowed_swipes_are_stalled_not_not_found(self):
        """滑动全被吞，只扫了第一页，绝不能谎称整份名单没目标。"""
        pages = [self._full_page(0), self._full_page(1),
                 self._full_page(2, rows=2)]
        maa, host = _std_setup(pages=pages, swallow_swipes=True)
        result = _run(host)
        self.assertEqual(result["result"], SCREEN_UNRECOGNIZED)
        self.assertEqual(result["scan_status"], "stalled")
        self.assertIn("吞", result["reason"])
        self.assertEqual(result["pages_scanned"], 1)
        decide_clicks = [c for c in maa.clicks if c[0] == _DECIDE_X]
        self.assertEqual(decide_clicks, [])
        _assert_never_departs(self, maa)

    def test_mid_scan_swallowed_swipes_cannot_fake_bottom(self):
        """精确回归（老大独立复现）：page0→page1 成功，page1 上第 2、3 次
        前滑被吞，之后反向滑和前滑全部正常。旧实现的回翻复归在 page1 上
        两步全对，误把 page1 当底部返回 not_found——但回翻复归只证明
        「反向和恢复有效」，证明不了候选页是底。必须继续探测并扫到
        page2 找到目标，绝不 false not_found。"""
        pages = [self._full_page(0), self._full_page(1),
                 [_ok_row(300), _row("小狐丸", 450, level=99, fatigue=50)]]
        maa, host = _std_setup(pages=pages)
        maa.swallow_forward = {2, 3}         # 只吞第 2、3 次前滑
        result = _run(host)
        self.assertEqual(result["result"], CHANGED)
        self.assertEqual(result["pages_scanned"], 3)
        _assert_never_departs(self, maa)

    def test_probe_swipes_also_swallowed_cannot_fake_bottom(self):
        """精确回归（老大第二轮反例）：吞第 2、3、5、7 次前滑——停滞触发
        核验后的两次「探测滑」也恰好被吞。探测滑本身也可能被吞，「两轮
        探测都没翻动」和「真到底」在指纹流上不可区分，没有独立末端证据
        时只能 stalled，绝不 not_found。"""
        pages = [self._full_page(0), self._full_page(1),
                 self._full_page(2, rows=2)]
        maa, host = _std_setup(pages=pages)
        maa.swallow_forward = {2, 3, 5, 7}   # 吞停滞滑 + 两次探测滑
        result = _run(host)
        self.assertEqual(result["result"], SCREEN_UNRECOGNIZED)
        self.assertEqual(result["scan_status"], "stalled")
        self.assertEqual(result["pages_scanned"], 2)
        decide_clicks = [c for c in maa.clicks if c[0] == _DECIDE_X]
        self.assertEqual(decide_clicks, [])
        _assert_never_departs(self, maa)

    def test_true_bottom_with_swallowed_probes_still_completes(self):
        """反向钉死：真只有两页、目标不存在，且探测滑也被吞——独立末端
        证据（当前位置就是末页）与「滑动是否被执行」无关，仍允许
        complete 并裁决 not_found。缺了这条，反例修复就退化成
        「永远 stalled」的过度收紧。"""
        pages = [self._full_page(0), self._full_page(1, rows=3)]
        maa, host = _std_setup(pages=pages)
        maa.swallow_forward = {2, 3, 5, 7}
        result = _run(host)
        self.assertEqual(result["result"], NOT_FOUND)
        self.assertEqual(result["pages_scanned"], 2)
        _assert_never_departs(self, maa)

    def test_blind_page_is_recognition_failure(self):
        """OCR 完全失明连续空页 → 识别失败，不是 not_found。"""
        maa, host = _std_setup(pages=[[]])
        result = _run(host)
        self.assertEqual(result["result"], SCREEN_UNRECOGNIZED)
        self.assertEqual(result["scan_status"], "blind")
        self.assertIn("失明", result["reason"])
        decide_clicks = [c for c in maa.clicks if c[0] == _DECIDE_X]
        self.assertEqual(decide_clicks, [])

    def test_full_last_page_proves_bottom_by_backtrack(self):
        """满页末页：回翻一页再翻回来，指纹两步都对上 → complete 可裁决。"""
        pages = [self._full_page(0), self._full_page(1),
                 [_ok_row(660)] + self._full_page(2, rows=5)]
        maa, host = _std_setup(pages=pages)
        result = _run(host)
        self.assertEqual(result["result"], CHANGED)
        self.assertEqual(result["pages_scanned"], 3)
        backward = [s for s in maa.swipes if s[3] > s[1]]
        self.assertTrue(backward)        # 确实做了回翻验证
        _assert_never_departs(self, maa)

    def test_single_short_page_is_honest_stalled(self):
        """单页短库存无从回翻验证：保守 stalled（honest stop，等真机
        末端视觉证据校准），不伪造 complete、不点决定。"""
        pages = [[_ok_row(300), _row("小狐丸", 450, level=99, fatigue=50)]]
        maa, host = _std_setup(pages=pages)
        result = _run(host)
        self.assertEqual(result["result"], SCREEN_UNRECOGNIZED)
        self.assertEqual(result["scan_status"], "stalled")
        decide_clicks = [c for c in maa.clicks if c[0] == _DECIDE_X]
        self.assertEqual(decide_clicks, [])

    def test_short_two_page_list_complete_via_backtrack(self):
        """真短末页 + 独立到底证据（回翻复归）→ complete，可确定 not_found。"""
        pages = [[_row("三日月宗近", 150, level=99, fatigue=100),
                  _row("歌仙兼定", 300, level=90, fatigue=80)],
                 [_row("小狐丸", 300, level=99, fatigue=50)]]
        maa, host = _std_setup(pages=pages)
        result = _run(host)
        self.assertEqual(result["result"], NOT_FOUND)

    def test_backtrack_mismatch_is_stalled(self):
        """满页停滞且回翻被吞（指纹对不上）→ stalled，不裁决。"""
        pages = [self._full_page(0), self._full_page(1)]
        maa, host = _std_setup(pages=pages)
        original_swipe = maa.swipe

        def flaky_swipe(x1, y1, x2, y2, duration_ms=400):
            if y2 > y1:              # 反滑被吞
                maa.swipes.append((x1, y1, x2, y2, duration_ms))
                return
            original_swipe(x1, y1, x2, y2, duration_ms)
        maa.swipe = flaky_swipe
        result = _run(host)
        self.assertEqual(result["result"], SCREEN_UNRECOGNIZED)
        self.assertEqual(result["scan_status"], "stalled")
        decide_clicks = [c for c in maa.clicks if c[0] == _DECIDE_X]
        self.assertEqual(decide_clicks, [])


# ==================== 末端证据：滚动条像素判定 ====================

class ScrollbarEndEvidenceTests(unittest.TestCase):
    """_list_end_sighted 的像素判定（合成帧；口径来自 2026-09-14 运行帧
    校准：滑轨体 x[1262,1270]、轨道 y[124,689]、滑块亮 243/轨道灰 113、
    到底底缘被轨道钳住恒定 689、离底一页的过渡帧底缘 685 只差 4px）。
    真机截图不进仓库，故用合成帧钉死判定逻辑。"""

    class _ShotMaa:
        def __init__(self, img):
            self._img = img

        def screenshot(self, force=False):
            return self._img

    def _sighted(self, img):
        host = FormationEditorMixin()
        host.maa = self._ShotMaa(img)
        return host._list_end_sighted()

    @staticmethod
    def _frame(thumb=None, with_track=True):
        """thumb=(top, bottom)：滑块 y 区间；with_track=False 模拟无滑轨页。"""
        img = np.full((720, 1280, 3), 247, dtype=np.uint8)    # 页面亮背景
        if with_track:
            img[124:690, 1262:1270] = 113                     # 灰色滑轨
        if thumb is not None:
            img[thumb[0]:thumb[1] + 1, 1256:1273] = 243       # 滑块略宽于轨
        return img

    def test_thumb_at_track_bottom_is_sighted(self):
        self.assertTrue(self._sighted(self._frame(thumb=(588, 689))))

    def test_thumb_mid_track_is_not_sighted(self):
        self.assertFalse(self._sighted(self._frame(thumb=(300, 403))))

    def test_thumb_one_page_short_of_bottom_is_not_sighted(self):
        # 真机反例 cal_page_28：离底一页的过渡帧底缘 685，内容仍在变，
        # 只差 4px——必须挡在门外
        self.assertFalse(self._sighted(self._frame(thumb=(582, 685))))

    def test_thumb_near_bottom_without_evidence_is_not_sighted(self):
        # 真机证据只有「到底恒为 689」，没有任何 687/688 的抖动样本；
        # 滑块 1~2px 就够藏一行姓名——零容差，差一点都不放行
        self.assertFalse(self._sighted(self._frame(thumb=(585, 687))))
        self.assertFalse(self._sighted(self._frame(thumb=(586, 688))))

    def test_track_without_thumb_is_not_sighted(self):
        self.assertFalse(self._sighted(self._frame(thumb=None)))

    def test_bright_page_without_track_is_not_sighted(self):
        # 无滑轨的亮页面不得冒充满轨滑块
        self.assertFalse(self._sighted(self._frame(with_track=False)))

    def test_no_frame_is_not_sighted(self):
        self.assertFalse(self._sighted(None))


if __name__ == "__main__":
    unittest.main()
