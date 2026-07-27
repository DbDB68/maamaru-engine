# -*- coding: utf-8 -*-
"""
中层：通用导航与识别机械
根据配置在游戏里"走路"：识别元素、点开目录、跳转界面、处理弹窗。
不知道什么是联队战、什么是领奖励——那是上层 flows/ 的事。
（从 touken_agent_engine_v2.py 原样搬家，逻辑未改）
"""

import time
from typing import Optional

from .maa_adapter import Point, Region, roi_4to4


class NavigationMixin:
    """
    通用识别 + 导航 + 弹窗处理
    依赖宿主类提供：self.config、self.maa、self.current_location
    """

    # ==================== 通用识别方法 ====================

    def _recognize(self, method_config: dict) -> Optional[Point]:
        """
        通用识别：根据配置选择 OCR 或 TemplateMatch

        Args:
            method_config: 来自配置文件的识别配置

        Returns:
            识别成功返回中心坐标，失败返回 None
        """
        method_type = method_config.get("type", "TemplateMatch")

        # 把 [x1,y1,x2,y2] 转成 Region(x,y,w,h)
        if "roi" in method_config:
            roi_raw = method_config["roi"]
            if len(roi_raw) == 4:
                roi = roi_4to4(roi_raw[0], roi_raw[1], roi_raw[2], roi_raw[3])
            else:
                roi = Region(*roi_raw)
        else:
            roi = None

        if method_type == "OCR":
            return self.maa.ocr(
                expected=method_config["expected"],
                roi=roi,
                match_mode=method_config.get("match_mode", "contains")
            )
        elif method_type == "TemplateMatch":
            threshold = method_config.get("threshold", 0.7)
            # 模板匹配默认全屏搜索，除非配置明确指定了 roi
            # 因为模板图片本身就是精确匹配，不需要额外限制区域
            if "roi" in method_config:
                tm_roi = roi
            else:
                tm_roi = None  # 全屏
            return self.maa.template_match(
                template=method_config["template"],
                roi=tm_roi,
                threshold=threshold
            )
        return None

    def _try_with_fallback(self, config: dict) -> Optional[Point]:
        """
        尝试 primary 方法，失败后用 fallback
        """
        if "primary" in config:
            result = self._recognize(config["primary"])
            if result:
                return result

        if "fallback" in config:
            result = self._recognize(config["fallback"])
            if result:
                return result

        return None

    def _click_point(self, target: list) -> bool:
        """点击坐标点 [x, y]"""
        point = Point(target[0], target[1])
        return self.maa.click(point)

    def _click_template_config(self, config: dict) -> bool:
        """根据模板配置点击"""
        if "target" in config:
            return self._click_point(config["target"])
        elif "template" in config:
            if "roi" in config:
                roi_raw = config["roi"]
                roi = roi_4to4(roi_raw[0], roi_raw[1], roi_raw[2], roi_raw[3])
            else:
                roi = None
            result = self.maa.template_match(config["template"], roi)
            if result:
                return self.maa.click(result)
            return False
        return False

    # ==================== 导航流程 ====================

    def _open_menu(self, max_attempts: int = 10) -> bool:
        """
        循环点击目录按钮，直到菜单展开

        Args:
            max_attempts: 最大尝试次数

        Returns:
            是否成功打开菜单
        """
        nav_config = self.config.get("navigation", {})
        common_config = nav_config.get("通用入口", {})

        # 如果菜单已经打开了，直接返回
        if self.current_location == "通用入口":
            return True

        for attempt in range(max_attempts):
            print(f"[NAV] 尝试打开目录 (第{attempt+1}次)")

            # 强制刷新截图
            self.maa.screenshot(force=True)

            # 检测菜单是否已展开：检测 ui目录.png
            if self.maa.exists("menu/ui目录.png"):
                print("[NAV] 目录已展开")
                self.current_location = "通用入口"
                return True

            # 菜单没展开：
            # 1) 可能在演结算动画/对话（连目录按钮都看不见），点跳过点把动画往前推
            # 2) 也可能被收件箱这种全屏界面压住（15:00 实测卡死元凶）——先关 X
            if self.maa.exists("目录.png", threshold=0.7):
                self._click_template_config(common_config)
            else:
                close_pt = self.maa.template_match("通用_关闭.png", threshold=0.7)
                if close_pt:
                    print("[NAV] 发现全屏界面/弹窗，点关闭")
                    self.maa.click(close_pt)
                else:
                    self.maa.click(Point(993, 690))
            time.sleep(0.8)

        print("[NAV] 目录始终未展开")
        return False

    def navigate_to(self, target: str, max_retries: int = 3) -> bool:
        """
        导航到指定界面

        Args:
            target: 目标界面名称，如 "本丸", "出阵", "远征"
            max_retries: 最大重试次数

        Returns:
            是否成功到达
        """
        nav_config = self.config.get("navigation", {})

        if target not in nav_config:
            print(f"[ERROR] 未知导航目标: {target}")
            return False

        target_config = nav_config[target]

        # 特殊处理：通用入口不是导航目标，而是动作（点击目录按钮）
        if target == "通用入口":
            print(f"[NAV] 点击通用入口（目录按钮）")
            self._click_template_config(target_config)
            time.sleep(0.5)
            self.current_location = "通用入口"
            return True

        # 1. 如果需要先打开通用入口（目录），循环点击直到展开
        if "from" in target_config:
            from_target = target_config["from"]
            if from_target == "通用入口" and self.current_location != "通用入口":
                if not self._open_menu():
                    return False

        # 2. 尝试进入目标界面
        # 给界面一点稳定时间，并强制刷新截图
        time.sleep(0.5)
        self.maa.screenshot(force=True)
        for attempt in range(max_retries):
            print(f"[NAV] 尝试进入 {target} (第{attempt+1}次)")

            result = self._try_with_fallback(target_config)
            if result:
                self.maa.click(result)

                # ===== 关键：等待界面切换完成 =====
                if "verify" in target_config:
                    verify_timeout = 10  # 最多等10秒
                    verify_start = time.time()
                    while time.time() - verify_start < verify_timeout:
                        time.sleep(0.8)
                        # 强制刷新截图，确保识别的是最新画面
                        self.maa.screenshot(force=True)
                        verify_result = self._recognize(target_config["verify"])
                        if verify_result:
                            self.current_location = target
                            print(f"[NAV] 成功到达: {target}")
                            return True
                        print(f"[NAV] 等待 {target} 界面加载中...")

                    print(f"[NAV] 等待 {target} 加载超时，重试")
                else:
                    # 没有 verify，等固定时间后认为成功
                    time.sleep(2.0)
                    self.current_location = target
                    print(f"[NAV] 成功到达: {target}（无验证）")
                    return True

            time.sleep(1)

        print(f"[NAV] 进入 {target} 失败")
        return False

    def navigate_to_stream(self, target: str, max_retries: int = 3):
        """
        流式导航到指定界面，每步 yield 状态消息

        Yields:
            str: 执行状态消息
        """
        nav_config = self.config.get("navigation", {})

        if target not in nav_config:
            yield f"[ERROR] 未知导航目标: {target}"
            return

        target_config = nav_config[target]

        # 特殊处理：通用入口
        if target == "通用入口":
            yield f"[NAV] 点击通用入口（目录按钮）"
            self._click_template_config(target_config)
            time.sleep(0.5)
            self.current_location = "通用入口"
            yield f"[NAV] 目录已点击"
            return

        # 1. 如果需要先打开通用入口（目录），循环点击直到展开
        if "from" in target_config:
            from_target = target_config["from"]
            if from_target == "通用入口" and self.current_location != "通用入口":
                yield f"[NAV] 需要先打开目录"
                if not self._open_menu():
                    yield f"[NAV] 目录始终未展开，导航失败"
                    return
                yield f"[NAV] 目录已展开"

        # 2. 尝试进入目标界面
        yield f"[NAV] 给界面一点稳定时间..."
        time.sleep(0.5)
        self.maa.screenshot(force=True)

        for attempt in range(max_retries):
            yield f"[NAV] 尝试进入 {target} (第{attempt+1}次)..."

            result = self._try_with_fallback(target_config)
            if result:
                self.maa.click(result)

                # 验证循环
                if "verify" in target_config:
                    verify_timeout = 10
                    verify_start = time.time()
                    while time.time() - verify_start < verify_timeout:
                        time.sleep(0.8)
                        self.maa.screenshot(force=True)
                        verify_result = self._recognize(target_config["verify"])
                        if verify_result:
                            self.current_location = target
                            yield f"[NAV] 成功到达: {target}"
                            return
                        yield f"[NAV] 等待 {target} 界面加载中..."

                    yield f"[NAV] 等待 {target} 加载超时，重试..."

                    # 救援：可能是弹窗/余波动画挡路（15:00 实测锻刀导航卡循环的教训）。
                    # 有关闭按钮就点掉，没有就点跳过点推一把，再进下一轮重试。
                    self.maa.screenshot(force=True)
                    close_pt = self.maa.template_match("通用_关闭.png", threshold=0.7)
                    if close_pt:
                        yield "[NAV] 救援：发现弹窗，点关闭"
                        self.maa.click(close_pt)
                        time.sleep(1.0)
                    elif not self.maa.exists("menu/ui目录.png"):
                        # 菜单都不见了：多半被动画/结算顶走了，推一把再重新开菜单
                        yield "[NAV] 救援：界面被顶走，点跳过点推一把"
                        self.maa.click(Point(993, 690))
                        time.sleep(1.0)
                        self.current_location = None
                        if not self._open_menu():
                            yield "[NAV] 救援后目录仍打不开，导航失败"
                            return
                else:
                    time.sleep(2.0)
                    self.current_location = target
                    yield f"[NAV] 成功到达: {target}（无验证）"
                    return

            time.sleep(1)

        yield f"[NAV] 进入 {target} 失败"

    # ==================== 弹窗处理 ====================

    def handle_popup(self, popup_type: str) -> bool:
        """
        处理确认弹窗

        Args:
            popup_type: 弹窗类型，如 "联队战道具", "远征确认", "内番确认"

        Returns:
            是否处理成功
        """
        popup_config = self.config.get("popup", {}).get(popup_type)
        if not popup_config:
            print(f"[ERROR] 未知弹窗类型: {popup_type}")
            return False

        # 联队战道具特殊处理
        if popup_type == "联队战道具":
            # 使用三倍枡
            triple = popup_config["triple"]
            self._click_point(triple["target"])
            time.sleep(0.3)

            # 检查是否勾选成功
            check_roi_raw = triple["check_roi"]
            check_roi = roi_4to4(check_roi_raw[0], check_roi_raw[1],
                                 check_roi_raw[2], check_roi_raw[3])
            if not self.maa.exists(popup_config["check_template"], check_roi):
                print("[POPUP] 三倍枡可能已用完")

        # 点击确定
        if "confirm" in popup_config:
            self._click_template_config(popup_config["confirm"])

        return True
