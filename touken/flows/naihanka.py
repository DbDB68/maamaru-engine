# -*- coding: utf-8 -*-
"""
上层业务：内番（日课，安全无消耗）

流程（教材原文）：
  目录 → 内番 → 内番开始 → 二次确认点确定
  → 内番开始动画/对话 → 跳过 → 可能弹"内番符"氪金加速（不准用，点取消）
  → 回到内番界面，右下角出现"内番中" = 完工

教材补充：
  - 完工标志也可以是"目录界面的内番没有角标"
  - 如果内番已经在跑（没有内番开始按钮，直接看到内番中），跳过不重复开始
"""

import time

from ..maa_adapter import roi_4to4


class NaihankaMixin:
    """内番流程。依赖宿主类的 navigate_to_stream、_click_point。"""

    def naihanka_stream(self):
        """
        流式开始内番

        Yields:
            str: 执行状态消息
        """
        cfg = self.config.get("naihanka", {})
        if not cfg:
            yield "[内番] 未配置内番"
            return

        # ========== 1. 导航到内番 ==========
        yield "[内番] 正在导航到内番..."
        for nav_msg in self.navigate_to_stream("内番"):
            yield nav_msg
        if self.current_location != "内番":
            yield "[内番] 到达内番失败"
            return

        # ========== 2. 判断状态：已在跑 or 可以开始 ==========
        time.sleep(1.0)
        self.maa.screenshot(force=True)

        marker_cfg = cfg["running_marker"]
        marker_roi = roi_4to4(*marker_cfg["roi"]) if "roi" in marker_cfg else None
        if self.maa.template_match(marker_cfg["template"], marker_roi):
            yield "[内番] 已经在内番中了，今天不用开始，收工"
            return

        start = self.maa.template_match(cfg["start_button"]["template"])
        if not start:
            yield "[内番] 既没看到内番开始按钮也没看到内番中标记，画面不对劲，停"
            return

        # ========== 3. 点开始 + 二次确认 ==========
        self.maa.click(start)
        time.sleep(1.0)

        confirmed = False
        for _ in range(10):
            self.maa.screenshot(force=True)
            confirm = self.maa.template_match(cfg["confirm_button"]["template"])
            if confirm:
                self.maa.click(confirm)
                confirmed = True
                break
            time.sleep(0.5)
        if not confirmed:
            yield "[内番] 二次确认弹窗没出现，停"
            return
        yield "[内番] 已确认开始，进入跳动画阶段"
        time.sleep(1.0)

        # ========== 4. 跳动画/对话，防内番符氪金弹窗 ==========
        for skip_msg in self.skip_dialogue_stream():
            yield skip_msg
        return

    # ---------- 对话跳过（独立公开，卡在对话里能单独救场）----------

    def skip_dialogue_stream(self):
        """
        跳过内番对话/动画，直到真正回到内番界面（标题 + 内番中标记）。

        防踩坑：点完确定后、对话开始前，内番界面会短暂闪现（内番中标记也在），
        此时判完工会被对话卡住——所以必须"见过画面离开内番界面"（对话发生过）
        或确认超过 10 秒，才接受完工判定。
        """
        cfg = self.config.get("naihanka", {})
        marker_cfg = cfg["running_marker"]
        marker_roi = roi_4to4(*marker_cfg["roi"]) if "roi" in marker_cfg else None
        title_template = cfg["ui_title"]["template"]

        confirm_time = time.time()
        dialogue_seen = False

        for _ in range(60):  # 安全上限
            self.maa.screenshot(force=True)

            # 内番符氪金弹窗 → 教材规矩：不准用，点取消
            cancel = self.maa.template_match(cfg["cancel_button"]["template"])
            if cancel:
                self.maa.click(cancel)
                yield "[内番] 检测到内番符弹窗，已点取消（咱不氪这个）"
                time.sleep(1.0)
                continue

            # 画面离开了内番界面 = 对话/动画正在演
            title_visible = self.maa.template_match(title_template)
            if not title_visible:
                dialogue_seen = True

            # 完工标志：回到内番界面 + 右下角内番中
            if title_visible and self.maa.template_match(marker_cfg["template"], marker_roi):
                elapsed = time.time() - confirm_time
                if dialogue_seen or elapsed > 10:
                    yield "[内番] 内番开始成功，收工 🎉"
                    # 落盘开工时间，看板显示"内番中·已跑X小时"（写砸不影响）
                    try:
                        import json as _json
                        from pathlib import Path as _P
                        d = _P(__file__).resolve().parent.parent.parent / "status"
                        d.mkdir(exist_ok=True)
                        (d / "naihanka.json").write_text(_json.dumps(
                            {"started_at": time.strftime("%Y-%m-%d %H:%M:%S")},
                            ensure_ascii=False), encoding="utf-8")
                    except Exception:
                        pass
                    return

            self._click_point(cfg["skip_tap"])
            time.sleep(0.8)

        yield "[内番] ⚠️ 跳动画超过安全上限还没看到内番中，你去看看卡哪了"
        return
