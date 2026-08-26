# -*- coding: utf-8 -*-
"""
上层业务：炼糖 = 收件箱清狗粮 + 习合循环（按需工具，不是日课）

总流程（用户亲授预期）：
  收件 → 习合一直喂，喂到没人 → 再收件 → 回来接着喂 → 邮件里没刀了收工。
  所持满了领不动：喂一轮腾位置再试；腾不出位置（没重刀）就收工。

收件箱：
  筛选 → 物品种类 → 全刀剑 → 确定 → 一键领取
  → 奖励确认窗关 X → 可能蹦购买详情（劝氪金）关 X
习合：
  强化 → 习合标签 → 点第一把没喂过的刀 → 一键选择 →
  习合开始（灰的说明没重刀了，换下一把）→ 二次确认 →
  动画连点跳过 → 回列表换下一把，循环
保护（上锁）的刀选不上，天然安全；用户已知晓风险自负

坐标（真机校准）：
  收件箱：筛选 (990,126) 物品种类 (1011,305) 全刀剑 (803,380) 确定 (640,625)
          一键领取 (1180,620) 奖励确认X (1144,48) 购买详情X (972,154) 收件箱X (1248,32)
  习合：标签模板 习合.png；本体行心 y [166,268,369,470,572,666]，选择 x≈1220
        本体名字 OCR roi x[160,290] y[cy+12,cy+50]
        一键选择 (1203,481) 习合开始模板 习合开始.png（蓝才命中）
        确认弹窗 确认 (785,630)；返回箭头 (141,25)；跳动画安全点 (290,550)
"""

import time

from ..maa_adapter import roi_4to4, Point

_ROW_CY = [166, 268, 369, 470, 572, 666]
_MAX_CYCLES = 60  # 习合循环安全上限（正常几十轮顶天，防识别抽风死循环）
_MAX_SWIPES = 10  # 本体列表翻页上限


class SugarMixin:
    """炼糖。依赖宿主类的 navigate_to_stream、maa。"""

    def sugar_stream(self, dry_run: bool = False):
        """
        流式炼糖（按需工具，不是日课）：
        收件 → 习合喂到没人 → 再收件 → 再喂……直到邮件里没刀了收工。
        所持满了领不动也不死循环：喂过一轮（消耗重刀腾位置）再试一次，
        还领不动就收工让用户自己想办法（刀解/氪刀位）。

        Yields:
            str: 执行状态消息
        """
        for cycle in range(1, 11):  # 外层安全上限 10 圈
            yield f"[炼糖] ===== 第 {cycle} 圈 ====="
            inbox = yield from self._inbox_claim_stream(dry_run)
            fed = yield from self._shugo_loop_stream(dry_run)
            yield f"[炼糖] 第 {cycle} 圈结算：收件={inbox} 喂了={fed} 轮"
            if dry_run:
                yield "[炼糖] 演习模式只跑一圈，收工"
                return
            if inbox == "empty":
                yield "[炼糖] 邮件里没刀了，收工"
                return
            if inbox in ("claimed", "blocked") and fed == 0:
                # 领到了但一把都喂不动（全是单张没重刀），再收也是白跑
                if inbox == "blocked":
                    yield "[炼糖] 所持满了领不动、也没重刀可喂腾位置，收工（去刀解或氪刀位吧）"
                else:
                    yield "[炼糖] 领到的刀都没重刀可喂，收工"
                return
            if inbox == "failed" and fed == 0:
                yield "[炼糖] 收件失败也喂不动，收工"
                return
        yield "[炼糖] 到安全上限 10 圈，强制收工"

    # ==================== 收件箱 ====================

    # 筛选面板按钮坐标（真机校准；面板里按钮大，点位取中心即可）
    _FILTER_OPEN = (990, 126)      # 收件箱列表页「筛选」
    _FILTER_CLEAR = (803, 157)     # 面板内「取消筛选」
    _FILTER_SWORDS = (803, 380)    # 「全刀剑」
    _FILTER_SUPPLIES = [           # 杂物四项：资源/货币/便利道具/其他物品
        (275, 455), (620, 455), (795, 455), (275, 530)]
    _FILTER_SORT_BY_KIND = (1011, 305)  # 右侧排序栏「物品种类」
    _FILTER_OK = (640, 625)        # 「确定」

    def _apply_inbox_filter(self, mode: str):
        """打开筛选面板并选过滤项。
        mode: "swords"（全刀剑，炼糖用）/ "supplies"（杂物四项）。
        supplies 先点「取消筛选」清场再点选，进来什么状态都不挑。"""
        self.maa.click(Point(*self._FILTER_OPEN))
        time.sleep(1.0)
        if mode == "supplies":
            self.maa.click(Point(*self._FILTER_CLEAR))
            time.sleep(0.6)
            for x, y in self._FILTER_SUPPLIES:
                self.maa.click(Point(x, y))
                time.sleep(0.5)
        else:
            self.maa.click(Point(*self._FILTER_SORT_BY_KIND))
            time.sleep(0.8)
            self.maa.click(Point(*self._FILTER_SWORDS))
            time.sleep(0.8)
        self.maa.click(Point(*self._FILTER_OK))
        time.sleep(1.5)

    def _inbox_claim_stream(self, dry_run: bool, filter_mode: str = "swords"):
        """
        收件箱清一波。
        filter_mode: "swords" 收全刀剑（炼糖默认）/ "supplies" 收杂物。
        Returns: "claimed" 领到了 / "blocked" 所持满领不动 / "empty" 没刀 / "failed" 导航失败 / "dry" 演习
        """
        yield "[炼糖·收件箱] 正在导航到收件箱..."
        for nav_msg in self.navigate_to_stream("收件箱"):
            yield nav_msg
        if self.current_location != "收件箱":
            yield "[炼糖·收件箱] 到达收件箱失败"
            return "failed"
        time.sleep(1.5)

        if dry_run:
            yield "[炼糖·收件箱] （演习模式：不点领取）"
            return "dry"

        # 筛选（收刀还是收杂物看 filter_mode）→ 确定
        self._apply_inbox_filter(filter_mode)

        # 一键领取（灰的配不上模板，空箱不点）
        self.maa.screenshot(force=True)
        go = self.maa.template_match(
            "收件箱一键领取.png",
            roi_4to4(1080, 540, 1275, 700), threshold=0.7)
        if not go:
            yield "[炼糖·收件箱] 没有能领的（空箱或全灰），跳过"
            self.maa.click(Point(1248, 32))  # 收箱子
            time.sleep(1.0)
            return "empty"
        self.maa.click(go)
        time.sleep(2.5)

        result = "claimed"

        # 奖励确认窗 → 关 X
        self.maa.screenshot(force=True)
        if self.maa.ocr("奖励确认", roi_4to4(500, 40, 780, 100)):
            self.maa.click(Point(1144, 48))
            time.sleep(1.5)
            yield "[炼糖·收件箱] 领了一批，奖励确认已关"

        # 可能蹦购买详情（劝氪金）→ 关 X
        self.maa.screenshot(force=True)
        if self.maa.ocr("购买详情", roi_4to4(500, 140, 780, 200)):
            self.maa.click(Point(972, 154))
            time.sleep(1.5)
            yield "[炼糖·收件箱] 所持满了蹦氪金窗，已关（领不动的先躺箱里）"
            result = "blocked"

        # 收箱子
        self.maa.click(Point(1248, 32))
        time.sleep(1.0)
        return result

    def inbox_supplies_stream(self, dry_run: bool = False):
        """收件箱只收杂物（资源/货币/便利道具/其他物品），不动刀剑邮件。

        从炼糖里拎出来的独立小工具：导航到收件箱 → 筛选杂物四项 →
        一键领取 → 关弹窗 → 收工。
        """
        result = yield from self._inbox_claim_stream(dry_run,
                                                     filter_mode="supplies")
        if result == "claimed":
            yield "[收杂物] 杂物领完收工"
        elif result == "blocked":
            yield "[收杂物] 有东西领不动（上限满了），收工"
        elif result == "empty":
            yield "[收杂物] 没有能领的杂物，收工"
        elif result == "dry":
            yield "[收杂物] 演习完毕（没真点领取）"
        else:
            yield "[收杂物] 没到收件箱，收工"
        return result

    # ==================== 习合 ====================

    def _shugo_loop_stream(self, dry_run: bool):
        """
        习合喂到没人（列表翻完/全喂过）为止。
        Returns: 喂了几轮
        """
        yield "[炼糖·习合] 正在导航到强化..."
        for nav_msg in self.navigate_to_stream("强化"):
            yield nav_msg
        if self.current_location != "强化":
            yield "[炼糖·习合] 到达强化失败"
            return 0
        time.sleep(1.5)

        tab = self.maa.template_match("习合.png", threshold=0.75)
        if not tab:
            yield "[炼糖·习合] 没找到习合标签，放弃"
            return 0
        self.maa.click(tab)
        time.sleep(2.0)

        exhausted = set()  # 喂过/没重刀的本体名字
        successes = 0
        swipes = 0

        for _ in range(_MAX_CYCLES):
            if dry_run and len(exhausted) >= 3:
                yield "[炼糖·习合] 演习模式看 3 把就够了，跳出"
                break
            self.maa.screenshot(force=True)

            # 找第一把没喂过的本体
            base = None
            for cy in _ROW_CY:
                tokens = self.maa.ocr_all(roi_4to4(160, cy + 12, 290, cy + 50))
                name = max((t for t, _ in tokens), key=len, default="")
                if len(name) < 2 or name in exhausted:
                    continue
                btn = self.maa.template_match(
                    "选择png.png", roi_4to4(1150, cy - 45, 1275, cy + 45), threshold=0.75)
                if btn:
                    base = (name, btn)
                    break

            if base is None:
                if swipes >= _MAX_SWIPES:
                    yield "[炼糖·习合] 列表翻完了，收工"
                    break
                self.maa.swipe(640, 550, 640, 250, 800)
                swipes += 1
                time.sleep(2.0)
                continue

            name, btn = base
            self.maa.click(btn)
            time.sleep(2.0)

            # 素材界面确认
            self.maa.screenshot(force=True)
            if not self.maa.template_match("一键选择.png", threshold=0.75):
                yield f"[炼糖·习合] 点 {name} 没进素材界面，跳过"
                exhausted.add(name)
                self.maa.click(Point(141, 25))
                time.sleep(1.5)
                continue

            if dry_run:
                yield f"[炼糖·习合] （演习）本体 {name} 可进素材界面，不动手"
                exhausted.add(name)
                self.maa.click(Point(141, 25))
                time.sleep(1.5)
                continue

            self.maa.click(Point(1203, 481))  # 一键选择
            time.sleep(1.5)
            self.maa.screenshot(force=True)
            go = self.maa.template_match("习合开始.png", threshold=0.7)
            if not go:
                yield f"[炼糖·习合] {name} 没有能喂的重刀，换下一把"
                exhausted.add(name)
                self.maa.click(Point(141, 25))
                time.sleep(1.5)
                continue

            self.maa.click(go)  # 习合开始
            time.sleep(2.0)
            self.maa.screenshot(force=True)
            if not self.maa.ocr("是否确认", roi_4to4(350, 100, 930, 160)):
                yield f"[炼糖·习合] {name} 确认弹窗没出现，换下一把"
                exhausted.add(name)
                self.maa.click(Point(141, 25))
                time.sleep(1.5)
                continue
            self.maa.click(Point(785, 630))  # 确认

            # 连点跳过动画，直到回素材界面
            backed = False
            for _ in range(12):
                time.sleep(1.5)
                self.maa.screenshot(force=True)
                if self.maa.template_match("一键选择.png", threshold=0.75):
                    backed = True
                    break
                self.maa.click(Point(290, 550))  # 安全点：成果面板区
            successes += 1
            yield f"[炼糖·习合] 炼了一轮: {name}（第 {successes} 糖）" + ("" if backed else "（回界面超时）")

            # 回本体列表，接着炼
            self.maa.click(Point(141, 25))
            time.sleep(1.5)

        yield f"[炼糖·习合] 收工：炼了 {successes} 轮"
        return successes
