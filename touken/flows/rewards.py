# -*- coding: utf-8 -*-
"""
上层业务：领取类——万屋暖心礼包、任务奖励（日常/月常/活动）
（从 touken_agent_engine_v2.py 原样搬家，逻辑未改）
"""

import time

from ..maa_adapter import roi_4to4


class RewardsMixin:
    """领取类流程。依赖宿主类的 navigate_to_stream、_click_point、_click_template_config。"""

    # ==================== 万屋领取 ====================

    def claim_free_gift(self) -> bool:
        """同步版本：领取暖心礼包，返回是否成功"""
        for msg in self.claim_free_gift_stream():
            print(msg)
        return "领取成功" in msg if 'msg' in dir() else False

    def claim_free_gift_stream(self):
        """
        流式版本：领取暖心礼包，每步 yield 状态消息

        Yields:
            str: 执行状态消息，前端可实时显示
        """
        shop_config = self.config.get("shop", {}).get("free_gift")
        if not shop_config:
            yield "[SHOP] 未配置暖心礼包"
            return

        # 1. 导航到万屋
        yield "[SHOP] 正在导航到万屋..."
        for nav_msg in self.navigate_to_stream("万屋"):
            yield nav_msg
        if self.current_location != "万屋":
            yield "[SHOP] 到达万屋失败"
            return

        # 2. 识别"暖心"文字
        yield "[SHOP] 寻找暖心礼包..."
        find_config = shop_config["find_text"]
        roi_raw = find_config["roi"]
        roi = roi_4to4(roi_raw[0], roi_raw[1], roi_raw[2], roi_raw[3])

        # 强制刷新截图
        self.maa.screenshot(force=True)

        # OCR 识别暖心
        result = self.maa.ocr(
            expected=find_config["expected"],
            roi=roi,
            match_mode=find_config.get("match_mode", "contains")
        )

        if not result:
            yield "[SHOP] 未找到暖心礼包，可能已经领过了或界面不对"
            return

        yield f"[SHOP] 找到暖心礼包 at ({result.x}, {result.y})"

        # 3. 点击领取按钮
        claim_config = shop_config["claim_button"]
        claim_roi_raw = claim_config.get("roi", [0, 0, 1280, 720])
        claim_roi = roi_4to4(claim_roi_raw[0], claim_roi_raw[1], claim_roi_raw[2], claim_roi_raw[3])

        # 售罄是“今天已经领过”的明确成功状态，不要再去点旧兜底坐标。
        sold_out_config = shop_config.get("sold_out", {})
        sold_out_template = sold_out_config.get("template")
        if sold_out_template and self.maa.template_match(
                sold_out_template, roi=claim_roi, threshold=0.5):
            yield "[SHOP] 今日暖心礼包已售罄，说明此前已经领取，跳过"
            return

        claim_result = self.maa.template_match(
            template=claim_config["template"],
            roi=claim_roi,
            threshold=0.5
        )

        if claim_result:
            yield f"[SHOP] 点击领取按钮 at ({claim_result.x}, {claim_result.y})"
            self.maa.click(claim_result)
        else:
            # 模板更新不及时还可以用文字兜底；两者都失败就不盲点。
            claim_result = self.maa.ocr("领取", claim_roi)
            if not claim_result:
                yield "[SHOP] 暖心礼包未售罄，但未识别到领取按钮，本次未点击"
                return
            yield f"[SHOP] 通过文字找到领取按钮 at ({claim_result.x}, {claim_result.y})"
            self.maa.click(claim_result)

        yield "[SHOP] 等待弹窗出现..."
        time.sleep(1.5)

        # 4. 验证弹窗：确认价格0
        yield "[SHOP] 验证弹窗价格..."
        verify_config = shop_config["popup_verify"]
        verify_roi_raw = verify_config["roi"]
        verify_roi = roi_4to4(verify_roi_raw[0], verify_roi_raw[1], verify_roi_raw[2], verify_roi_raw[3])

        # 循环等待弹窗出现
        for _ in range(10):
            self.maa.screenshot(force=True)
            verify_result = self.maa.ocr(
                expected=verify_config["expected"],
                roi=verify_roi,
                match_mode=verify_config.get("match_mode", "contains")
            )
            if verify_result:
                yield "[SHOP] 确认价格0，安全"
                break
            time.sleep(0.5)
        else:
            yield "[SHOP] 未检测到0价格弹窗，可能不是免费礼包，取消"
            # 尝试关闭弹窗
            close_config = shop_config.get("popup_close")
            if close_config:
                self._click_template_config(close_config)
            return

        # 5. 点击弹窗购买按钮
        yield "[SHOP] 点击购买按钮..."
        buy_config = shop_config["popup_buy"]
        buy_roi_raw = buy_config.get("roi", [0, 0, 1280, 720])
        buy_roi = roi_4to4(buy_roi_raw[0], buy_roi_raw[1], buy_roi_raw[2], buy_roi_raw[3])

        buy_result = self.maa.template_match(
            template=buy_config["template"],
            roi=buy_roi,
            threshold=0.5
        )

        if buy_result:
            self.maa.click(buy_result)
            yield f"[SHOP] 点击购买 at ({buy_result.x}, {buy_result.y})"
        else:
            # 使用配置的固定坐标
            fallback = buy_config.get("fallback_target", [640, 550])
            yield f"[SHOP] 模板匹配购买按钮失败，使用固定坐标 {fallback}"
            self._click_point(fallback)

        yield "[SHOP] 等待领取完成..."
        time.sleep(1.0)

        # 6. 关闭可能的后续弹窗
        close_config = shop_config.get("popup_close")
        if close_config:
            for _ in range(3):
                self.maa.screenshot(force=True)
                if self.maa.exists(close_config.get("template")):
                    self._click_template_config(close_config)
                    time.sleep(0.5)
                else:
                    break

        yield "[SHOP] 领取成功！"
        return

    # ==================== 任务奖励领取 ====================

    def claim_task_rewards_stream(self):
        """
        流式领取任务奖励（日常、月常、活动）
        主线不领（长线成就，不会过期）

        Yields:
            str: 执行状态消息
        """
        task_config = self.config.get("task_reward", {})
        if not task_config:
            yield "[TASK] 未配置任务领取"
            return

        # 1. 导航到任务
        yield "[TASK] 正在导航到任务..."
        for nav_msg in self.navigate_to_stream("任务"):
            yield nav_msg
        if self.current_location != "任务":
            yield "[TASK] 到达任务失败"
            return

        # 2. 领取各标签页奖励
        tabs = task_config.get("tabs", {})
        for tab_name, tab_coord in tabs.items():
            yield f"[TASK] 切换到 {tab_name}..."

            # 点击标签
            self._click_point(tab_coord)
            time.sleep(0.8)

            # 检查一键领取按钮
            claim_config = task_config["claim_button"]
            self.maa.screenshot(force=True)

            claim_result = self.maa.template_match(
                template=claim_config["template"],
                roi=None,
                threshold=0.5
            )

            if claim_result:
                yield f"[TASK] {tab_name} 有奖励可领，点击一键领取..."
                self.maa.click(claim_result)

                # 等待领取动画/弹窗
                time.sleep(1.5)

                # 关闭可能的奖励弹窗
                # 判定：必须同时有 通用_关闭.png 和 ui完成任务.png
                # 防止误关任务界面本身
                close_config = task_config.get("popup_close")
                if close_config:
                    for _ in range(5):
                        self.maa.screenshot(force=True)
                        has_close = self.maa.exists(close_config.get("template"))
                        has_complete = self.maa.exists("ui完成任务.png")

                        if has_close and has_complete:
                            # 是奖励弹窗，关闭
                            self._click_template_config(close_config)
                            yield "[TASK] 关闭奖励弹窗"
                            time.sleep(0.5)
                        elif has_close and not has_complete:
                            # 是任务界面本身的关闭按钮，不点
                            yield "[TASK] 检测到任务界面关闭按钮，跳过"
                            break
                        else:
                            break

                # 处理"任务信息已失效"弹窗
                confirm_point = self.maa.template_match("通用_确定.png", None)
                if confirm_point:
                    self.maa.click(confirm_point)
                    yield "[TASK] 任务信息已失效，刷新"
                    time.sleep(0.5)

                yield f"[TASK] {tab_name} 领取完成"
            else:
                yield f"[TASK] {tab_name} 没有可领奖励，跳过"

        yield "[TASK] 所有任务奖励领取完毕"
        return
