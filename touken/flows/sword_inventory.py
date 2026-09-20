# -*- coding: utf-8 -*-
"""
刀帐盘点：走进「刀剑男士一览」，逐页认出每一把刀记成快照

页面结构（2026-09-12 真机科研，运行帧在 Maamaru-Dev debug/research/）：
  1. 本丸左侧栏「刀剑男士」进一览；标题栏「所持刀剑 196/200」。
     列表每页 5 行、一行一把刀（同名刀可锻出多把，各占一行），
     总页数 = ceil(所持数 / 5)。
  2. 翻页只能横向拖动；300ms 快甩会惯性连翻两页（首扫缺 18 行的根因），
     2500ms 慢拖一次恰好一页。竖向滚动、点页码、跳页键都不吃。
  3. 每行自带完整档案：名字、等级、乱舞级、生存/疲劳双血条、九项属性、
     极化显现日期。名字走 sword_db 名册匹配拿标准名；等级/乱舞/双血条
     用行首竖排标签（刀剑/乱舞/生存/疲劳）做布局锚点归位——直接按 y
     排序猜语义会被 OCR ±几像素的抖动翻序。
  4. 「刀帐」图鉴 tab（卡牌收集）没有等级，只适合对收集度，另见
     sword_album_stream；它滚动一划会惯性飞 30 格，同款慢拖才安全。

  另：一览里偶尔整行认不出（暗底/特殊状态卡），记 fail 行如实上报，
  绝不静默丢行硬报绿。
"""

import math
import os
import re
import time
from pathlib import Path

from ..maa_adapter import roi_4to4, Point
from .. import sword_db
from ..roi_overrides import get_roi
from .team_roster import (load_flower_templates, match_badge_flowers,
                          conclude_kiwame, norm_sword_type)

# 置 MAAMARU_SWEEP_DEBUG=1 时，扫描把每页运行帧存到数据目录 debug/sweep/
# （只写用户数据目录，不进仓库），用于事后核对"OCR 当时看到的是什么"
_SWEEP_DEBUG = os.environ.get("MAAMARU_SWEEP_DEBUG") == "1"

# 全部 1280×720 语义坐标，2026-09-12 真机科研标定
_SWORD_MENU_POINT = (28, 172)      # 本丸左侧栏「刀剑男士」
_FILTER_BTN = (810, 112)           # 「筛选/排序」
_SORT_ROSTER_BTN = (1010, 377)     # 排序菜单「刀帐顺序」
_SORT_CONFIRM = (640, 625)         # 菜单「确定」
# 读取型 ROI 走注册表 + 覆盖（面板「代码 ROI」页可临时改，存用户数据目录
# DEBUG_DIR/template_lab/code-rois.json）：工人民工进程一跑一 import，改完
# 覆盖要等下次跑任务才生效；坏覆盖在 roi_overrides 里静默回落这里的默认。
_TITLE_ROI = get_roi("sword_inventory.title", (400, 15, 880, 50))    # 「刀剑男士一览」标题
_OWNED_ROI = get_roi("sword_inventory.owned", (640, 15, 1065, 50))   # 「所持刀剑 196/200」
# 列表区（含显现日期块 x≈1062，避开按钮 x≥1134）
_LIST_ROI = get_roi("sword_inventory.list", (130, 145, 1120, 660))
_ROWS_PER_PAGE = 5

# 逐格精读 ROI：2026-09-20 老大在模板工坊逐格手工框定（25 格注册进
# roi_registry，离线实测见交接）。整列 token 汤在小 ROI 上会胶连（数值带
# 第一行 8 个数字糊成一个 token），逐格读是唯一稳的路；整列读法留作兜底。
ROW_CELL_ROIS = {
    1: {"name": get_roi("sword_inventory.row1.name", (160, 202, 402, 233)),
        "levels": get_roi("sword_inventory.row1.levels", (400, 141, 523, 234)),
        "date": get_roi("sword_inventory.row1.date", (1023, 141, 1103, 232)),
        "stats": get_roi("sword_inventory.row1.stats", (521, 144, 1026, 231)),
        "badge": get_roi("sword_inventory.row1.badge", (170, 143, 231, 205))},
    2: {"name": get_roi("sword_inventory.row2.name", (162, 303, 398, 335)),
        "levels": get_roi("sword_inventory.row2.levels", (399, 242, 523, 333)),
        "date": get_roi("sword_inventory.row2.date", (1023, 242, 1105, 333)),
        "stats": get_roi("sword_inventory.row2.stats", (521, 244, 1025, 331)),
        "badge": get_roi("sword_inventory.row2.badge", (170, 243, 232, 306))},
    3: {"name": get_roi("sword_inventory.row3.name", (162, 403, 399, 434)),
        "levels": get_roi("sword_inventory.row3.levels", (399, 343, 523, 435)),
        "date": get_roi("sword_inventory.row3.date", (1023, 342, 1105, 434)),
        "stats": get_roi("sword_inventory.row3.stats", (521, 345, 1024, 431)),
        "badge": get_roi("sword_inventory.row3.badge", (170, 345, 233, 406))},
    4: {"name": get_roi("sword_inventory.row4.name", (162, 504, 400, 534)),
        "levels": get_roi("sword_inventory.row4.levels", (398, 443, 522, 536)),
        "date": get_roi("sword_inventory.row4.date", (1023, 443, 1104, 533)),
        "stats": get_roi("sword_inventory.row4.stats", (521, 446, 1024, 532)),
        "badge": get_roi("sword_inventory.row4.badge", (169, 444, 232, 507))},
    5: {"name": get_roi("sword_inventory.row5.name", (161, 604, 400, 637)),
        "levels": get_roi("sword_inventory.row5.levels", (398, 544, 522, 637)),
        "date": get_roi("sword_inventory.row5.date", (1025, 544, 1103, 636)),
        "stats": get_roi("sword_inventory.row5.stats", (521, 546, 1025, 633)),
        "badge": get_roi("sword_inventory.row5.badge", (171, 546, 232, 608))},
}

_NEXT_PAGE_SWIPE = ((1100, 400), (200, 400), 2500)  # 右→左慢拖 = 下一页
_PAGE_TURN_WAIT_S = 3.0            # 翻页樱花转场实测 2~3s
# 页码条 ROI（x0,y0,x1,y1）：列表底部「◀ 12 13 14 15 16 17 ▶」，当前页
# 带高亮块，翻页必动。兜底场景：相邻两页内容一模一样（五振 Lv.1 狮子王
# 连排两页，2026-09-21 真机实锤）时行指纹分不出翻没翻，会误判卡死。
# 实测相邻页该条稳定 700+ 像素差异，同页复读为 0。
_PAGE_STRIP = (500, 655, 900, 700)
_STRIP_DIFF_MIN_PX = 50            # 条内灰度差 >20 的像素数阈值
_LEVEL_RETRY_ROI = lambda base_y: (455, base_y - 70, 575, base_y + 5)

# 五行的名字基线 y（行距约 100.5px，行内容 y 波动 ±50 内归到该行）
_ROW_NAME_YS = (215, 316, 417, 517, 617)
_STAT_SLOT_XS = (551, 603, 662, 716, 770, 827, 883, 936)
_STAT_NAMES = ("生存", "打击", "防御", "机动", "冲力", "侦察", "隐蔽", "必杀")
_LEVEL_PAT = r"\d{1,2}\s*级"
_BAR_PAT = r"\d+/\d+"

# 一览行首刀种徽章 ROI（相对行基线 _ROW_NAME_YS）：真机科研帧
# （Maamaru-Dev debug/research/after_scan.png）三日月行徽章实测
# x 168-225 / y 138-194（base_y=215），放宽余量定为 x 150-260、
# y base_y-85 ~ base_y-12（避开下方名字行）
_INV_BADGE_X = (150, 260)
_INV_BADGE_DY = (-85, -12)

# 一览页花数证据白名单：与编队页 _PROVEN_FLOWER_COMBOS 各自校准——
# 模板同尺度（2026-09-15 after_scan 探针：五花太刀 0.837 达标），但证据
# 必须来自一览同源运行帧，不跨页挪用。
# 校准依据（2026-09-15 快照 #18，199 行真机帧 debug/sweep/ 全量复算）：
# 入列组合满足 p10 分 ≥0.72 且确认刀种内次高区分度 p25 ≥0.08 且有零冲突
# 正样本；与编队页直读真值按（刀+等级）交叉核对零矛盾（页 21 双 99 级
# 长谷部一普一极、页 26 加州清光极/普对，眼见帧逐行复核）。
# 结构不可靠、永久排除：短刀（1/2 花徽章只差一朵花瓣，margin p25≤0.08
# 且 2 花样本 15/19 跨刀种冲突）、太刀 6 花（与 5 花 margin 0.006）、
# 大太刀 4 花（p10 0.679）、枪 3/4 花（冲突或低分）、薙刀 3 花（唯一
# 样本即冲突）、剑 5 花（p10 0.705）。未入列组合的行保持 unknown，
# 原始观测照常落盘。
_INV_PROVEN_FLOWER_COMBOS = frozenset({
    ("打刀", 2), ("打刀", 3), ("打刀", 4),
    ("太刀", 3), ("太刀", 4), ("太刀", 5),
    ("胁差", 2), ("胁差", 3),
    ("大太刀", 3), ("薙刀", 4), ("剑", 4), ("枪", 5),
})

# 图鉴（刀帐 tab）扫描参数
_ALBUM_TAB_POINT = (20, 612)
_ALBUM_TITLE_ROI = (400, 15, 880, 50)
_COLLECT_ROI = (790, 15, 1070, 50)
_GRID_ROI = (100, 115, 1280, 665)
_TO_TOP_SWIPE = ((640, 200), (640, 620), 250)
_ALBUM_NEXT_SWIPE = ((640, 600), (640, 250), 2500)
_ALBUM_PREV_SWIPE = ((640, 250), (640, 600), 2500)
_ALBUM_SCROLL_WAIT_S = 1.6
_NAME_DX = (30, 175)
_NAME_DY = (45, 115)
_KIWIAME_DY = (40, 115)
_KIWIAME_DX = 45
_MAX_ALBUM_SCREENS = 60


def _as_xy(pt) -> tuple:
    return (int(pt.x), int(pt.y)) if hasattr(pt, "x") else (int(pt[0]), int(pt[1]))


def _int_of(text: str) -> int | None:
    m = re.search(r"\d{1,3}", text or "")
    return int(m.group()) if m else None


def _pair_of(text: str) -> tuple:
    cur, _, total = (text or "").partition("/")
    return _int_of(cur), _int_of(total)


def _row_key(row: dict) -> tuple:
    """行指纹：同名刀有多把（锻刀堆藤四郎是日常），一行一把，
    按 名字+等级+生存上限+显现日期 区分；等级没读出来时退回生存现值。"""
    return (row["sword_id"], row.get("level"), row.get("survival_max"),
            row.get("survival"), row.get("kiwame_date"))


def _strip_changed(prev, cur) -> bool:
    """页码条像素是否变了（当前页高亮块随翻页移动）。任一帧缺失返回 False。"""
    if prev is None or cur is None:
        return False
    import numpy as np
    diff = np.abs(prev.astype(np.int16) - cur.astype(np.int16))
    return bool((diff > 20).any(axis=2).sum() >= _STRIP_DIFF_MIN_PX)


def _page_turned(old_fp, new_fp, old_strip, new_strip, has_rows: bool) -> bool:
    """翻页确认：行指纹（有序多重集，保留重复行）变了，或页码条动了。"""
    if has_rows and new_fp != old_fp:
        return True
    return _strip_changed(old_strip, new_strip)


def _row_baselines(cells) -> list[int]:
    """动态行基线：以左列竖排「刀剑」标签为锚（每行恰好一个、全页 OCR
    最稳的 token），名字基线 = 锚 + 62px。锚缺失按行距插值补齐；一个锚都
    没有时退回硬编码基线（旧行为）。

    为什么不用固定 ±50 窗口：刀剑/等级行在名字上方 ~61px，乱舞在上方
    ~40px——等级行永远更靠近上一行基线（40px），整列等级会静默错一行
    （2026-09-18 真机帧实锤：三日月 95 级被记成下一行的 1 级）。
    """
    anchors = set()
    for text, pt in cells:
        x, y = _as_xy(pt)
        if str(text).strip() == "刀剑" and 400 <= x <= 460:
            anchors.add(y)
    anchors = sorted(anchors)
    deduped = []  # 同一标签偶尔被 OCR 出两次，30px 内算同一个
    for y in anchors:
        if not deduped or y - deduped[-1] > 30:
            deduped.append(y)
    if not deduped:
        return list(_ROW_NAME_YS)
    gaps = sorted(b - a for a, b in zip(deduped, deduped[1:]))
    spacing = gaps[(len(gaps) - 1) // 2] if gaps else 101
    full = []
    for i, anchor in enumerate(deduped):
        full.append(anchor)
        if i + 1 < len(deduped):
            missing = round((deduped[i + 1] - anchor) / spacing) - 1
            for k in range(1, max(missing, 0) + 1):
                full.append(anchor + spacing * k)
    return [anchor + 62 for anchor in full]


def parse_list_tokens(tokens) -> dict:
    """把一览页一屏的 OCR token 按行动态锚点解析成每行结构。

    tokens: [(text, (x, y)) ...]（中心点）。返回 {"rows": [...], "fail_rows": n}；
    页面上有内容却认不出名字的行计入 fail_rows（空行不算），绝不静默丢。
    """
    norm = []
    for text, pt in tokens:
        x, y = _as_xy(pt)
        if text.strip() and x <= 1115:  # 右界卡在按钮列（裝备 x≈1134）之前
            norm.append((x, y, text.strip()))
    baselines = _row_baselines(tokens)
    buckets = {y: [] for y in baselines}
    for x, y, text in norm:
        # 按行带归属：内容从锚(刀剑行,基线-62)一路到疲劳行(基线+13)，
        # 行带下沿取基线+22——名字(基线±几)永远归本行，邻行内容进不来
        for base_y in baselines:
            if base_y - 82 <= y < base_y + 22:
                buckets[base_y].append((x, y, text))
                break

    rows, fail_rows = [], 0
    for base_y in baselines:
        row = _parse_row(buckets[base_y])
        if row is None:
            continue
        row["_base_y"] = base_y  # 等级漏读时按行重读用；落库前由调用方去掉
        rows.append(row)
        fail_rows += row.pop("_failed", 0)
    return {"rows": rows, "fail_rows": fail_rows}


def _parse_row(cells) -> dict | None:
    """解析单行 token。cells 可为 (x, y, text) 或原始 (text, (x, y))；空行返回 None"""
    norm = []
    for cell in cells:
        if len(cell) == 3:
            norm.append((int(cell[0]), int(cell[1]), str(cell[2]).strip()))
        else:
            x, y = _as_xy(cell[1])
            norm.append((x, y, str(cell[0]).strip()))
    if len(norm) < 3:  # 真行至少有名字+等级+一串数字，零星 token 是空白噪点
        return None
    texts = sorted(norm)

    name_hit = None
    for x, _y, t in texts:
        if x > 450:
            break  # 名字列在最左，越过去就不是名字了
        found = sword_db.find_by_name(t, fuzzy=True)
        if found:
            sid, info = found
            name_hit = {"sword_id": sid,
                        "name_zh": info.get("name_zh") or info["name"]}
            break
    if not name_hit:
        return {"_failed": 1, "sword_id": None, "name_zh": None}

    # 行首竖排标签「刀剑/乱舞/生存/疲劳」是布局锚：左列的「n 级」「n/n」
    # 各归各的标签，避开 y 抖动翻序
    label_y = {}
    for x, y, t in texts:
        if 410 <= x <= 445 and t in ("刀剑", "乱舞", "生存", "疲劳"):
            label_y.setdefault(t, y)

    def _nearest_label(anchor_y, label):
        if anchor_y is None:
            return None
        pat = _LEVEL_PAT if label in ("刀剑", "乱舞") else _BAR_PAT
        cands = [(abs(yy - anchor_y), t) for xx, yy, t in texts
                 if 460 <= xx <= 560 and re.fullmatch(pat, t)]
        return min(cands)[1] if cands else None

    level = _int_of(_nearest_label(label_y.get("刀剑"), "刀剑"))
    tou_level = _int_of(_nearest_label(label_y.get("乱舞"), "乱舞"))
    # 值域双保险：锚定靠 y 排序，OCR 把两个级 token 的 y 读翻（间距仅
    # ~17px）时整列会错位。乱舞等级最多十几级，出现大数值必是刀剑等级
    if (level is not None and tou_level is not None
            and level <= 15 < tou_level):
        level, tou_level = tou_level, level

    survival = fatigue = survival_max = fatigue_max = None
    survival_text = _nearest_label(label_y.get("生存"), "生存")
    fatigue_text = _nearest_label(label_y.get("疲劳"), "疲劳")
    if survival_text:
        survival, survival_max = _pair_of(survival_text)
    if fatigue_text:
        fatigue, fatigue_max = _pair_of(fatigue_text)
    if survival is None:
        # 标签连读形态：OCR 偶尔把「疲劳」和数字连成一个 token
        for xx, _yy, t in texts:
            if 400 <= xx <= 560:
                m = re.fullmatch(r"生存(\d{1,3}/\d{1,3})", t)
                if m:
                    survival, survival_max = _pair_of(m.group(1))
                    break
    if fatigue is None:
        for xx, _yy, t in texts:
            if 400 <= xx <= 560:
                m = re.fullmatch(r"疲劳(\d{1,3}/\d{1,3})", t)
                if m:
                    fatigue, fatigue_max = _pair_of(m.group(1))
                    break

    stats = {}
    for x, _y, t in texts:
        if x < 515 or not re.fullmatch(r"\d{1,3}", t):
            continue
        slot = min(range(len(_STAT_SLOT_XS)),
                   key=lambda i: abs(_STAT_SLOT_XS[i] - x))
        if abs(_STAT_SLOT_XS[slot] - x) <= 26 and _STAT_NAMES[slot] not in stats:
            stats[_STAT_NAMES[slot]] = int(t)

    return {"sword_id": name_hit["sword_id"], "name_zh": name_hit["name_zh"],
            "level": level, "tou_level": tou_level,
            "survival": survival, "survival_max": survival_max,
            "fatigue": fatigue, "fatigue_max": fatigue_max,
            "stats": stats, "kiwame_date": _parse_kiwame(texts),
            "locked": None}


def _parse_kiwame(texts) -> str | None:
    """「显现」日期块：年份（4 位数）+ 月/日（n/n），x 都在 1040 附近。

    历史名字叫 kiwame_date 是误命名（2026-09-15 P0）：这是每振刀都有
    的获得/显现日期，不是极化日期，禁止拿去推普通/极化。"""
    year = day = None
    for x, y, t in sorted(texts, key=lambda c: (c[1], c[0])):  # 块从上往下读
        if x < 1020:
            continue
        if re.fullmatch(r"20\d{2}", t):
            year = t
        elif re.fullmatch(r"\d{1,2}/\d{1,2}", t) and year:
            day = t
    return f"{year}-{day.replace('/', '-')}" if year and day else None


def _joined(tokens) -> str:
    return re.sub(r"\s+", "", "".join(str(t).strip() for t, _p in tokens))


def match_name_text(text: str) -> dict | None:
    """拼接后的名字文本过名册；命中返回 {sword_id, name_zh}，否则 None。"""
    if not text:
        return None
    found = sword_db.find_by_name(text, fuzzy=True)
    if not found:
        return None
    sid, info = found
    return {"sword_id": sid, "name_zh": info.get("name_zh") or info["name"]}


def _split_label_tokens(tokens) -> list:
    """把等级格 token 在标签边界切开：粘连巨 token（"刀剑99级乱舞1级…"）
    摊成序列，原坐标保留（同格同坐标，顺序即语义，给顺序兜底用）。"""
    items = []
    for t, pt in tokens:
        x, y = _as_xy(pt)
        text = re.sub(r"\s+", "", str(t))
        if not text:
            continue
        pos = 0
        for m in re.finditer(r"刀[剑剣]|乱舞|生存|疲[劳労]", text):
            if m.start() > pos:
                items.append((None, text[pos:m.start()], x, y))
            items.append((m.group(), m.group(), x, y))
            pos = m.end()
        if pos < len(text):
            items.append((None, text[pos:], x, y))
    return items


def parse_levels_cell(tokens) -> dict:
    """等级格（刀剑/乱舞/生存/疲劳四行标签+值）token → 行字段。

    两条解析策略取并集（按字段 A 优先）：
    A. y 锚定配对——2026-09-20 实测小格 OCR 返回的 token 顺序会乱
       （「刀剑 乱舞 1级 99级」），顺序正则会把「乱舞1级」安给刀剑；
       y 锚定与旧整列路径同源。
    B. 标签序切分——整个格子糊成一个巨 token 时所有 token 同坐标，
       A 无从配对，退回「标签后跟着的值归该标签」。
    等级格本身就含四个标签，读不出就是 None，如实落库，不静默编数
    （逐格路径下 _retry_missing_levels 是多余的）。
    """
    items = _split_label_tokens(tokens)
    labels = [(kind, x, y) for kind, _t, x, y in items if kind]
    levels = [(x, y, int(m.group(1))) for kind, t, x, y in items
              if not kind and (m := re.fullmatch(r"(\d{1,2})级", t))]
    bars = [(x, y, int(m.group(1)), int(m.group(2))) for kind, t, x, y in items
            if not kind and (m := re.fullmatch(r"(\d{1,3})/(\d{1,3})", t))]

    plan_a = {"level": None, "tou_level": None,
              "survival": None, "survival_max": None,
              "fatigue": None, "fatigue_max": None}
    # y 没有区分度（巨 token 全同坐标）时 A 无从配对，交给 B 的顺序兜底
    ys = [y for _k, _t, _x, y in items]
    positional_ok = items and (max(ys) - min(ys) >= 5)
    if positional_ok:
        for kind, lx, ly in labels:
            if kind in ("刀剑", "刀剣", "乱舞"):
                if levels:
                    _d, _vx, _vy, value = min(
                        (abs(vy - ly), vx, vy, value) for vx, vy, value in levels)
                    if kind in ("刀剑", "刀剣"):
                        plan_a["level"] = value
                    else:
                        plan_a["tou_level"] = value
            else:
                if bars:
                    _d, _bx, _by, cur, total = min(
                        (abs(by - ly), bx, by, cur, total) for bx, by, cur, total in bars)
                    if kind == "生存":
                        plan_a["survival"], plan_a["survival_max"] = cur, total
                    else:
                        plan_a["fatigue"], plan_a["fatigue_max"] = cur, total

    plan_b = {"level": None, "tou_level": None,
              "survival": None, "survival_max": None,
              "fatigue": None, "fatigue_max": None}
    current = None
    for kind, t, _x, _y in items:
        if kind:
            current = kind
            continue
        mv = re.fullmatch(r"(\d{1,2})级", t)
        mb = re.fullmatch(r"(\d{1,3})/(\d{1,3})", t)
        if mv and current in ("刀剑", "刀剣", "乱舞"):
            field = "tou_level" if current == "乱舞" else "level"
            if plan_b[field] is None:
                plan_b[field] = int(mv.group(1))
        elif mb and current in ("生存", "疲劳", "疲労"):
            if current == "生存" and plan_b["survival"] is None:
                plan_b["survival"], plan_b["survival_max"] = (int(mb.group(1)),
                                                              int(mb.group(2)))
            elif current in ("疲劳", "疲労") and plan_b["fatigue"] is None:
                plan_b["fatigue"], plan_b["fatigue_max"] = (int(mb.group(1)),
                                                            int(mb.group(2)))

    out = {k: (plan_a[k] if plan_a[k] is not None else plan_b[k])
           for k in plan_a}
    level, tou_level = out["level"], out["tou_level"]
    # 值域双保险：乱舞等级最多十几级，出现大数值必是刀剑等级被读串
    if level is not None and tou_level is not None and level <= 15 < tou_level:
        out["level"], out["tou_level"] = tou_level, level
    return out


def split_stats_roi(roi, inset: int = 2) -> list:
    """数值带（xyxy）按宽 9 等分成 9 个子格，每格向内缩 inset 防串行。

    小 ROI 的 OCR 会把紧贴的数字胶连成一个 token（真机实测第一行
    8 个数字糊成「487167385141」），所以必须逐格分别 OCR。
    第 9 格是「范围」（狭/广/横），不进 stats。
    """
    x1, y1, x2, y2 = roi
    step = (x2 - x1) / 9
    return [(round(x1 + i * step) + inset, y1,
             round(x1 + (i + 1) * step) - inset, y2) for i in range(9)]


def stats_from_cells(cell_texts: list) -> dict:
    """9 个子格的 OCR 文本 → stats dict；前 8 格取数字入 _STAT_NAMES，第 9 格忽略。"""
    stats = {}
    for name, text in zip(_STAT_NAMES, cell_texts[:8]):
        m = re.search(r"\d{1,3}", text or "")
        if m:
            stats[name] = int(m.group())
    return stats


def parse_date_cell(tokens) -> str | None:
    """显现日期格：「显现」「2026」「2/12」三个 token → "2026-2-12"。
    输出形状与 _parse_kiwame 一致；名字沿旧是误命名，禁止拿去推极化。"""
    year = day = None
    for t, _p in tokens:
        t = str(t).strip()
        if re.fullmatch(r"20\d{2}", t):
            year = t
        else:
            m = re.fullmatch(r"(\d{1,2})\s*/\s*(\d{1,2})", t)
            if m and year:
                day = f"{m.group(1)}-{m.group(2)}"
    return f"{year}-{day}" if year and day else None


def read_page_cells(ocr_fn) -> dict:
    """逐格精读一页：5 行 × (名字/等级/日期 OCR 格 + 数值带 9 等分)，
    徽章 ROI 挂进 row["_badge_rect"] 由调用方同帧读。

    ocr_fn(roi_xyxy) -> [(text, (x, y)) ...]。返回形状与 parse_list_tokens
    相同：{"rows", "fail_rows"}。名字格有字却过不了名册 → fail 行
    （如实上报语义不变）；名字格空白 → 空行（末页尾巴），不算 fail。
    """
    rows, fail_rows = [], 0
    for rois in ROW_CELL_ROIS.values():
        name_text = _joined(ocr_fn(rois["name"]))
        name_hit = match_name_text(name_text)
        if not name_hit:
            if name_text:
                fail_rows += 1
                rows.append({"sword_id": None, "name_zh": None})
            continue
        stats_texts = [_joined(ocr_fn(cell))
                       for cell in split_stats_roi(rois["stats"])]
        row = {**name_hit, **parse_levels_cell(ocr_fn(rois["levels"])),
               "stats": stats_from_cells(stats_texts),
               "kiwame_date": parse_date_cell(ocr_fn(rois["date"])),
               "locked": None,
               "_badge_rect": rois["badge"]}
        rows.append(row)
    return {"rows": rows, "fail_rows": fail_rows}


def parse_owned(text: str) -> tuple:
    """「196/200」→ (196, 200)；读不出返回 (None, None)"""
    m = re.search(r"(\d+)\s*/\s*(\d+)", text or "")
    return (int(m.group(1)), int(m.group(2))) if m else (None, None)


def read_row_form_fact(img, badge_rect, sword_id, templates, proven_combos):
    """一览行徽章形态事实：同帧刀种+花数匹配 → 复用 team_roster 结论规则。

    badge_rect: 行首徽章格 xyxy（逐格路径来自 ROW_CELL_ROIS，整列兜底
    路径由调用方按行基线换算 _INV_BADGE_X/_INV_BADGE_DY）；None 或截图
    失明 → 不出证据。
    确认刀种与名册基线取自 sword_db（一览行名已过名册匹配，身份可靠）；
    白樱花通道不在此页使用（编队页专属 ROI，未做一览同源校准）。
    返回 form_fact dict：status（kiwame/normal/unknown）+ evidence（人读
    字符串）+ badge（原始观测全保留：花数/分数/全局顶分）+ 名册基线，
    随快照落盘；结论只认白名单内达标的正面证据，绝不默认普通/极化。
    """
    info = (sword_db.all_swords() or {}).get(sword_id) or {}
    confirmed_type = norm_sword_type(info.get("type"))
    rarity_base = info.get("rarity")
    region = None
    if img is not None and badge_rect:
        x0, y0, x1, y1 = (int(v) for v in badge_rect)
        if 0 <= y0 < y1 <= img.shape[0] and 0 <= x0 < x1 <= img.shape[1]:
            region = img[y0:y1, x0:x1]
    badge = match_badge_flowers(region, templates, confirmed_type,
                                proven_combos)
    status, evidence = conclude_kiwame(sword_id, rarity_base, badge)
    return {"status": status,
            "evidence": [str(e["raw_value"]) for e in evidence],
            "badge": badge,
            "rarity_base": rarity_base,
            "sword_type": confirmed_type}


def parse_album_tokens(tokens) -> list[dict]:
    """刀帐图鉴一屏：序号+竖排名（OCR 直接读成横排全文）+「极」字标。"""
    seqs, names, kiwames = [], [], []
    for text, pt in tokens:
        x, y = _as_xy(pt)
        t = (text or "").strip()
        if not t:
            continue
        m = re.fullmatch(r"序号[.．:\s]*(\d{1,3})", t)
        if m:
            seqs.append((int(m.group(1)), x, y))
        elif t == "极":
            kiwames.append((x, y))
        elif len(t) >= 2:
            names.append((x, y, t))

    out = []
    for no, sx, sy in sorted(seqs):
        hit = None
        for x, y, t in names:
            if not (_NAME_DX[0] <= x - sx <= _NAME_DX[1]):
                continue
            if not (_NAME_DY[0] <= y - sy <= _NAME_DY[1]):
                continue
            found = sword_db.find_by_name(t, fuzzy=True)
            if found:
                _sid, info = found
                hit = (x, y, info.get("name_zh") or info["name"])
                break
        if not hit:
            continue  # 空栏（未收集）或没认出的格子
        nx, ny, name_zh = hit
        kiwame = any(abs(kx - nx) <= _KIWIAME_DX and
                     _KIWIAME_DY[0] <= ky - ny <= _KIWIAME_DY[1]
                     for kx, ky in kiwames)
        out.append({"no": no, "name_zh": name_zh, "kiwame": kiwame})
    return out


def parse_collected(text: str) -> tuple:
    """「收集 204/208」→ (204, 208)；读不出返回 (None, None)"""
    m = re.search(r"(\d+)\s*/\s*(\d+)", text or "")
    return (int(m.group(1)), int(m.group(2))) if m else (None, None)


class SwordInventoryMixin:
    """刀帐盘点：只读扫描，全程不碰任何确认/消耗按钮"""

    def sword_inventory_stream(self):
        """主入口：一览逐页扫描，每行一把刀（等级/乱舞/血条/属性/显现日期）"""
        maa = self.maa
        # ── 1. 到本丸 → 进一览 ──
        if self.current_location != "本丸":
            yield "[刀帐] 先回本丸..."
            if not self.navigate_to("本丸"):
                yield "[刀帐] ✗ 到不了本丸，停"
                return
        yield "[刀帐] 打开刀剑男士一览..."
        opened = False
        for attempt in range(3):
            maa.click(Point(*_SWORD_MENU_POINT))
            if self._wait_list_page():
                opened = True
                break
            time.sleep(2.0)  # 回城转场/近侍台词可能吃掉第一次点击，重试
        if not opened:
            yield "[刀帐] ✗ 三次都没打开刀剑男士一览，停"
            return

        # ── 2. 排序设为「刀帐顺序」（稳定编号序；重复设置无害） ──
        yield "[刀帐] 排序设为刀帐顺序..."
        maa.click(Point(*_FILTER_BTN))
        time.sleep(1.2)
        maa.screenshot(force=True)
        if maa.ocr("排序", roi_4to4(910, 60, 1120, 115)):
            maa.click(Point(*_SORT_ROSTER_BTN))
            time.sleep(0.6)
            maa.click(Point(*_SORT_CONFIRM))
            time.sleep(1.5)
            if not self._wait_list_page():
                yield "[刀帐] ✗ 排序后没回到一览页，停"
                return

        owned, capacity = self._read_owned()
        if owned:
            pages = math.ceil(owned / _ROWS_PER_PAGE)
            yield f"[刀帐] 所持 {owned}/{capacity or '？'}，共 {pages} 页，开始逐页认刀"
        else:
            pages = None
            yield "[刀帐] 所持数没读出来，改用到底判定继续扫"

        # ── 3. 逐页扫描（页数驱动；页数未知时用连续空页兜底） ──
        debug_dir = None
        if _SWEEP_DEBUG:
            from ..runtime_paths import DEBUG_DIR
            debug_dir = DEBUG_DIR / "sweep"
            debug_dir.mkdir(parents=True, exist_ok=True)
        all_rows: list[dict] = []
        fail_rows_total = 0
        page_no = 0
        blank_pages = 0
        while True:
            page_no += 1
            if pages and page_no > pages:
                yield f"[刀帐] 已翻满 {pages} 页，扫描完成"
                break
            if not pages and blank_pages >= 2:
                yield "[刀帐] 连续两页读不到内容，应该到头了"
                break
            if page_no > 80:  # 页数未知时的硬上限（200 把 ÷ 5 = 40 页）
                yield "[刀帐] ✗ 翻页翻到上限还没收尾，停"
                return

            maa.screenshot(force=True)
            img = maa.screenshot()
            if debug_dir is not None:
                from PIL import Image
                Image.fromarray(img[:, :, ::-1]).save(debug_dir / f"page_{page_no:02d}.png")
            parsed, fell_back = self._scan_list_page(img)
            if fell_back:
                yield (f"[刀帐] 第 {page_no} 页逐格精读一行名字都没认出，"
                       f"改用整列读法")
            if not parsed["rows"] and page_no > 1:
                # 整页读空：多半撞上翻页转场尾巴，等两秒重读一次再算数
                time.sleep(2.0)
                maa.screenshot(force=True)
                img = maa.screenshot()
                parsed, fell_back = self._scan_list_page(img)
                if fell_back:
                    yield (f"[刀帐] 第 {page_no} 页逐格精读一行名字都没认出，"
                           f"改用整列读法")
            fail_rows_total += parsed["fail_rows"]
            self._retry_missing_levels(parsed["rows"])
            # 同帧读行首徽章（刀种+花数）→ 形态事实随快照落盘
            self._read_row_form_facts(img, parsed["rows"])

            new_names = []
            for row in parsed["rows"]:
                if not row.get("sword_id"):
                    continue
                row["page_no"] = page_no
                all_rows.append(row)
                new_names.append(f"{row['name_zh']}{row['level'] or '?'}级")

            if parsed["fail_rows"]:
                yield (f"[刀帐] 第 {page_no} 页有 {parsed['fail_rows']} 行认不出，"
                       f"先记下继续看")
            elif new_names:
                shown = "、".join(new_names)
                if len(shown) > 40:
                    shown = shown[:38] + "…"
                yield f"[刀帐] 第 {page_no} 页：{shown}"
            if not parsed["rows"]:
                blank_pages += 1
            else:
                blank_pages = 0

            if fail_rows_total > 4:
                yield "[刀帐] ✗ 认不出的行太多，快照不完整，不落库（免得账本掺假）"
                return

            if pages and page_no >= pages:
                yield f"[刀帐] 末页扫完，扫描完成"
                break

            # ── 翻页并确认：内核慢拖实测约有一半概率静默不翻（往回 20 翻
            # 只翻了 10 页的实测），翻完比对整页行指纹，没翻动就重翻。
            # 指纹用有序多重集（frozenset 会把整页重复行压成一条，两页
            # 五振相同狮子王会误判没翻）；仍分不清时看页码条像素兜底 ──
            old_fp = sorted(_row_key(r) for r in parsed["rows"])
            sx0, sy0, sx1, sy1 = _PAGE_STRIP
            old_strip = img[sy0:sy1, sx0:sx1]
            turned = False
            for _ in range(3):
                maa.touch_swipe(*_NEXT_PAGE_SWIPE[0], *_NEXT_PAGE_SWIPE[1],
                                _NEXT_PAGE_SWIPE[2])
                time.sleep(_PAGE_TURN_WAIT_S)
                maa.screenshot(force=True)
                img = maa.screenshot()
                tokens = [(t, (p.x, p.y)) for t, p in
                          maa.ocr_all(roi_4to4(*_LIST_ROI), img) or []]
                check = parse_list_tokens(tokens)
                new_fp = sorted(_row_key(r) for r in check["rows"])
                if _page_turned(old_fp, new_fp, old_strip,
                                img[sy0:sy1, sx0:sx1], bool(check["rows"])):
                    turned = True
                    break
                time.sleep(1.5)
            if not turned:
                yield "[刀帐] ✗ 连续三次翻页页面都没动，停在这里"
                return

        # ── 4. 对账 + 落库 ──
        # 不去重：同名刀有多把（锻刀堆出来的），同属性同日期的行也是真行；
        # 翻页扫描每页只处理一次，行即身份
        for row in all_rows:
            row.pop("_base_y", None)
            row.pop("_badge_rect", None)
        missing = (owned - len(all_rows)) if owned else None
        if owned and missing > 0:
            yield (f"[刀帐] ⚠️ 对账差 {missing} 把（所持 {owned}，认出 {len(all_rows)}），"
                   f"快照照记，但账本会标注缺口")
        elif owned:
            yield f"[刀帐] ✓ 对账平了：{len(all_rows)}/{owned} 把全认出"
        form_ok = sum(1 for r in all_rows
                      if (r.get("form_fact") or {}).get("status")
                      in ("kiwame", "normal"))
        yield (f"[刀帐] 形态确认 {form_ok}/{len(all_rows)} 振"
               f"（未确认的存原始观测，证据随档案落盘）")
        snapshot_id = self.telemetry_save_swords(
            all_rows, owned=owned, capacity=capacity, missing=missing,
            source="owned_inventory")
        yield (f"[刀帐] 快照 #{snapshot_id} 已入账：{len(all_rows)} 把刀"
               + (f"（缺 {missing}）" if missing else ""))

    def sword_album_stream(self):
        """附入口：刀帐图鉴扫描（收集度+极化标记，没有等级）"""
        maa = self.maa
        if self.current_location != "本丸":
            yield "[刀帐] 先回本丸..."
            if not self.navigate_to("本丸"):
                return
        opened = False
        for attempt in range(3):
            maa.click(Point(*_SWORD_MENU_POINT))
            if self._wait_album_ready():
                opened = True
                break
            time.sleep(2.0)
        if not opened:
            yield "[刀帐] ✗ 三次都没打开刀帐页面，停"
            return
        collected, total = self._read_collected()
        if collected:
            yield f"[刀帐] 图鉴收集 {collected}/{total or '？'}，开始逐屏认卡"

        for _ in range(6):
            maa.touch_swipe(*_TO_TOP_SWIPE[0], *_TO_TOP_SWIPE[1],
                            _TO_TOP_SWIPE[2])
            time.sleep(0.8)

        seen: dict[int, dict] = {}
        yield from self._album_sweep(maa, seen, downward=True)
        missing_now = (collected - len(seen)) if collected else None
        if missing_now:
            yield (f"[刀帐] 第一遍认出 {len(seen)} 格、缺 {missing_now}，"
                   f"反向再扫一遍补漏...")
            yield from self._album_sweep(maa, seen, downward=False)

        rows = []
        for no in sorted(seen):
            cell = seen[no]
            rows.append({"sword_id": f"album_{no:03d}",
                         "name_zh": cell["name_zh"],
                         "stats": {"极化": True} if cell["kiwame"] else {},
                         "page_no": None})
        missing = (collected - len(rows)) if collected else None
        if collected and missing > 0:
            yield (f"[刀帐] 认出 {len(rows)} 格、图鉴记录 {collected}，差额 {missing}："
                   f"含未收集空格、未实装跳号，也可能有漏读——快照照记，账本标注差额")
        elif collected:
            yield f"[刀帐] ✓ 对账平了：{len(rows)}/{collected} 格全认出"
        snapshot_id = self.telemetry_save_swords(
            rows, owned=collected, capacity=total, missing=missing,
            source="album")
        yield (f"[刀帐] 快照 #{snapshot_id} 已入账：{len(rows)} 格"
               + (f"（缺 {missing}）" if missing else ""))

    # ---- 内部零件 ----

    def _read_row_form_facts(self, img, rows):
        """逐行读徽章形态事实（与 OCR 同一帧），挂 row['form_fact'] 随落盘。

        只处理身份已确认的行（名字过了名册匹配）；认不出的行没有确认
        刀种，不产生花数证据（规则本体在 team_roster，结论冲突/证据
        不足一律 unknown，原始观测照样落盘供审计与校准）。
        逐格路径的行自带 _badge_rect；整列兜底路径的行按行基线换算老位置。
        """
        templates = load_flower_templates(
            getattr(self.maa, "resource_dir", "resource/base"))
        for row in rows:
            if not row.get("sword_id"):
                continue
            rect = row.get("_badge_rect")
            if rect is None and row.get("_base_y"):
                base_y = row["_base_y"]
                rect = (_INV_BADGE_X[0], base_y + _INV_BADGE_DY[0],
                        _INV_BADGE_X[1], base_y + _INV_BADGE_DY[1])
            row["form_fact"] = read_row_form_fact(
                img, rect, row["sword_id"], templates, _INV_PROVEN_FLOWER_COMBOS)

    def _scan_list_page(self, img):
        """逐格精读一页；整页一行名字都认不出时退回整列 token 汤（老路径）。

        退回条件刻意收紧：逐格有名字命中就不混用；逐格全空且整列也全空
        （真空页/转场帧）不算兜底，安静按空页处理。返回 (parsed, fell_back)。
        """
        maa = self.maa

        def cell_ocr(roi):
            return [(t, (p.x, p.y)) for t, p in
                    maa.ocr_all(roi_4to4(*roi), img) or []]

        parsed = read_page_cells(cell_ocr)
        if any(r.get("sword_id") for r in parsed["rows"]):
            return parsed, False
        tokens = [(t, (p.x, p.y)) for t, p in
                  maa.ocr_all(roi_4to4(*_LIST_ROI), img) or []]
        legacy = parse_list_tokens(tokens)
        if parsed["fail_rows"] or any(r.get("sword_id") for r in legacy["rows"]):
            # 标题门禁：部队选择页（2026-09-20 离线验收 221316 实锤）同样
            # 能读出刀名 token，无标题时整列路径读出的全是假行，宁可空页。
            # maa.ocr 用最近缓存帧（调用点都是刚 force 截图后，与 img 同源）。
            if maa.ocr("刀剑男士一览", roi_4to4(*_TITLE_ROI)):
                return legacy, True
        return parsed, False

    def _retry_missing_levels(self, rows):
        """整列 OCR 偶发漏读等级：按行窄条单独重读"""
        for row in rows:
            if row.get("level") is not None or not row.get("sword_id"):
                continue
            base_y = row.get("_base_y")
            if not base_y:
                continue
            x0, y0, x1, y1 = _LEVEL_RETRY_ROI(base_y)
            tokens = self.maa.ocr_all(roi_4to4(x0, y0, x1, y1)) or []
            levels = sorted(
                _int_of(t) for t, _pt in tokens
                if re.fullmatch(r"\d{1,2}\s*级", t.strip()))
            levels = [v for v in levels if v]
            if levels and 1 <= levels[0] <= 99:
                row["level"] = levels[0]
            if len(levels) > 1 and 1 <= levels[1] <= 15:
                row["tou_level"] = levels[1]

    def _wait_list_page(self, timeout_s: float = 15.0) -> bool:
        """等「刀剑男士一览」标题出现（转场樱花可能要几秒）"""
        deadline = time.time() + timeout_s
        while time.time() < deadline:
            time.sleep(0.8)
            self.maa.screenshot(force=True)
            if self.maa.ocr("刀剑男士一览", roi_4to4(*_TITLE_ROI)):
                return True
        return False

    def _read_owned(self) -> tuple:
        self.maa.screenshot(force=True)
        tokens = self.maa.ocr_all(roi_4to4(*_OWNED_ROI)) or []
        for text, _pt in tokens:
            owned, capacity = parse_owned(text)
            if owned:
                return owned, capacity
        return None, None

    def _wait_album_ready(self, timeout_s: float = 12.0) -> bool:
        """等刀帐 tab 可点：一览标题或刀帐标题出现都算（页面记忆上次位置）"""
        deadline = time.time() + timeout_s
        on_album = False
        while time.time() < deadline:
            time.sleep(0.8)
            self.maa.screenshot(force=True)
            if (self.maa.ocr("刀剑男士一览", roi_4to4(*_TITLE_ROI))
                    or self.maa.ocr("刀帐", roi_4to4(*_TITLE_ROI))):
                on_album = True
                break
        if not on_album:
            return False
        self.maa.screenshot(force=True)
        if self.maa.ocr("刀帐", roi_4to4(*_TITLE_ROI)):
            return True
        self.maa.click(Point(*_ALBUM_TAB_POINT))
        time.sleep(1.5)
        self.maa.screenshot(force=True)
        return bool(self.maa.ocr("刀帐", roi_4to4(*_TITLE_ROI)))

    def _read_collected(self) -> tuple:
        self.maa.screenshot(force=True)
        tokens = self.maa.ocr_all(roi_4to4(*_COLLECT_ROI)) or []
        for text, _pt in tokens:
            collected, total = parse_collected(text)
            if collected:
                return collected, total
        return None, None

    def _album_sweep(self, maa, seen: dict, downward: bool):
        """图鉴单方向扫一趟。结束判定看「页面位置不再变化」——
        补漏趟从已扫区域出发，一路全是旧卡是正常现象，按有无新卡判定
        会在出发第二屏就误判到边。"""
        swipe = _ALBUM_NEXT_SWIPE if downward else _ALBUM_PREV_SWIPE
        edge = "到底" if downward else "到顶"
        last_seqs = None
        still = 0
        screen_no = 0
        while screen_no < _MAX_ALBUM_SCREENS:
            screen_no += 1
            maa.screenshot(force=True)
            img = maa.screenshot()
            tokens = [(t, (p.x, p.y)) for t, p in
                      maa.ocr_all(roi_4to4(*_GRID_ROI), img) or []]
            cells = parse_album_tokens(tokens)
            fresh = [c for c in cells if c["no"] not in seen]
            for cell in fresh:
                seen[cell["no"]] = cell
            if fresh:
                names = "、".join(f"{c['name_zh']}{'极' if c['kiwame'] else ''}"
                                  for c in fresh[:4])
                yield f"[刀帐] 第 {screen_no} 屏：{names}{'…' if len(fresh) > 4 else ''}"

            seqs_now = frozenset(c["no"] for c in cells)
            # 到边判定看「页面位置不再变化」。滚到底后内核回弹会让序号集合
            # 抖动（回弹露出不同的半行），严格相等永远等不到，用重合度兜底
            overlap = (len(seqs_now & (last_seqs or frozenset()))
                       / max(1, len(seqs_now | (last_seqs or frozenset()))))
            if seqs_now and last_seqs and overlap >= 0.8:
                still += 1
                if still >= 3:
                    yield f"[刀帐] 页面连续 3 屏位置没变，{edge}了"
                    return
            else:
                still = 0
            last_seqs = seqs_now

            maa.touch_swipe(*swipe[0], *swipe[1], swipe[2])
            time.sleep(_ALBUM_SCROLL_WAIT_S)
        yield "[刀帐] ✗ 单趟滚了太多屏还没到边，停"
        return

    def telemetry_save_swords(self, rows, *, owned, capacity, missing,
                              source) -> int:
        from ..telemetry import get_telemetry_store
        snapshot_id = get_telemetry_store().save_sword_snapshot(
            rows, owned=owned, capacity=capacity, missing=missing,
            source=source)
        try:
            if hasattr(self, "record_event"):
                self.record_event("sword_inventory.completed", snapshot_id=snapshot_id,
                                  count=len(rows), owned=owned, missing=missing,
                                  source=source)
        except Exception:
            pass
        return snapshot_id
