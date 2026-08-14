# -*- coding: utf-8 -*-
"""
上层业务：登录流程
（从 touken_agent_engine_v2.py 原样搬家，逻辑未改）
"""

import time

from ..maa_adapter import roi_4to4


class LoginMixin:
    """登录流程。依赖宿主类的 _click_template_config（见 navigator.py）。"""

    UPDATE_TEXT_ROI = roi_4to4(300, 180, 980, 410)
    UPDATE_CONFIRM_ROI = roi_4to4(430, 400, 850, 560)
    UPDATE_LINE_ROI = roi_4to4(160, 240, 1120, 650)

    def _game_update_prompt_visible(self) -> bool:
        """只在更新正文明确出现时才允许点弹窗，避免把普通「确定」误点掉。"""
        results = self.maa.ocr_all(self.UPDATE_TEXT_ROI)
        text = "".join(str(item[0]) for item in results if item)
        return "检测到更新" in text and ("重新启动" in text or "进行更新" in text)

    def recover_game_update_stream(self, timeout: int = 1800):
        """处理运行途中强制更新，并等到重新落回本丸。

        返回 True 表示确实处理了一次更新；False 表示当前并非更新弹窗；
        None 表示识别到了更新，但未能在限时内恢复。调用方在 True 后必须从
        玩法入口重来，不能沿用更新前的画面状态继续点击。
        """
        if not self._game_update_prompt_visible():
            return False

        yield "[更新] 检测到游戏强制更新，暂停当前玩法"
        confirm = self.maa.template_match(
            "通用_确定.png", roi=self.UPDATE_CONFIRM_ROI, threshold=0.7)
        if not confirm:
            confirm = self.maa.ocr("确定", self.UPDATE_CONFIRM_ROI,
                                   match_mode="exact")
        if not confirm:
            yield "[更新] 看到了更新提示，但没能安全找到【确定】，停止点击"
            return None
        self.maa.click(confirm)
        time.sleep(2.0)

        deadline = time.time() + max(60, int(timeout))
        last_notice = 0.0
        line_selected = False
        while time.time() < deadline:
            self.maa.screenshot(force=True)

            # 更新完成后可能先回登录，也可能自动进入本丸。
            if (self.maa.exists("目录.png", threshold=0.7)
                    and not self._game_update_prompt_visible()):
                yield "[更新] ✓ 游戏已更新并重新回到本丸"
                self.current_location = "本丸"
                return True

            login = self.maa.template_match("登录.png", threshold=0.7)
            if login:
                yield "[更新] 登录页已出现，点击登录"
                self.maa.click(login)
                time.sleep(2.0)
                continue

            # 登录后若客户端需要下载资源，会要求选线路。优先线路一；线路一
            # 没识别到才用线路二。点击一次后只等待，避免下载页反复误触。
            if not line_selected:
                line = (self.maa.ocr("线路一", self.UPDATE_LINE_ROI,
                                     match_mode="contains")
                        or self.maa.ocr("线路二", self.UPDATE_LINE_ROI,
                                        match_mode="contains"))
                if line:
                    self.maa.click(line)
                    line_selected = True
                    yield "[更新] 已选择更新线路，等待游戏下载资源（最长 30 分钟）"
                    time.sleep(3.0)
                    continue

            now = time.time()
            if now - last_notice >= 60:
                yield "[更新] 仍在等待更新/登录完成……"
                last_notice = now
            time.sleep(3.0)

        yield "[更新] 等待更新完成超时；当前任务已安全停止，请查看游戏画面"
        return None

    def login(self) -> bool:
        """执行登录流程"""
        login_steps = self.config.get("login", {})

        for step_name, step_config in login_steps.items():
            print(f"\n[LOGIN] 执行: {step_name}")

            if step_config.get("repeat") == "until_gone":
                while True:
                    if "roi" in step_config:
                        roi_raw = step_config["roi"]
                        roi = roi_4to4(roi_raw[0], roi_raw[1], roi_raw[2], roi_raw[3])
                    else:
                        roi = None

                    if not self.maa.exists(step_config["template"], roi):
                        break
                    self._click_template_config(step_config)
                    time.sleep(0.5)
            else:
                self._click_template_config(step_config)
                time.sleep(step_config.get("post_delay", 500) / 1000)

        print("[LOGIN] 登录完成")
        return True
