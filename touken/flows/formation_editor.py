# -*- coding: utf-8 -*-
"""共用编队执行器 v1（"听命令的手"）：把指定部队的指定槽位换成明确目标。

只做换人 + 回读验收。绝不选人（目标由调用方从当前本丸共用档案里挑好
给进来），绝不点击"即刻出阵/远征派遣/演练开始"——出发安全流程永远归
各玩法的 BattleMixin._safe_depart_stream + _confirm_departure。

为什么是一条共用链路（老大现场确认）：
  从目录→编队，以及出阵/远征/演练前的部队选择进入，每个槽位点"替换"
  后进入的是同一套"刀剑男士选择"列表：结构、筛选/排序、翻页、决定均
  相同，只是入口主题字样和配色不同（编队橙/出阵红）。所以：
  - 本执行器同时服务"部队编成"与"部队选择"两种外壳（entry_context）；
  - 页面识别只用标题/布局 OCR，绝不依赖主题色，不维护两套模板。

坐标（1280x720，全部沿用既有同源校准，本模块不新拍脑袋标定）：
  部队标签/六行行心：与 team_roster.py、sakura.py 相同（真机校准）；
  行内"替换"按钮 x=1033（sakura 实测）；
  "刀剑男士选择"列表：标题 OCR ROI、整列 OCR、决定按钮 x=1197、
  翻页 swipe(640,550→640,200,800ms)、8 页上限，均来自 sakura 换人链路
  与 repair 选择列表的真机用法。
  ⚠️ 列表行内目前只有"名字+疲劳"有真机校准（sakura 在用）；等级列
  ROI 是按布局推的待校准通道，读不出就 None，绝不硬猜——见
  parse_selection_rows 的 unknown_fields 与汇报盲区。

身份证据纪律（与 honmaru_profile / expedition_planner 同一套铁律）：
  - sword_catalog_id 是刀种/同位键，不是本丸实例 ID；observation_id
    只作档案引用随结果带回，不能单独拿来声称"页面上找到了那一振"；
  - 跨页面定位只用候选页实际能看到、且本轮仍可靠的证据（默认
    match_fields=("name","form","level")）。疲劳会自然恢复，不是身份
    证据，默认不参与匹配；
  - 「零冲突」只是候选，「证据充分」才放行：对 match_fields 里 target
    有值的身份字段，候选行缺值时不得 unique——target.form 已知而页面
    形态未知、target.level 已知而等级没读到，都只凭同位名字点不得；
    同名多振拉不开、有证据不足的同名行、或存在读不清的行，一律
    ambiguous 并附 missing_evidence，绝不点第一条；
  - 槽位验收同样三态：换前/换后都必须逐项验明（形态读不出=证据不足），
    证据不足换前可继续开名单、换后必须 verification_failed；
  - 当前选择列表没有形态直读通道（行 form 恒 None）：普通/极化同名
    在无法由其他可靠身份证据区分时应诚实停住，不装能认。调用方若从
    档案确知同名唯一，可显式收窄 match_fields（如 ("name","level")）
    来证明证据链，而不是让执行器默认放宽。

扫描完整度契约：
  - 翻页停滞只是"没翻动"（可能被吞），不等于到底；到底须经多阶段
    核验（回翻复归+向前探测+独立末端视觉证据），另有绕圈/截断/
    失明结局；max_pages=60 只是防死循环安全阀，不是"全表"的同义词；
  - 只有 complete（确认到底）的扫描才允许裁决 unique 或确定
    not_found；stalled/truncated/loop/blind 一律 screen_unrecognized +
    scan_incomplete 原因，绝不点击。

失败边界：
  - 找不到列表 / 切队未确认 / 回读页认不出 → screen_unrecognized；
  - 目标整表不存在（可能被别队/手入/修行/互斥隐藏，或档案陈旧）
    → not_found，不换相似候选；
  - 决定已点但列表不关闭（游戏禁用该目标）→ unavailable；
  - 决定后回读不是目标或证据不足 → verification_failed，明确告知
    "游戏队伍可能已发生变化"；只有原成员能被唯一定位时才允许恢复，
    本版不做盲回滚；
  - 翻页有指纹停滞/绕圈检测与页数上限，不在死循环里翻名单。
"""

import json
import re
import time

import numpy as np

from .. import sword_db
from ..maa_adapter import roi_4to4, Point
from ..runtime_paths import STATE_DIR
from .team_roster import _match_name, _ROW_CY, _TEAM_TAB

RESULT_SCHEMA_VERSION = 1

# 结果枚举（机器可读契约）
ALREADY_CORRECT = "already_correct"
CHANGED = "changed"
AMBIGUOUS = "ambiguous"
NOT_FOUND = "not_found"
UNAVAILABLE = "unavailable"
SCREEN_UNRECOGNIZED = "screen_unrecognized"
VERIFICATION_FAILED = "verification_failed"
INVALID_REQUEST = "invalid_request"

_SWAP_X = 1033            # 行内"替换"按钮（sakura 真机校准）
_DECIDE_X = 1197          # 列表行内"决定"按钮（sakura 真机校准）
_DECIDE_DY = -22          # 决定中心 ≈ 名字行中心上方 22px（sakura: 疲劳行-40）
_LIST_TITLE = ("刀剑男士选择", (450, 0, 830, 110))
_FORMATION_TITLE = ("部队编成", (480, 0, 800, 60))      # 与 navigator verify 一致
_TEAM_SELECT_TITLE = ("部队选择", (506, 1, 774, 55))    # 与各玩法 team_ui_ocr 一致
_LIST_ROI = (60, 100, 1240, 700)    # 列表整列 OCR
_NAME_X = (100, 300)                # 姓名带（sakura 名字 ROI x[100,265] 同源）；
                                    # x<100 是位置标记/锁图标区，直接排除
_LEVEL_X = (300, 460)               # 等级列（布局推算，待真机校准）
_FATIGUE_X = (460, 620)             # 疲劳列（sakura 真机校准）
_POS_MARK = re.compile(r"^[一二三四五]\s*之\s*[一二三四五六]?$")  # "N之M"位置标记
_ROW_MERGE_DY = 25                  # 同一行碎 token 归并的 y 容差
_ROW_ATTACH_DY = 40                 # 疲劳/等级 token 归属名字行的 y 容差
_MAX_PAGES = 60                     # 翻页安全阀（防死循环），不是"全表"同义词；
                                    # 全局唯一只允许在 reached_end 后声称
_STALL_LIMIT = 2                    # 指纹连续不动触发「到底核验」（不等于到底）
_BOTTOM_PROOF_STAGES = 2            # 到底核验的独立阶段数：每阶段都重新正面
                                    # 验证反向+恢复有效后再探测；探测无新页还
                                    # 须独立末端视觉证据（_list_end_sighted），
                                    # 可能被吞的探测滑不包装成绝对证明
_SWIPE_NEXT = (640, 550, 640, 200, 800)   # 下一页（sakura/repair 实测 800ms）
_SWIPE_PREV = (640, 200, 640, 550, 800)
# 选择列表右缘滚动条（_list_end_sighted 的独立末端证据通道，
# 校准口径见该函数 docstring；改动这些数必须重新从运行帧取样验证）
_SCROLLBAR_BAND_X = (1262, 1270)          # 滑轨体列带
_SCROLLBAR_TRACK_Y = (124, 690)           # 滑轨纵向范围
_SCROLLBAR_BOTTOM_Y = 689                 # 滑块到底时底缘 y（钳在轨底，
                                          # 阈值 180~235 读数恒定 689）
_SCROLLBAR_BOTTOM_TOL = 0                 # 贴底零容差：真机证据只有
                                          # 「到底恒为 689」，没有任何
                                          # 687/688 的抖动样本；而滑块
                                          # 4px≈内容 62px，1px 也够藏住
                                          # 一行姓名，故只有明确读到 689
                                          # 才算到底，其余宁可 stalled
_SCROLLBAR_THUMB_BRIGHT = 200             # 滑块亮 ~243 / 轨道灰 ~113
_SCROLLBAR_TRACK_DARK = 150               # 轨道灰必须成段存在（防无滑轨
                                          # 页面的亮背景冒充满轨滑块）
_CONFIRM_POPUP_TEMPLATE = "通用_确定.png"
DEFAULT_MATCH_FIELDS = ("name", "form", "level")

# 安全声明：本执行器的点击只允许落在以下目标上——部队标签、行内"替换"
# (1033)、列表行内"决定"(1197)、确认弹窗"通用_确定"、翻页 swipe。
# 出发类按钮的实测坐标钉在这里，永不点击；测试据此断言。
FORBIDDEN_DEPART_CLICKS = frozenset({
    (1198, 625),   # team_select.depart「即刻出阵」（touken_config.example.json）
    (1200, 630),   # 演练「演练开始」（practice.py）
})

_LEVEL_TOKEN = re.compile(r"(?:Lv\.?|刀剑)?\s*(\d{1,3})\s*级?$")
_FATIGUE_PAIR = re.compile(r"(\d{1,3})\D{0,2}/\D{0,2}(\d{1,3})")


# ==================== 纯函数：目标 / 行解析 / 匹配判定 ====================

def normalize_target(target):
    """把候选池条目（或等价 dict）规范化成执行目标。

    必填身份：sword_catalog_id 或 name（能过名册校正）；observation_id
    仅作档案引用随结果带回。form 只认两条来路：调用方显式给的
    form（normal/kiwame），或档案候选条目的 form_status 结论
    （ambiguous/unknown 一律落 None）。kiwame_date 是「显现日期」，
    每振刀都有，永远不参与形态推断（2026-09-15 P0 修正：旧版拿它
    推形态，把 185/196 振全误判成极）。
    Returns: (normalized, error)；error 非 None 表示输入不可用。
    """
    if not isinstance(target, dict):
        return None, "target 必须是候选池条目 dict"
    sid = target.get("sword_catalog_id")
    name = target.get("name") or target.get("name_zh")
    if not sid and name:
        sid = _match_name(name)
    if not sid:
        return None, "target 缺身份（sword_catalog_id/name 都没有或认不出）"
    info = sword_db.all_swords().get(sid) or {}
    if not name:
        name = info.get("name_zh") or info.get("name")
    form = target.get("form")
    if form not in ("normal", "kiwame"):
        status = target.get("form_status")
        form = status if status in ("normal", "kiwame") else None
    out = {"observation_id": target.get("observation_id"),
           "sword_catalog_id": sid,
           "name": name,
           "form": form,
           "level": target.get("level"),
           "tou_level": target.get("tou_level"),
           "survival": target.get("survival"),
           "survival_max": target.get("survival_max")}
    return out, None


def _parse_level_token(text):
    m = _LEVEL_TOKEN.search(str(text or "").strip())
    return int(m.group(1)) if m else None


def _parse_fatigue_token(text):
    for cur, mx in _FATIGUE_PAIR.findall(str(text or "")):
        if mx == "100":
            return int(cur)
    return None


def parse_selection_rows(tokens):
    """列表整列 OCR token → 行列表（纯函数，可测）。

    姓名带只收 x∈[100,300) 的 token：左侧 x<100 是"N之M"位置标记和
    锁图标区（真机布局），落进姓名带的"N之M"标记也按格式排除——
    两者都不算"读不清的名字"。姓名带里的其他乱码仍计入 unreadable
    （保守阻断）。碎 token 按 y 归并成文本行再过名册校正；等级/疲劳
    token 按 y 就近归属。 Returns: (rows, unreadable_rows)。
    rows 每项: {"y", "name_raw", "name", "sword_catalog_id", "level",
    "fatigue", "form": None, "unknown_fields": [...]}。
    form 恒为 None——选择列表目前没有形态直读通道（盲区，如实标注）。
    """
    name_band, level_band, fatigue_band = [], [], []
    for text, pt in tokens or []:
        text = str(text or "").strip()
        if not text:
            continue
        x, y = getattr(pt, "x", 0) or 0, getattr(pt, "y", 0) or 0
        if x < _NAME_X[0]:
            continue                # 位置标记/锁图标区：不是名字，不是乱码
        if x < _NAME_X[1]:
            if _POS_MARK.match(text):
                continue            # 落进姓名带的"N之M"标记：排除，不算乱码
            name_band.append((x, y, text))
        elif _LEVEL_X[0] <= x < _LEVEL_X[1]:
            lv = _parse_level_token(text)
            if lv is not None:
                level_band.append((y, lv))
        elif _FATIGUE_X[0] <= x < _FATIGUE_X[1]:
            fv = _parse_fatigue_token(text)
            if fv is not None:
                fatigue_band.append((y, fv))

    # 名字碎 token 归行：按 y 排序后 proximity 归并，同组按 x 拼接
    name_band.sort(key=lambda t: (t[1], t[0]))
    lines = []
    for x, y, text in name_band:
        if lines and abs(y - lines[-1][0]) <= _ROW_MERGE_DY:
            lines[-1][1].append((x, text))
        else:
            lines.append([y, [(x, text)]])

    rows, unreadable = [], 0
    for y, parts in lines:
        name_raw = "".join(t for _x, t in sorted(parts))
        sid = _match_name(name_raw)
        if sid is None:
            unreadable += 1
        info = sword_db.all_swords().get(sid) if sid else None
        level = fatigue = None
        for ty, lv in level_band:
            if abs(ty - y) <= _ROW_ATTACH_DY:
                level = lv
                break
        for ty, fv in fatigue_band:
            if abs(ty - y) <= _ROW_ATTACH_DY:
                fatigue = fv
                break
        unknown = []
        if sid is None:
            unknown.append("name")
        if level is None:
            unknown.append("level")
        if fatigue is None:
            unknown.append("fatigue")
        unknown.append("form")   # 页面无形态通道，永远算缺口
        rows.append({"y": y, "name_raw": name_raw,
                     "name": (info.get("name_zh") or info["name"])
                             if info else None,
                     "sword_catalog_id": sid, "level": level,
                     "fatigue": fatigue, "form": None,
                     "unknown_fields": unknown})
    return rows, unreadable


def page_fingerprint(rows):
    """一页的指纹：翻页停滞/绕圈检测与回退定位用。"""
    return tuple(sorted((r["sword_catalog_id"] or r["name_raw"] or "?",
                         r["level"], r["fatigue"]) for r in rows))


def row_conflicts_target(row, target, match_fields):
    """行与目标在某字段上两边都有值且不一致 → True（冲突，排除）。
    任何一边缺值都不构成冲突（缺证据 ≠ 反证）。"""
    for field in match_fields:
        tv = target.get(field)
        if tv is None:
            continue
        if field == "name":
            rv = row.get("sword_catalog_id")
            if rv is not None and rv != target["sword_catalog_id"]:
                return True
        else:
            rv = row.get(field)
            if rv is not None and rv != tv:
                return True
    return False


def row_evidence_gaps(row, target, match_fields):
    """目标有值但行读不出的字段（唯一匹配时也要如实带出）。"""
    gaps = []
    for field in match_fields:
        if target.get(field) is None:
            continue
        if field == "name":
            if row.get("sword_catalog_id") is None:
                gaps.append("name")
        elif row.get(field) is None:
            gaps.append(field)
    return gaps


def decide_match(pages, target, match_fields=DEFAULT_MATCH_FIELDS,
                 unreadable_rows=0):
    """全表扫描后的裁决（纯函数）。「零冲突」只是候选，「证据充分」才放行。

    对调用方要求参与 match_fields 且 target 有值的身份字段，候选行缺值
    时不得 unique——只凭同位名字点击会把"没证据反对"误当"有证据确认"。
    只有满足以下全部条件才 unique：全表恰好一条零冲突且证据充分的行、
    没有证据不足的同名行、没有读不清的行、扫描域完整（由调用方保证，
    截断扫描不得进入本裁决）。

    Returns:
        {"status": "unique", "page", "row", "evidence_gaps": []}
        {"status": "ambiguous", "candidates", "reason", "missing_evidence"}
        {"status": "not_found", "reason"}
    """
    confirmed, unconfirmed = [], []
    for page_idx, rows in enumerate(pages):
        for row in rows:
            sid = row.get("sword_catalog_id")
            if sid is None or sid != target["sword_catalog_id"]:
                continue  # 读不清的行单独算 unreadable，别家的刀无关
            if row_conflicts_target(row, target, match_fields):
                continue
            missing = row_evidence_gaps(row, target, match_fields)
            if missing:
                unconfirmed.append((page_idx, row, missing))
            else:
                confirmed.append((page_idx, row))

    if len(confirmed) == 1 and not unconfirmed and not unreadable_rows:
        page_idx, row = confirmed[0]
        return {"status": "unique", "page": page_idx, "row": row,
                "evidence_gaps": []}

    if not confirmed and not unconfirmed:
        return {"status": "not_found",
                "reason": ("整份列表没有与目标零冲突的行：目标可能被游戏"
                           "隐藏/禁用（在别队、手入/修行、同位互斥、远征中），"
                           "或档案字段已陈旧（等级变了会对不上）")}

    missing_evidence = sorted({f for _p, _r, m in unconfirmed for f in m})
    candidates = [_row_summary(r) for _p, r in
                  [(p, r) for p, r in confirmed]
                  + [(p, r) for p, r, _m in unconfirmed]]
    if len(confirmed) > 1:
        reason = (f"同名同型候选 {len(confirmed)} 振在可观察字段上"
                  "拉不开，拒绝点第一条（不伪造一号/二号）")
    elif unconfirmed:
        reason = (f"同名候选缺身份证据（{'、'.join(missing_evidence)}）："
                  "缺证据不等于没冲突，不能排除是另一振，拒绝下点")
    else:  # 唯一确认行，但有读不清的行不能排除
        reason = (f"有 {unreadable_rows} 行名字读不清，不能排除"
                  "目标是其一，拒绝下点")
    return {"status": "ambiguous", "candidates": candidates,
            "missing_evidence": missing_evidence, "reason": reason}


def _row_summary(row):
    return {"name": row.get("name") or row.get("name_raw"),
            "level": row.get("level"), "fatigue": row.get("fatigue"),
            "form": row.get("form"),
            "unknown_fields": list(row.get("unknown_fields") or [])}


def slot_matches_target(slot, target, match_fields=DEFAULT_MATCH_FIELDS):
    """编队槽观察 vs 目标身份：三态 True / False / None（证据不足）。

    刀种目录必须一致（不一致=False）。对 match_fields 里 target 有值的
    身份字段：槽位有值且冲突 → False；槽位缺值 → None（证据不足，
    不算确认也不算排除）。目标 form 已知而槽位形态读不出时绝不通过——
    换前不能零点击宣称 already_correct，换后也不能报 changed。
    疲劳不在默认 match_fields 里（自然恢复，不是身份证据）。
    """
    status = slot.get("slot_status")
    if status == "empty":
        return False
    if status != "occupied":
        return None
    sid = slot.get("sword_catalog_id")
    if not sid:
        return None
    if sid != target["sword_catalog_id"]:
        return False
    for field in match_fields:
        if field == "name":
            continue
        tv = target.get(field)
        if tv is None:
            continue
        if field == "form":
            sv = slot.get("kiwame_status")
            if sv in ("kiwame", "normal"):
                if sv != tv:
                    return False
            else:
                return None        # 形态证据不足
        else:
            sv = slot.get(field)
            if sv is None:
                return None        # 字段证据不足
            if sv != tv:
                return False
    return True


# ==================== 远征占用预检（预设编队用） ====================

def _expedition_busy(team_no):
    """目标队此刻是否还在远征（读 STATE_DIR/expeditions.json）。
    口径同 panel.scheduler.team_available：dispatched_at + duration_min
    没过完就算占用；文件缺失/损坏/字段缺一律当作没占用，不拦。
    （touken 层不 import panel，故口径在此复写一份，别反向依赖。）"""
    try:
        records = json.loads(
            (STATE_DIR / "expeditions.json").read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return False
    record = records.get(str(team_no), {}) if isinstance(records, dict) else {}
    try:
        end = time.mktime(time.strptime(record["dispatched_at"],
                                        "%Y-%m-%d %H:%M:%S"))
        end += int(record["duration_min"]) * 60
        return time.time() < end
    except (KeyError, TypeError, ValueError):
        return False


def _slot_no(key):
    """槽位键转 int；认不出的键返回 0——ensure 会按 INVALID_REQUEST 收拾它。"""
    try:
        return int(key)
    except (TypeError, ValueError):
        return 0


# ==================== 执行器 ====================

class FormationEditorMixin:
    """共用编队执行器。依赖宿主：maa、config、record_event、
    navigate_to_stream、current_location，以及 TeamRosterMixin 的
    _read_team_page / _read_row_label（经 _formation_* 注入缝调用）。"""

    # ---- 注入缝（测试/未来页面差异收口处） ----

    def _formation_read_team(self):
        """当前帧读六槽（默认复用 TeamRosterMixin 的只读点名）。"""
        return self._read_team_page()

    def _formation_row_label(self, cy):
        """读行首"N之M"位置标签（切队正面确认）。"""
        return self._read_row_label(cy)

    # ---- 对外契约 ----

    def ensure_team_member(self, team_no, slot_no, target, **kw):
        """非流式便捷入口：跑完返回机器可读结果 dict。"""
        gen = self.ensure_team_member_stream(team_no, slot_no, target, **kw)
        while True:
            try:
                next(gen)
            except StopIteration as stop:
                return stop.value

    def ensure_team_member_from_honmaru_stream(self, team_no, slot_no,
                                               target, **kw):
        """standalone 入口：从本丸安全进入目录→编队后执行（供前端调用）。
        目录路径不是玩法自动化的必经路；已在部队选择页的调用方直接用
        ensure_team_member_stream(entry_context="team_select")。"""
        for msg in self.navigate_to_stream("编队"):
            yield msg
        kw["entry_context"] = "formation"
        return (yield from self.ensure_team_member_stream(
            team_no, slot_no, target, **kw))

    def ensure_team_member_stream(self, team_no, slot_no, target,
                                  entry_context="auto",
                                  match_fields=None, max_pages=None):
        """把部队 team_no(1~5) 的 slot_no(1~6) 换成明确目标，回读验收。

        entry_context:
          "auto"       已在编队/部队选择页则原地执行；都不在 → 导航去编队；
          "formation"  要求在/导航到"部队编成"页；
          "team_select" 要求当前已在"部队选择"页，不在就如实失败（不乱逛）。
        Returns（yield from 接）: 机器可读结果 dict（RESULT_SCHEMA_VERSION）。
        """
        cfg = self.config.get("formation_editor", {}) \
            if isinstance(getattr(self, "config", None), dict) else {}
        match_fields = tuple(match_fields
                             or cfg.get("match_fields")
                             or DEFAULT_MATCH_FIELDS)
        max_pages = int(max_pages or cfg.get("max_pages") or _MAX_PAGES)

        tgt, err = normalize_target(target)
        if err or not isinstance(team_no, int) or team_no not in _TEAM_TAB \
                or not isinstance(slot_no, int) or not 1 <= slot_no <= 6:
            reason = err or f"team_no/slot_no 越界（{team_no}/{slot_no}）"
            yield f"[编队] 请求无效：{reason}"
            return self._finish(INVALID_REQUEST, team_no, slot_no, target,
                                reason)

        yield (f"[编队] 目标：部队{team_no} {slot_no}号位 ← "
               f"{tgt['name']}（{tgt['sword_catalog_id']}，"
               f"形态 {tgt['form'] or '未知'}，Lv {tgt['level'] or '?'}）")

        # 1) 站上共用编队表面（两种外壳同一条链路）
        shell = yield from self._ensure_surface(entry_context)
        if shell is None:
            yield "[编队] 既不在部队编成也不在部队选择页，停"
            return self._finish(SCREEN_UNRECOGNIZED, team_no, slot_no, tgt,
                                "无法确认处于共用编队表面（编成/部队选择）")
        yield f"[编队] 当前外壳：{'部队编成' if shell == 'formation' else '部队选择'}"

        # 2) 切队正面确认（位置标签必须显示请求的队号）
        if not (yield from self._select_team_confirmed(team_no)):
            yield f"[编队] 部队{team_no}切队未确认，停"
            return self._finish(SCREEN_UNRECOGNIZED, team_no, slot_no, tgt,
                                f"部队{team_no}标签切队未确认，不落任何点击",
                                entry_shell=shell)

        # 3) 换前观察：三态验收——确认是目标才零点击；证据不足不冒充正确，
        #    但可以继续打开名单寻找明确目标
        team_before = self._formation_read_team()
        slot_before = team_before[slot_no - 1] if team_before else None
        if slot_before is None:
            yield f"[编队] {slot_no}号位读不出（失明页？），停"
            return self._finish(SCREEN_UNRECOGNIZED, team_no, slot_no, tgt,
                                "换前观察失败：整页读不出", entry_shell=shell)
        m = slot_matches_target(slot_before, tgt, match_fields)
        if m is True:
            yield f"[编队] {slot_no}号位已确认是目标，零点击收工"
            return self._finish(ALREADY_CORRECT, team_no, slot_no, tgt,
                                "目标槽位回读与目标逐项一致，未做任何换人点击",
                                entry_shell=shell,
                                before=slot_before, after=slot_before,
                                team_before=team_before,
                                team_after=team_before)
        if m is None:
            yield (f"[编队] {slot_no}号位读数与目标不足以互相确认"
                   "（形态/等级证据缺口），不能零点击宣称正确——"
                   "打开名单寻找明确目标")

        # 4) 点"替换"，确认进入"刀剑男士选择"
        cy = _ROW_CY[slot_no - 1]
        self.maa.click(Point(_SWAP_X, cy))
        if not self._wait_list_open():
            yield "[编队] 刀剑男士选择列表没打开，停（未做任何变更）"
            return self._finish(SCREEN_UNRECOGNIZED, team_no, slot_no, tgt,
                                "点了替换但选择列表未出现", entry_shell=shell,
                                before=slot_before, team_before=team_before)

        # 5) 全表扫描（指纹停滞=到底 / 绕圈 / 截断三种结局分明），
        #    只有确定扫到底的完整扫描才允许裁决唯一——截断名单上的
        #    "唯一"既找不到后段目标，也证明不了全局唯一
        pages, fps, current_idx, unreadable, scan_status = \
            yield from self._scan_selection_list(max_pages)
        if scan_status != "complete":
            why = {"truncated": "触达安全上限仍未到底",
                   "loop": "翻页指纹绕圈，页序异常",
                   "stalled": "连续滑动无响应且无法证明到底"
                              "（滑动可能被模拟器吞掉）",
                   "blind": "整页 OCR 失明，一行都读不出（页面识别失败）",
                   }.get(scan_status, scan_status)
            yield (f"[编队] 扫描未到底（scan_incomplete={scan_status}）："
                   f"已扫 {len(pages)} 页，{why}，不能证明全局唯一，拒绝下点")
            return self._finish(SCREEN_UNRECOGNIZED, team_no, slot_no, tgt,
                                f"scan_incomplete：{why}（已扫 {len(pages)} 页），"
                                "不点击、不裁决", entry_shell=shell,
                                before=slot_before, team_before=team_before,
                                pages_scanned=len(pages),
                                scan_status=scan_status)
        verdict = decide_match(pages, tgt, match_fields, unreadable)
        if verdict["status"] == "not_found":
            yield f"[编队] 翻遍 {len(pages)} 页没找到目标：{verdict['reason']}"
            return self._finish(NOT_FOUND, team_no, slot_no, tgt,
                                verdict["reason"], entry_shell=shell,
                                before=slot_before, team_before=team_before,
                                pages_scanned=len(pages))
        if verdict["status"] == "ambiguous":
            yield f"[编队] 目标不唯一：{verdict['reason']}"
            return self._finish(AMBIGUOUS, team_no, slot_no, tgt,
                                verdict["reason"], entry_shell=shell,
                                before=slot_before, team_before=team_before,
                                candidates=verdict["candidates"],
                                missing_evidence=verdict.get(
                                    "missing_evidence", []),
                                pages_scanned=len(pages))

        # 6) 回到目标所在页，用同一套「证据充分」条件重新确认该行后点"决定"
        target_page = verdict["page"]
        row = verdict["row"]
        yield (f"[编队] 唯一匹配在第 {target_page + 1} 页："
               f"{row['name']} Lv{row.get('level') or '?'}")
        current_idx = yield from self._goto_page(
            pages, fps, current_idx, target_page)
        if current_idx is None:
            yield "[编队] 无法在列表里重新定位目标页，停（未点决定）"
            return self._finish(SCREEN_UNRECOGNIZED, team_no, slot_no, tgt,
                                "列表翻页指纹对不上，重新定位失败",
                                entry_shell=shell, before=slot_before,
                                team_before=team_before)
        row = self._relocate_row(tgt, row, match_fields)
        if row is None:
            yield "[编队] 回到目标页后该行读不稳，停（未点决定）"
            return self._finish(SCREEN_UNRECOGNIZED, team_no, slot_no, tgt,
                                "目标行重新读取与扫描时不一致",
                                entry_shell=shell, before=slot_before,
                                team_before=team_before)

        self.maa.click(Point(_DECIDE_X, row["y"] + _DECIDE_DY))
        if not self._wait_list_closed():
            yield ("[编队] 决定已点但列表不关闭：目标可能被游戏规则禁用"
                   "（手入/修行/同位互斥/远征中），停")
            return self._finish(UNAVAILABLE, team_no, slot_no, tgt,
                                "决定未生效：目标不可选或已被占用",
                                entry_shell=shell, before=slot_before,
                                team_before=team_before)

        # 7) 回到原编队表面，重新观察验收：三态——确认是目标才 changed；
        #    证据不足与确认不是目标一样算 verification_failed，绝不假报成功
        shell_after = self._detect_shell()
        if shell_after is None:
            yield "[编队] 决定后回不到编队表面，页面状态未知，停"
            return self._finish(SCREEN_UNRECOGNIZED, team_no, slot_no, tgt,
                                "决定后既认不出编成才也认不出部队选择",
                                entry_shell=shell, before=slot_before,
                                team_before=team_before)
        if not (yield from self._select_team_confirmed(team_no)):
            yield f"[编队] 回读前切不回部队{team_no}，验收失败"
            return self._finish(VERIFICATION_FAILED, team_no, slot_no, tgt,
                                "决定已生效但回读前切队未确认；游戏队伍可能"
                                "已发生变化，请人工核对", entry_shell=shell,
                                before=slot_before, team_before=team_before)
        team_after = self._formation_read_team()
        slot_after = team_after[slot_no - 1] if team_after else None
        others = _other_slot_changes(team_before, team_after, slot_no)
        if slot_after is not None \
                and slot_matches_target(slot_after, tgt, match_fields) is True:
            yield (f"[编队] ✓ 换好了：部队{team_no} {slot_no}号位 = "
                   f"{slot_after.get('name') or tgt['name']}")
            return self._finish(CHANGED, team_no, slot_no, tgt,
                                "回读逐项验收通过", entry_shell=shell,
                                before=slot_before, after=slot_after,
                                team_before=team_before, team_after=team_after,
                                other_slot_changes=others,
                                evidence_gaps=[],
                                pages_scanned=len(pages))
        if slot_after is not None \
                and slot_matches_target(slot_after, tgt, match_fields) is None:
            detail = ("回读证据不足（形态/等级未能逐项复核），无法确认是目标")
        else:
            detail = (f"回读不是目标（{(slot_after or {}).get('name') or '读不出'}）")
        yield (f"[编队] ⚠️ {detail}，"
               "游戏队伍可能已发生变化，请人工核对；本版不做盲回滚")
        return self._finish(VERIFICATION_FAILED, team_no, slot_no, tgt,
                            f"{detail}；游戏队伍可能已发生变化，未做盲回滚",
                            entry_shell=shell,
                            before=slot_before, after=slot_after,
                            team_before=team_before, team_after=team_after,
                            other_slot_changes=others)

    def apply_preset_formation_stream(self, team_no: int, slots: dict,
                                      name: str = "预设编队"):
        """把预设编队套到游戏内部队 team_no(1~5)：逐槽 ensure 换人。

        先预检目标队远征占用（占用直接停，不做还原），导航到编队页切队后
        按槽位号升序逐槽 ensure（entry_context="formation"）。任何一槽结果
        不是 changed/already_correct 就停：队伍是半套状态，如实汇报，
        不还原、不装绿。
        Returns（yield from 接）: True 全部落妥 / False 没应用完。
        """
        if not isinstance(team_no, int) or team_no not in _TEAM_TAB:
            yield f"[预设编队] 部队编号 {team_no} 不认识，无法换人（只支持 1~5）"
            return False
        if not isinstance(slots, dict) or not slots:
            yield ("[预设编队] 这套预设一个位置都没指定，"
                   "无法应用：去编队页编辑一下")
            return False
        if _expedition_busy(team_no):
            yield (f"[预设编队] 部队{team_no}还在远征没回来，"
                   "换不了人，等收远征再说")
            return False

        for msg in self.navigate_to_stream("编队"):
            yield msg
        if self.current_location != "编队":
            yield "[预设编队] 无法到编队页，预设没应用完"
            return False
        self.maa.click(Point(*_TEAM_TAB[team_no]))
        time.sleep(1.5)

        changed = already = 0
        for slot_key in sorted(slots, key=_slot_no):
            slot_no = _slot_no(slot_key)
            # 选择列表没有形态直读通道（行 form 恒 None）：预设槽位里的
            # form_status 是档案结论，放进 match_fields 只会让每行都背上
            # 证据缺口而必判 ambiguous。收窄到列表真正能出示证据的字段；
            # 同名多振靠等级拉开，等级也拉不开就如实 ambiguous 停下。
            result = yield from self.ensure_team_member_stream(
                team_no, slot_no, slots[slot_key], entry_context="formation",
                match_fields=("name", "level"))
            verdict = result.get("result") if isinstance(result, dict) else None
            if verdict == ALREADY_CORRECT:
                already += 1
                continue
            if verdict == CHANGED:
                changed += 1
                continue
            reason = result.get("reason") if isinstance(result, dict) \
                else f"ensure 没返回结果 dict（{result!r}）"
            yield (f"[预设编队] 卡在{slot_no}号位：{reason}，"
                   "预设没应用完，队伍现在是半套，去看看")
            return False
        yield (f"[预设编队] ✓ 『{name}』已覆盖部队{team_no}："
               f"换好 {changed} 位，{already} 位本来就在")
        return True

    # ---- 外壳与切队 ----

    def _detect_shell(self):
        """认当前编队外壳：标题 OCR 判定，不看主题色。"""
        self.maa.screenshot(force=True)
        text, roi = _FORMATION_TITLE
        if self.maa.ocr(text, roi_4to4(*roi)):
            return "formation"
        text, roi = _TEAM_SELECT_TITLE
        if self.maa.ocr(text, roi_4to4(*roi)):
            return "team_select"
        return None

    def _ensure_surface(self, entry_context):
        if entry_context in ("auto", "formation", "team_select"):
            shell = self._detect_shell()
            if shell and (entry_context == "auto" or shell == entry_context):
                return shell
            if entry_context == "team_select":
                return None  # 指定了部队选择却不在：如实失败，不乱逛
            # auto/formation：导航到编队（navigate_to_stream 自带 verify）
            for _msg in self.navigate_to_stream("编队"):
                yield _msg
            return self._detect_shell()
        return None

    def _select_team_confirmed(self, team_no):
        """点部队标签并用位置标签正面确认（team_roster 同款纪律）。"""
        for attempt in (1, 2, 3):
            self.maa.click(Point(*_TEAM_TAB[team_no]))
            time.sleep(1.0)
            self.maa.screenshot(force=True)
            seen = (self._formation_row_label(_ROW_CY[0]),
                    self._formation_row_label(_ROW_CY[5]))
            if seen == (team_no, team_no):
                return True
            yield f"[编队] 切部队{team_no}第 {attempt}/3 次未确认，重试"
        return False

    # ---- 列表交互 ----

    def _wait_list_open(self, attempts=10):
        text, roi = _LIST_TITLE
        for _ in range(attempts):
            self.maa.screenshot(force=True)
            if self.maa.ocr(text, roi_4to4(*roi)):
                return True
            time.sleep(0.5)
        return False

    def _wait_list_closed(self, attempts=8):
        """决定/弹窗处理：列表标题消失才算生效；期间兜底确认弹窗。"""
        text, roi = _LIST_TITLE
        for _ in range(attempts):
            time.sleep(0.5)
            self.maa.screenshot(force=True)
            pt = self.maa.template_match(_CONFIRM_POPUP_TEMPLATE,
                                         threshold=0.7)
            if pt:
                self.maa.click(pt)
                time.sleep(0.8)
                self.maa.screenshot(force=True)
            if not self.maa.ocr(text, roi_4to4(*roi)):
                return True
        return False

    def _parse_selection_rows(self, tokens):
        """注入缝：默认调纯函数 parse_selection_rows；未来真机校准出
        形态/其他行内通道时在这里给行补证据（测试也经此注入剧本证据）。"""
        return parse_selection_rows(tokens)

    def _read_list_page(self):
        """当前帧读列表页。Returns (rows, unreadable)。"""
        self.maa.screenshot(force=True)
        tokens = self.maa.ocr_all(roi_4to4(*_LIST_ROI)) or []
        return self._parse_selection_rows(tokens)

    def _scan_selection_list(self, max_pages):
        """逐页 OCR 全表。Returns (pages, fps, current_idx, unreadable, status)。

        status 四态分明——「滑不动」和「确认到底」是两件事：
          complete  —— 停滞后通过多阶段到底核验（每阶段：反滑回上一页、
                      正滑恢复候选页、再正滑探测候选页之后；探测无新页
                      还必须由独立末端视觉证据确认「候选页就是末页」，
                      连续 _BOTTOM_PROOF_STAGES 个阶段全过才允许称底）。
                      回翻复归只证明「反向和恢复有效」，证明不了候选页
                      是底：中途被吞的前滑会在恢复后的探测里露出新页，
                      新页交还本循环继续扫，不丢页不重复；而探测滑本身
                      也可能被吞，「探测没翻动」与真底在指纹流上不可
                      区分，故末端证据独立成章。OCR 行数不足不是独立
                      到底证据（满页被整行漏识与真正短末页长得一样，见
                      2026-09-14 牛老师组合反例），绝不使用；
          stalled   —— 连续滑动无响应且拿不出到底证据（滑动可能被吞；
                      探测被吞与真底不可区分、滚动条没贴底、或单页名单
                      无从回翻验证，同样保守 stalled——这是 honest stop）；
          blind     —— 任何一页 OCR 一行都读不出（整页失明，识别失败）；
          truncated —— 触达 max_pages 安全阀仍未到底；
          loop      —— 指纹绕回已见过的页（页序异常，不等于到底）。
        只有 complete 允许裁决唯一/确定 not_found，其余一律拒绝下点。
        """
        pages, fps, unreadable = [], [], 0
        current_idx, stalls, status = 0, 0, "complete"
        pending = None          # 到底核验探出的新页，交还循环当当前页处理
        while True:
            if pending is not None:
                rows, bad = pending
                pending = None
            else:
                rows, bad = self._read_list_page()
            if fps and not rows:
                status = "blind"       # 翻页后整页失明
                break
            fp = page_fingerprint(rows)
            if fps and fp == fps[-1]:
                stalls += 1
                if stalls >= _STALL_LIMIT:
                    outcome, recovered = self._verify_bottom(fps)
                    if outcome != "advanced":
                        status = outcome           # complete / stalled
                        break
                    pending = recovered            # 候选页之后还有页：继续扫
                    continue
                self.maa.swipe(*_SWIPE_NEXT)
                time.sleep(1.2)
                continue
            if fp in fps:
                status = "loop"
                break
            if not rows:
                status = "blind"       # 首页就一行都读不出
                break
            pages.append(rows)
            fps.append(fp)
            unreadable += bad
            current_idx = len(pages) - 1
            stalls = 0
            if len(pages) >= max_pages:
                status = "truncated"
                break
            self.maa.swipe(*_SWIPE_NEXT)
            time.sleep(1.2)
        yield (f"[编队] 列表扫描 {len(pages)} 页"
               f"（{'已到底' if status == 'complete' else '未到底：' + status}，"
               f"读不清 {unreadable} 行）")
        return pages, fps, current_idx, unreadable, status

    def _verify_bottom(self, fps):
        """停滞后的「到底」多阶段核验。Returns (outcome, recovered)：
          ("stalled",  None)       证据不足（只有一页无从回翻，或回翻/
                                   恢复/探测任一环失效，或探测无新页却
                                   拿不出独立末端证据）——绝不称底；
          ("complete", None)       连续 _BOTTOM_PROOF_STAGES 个阶段，每阶段
                                   反向+恢复都被正面验证、探测无新页、且
                                   独立末端证据确认当前位置就是末页；
          ("advanced", (rows,bad)) 恢复后探测出新页——候选页不是底，新页
                                   交还扫描循环继续（由主循环判 loop/blind）。

        纪律：回翻复归只证明「此刻反向和恢复滑都有效」，证明不了候选页
        就是底——中途被吞的前滑正是这么骗过单步核验的（2026-09-14 精确
        反例：page1 上两次前滑被吞，回翻复归两步全对，page2 从未被看见，
        误报 not_found）。而「探测无新页」同样证明不了到底——探测滑本身
        也可能被吞，与真底在指纹流上不可区分（同日第二轮反例：吞第 2、3、
        5、7 次前滑，两轮探测全被吞，照样假 complete）。所以称底必须
        同时具备：① 逐阶段正面验证的反向+恢复机制（证明「我在候选页」）、
        ② 探测后无新页、③ 独立末端视觉证据（证明「候选页就是末页」）。
        任何一环证据不足都只报 stalled，绝不 not_found。
        """
        if len(fps) < 2:
            return "stalled", None      # 单页无从回翻：honest stop
        for _stage in range(_BOTTOM_PROOF_STAGES):
            self.maa.swipe(*_SWIPE_PREV)            # ① 反滑回上一页
            time.sleep(1.2)
            rows, _bad = self._read_list_page()
            if page_fingerprint(rows) != fps[-2]:
                return "stalled", None
            self.maa.swipe(*_SWIPE_NEXT)            # ② 正滑恢复候选页
            time.sleep(1.2)
            rows, _bad = self._read_list_page()
            if page_fingerprint(rows) != fps[-1]:
                return "stalled", None
            self.maa.swipe(*_SWIPE_NEXT)            # ③ 探测候选页之后
            time.sleep(1.2)
            rows, bad = self._read_list_page()
            if not rows:
                return "stalled", None              # 探测后失明：证据不足
            if page_fingerprint(rows) != fps[-1]:
                return "advanced", (rows, bad)      # 还有页：交还扫描循环
            if not self._list_end_sighted():
                return "stalled", None              # 探测没翻动 ≠ 到底：探测滑
                                                    # 本身也可能被吞（指纹流与
                                                    # 真底不可区分），须独立
                                                    # 末端证据才能称底
        return "complete", None

    def _list_end_sighted(self):
        """独立末端视觉证据：选择列表右缘滚动条的滑块底缘贴上滑轨底部。
        回答「当前位置是不是列表末尾」——与滑动是否被执行无关的绝对
        位置证据，探测滑被吞也不影响读数。读帧失败或找不到滑块时保守
        False（证据不足，调用方只能 stalled）。测试经子类注入剧本证据。

        校准来源（2026-09-14，MAAAdapter 运行帧通道逐页取样 30 页）：
        滑轨体 x[1262,1270]、轨道 y[124,689]；滑块亮 ~243 / 轨道灰 ~113；
        滑块高约 103px。到底时滑块被轨道物理钳住，底缘读数在亮度阈值
        180~235 下恒定 689；离底一页的过渡帧底缘 685（cal_page_28，
        该页内容仍在变）。滑块每 px 约对应列表内容 15px（实测 4px
        滑块 = 62px 内容），1~2px 的「差不多贴底」就足够藏住一行
        姓名——故零容差：只有明确读到 689 才算到底，687/688 一律
        不放行；读数差一点就只配 stalled，不配 complete。
        """
        img = self.maa.screenshot()     # 复用核验刚读过的那一帧，不再截
        if img is None or img.shape[0] < 690 or img.shape[1] < 1270:
            return False
        x0, x1 = _SCROLLBAR_BAND_X
        y0, y1 = _SCROLLBAR_TRACK_Y
        band = np.asarray(img[y0:y1, x0:x1], dtype=np.int32).mean(axis=(1, 2))
        hot = band > _SCROLLBAR_THUMB_BRIGHT
        if (band < _SCROLLBAR_TRACK_DARK).sum() < 100:
            return False                # 看不到灰色滑轨：不在选择列表上
        best_len = best_end = cur = 0
        for i, h in enumerate(hot):
            cur = cur + 1 if h else 0
            if cur > best_len:
                best_len, best_end = cur, i
        if best_len < 20:               # 滑块实测高 ~103px，太短当噪声
            return False
        return y0 + best_end >= _SCROLLBAR_BOTTOM_Y - _SCROLLBAR_BOTTOM_TOL

    def _goto_page(self, pages, fps, current_idx, target_idx):
        """按指纹把列表翻回目标页；对不上就如实失败（返回 None）。"""
        if len(set(fps)) != len(fps):
            yield "[编队] 列表存在指纹相同的页，无法可靠定位，停"
            return None
        while current_idx != target_idx:
            step = 1 if target_idx > current_idx else -1
            self.maa.swipe(*(_SWIPE_NEXT if step > 0 else _SWIPE_PREV))
            time.sleep(1.2)
            ok = False
            for _retry in range(2):
                self.maa.screenshot(force=True)
                rows, _bad = parse_selection_rows(
                    self.maa.ocr_all(roi_4to4(*_LIST_ROI)) or [])
                fp = page_fingerprint(rows)
                if fp == fps[current_idx + step]:
                    ok = True
                    break
                self.maa.swipe(*(_SWIPE_NEXT if step > 0 else _SWIPE_PREV))
                time.sleep(1.2)
            if not ok:
                return None
            current_idx += step
        return current_idx

    def _relocate_row(self, target, scanned_row, match_fields):
        """回到目标页后重读该行：与扫描裁决同一套「证据充分」条件——
        零冲突且无缺证据的唯一行才返回新坐标（回页阶段不比扫描阶段宽）。"""
        self.maa.screenshot(force=True)
        rows, _bad = self._parse_selection_rows(
            self.maa.ocr_all(roi_4to4(*_LIST_ROI)) or [])
        hits = [r for r in rows
                if r.get("sword_catalog_id") == target["sword_catalog_id"]
                and not row_conflicts_target(r, target, match_fields)
                and not row_evidence_gaps(r, target, match_fields)]
        if len(hits) != 1:
            return None
        # 与扫描时的行特征一致才认（y 允许微漂）
        if scanned_row.get("level") is not None \
                and hits[0].get("level") != scanned_row["level"]:
            return None
        return hits[0]

    # ---- 结果组装 ----

    def _finish(self, result, team_no, slot_no, tgt, reason, **extra):
        out = {"schema_version": RESULT_SCHEMA_VERSION,
               "result": result, "team_no": team_no, "slot_no": slot_no,
               "target": tgt if isinstance(tgt, dict) else {"raw": tgt},
               "reason": reason}
        out.update(extra)
        if hasattr(self, "record_event"):
            payload = {"team_no": team_no, "slot_no": slot_no,
                       "result": result, "reason": reason,
                       "entry_shell": extra.get("entry_shell"),
                       "target": out["target"],
                       "before": extra.get("before"),
                       "after": extra.get("after"),
                       "candidates": extra.get("candidates"),
                       "other_slot_changes":
                           extra.get("other_slot_changes") or []}
            try:
                self.record_event("formation.member_ensured", **payload)
            except Exception:
                pass  # 记账失败不阻塞执行结果
            # 换后事实刷新：验收通过（CHANGED/ALREADY_CORRECT）时把刚回读的
            # 整队六槽落成 team_roster.observed。本丸档案的编队层
            # （honmaru_profile.build_roster）只认这类事件——不补这条，
            # 页面会一直显示旧成员，点"刷新档案"也救不回来。
            # verification_failed 不落：那时队伍状态存疑，不拿存疑读数冒充事实。
            team_after = extra.get("team_after")
            if result in (CHANGED, ALREADY_CORRECT) and team_after:
                try:
                    observe = getattr(self, "_observation_status", None)
                    status = observe(team_after) if observe else (
                        "partial" if any(
                            s.get("slot_status") == "unknown"
                            or s.get("unknown_fields")
                            for s in team_after) else "complete")
                    self.record_event("team_roster.observed",
                                      team_no=team_no, slots=team_after,
                                      observation_status=status,
                                      source="formation_editor")
                except Exception:
                    pass  # 记账失败不阻塞执行结果
        return out


def _other_slot_changes(team_before, team_after, slot_no):
    """整队前后对比（目标槽以外）：别的槽位身份变了要如实报出来。"""
    if not team_before or not team_after:
        return []
    changes = []
    for b, a in zip(team_before, team_after):
        if b.get("slot") == slot_no:
            continue
        if (b.get("sword_catalog_id"), b.get("level")) != \
                (a.get("sword_catalog_id"), a.get("level")):
            changes.append({"slot": b.get("slot"),
                            "before": b.get("name") or b.get("name_raw"),
                            "after": a.get("name") or a.get("name_raw")})
    return changes
