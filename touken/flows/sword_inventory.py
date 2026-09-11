# -*- coding: utf-8 -*-
"""
刀帐盘点：走进游戏「刀帐」图鉴，逐屏认出每一格并记成快照

页面结构（2026-09-12 真机科研，运行帧在 Maamaru-Dev debug/research/）：
  1. 本丸左侧栏「刀剑男士」→ 页面内左下「刀帐」tab（卡牌图鉴）。
     标题栏「收集 204/208」：208 是图鉴总条目、204 是已收集。
  2. 网格 6 列 × 每屏 2 行；竖向滚动一划约 19 格，无转场动画。
  3. 每格：横排「序号.N」+ 竖排刀名（OCR 直接读成横排全文，实测无误）+
     金色「极」字标（极化条目；同一把刀的普通/极化是两个图鉴条目，
     前田藤四郎序号 39/40 同屏相邻是正常现象）。
  4. 序号是唯一键；名字走 sword_db 名册校验（防误读）。

注意：本丸左侧「刀剑男士」默认落在的「刀剑男士一览」列表**不是**全刀
清单——同名刀会占多行（蜂须贺虎彻 ×5，显现日期各不相同，像是近侍/
极化履历），行语义未考证清楚，不能当账本。所以扫图鉴。

完成判定：进页面先猛滚回顶，再向下逐屏扫；连续 2 屏没有新序号即到底。
扫完对账：认出格数 vs 标题栏收集数，缺口如实上报，不硬报绿。
"""

import re
import time

from ..maa_adapter import roi_4to4, Point
from .. import sword_db

# 全部 1280×720 语义坐标，2026-09-12 真机科研标定
_SWORD_MENU_POINT = (28, 172)      # 本丸左侧栏「刀剑男士」
_ALBUM_TAB_POINT = (20, 612)       # 页面内左侧「刀帐」tab
_TITLE_ROI = (400, 15, 880, 50)    # 「刀帐」标题
_COLLECT_ROI = (790, 15, 1070, 50) # 「收集 204/208」
_GRID_ROI = (100, 115, 1280, 665)  # 卡牌网格区
_TO_TOP_SWIPE = ((640, 200), (640, 620), 250)   # 自下而上甩：滚回顶部
_NEXT_SWIPE = ((640, 600), (640, 250), 2500)    # 慢拖向下滚一行（6 格）
_PREV_SWIPE = ((640, 250), (640, 600), 2500)    # 慢拖向上滚一行（补漏趟用）
_SCROLL_WAIT_S = 1.6               # 慢拖本身 2.5s，落定稍等即稳

# 滚动速度是校准过的：300ms 甩一次会惯性飞出 30+ 格（fling），中间全跳过；
# 2500ms 慢拖实测一次正好滚一行、零惯性，步间天然重叠一行

_MAX_SCREENS = 60                  # 250 格 ÷ 每步 6 格 ≈ 42 步，留余量

_NAME_DX = (30, 175)               # 名字相对序号 token 的 x 范围
_NAME_DY = (45, 115)               # 名字相对序号 token 的 y 范围
_KIWIAME_DY = (40, 115)            # 「极」相对名字 token 的 y 范围
_KIWIAME_DX = 45                   # 「极」与名字 token 的 x 距离上限


def _as_xy(pt) -> tuple:
    return (int(pt.x), int(pt.y)) if hasattr(pt, "x") else (int(pt[0]), int(pt[1]))


def parse_album_tokens(tokens) -> list[dict]:
    """把刀帐图鉴一屏的 OCR token 解析成格子列表。

    tokens: [(text, (x, y)) ...]。返回 [{no, name_zh, kiwame}]，
    名字读不出或过不了名册校验的格子不收（宁可缺口也不掺错）。
    """
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
        maa = self.maa
        # ── 1. 到本丸 → 进一览 → 切刀帐 tab ──
        if self.current_location != "本丸":
            yield "[刀帐] 先回本丸..."
            if not self.navigate_to("本丸"):
                yield "[刀帐] ✗ 到不了本丸，停"
                return
        yield "[刀帐] 打开刀剑男士一览..."
        opened = False
        for attempt in range(3):
            maa.click(Point(*_SWORD_MENU_POINT))
            if self._wait_album_ready():
                opened = True
                break
            time.sleep(2.0)  # 回城转场/近侍台词可能吃掉第一次点击，重试
        if not opened:
            yield "[刀帐] ✗ 三次都没打开刀帐页面，停"
            return

        collected, total = self._read_collected()
        if collected:
            yield f"[刀帐] 图鉴收集 {collected}/{total or '？'}，开始逐屏认卡"

        # ── 2. 滚回顶部 ──
        for _ in range(6):
            maa.touch_swipe(*_TO_TOP_SWIPE[0], *_TO_TOP_SWIPE[1], _TO_TOP_SWIPE[2])
            time.sleep(0.8)

        # ── 3. 两遍扫描：先向下、缺了再向上补漏（OCR 漏格是随机的，
        #      慢拖偶发也会跳一行；双向合并后基本归零） ──
        seen: dict[int, dict] = {}
        yield from self._sweep(maa, seen, downward=True)
        missing_now = (collected - len(seen)) if collected else None
        if missing_now:
            yield (f"[刀帐] 第一遍认出 {len(seen)} 格、缺 {missing_now}，"
                   f"反向再扫一遍补漏...")
            yield from self._sweep(maa, seen, downward=False)

        # ── 4. 对账 + 落库 ──
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

    def _sweep(self, maa, seen: dict, downward: bool):
        """单方向扫一趟，边扫边 yield 进度。新格合并进 seen（跨趟共享）。

        结束判定是「页面不再滚动」（连续 3 屏序号集合相同），不是「没有
        新卡」——补漏趟从已扫区域出发，一路全是旧卡是正常现象，按无新卡
        判定会在出发第二屏就误判到边（首扫就踩过这坑）。
        """
        swipe = _NEXT_SWIPE if downward else _PREV_SWIPE
        edge = "到底" if downward else "到顶"
        last_seqs = None
        still = 0
        screen_no = 0
        while screen_no < _MAX_SCREENS:
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
            time.sleep(_SCROLL_WAIT_S)
        yield "[刀帐] ✗ 单趟滚了太多屏还没到边，停"
        return

    def _wait_album_ready(self, timeout_s: float = 12.0) -> bool:
        """等刀帐 tab 可点：一览标题或刀帐标题出现都算（页面记忆上次位置）"""
        deadline = time.time() + timeout_s
        while time.time() < deadline:
            time.sleep(0.8)
            self.maa.screenshot(force=True)
            if (self.maa.ocr("刀剑男士一览", roi_4to4(*_TITLE_ROI))
                    or self.maa.ocr("刀帐", roi_4to4(*_TITLE_ROI))):
                break
        else:
            return False
        # 已经在刀帐页就不用切；否则点过去
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
