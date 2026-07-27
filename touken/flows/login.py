# -*- coding: utf-8 -*-
"""
上层业务：登录流程
（从 touken_agent_engine_v2.py 原样搬家，逻辑未改）
"""

import time

from ..maa_adapter import roi_4to4


class LoginMixin:
    """登录流程。依赖宿主类的 _click_template_config（见 navigator.py）。"""

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
