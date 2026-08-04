# -*- coding: utf-8 -*-
"""
上层业务：签到（公告里领每日奖励）

路径（真机校准）：
  目录 → 公告（菜单右栏）→ 一般直接落在签到页 → OCR 领取奖励 → 道具弹窗关掉 → 关公告
  落不在签到页就点顶部"签到"标签
  没有领取奖励按钮 = 今天签过了，跳过——幂等，每天随便跑。
"""

import time

from ..maa_adapter import roi_4to4, Point


class SigninMixin:
    """签到。依赖宿主类的 _open_menu、maa。"""

    def signin_stream(self):
        """
        流式签到

        Yields:
            str: 执行状态消息
        """
        # ========== 1. 打开目录 → 公告 ==========
        yield "[签到] 打开目录..."
        if not self._open_menu():
            yield "[签到] 目录没打开，放弃"
            return
        time.sleep(1.0)

        self.maa.screenshot(force=True)
        pt = self.maa.ocr("公告", roi_4to4(1100, 100, 1280, 680))
        if not pt:
            yield "[签到] 目录里没找到公告入口，放弃"
            return
        self.maa.click(pt)
        time.sleep(3.0)

        # ========== 2. 找领取奖励按钮（不在签到页就先点签到标签）==========
        pt = self._find_claim_button()
        if not pt:
            yield "[签到] 没直接落在签到页，点签到标签"
            self.maa.click(Point(550, 55))  # 顶部"签到"标签
            time.sleep(2.0)
            pt = self._find_claim_button()

        if not pt:
            yield "[签到] 没有领取奖励按钮（今天签过了？），跳过"
            self._close_all()
            return

        # ========== 3. 领取 ==========
        yield "[签到] 看到领取奖励按钮，点！"
        self.maa.click(pt)
        time.sleep(2.5)

        # 真领到了会出道具详情弹窗；按钮是灰的（签过了）就什么都不会发生
        self.maa.screenshot(force=True)
        if self.maa.ocr("道具详情", roi_4to4(450, 80, 830, 140)):
            self.maa.click(Point(945, 105))  # 弹窗 X
            time.sleep(1.5)
            yield "[签到] 签到完成，奖励到手"
        else:
            yield "[签到] 按钮是灰的——今天已经签过了"

        self.maa.click(Point(640, 400))
        time.sleep(1.0)

        self._close_all()

    def _find_claim_button(self):
        """OCR 找领取奖励按钮，返回 Point 或 None"""
        self.maa.screenshot(force=True)
        return self.maa.ocr("领取奖励", roi_4to4(750, 550, 1100, 670))

    def _close_all(self):
        """关弹窗 + 关公告回本丸"""
        self.maa.click(Point(1195, 30))  # 公告右上角 X
        time.sleep(1.5)
        # 打开公告前目录是展开的，但关公告后已经回到本丸。
        # 不清空会让下一步误以为目录仍开着，直接在本丸画面找菜单项。
        self.current_location = None
