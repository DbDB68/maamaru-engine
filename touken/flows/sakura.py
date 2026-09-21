# -*- coding: utf-8 -*-
"""
上层业务：刷花（刷疲劳到100）——1-1 单曲循环（按需工具，不是日课）

为什么要刷花（用户亲授）：
  疲劳掉到 49 就不飘花（樱吹雪），远征大成功概率跟着掉。
  游戏机制：队长位必定+疲劳，誉（MVP）也+疲劳——所以刷花是
  【队长一个人穿好刀装，单挑 1-1】，不能往队里塞别人（会抢誉）。

流程：
  编队 → 装备解除（刀装·部队以外，把不出阵的人的刀装扒回仓库）
  → 切到目标部队标签 → OCR 读队长疲劳
  → 队长已达标/空位：点"替换"在刀剑男士选择里找疲劳<50的换进来
  → 点"装备"→ 更换装备页点"自动装备刀装"→ 返回
  → 1-1 打一圈（复用 sortie，自动行军+阵形选择+重伤保护全套）
  → 回编队再读疲劳 → 够了收工，不够接着刷

坐标（真机校准，1280x720）：
  编队页部队标签：部队一(154,91) 二(274,91) 三(394,91) 四(516,91) 五(638,91)
  成员行心 y [160,258,357,455,553,652]（一之一~一之六）
  疲劳文本在每行 "疲劳 xx/100"：roi x[290,425] y[cy+28,cy+52]
  每行"装备"按钮 x≈963 y=cy；更换装备页"自动装备刀装"(621,96)；返回箭头(135,25)

疲劳值识别要点：roi 可能蹭到上面那行"生存 xx/xx"，
  所以配对的两个数里分母是 100 的才是疲劳（疲劳上限永远 100）。
"""

import re
import time

from .. import sword_db
from ..maa_adapter import roi_4to4, Point

_TEAM_TAB = {1: (154, 91), 2: (274, 91), 3: (394, 91), 4: (516, 91), 5: (638, 91)}
_ROW_CY = [160, 258, 357, 455, 553, 652]
_EQUIP_X = 963            # 每行"装备"按钮
_SWAP_X = 1033            # 每行"替换"按钮
_AUTO_EQUIP = (621, 96)   # 更换装备页"自动装备刀装"
_EQUIP_BACK = (135, 25)   # 更换装备页返回箭头

# 换队长拖拽：从成员卡片拖到队长位。起点 x 是真机校准点——
# 太快会被游戏吞（repair.py 实测 <400ms 失灵）；adb input swipe 匀速
# 插值，拖远了速度跟着变快，容易被当成列表滚动，所以时长按距离放大
_DRAG_X = 200
_DRAG_MS = 1000   # 起步时长，实际取 max(此值, 拖动距离×2.5)

# 换队长读疲劳：成员信息列整列 OCR（x 覆盖"疲劳 xx/100"文本）后按 y
# 归位。血泪（2026-09-21 六号位隐形事故）：编队页行距 ~98px、部队选择页
# ~94.5px，写死六行坐标会在底部行累积 60px+ 偏差，5/6 号位疲劳整个
# 读空——累的人对轮换隐形。两页不再共用行坐标假设。
_FATIGUE_COL = (285, 100, 435, 710)      # 疲劳列整列 ROI（xyxy）
_FIRST_ROW_Y = (140, 260)                # 首行疲劳 y 合理范围（两页均 ~196-199）
_FATIGUE_TO_ROW_CY = 36                  # 疲劳行 y → 行中心（拖拽/名字定位用）


def _parse_fatigue_text(text: str):
    """从一行 OCR 文本里挑疲劳值：配对的两个数里分母是 100 的才是疲劳
    （roi 可能蹭到上面那行"生存 xx/xx"，疲劳上限永远 100）。
    Returns: 疲劳值 int 或 None
    """
    pairs = re.findall(r"(\d{1,3})\D{0,2}/\D{0,2}(\d{1,3})", text)
    if not pairs:
        return None
    for cur, mx in pairs:
        if mx == "100":
            return int(cur)
    return int(pairs[0][0])

# 刀剑男士选择（替换列表）：行位置随滚动会飘，不写死行坐标，
# 整列 OCR 按 y 分行找"疲劳"行；决定按钮 x≈1197，中心≈疲劳行上方 40
_SEL_DECIDE_X = 1197
_SEL_MAX_PAGES = 8        # 翻页安全上限


class SakuraMixin:
    """刷花。依赖宿主类的 navigate_to_stream、sortie_stream、maa。"""

    def sakura_stream(self, team_no: int = 5, slot: int = 1,
                      target: int = 100, max_rounds: int = 40,
                      auto_swap: bool = True, swap_threshold: int = 50):
        """
        流式刷花

        Args:
            team_no: 部队编号（1-5）
            slot: 位置（1=队长，刷花一般刷队长）
            target: 目标疲劳（默认 100 飘花）
            max_rounds: 1-1 安全上限圈数
            auto_swap: 位置上的刀已达标时，自动点"替换"找疲劳低的人换进来刷
            swap_threshold: 换人标准：疲劳低于这个值才算"累了需要刷"

        Yields:
            str: 执行状态消息
        """
        if team_no not in _TEAM_TAB:
            yield f"[刷花] 部队{team_no}不存在（1-5）"
            return
        if not 1 <= slot <= 6:
            yield "[刷花] 位置得在 1-6 之间"
            return

        yield f"[刷花] 目标：部队{team_no} {slot}号位 刷到疲劳{target}"

        # ========== 先读当前疲劳，决定要不要换人 ==========
        fatigue = yield from self._check_fatigue(team_no, slot)
        if fatigue is not None:
            # 不管换不换人，先把部队以外的刀装扒回仓库，
            # 不然不出阵的刀占着刀装，刷花的人没得穿（用户亲授）
            yield from self._unequip_others()
        need_swap = False
        if fatigue is None:
            if not auto_swap:
                yield "[刷花] 读不到疲劳值，停（队伍在远征？这个位置没人？）"
                return
            yield "[刷花] 这位置是空位（或读不到），直接去替换找累的人填上"
            need_swap = True
        else:
            yield f"[刷花] 当前疲劳 {fatigue}/100"
            if fatigue >= target:
                if not auto_swap:
                    yield "[刷花] 已经达标，不用刷，收工"
                    return
                yield f"[刷花] 这位已达标，去替换列表找疲劳<{swap_threshold}的人换进来..."
                need_swap = True

        if need_swap:
            swapped = yield from self._swap_tired_in(slot, swap_threshold)
            if not swapped:
                yield "[刷花] 列表翻完也没找到累的人，全军飘花，收工"
                return
            fatigue = yield from self._check_fatigue(team_no, slot)
            if fatigue is None:
                yield "[刷花] 换完人读不到疲劳了，停"
                return
            yield f"[刷花] 换人完成，新同事疲劳 {fatigue}/100"
            if fatigue >= target:
                yield "[刷花] 换进来这位也达标？不用刷，收工"
                return

        # ========== 自动装备刀装 ==========
        yield from self._auto_equip(slot)

        # ========== 1-1 单曲循环 ==========
        for rd in range(1, max_rounds + 1):
            if self._expedition_takeover_requested():
                yield "[刷花] 🚩 远征排班请求接管：不开新圈，安全收工"
                return
            yield f"[刷花] ===== 第 {rd} 圈 1-1（疲劳 {fatigue}/{target}） ====="
            round_done = False
            stop = False
            for msg in self.sortie_stream(chapter=1, map_no=1, team_no=team_no,
                                          auto_march=True, max_loops=1):
                yield msg
                if "圈打完" in msg:
                    round_done = True
                if "绝不出阵" in msg or "强制停" in msg or "行军中断" in msg:
                    stop = True
            if stop:
                yield "[刷花] 出阵被安全规矩拦下了，停止刷花，你去看看情况"
                return
            if not round_done:
                yield "[刷花] 这圈没打完，停止刷花，你去看看卡哪了"
                return

            # 回编队再读疲劳
            fatigue = yield from self._check_fatigue(team_no, slot)
            if fatigue is None:
                yield "[刷花] 打完一圈读不到疲劳了，停（界面状态不对？）"
                return
            yield f"[刷花] 第 {rd} 圈后疲劳 {fatigue}/100"
            if fatigue >= target:
                yield f"[刷花] 飘花了！{rd} 圈刷到 {fatigue}，收工"
                return

        yield f"[刷花] 刷了 {max_rounds} 圈还没到 {target}（当前 {fatigue}），安全上限收工"

    def _rotate_captain_here(self, margin: int = 10):
        """
        在当前页原地换队长：整列 OCR 读全队疲劳，最低的拖到队长位，拖完复查。

        调用前必须已停在目标部队的成员列表页（部队标签已切好）。
        编队页和出阵前的部队选择页都能拖人换位，但两页行距不同
        （编队 ~98px、部队选择 ~94.5px），所以读数走整列 OCR 按 y
        归位，不写死行坐标——写死会在底部行累积偏差，2026-09-21
        出过 5/6 号位疲劳读空、红脸队员对轮换隐形的事故。

        Yields:
            str: 执行状态消息
        """
        rows = self._read_rows_fatigue()
        if not rows:
            yield "[换队长] 全队疲劳读不齐（在远征？界面不对？），本轮不换"
            return

        values = {slot: value for slot, (fy, value) in rows.items()}
        captain = values.get(1)
        if captain is None:
            yield "[换队长] 队长位读不到疲劳（空位？），跳过"
            return
        low_slot = min(values, key=values.get)
        low = values[low_slot]
        overview = "、".join(f"{s}号位{v}" for s, v in sorted(values.items()))
        yield f"[换队长] 全队疲劳：{overview}"

        if low_slot == 1:
            yield f"[换队长] 队长自己就是全队最低（{captain}/100），位置没毛病，收工"
            return
        if captain - low < margin:
            yield (f"[换队长] 全队最低才 {low}/100，跟队长（{captain}）"
                   f"差不到 {margin}，不值得折腾，收工")
            return

        # 读个名字好汇报（名字在疲劳行上方，同 _swap_tired_in 的相对位置）。
        # OCR 老眼昏花会漏字（"夜左文字"），过名册校正成标准名再上日志
        low_fy = rows[low_slot][0]
        cy_low = low_fy - _FATIGUE_TO_ROW_CY
        cy_top = rows[1][0] - _FATIGUE_TO_ROW_CY
        name_tokens = self.maa.ocr_all(roi_4to4(100, low_fy - 32, 265, low_fy - 4))
        name_raw = max((t for t, _ in name_tokens), key=len, default=f"{low_slot}号位")
        name = sword_db.display_name(name_raw)
        yield f"[换队长] {name} 疲劳 {low} 全队最低，拖去队长位（原队长 {captain}/100）"

        # adb input swipe 匀速插值：拖远了速度跟着变快，容易被游戏当成
        # 列表滚动吞掉，时长按距离放大
        duration = max(_DRAG_MS, int((cy_low - cy_top) * 2.5))
        after_values = {}
        for attempt in (1, 2):
            self.maa.swipe(_DRAG_X, cy_low, _DRAG_X, cy_top,
                           duration if attempt == 1 else int(duration * 1.5))
            time.sleep(2.0)

            # 拖完复查：队长位的疲劳应该变成刚才那位最低值
            after = self._read_rows_fatigue()
            after_values = {s: v for s, (f, v) in after.items()}
            if after_values.get(1) == low:
                yield f"[换队长] ✓ 换好了，{name} 上任队长，去吃疲劳加成吧"
                return
            # 疲劳复读会 OCR 错字（88 认成 86）：用队长位的名字再核一遍
            if after:
                cap_fy = after[1][0]
                cap_tokens = self.maa.ocr_all(
                    roi_4to4(100, cap_fy - 32, 265, cap_fy - 4))
                cap_name = sword_db.display_name(
                    max((t for t, _ in cap_tokens), key=len, default=""))
                if cap_name and cap_name == name:
                    yield (f"[换队长] ✓ 换好了（疲劳复读 {after_values.get(1)} "
                           f"对不上 {low}，但队长位已是 {name}），去吃疲劳加成吧")
                    return
            if attempt == 1:
                # 手势若被当成滚动，行位置可能已经飘了：按现位置再拖一次
                if after:
                    cy_low = next((fy for fy, v in after.values() if v == low),
                                  after[1][0]) - _FATIGUE_TO_ROW_CY
                    cy_top = after[1][0] - _FATIGUE_TO_ROW_CY
                yield "[换队长] 复查对不上，按当前位置再拖一次..."
        got = after_values.get(1, "读不到")
        yield (f"[换队长] ⚠️ 拖完队长位疲劳是 {got}，不是预期的 {low}"
               "——拖动可能没生效（手势被吞？），你手动瞅一眼")

    def _read_rows_fatigue(self) -> dict:
        """当前页成员列表整列 OCR：抓所有"疲劳"行连同 y 坐标，按 y 排序
        对号 1~N 号位（适配 3~6 人队伍，编队/部队选择两页通吃）。

        Returns: {位置: (疲劳行y, 疲劳值)}；首行位置不对或相邻行距突变
        说明整列错位/中间漏行，对号会错——返回 {}，宁可不读也不拖错人。
        """
        self.maa.screenshot(force=True)
        tokens = self.maa.ocr_all(roi_4to4(*_FATIGUE_COL))
        lines = {}  # y 聚类 -> 该行 token（±12px 算同一行）
        for t, p in tokens:
            key = round(p.y / 12)
            lines.setdefault(key, []).append((p.x, t, p.y))
        rows = []  # (疲劳行y, 疲劳值)
        for group in lines.values():
            group.sort()
            text = "".join(t for _, t, _ in group)
            if "疲" not in text:  # "疲劳"偶发认成"疲务"，只看半边
                continue
            value = _parse_fatigue_text(text)
            if value is None:
                continue
            rows.append((group[0][2], value))
        rows.sort()
        if not rows:
            return {}
        # 漏读首行会让全队错号（顶 anchor）；中间漏行会留下倍距空洞
        if not (_FIRST_ROW_Y[0] <= rows[0][0] <= _FIRST_ROW_Y[1]):
            return {}
        if len(rows) >= 3:
            gaps = [rows[i + 1][0] - rows[i][0] for i in range(len(rows) - 1)]
            median = sorted(gaps)[len(gaps) // 2]
            if any(g > median * 1.6 for g in gaps):
                return {}
        return {slot: row for slot, row in enumerate(rows, start=1)}

    # ==================== 读疲劳 ====================

    def _check_fatigue(self, team_no: int, slot: int):
        """
        导航到编队 → 切部队标签 → OCR 读疲劳。
        Returns: 疲劳值 int；读不到返回 None（yield from 接返回值）
        """
        for nav_msg in self.navigate_to_stream("编队"):
            yield nav_msg
        if self.current_location != "编队":
            yield "[刷花] 到不了编队"
            return None
        self.maa.click(Point(*_TEAM_TAB[team_no]))
        time.sleep(1.5)
        self.maa.screenshot(force=True)

        cy = _ROW_CY[slot - 1]
        tokens = self.maa.ocr_all(roi_4to4(290, cy + 28, 425, cy + 52))
        text = "".join(t for t, _ in tokens)
        return _parse_fatigue_text(text)

    # ==================== 装备解除：刀装·部队以外 ====================

    def _unequip_others(self):
        """
        编队页：装备解除 → 刀装 → 部队以外 → 确定。
        把不出阵的人的刀装扒回仓库，刷花的人才有得穿（此时已经在编队页）。
        坐标（真机校准）：装备解除(1186,315) 刀装(376,279) 部队以外(727,471) 确定(640,604)
        """
        yield "[刷花] 装备解除：刀装·部队以外..."
        self.maa.click(Point(1186, 315))
        time.sleep(1.5)
        self.maa.screenshot(force=True)
        if not self.maa.ocr("装备解除", roi_4to4(540, 60, 740, 115)):
            yield "[刷花] 装备解除弹窗没开，跳过"
            return
        self.maa.click(Point(376, 279))   # 刀装
        time.sleep(0.6)
        self.maa.click(Point(727, 471))   # 部队以外
        time.sleep(0.6)
        self.maa.click(Point(640, 604))   # 确定
        time.sleep(1.5)
        # 结果确认弹窗（"解除了N个"之类）
        self.maa.screenshot(force=True)
        pt = self.maa.template_match("通用_确定.png", threshold=0.7)
        if pt:
            self.maa.click(pt)
            time.sleep(1.0)
        yield "[刷花] 部队以外的刀装已解"

    # ==================== 换人：找疲劳低的换进来 ====================

    def _swap_tired_in(self, slot: int, threshold: int):
        """
        编队页点那行的"替换"→ 刀剑男士选择列表逐行 OCR 疲劳，
        第一个低于 threshold 的点"决定"换进来（此时已经在编队页）。
        Returns: 是否换人成功（yield from 接返回值）
        """
        cy = _ROW_CY[slot - 1]
        self.maa.click(Point(_SWAP_X, cy))
        time.sleep(2.0)
        self.maa.screenshot(force=True)
        if not self.maa.ocr("刀剑男士选择", roi_4to4(500, 0, 780, 55)):
            yield "[刷花·换人] 选择列表没打开，放弃换人"
            return False

        for page in range(_SEL_MAX_PAGES):
            self.maa.screenshot(force=True)
            # 整列 OCR 按 y 分行找"疲劳"——列表滚动后行位置会飘，不写死行坐标
            tokens = self.maa.ocr_all(roi_4to4(460, 100, 620, 700))
            lines = {}  # y中心 -> 该行文本
            for t, p in tokens:
                key = round(p.y / 12)
                lines.setdefault(key, []).append((p.x, t, p.y))
            for group in lines.values():
                group.sort()
                text = "".join(t for _, t, _ in group)
                if "疲劳" not in text:
                    continue
                fy = group[0][2]
                pairs = re.findall(r"(\d{1,3})\D{0,2}/\D{0,2}(\d{1,3})", text)
                value = None
                for cur, mx in pairs:
                    if mx == "100":
                        value = int(cur)
                        break
                if value is None or value >= threshold:
                    continue
                # 找到累的了：读个名字好汇报（过名册校正错别字），点决定
                # （按钮中心≈疲劳行上方40）
                name_tokens = self.maa.ocr_all(roi_4to4(100, fy - 32, 265, fy - 4))
                name = sword_db.display_name(
                    max((t for t, _ in name_tokens), key=len, default="?"))
                yield f"[刷花·换人] 第{page + 1}页找到 {name} 疲劳{value}，换！"
                self.maa.click(Point(_SEL_DECIDE_X, fy - 40))
                time.sleep(1.5)
                # 可能有确认弹窗
                self.maa.screenshot(force=True)
                pt = self.maa.template_match("通用_确定.png", threshold=0.7)
                if pt:
                    self.maa.click(pt)
                    time.sleep(1.5)
                return True
            # 本页没有累的，翻页
            self.maa.swipe(640, 550, 640, 200, 800)
            time.sleep(2.0)
        return False

    # ==================== 自动装备刀装 ====================

    def _auto_equip(self, slot: int):
        """编队页点那行的"装备"→ 自动装备刀装 → 返回（此时已经在编队页）"""
        cy = _ROW_CY[slot - 1]
        self.maa.click(Point(_EQUIP_X, cy))
        time.sleep(2.0)
        self.maa.screenshot(force=True)
        if not self.maa.ocr("更换装备", roi_4to4(530, 0, 730, 60)):
            yield "[刷花] 装备页没打开，跳过装备直接刷（可能有刀装/远征中）"
            return
        self.maa.click(Point(*_AUTO_EQUIP))
        time.sleep(1.5)
        # 可能有确认弹窗
        self.maa.screenshot(force=True)
        pt = self.maa.template_match("通用_确定.png", threshold=0.7)
        if pt:
            self.maa.click(pt)
            time.sleep(1.0)
        yield "[刷花] 自动装备刀装完成"
        self.maa.click(Point(*_EQUIP_BACK))
        time.sleep(1.5)
