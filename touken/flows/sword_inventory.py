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

# 置 MAAMARU_SWEEP_DEBUG=1 时，扫描把每页运行帧存到数据目录 debug/sweep/
# （只写用户数据目录，不进仓库），用于事后核对"OCR 当时看到的是什么"
_SWEEP_DEBUG = os.environ.get("MAAMARU_SWEEP_DEBUG") == "1"

# 全部 1280×720 语义坐标，2026-09-12 真机科研标定
_SWORD_MENU_POINT = (28, 172)      # 本丸左侧栏「刀剑男士」
_FILTER_BTN = (810, 112)           # 「筛选/排序」
_SORT_ROSTER_BTN = (1010, 377)     # 排序菜单「刀帐顺序」
_SORT_CONFIRM = (640, 625)         # 菜单「确定」
_TITLE_ROI = (400, 15, 880, 50)    # 「刀剑男士一览」标题
_OWNED_ROI = (640, 15, 1065, 50)   # 「所持刀剑 196/200」
_LIST_ROI = (130, 145, 1120, 660)  # 列表区（含显现日期块 x≈1062，避开按钮 x≥1134）
_ROWS_PER_PAGE = 5

_NEXT_PAGE_SWIPE = ((1100, 400), (200, 400), 2500)  # 右→左慢拖 = 下一页
_PAGE_TURN_WAIT_S = 3.0            # 翻页樱花转场实测 2~3s
_LEVEL_RETRY_ROI = lambda base_y: (455, base_y - 70, 575, base_y + 5)

# 五行的名字基线 y（行距约 100.5px，行内容 y 波动 ±50 内归到该行）
_ROW_NAME_YS = (215, 316, 417, 517, 617)
_STAT_SLOT_XS = (551, 603, 662, 716, 770, 827, 883, 936)
_STAT_NAMES = ("生存", "打击", "防御", "机动", "冲力", "侦察", "隐蔽", "必杀")
_LEVEL_PAT = r"\d{1,2}\s*级"
_BAR_PAT = r"\d+/\d+"

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


def parse_list_tokens(tokens) -> dict:
    """把一览页一屏的 OCR token 按五行基线解析成每行结构。

    tokens: [(text, (x, y)) ...]。返回 {"rows": [...], "fail_rows": n}；
    页面上有内容却认不出名字的行计入 fail_rows（空行不算），绝不静默丢。
    """
    buckets = {y: [] for y in _ROW_NAME_YS}
    for text, pt in tokens:
        x, y = _as_xy(pt)
        if not text.strip() or x > 1115:  # 右界卡在按钮列（裝备 x≈1134）之前
            continue
        nearest = min(_ROW_NAME_YS, key=lambda ry: abs(ry - y))
        if abs(nearest - y) <= 50:
            buckets[nearest].append((x, y, text.strip()))

    rows, fail_rows = [], 0
    for base_y in _ROW_NAME_YS:
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
    """极化「显现」块：年份（4 位数）+ 月/日（n/n），x 都在 1040 附近"""
    year = day = None
    for x, y, t in sorted(texts, key=lambda c: (c[1], c[0])):  # 块从上往下读
        if x < 1020:
            continue
        if re.fullmatch(r"20\d{2}", t):
            year = t
        elif re.fullmatch(r"\d{1,2}/\d{1,2}", t) and year:
            day = t
    return f"{year}-{day.replace('/', '-')}" if year and day else None


def parse_owned(text: str) -> tuple:
    """「196/200」→ (196, 200)；读不出返回 (None, None)"""
    m = re.search(r"(\d+)\s*/\s*(\d+)", text or "")
    return (int(m.group(1)), int(m.group(2))) if m else (None, None)


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
        """主入口：一览逐页扫描，每行一把刀（等级/乱舞/血条/属性/极化日期）"""
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
            tokens = [(t, (p.x, p.y)) for t, p in
                      maa.ocr_all(roi_4to4(*_LIST_ROI), img) or []]
            parsed = parse_list_tokens(tokens)
            if not parsed["rows"] and page_no > 1:
                # 整页读空：多半撞上翻页转场尾巴，等两秒重读一次再算数
                time.sleep(2.0)
                maa.screenshot(force=True)
                img = maa.screenshot()
                tokens = [(t, (p.x, p.y)) for t, p in
                          maa.ocr_all(roi_4to4(*_LIST_ROI), img) or []]
                parsed = parse_list_tokens(tokens)
            fail_rows_total += parsed["fail_rows"]
            self._retry_missing_levels(parsed["rows"])

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
            # 只翻了 10 页的实测），翻完比对整页行指纹，没翻动就重翻 ──
            old_fp = frozenset(_row_key(r) for r in parsed["rows"])
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
                new_fp = frozenset(_row_key(r) for r in check["rows"])
                if check["rows"] and new_fp != old_fp:
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
        missing = (owned - len(all_rows)) if owned else None
        if owned and missing > 0:
            yield (f"[刀帐] ⚠️ 对账差 {missing} 把（所持 {owned}，认出 {len(all_rows)}），"
                   f"快照照记，但账本会标注缺口")
        elif owned:
            yield f"[刀帐] ✓ 对账平了：{len(all_rows)}/{owned} 把全认出"
        snapshot_id = self.telemetry_save_swords(
            all_rows, owned=owned, capacity=capacity, missing=missing)
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
            rows, owned=collected, capacity=total, missing=missing)
        yield (f"[刀帐] 快照 #{snapshot_id} 已入账：{len(rows)} 格"
               + (f"（缺 {missing}）" if missing else ""))

    # ---- 内部零件 ----

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

    def telemetry_save_swords(self, rows, *, owned, capacity, missing) -> int:
        from ..telemetry import get_telemetry_store
        snapshot_id = get_telemetry_store().save_sword_snapshot(
            rows, owned=owned, capacity=capacity, missing=missing)
        try:
            if hasattr(self, "record_event"):
                self.record_event("sword_inventory.completed", snapshot_id=snapshot_id,
                                  count=len(rows), owned=owned, missing=missing)
        except Exception:
            pass
        return snapshot_id
