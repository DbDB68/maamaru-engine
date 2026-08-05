# -*- coding: utf-8 -*-
"""
上层业务：联队战（限时活动，专用流程，别抄去别的地方）

流程（教材 + 旧 raid.json 思路）：
  本丸 → 目录 → 出阵 → 活动 → 联队战界面 → 选难度（固定坐标）
  → 部队选择 → 选部队（固定坐标点两下）→ 即刻出阵
  → 确认弹窗（可选三倍枡）→ 确定
  → 战斗循环：安全区点击跳动画 + OCR"战斗"按钮连点
  → 回到联队战界面 = 一圈结束

安全说明：
  - 联队战每场血量重置，无碎刀风险
  - 刀装未满警告（继续出阵/整备刀装弹窗）按教材规矩：停下上报，不擅自动
  - 手形不足自动补充（补充→恢复1个→确定）：补充.png 没截到，
    暂用 OCR 识别"补充"二字，标记【未实测】，等真没票了再验证
"""

import time

from ..maa_adapter import roi_4to4


class RaidMixin:
    """联队战流程。依赖宿主类的 navigate_to_stream、_click_point。"""

    def raid_stream(self, max_rounds: int = 1, team_no: int = None,
                    use_triple: bool = True, max_buys: int = None):
        """
        流式跑联队战

        Args:
            max_rounds: 跑几圈（一圈 = 选难度到回到联队战界面）
            team_no: 部队编号，默认读配置 raid.team_no
            use_triple: 是否在确认弹窗勾三倍枡（已勾选会跳过，游戏有记忆）
            max_buys: 本次最多小判买几次手形（加班模式用），
                      不给就读配置 raid.max_buys_per_run

        Yields:
            str: 执行状态消息
        """
        cfg = self.config.get("raid", {})
        if not cfg:
            yield "[RAID] 未配置联队战"
            return
        if max_buys is not None:
            cfg = dict(cfg)
            cfg["max_buys_per_run"] = max_buys

        team_no = team_no or cfg.get("team_no", 3)
        teams = self.config.get("team_select", {}).get("teams", {})
        if str(team_no) not in teams:
            yield f"[RAID] 配置里没有部队{team_no}的坐标"
            return

        self._ticket_buys = 0  # 本次运行的小判买票计数

        # ========== 1. 导航到出阵 ==========
        yield "[RAID] 正在导航到出阵..."
        for nav_msg in self.navigate_to_stream("出阵"):
            yield nav_msg
        if self.current_location != "出阵":
            yield "[RAID] 到达出阵失败"
            return

        # ========== 2. 进入联队战界面 ==========
        # 点"活动"按钮，等 ui陆联 标题出现（可能已经在联队战界面，那就直接过）
        entered = False
        for _ in range(6):
            self.maa.screenshot(force=True)
            if self.maa.template_match(cfg["ui_title"]["template"]):
                entered = True
                break
            entry = self.maa.template_match(cfg["activity_entry"]["template"])
            if entry:
                self.maa.click(entry)
                time.sleep(2.0)
            else:
                time.sleep(1.0)
        if not entered:
            yield "[RAID] 进不去联队战界面（活动结束了？）"
            return
        yield "[RAID] 到达联队战界面"
        # 上报仪表盘：陆联还是海联。现在只截了 ui陆联，所以必为陆联；
        # 以后有海联标题模板后，在这里加分支写 "raid:hailian" 即可
        self.set_progress("raid:lulian")

        # ========== 3. 逐圈跑 ==========
        for round_no in range(1, max_rounds + 1):
            yield f"[RAID] ===== 第 {round_no}/{max_rounds} 圈 ====="

            # 3.1 选难度（固定坐标，教材指定图4-乱）
            self._click_point(cfg["difficulty_target"])
            time.sleep(0.8)

            # 3.2 点"部队选择"，OCR 验证标题
            deploy = self.maa.template_match(cfg["deploy_button"]["template"])
            if not deploy:
                yield "[RAID] 找不到部队选择按钮，本圈放弃"
                continue
            self.maa.click(deploy)
            time.sleep(1.5)

            ocr_cfg = cfg["team_ui_ocr"]
            roi = roi_4to4(*ocr_cfg["roi"])
            team_ui_ok = False
            for _ in range(10):
                self.maa.screenshot(force=True)
                if self.maa.ocr(expected=ocr_cfg["expected"], roi=roi):
                    team_ui_ok = True
                    break
                time.sleep(0.5)
            if not team_ui_ok:
                yield "[RAID] 部队选择界面没打开，本圈放弃"
                continue

            # 3.3 选部队（固定坐标，点两下确认）
            self._click_point(teams[str(team_no)])
            time.sleep(0.3)
            self._click_point(teams[str(team_no)])
            time.sleep(0.5)

            # 3.4 点"即刻出阵"
            depart = self.maa.template_match(cfg["depart_button"]["template"])
            if not depart:
                yield "[RAID] 找不到即刻出阵按钮，本圈放弃"
                continue
            self.maa.click(depart)
            time.sleep(1.5)

            # 3.5 出阵后的分支：刀装警告 / 确认弹窗 / 手形不足
            self.maa.screenshot(force=True)

            # 刀装未满警告 → 教材规矩：停下上报
            if self.maa.template_match(cfg["equip_warning_button"]["template"]):
                yield "[RAID] ⚠️ 刀装未满警告！按规矩停下来了，你去游戏里看一眼要不要补刀装"
                return

            # 手形不足弹窗 → 按配置决定买不买
            if not self.maa.template_match(cfg["confirm_ui"]["template"]):
                rec_cfg = cfg["ticket_recover"]
                if not self.maa.template_match(rec_cfg["popup_button"]["template"]):
                    yield "[RAID] 既没确认弹窗也没补充弹窗，卡在未知画面，停"
                    return

                buys = getattr(self, "_ticket_buys", 0)
                max_buys = cfg.get("max_buys_per_run", 10)
                if not cfg.get("auto_buy_ticket", False) or buys >= max_buys:
                    reason = "配置不自动买" if not cfg.get("auto_buy_ticket", False) else f"本次已买 {buys} 次到上限"
                    yield f"[RAID] 手形耗尽（{reason}），点关闭收工"
                    close = self.maa.template_match(rec_cfg["close_button"]["template"])
                    if close:
                        self.maa.click(close)
                    return

                yield f"[RAID] 手形不足，小判自动补充（本次第 {buys + 1} 次买）..."
                for rec_msg in self._recover_ticket_stream(cfg):
                    yield rec_msg
                if not self._recover_ok:
                    yield "[RAID] 手形补充失败，停"
                    return
                self._ticket_buys = buys + 1

                # 补充完重新点即刻出阵
                depart = self.maa.template_match(cfg["depart_button"]["template"])
                if depart:
                    self.maa.click(depart)
                    time.sleep(1.5)
                self.maa.screenshot(force=True)
                if not self.maa.template_match(cfg["confirm_ui"]["template"]):
                    yield "[RAID] 补充手形后还是没看到确认弹窗，停"
                    return

            # 3.6 确认弹窗：勾三倍枡（游戏有记忆，已勾会跳过）→ 确定
            if use_triple:
                tri = cfg["triple"]
                check_roi = roi_4to4(*tri["check_roi"])
                self.maa.screenshot(force=True)
                if self.maa.template_match(tri["check_template"], check_roi):
                    yield "[RAID] 三倍枡已勾选，跳过"
                else:
                    self._click_point(tri["click"])
                    time.sleep(0.3)
                    yield "[RAID] 已勾三倍枡"

            confirm_cfg = cfg["confirm_button"]
            confirm_roi = roi_4to4(*confirm_cfg["roi"]) if "roi" in confirm_cfg else None
            confirm = self.maa.template_match(confirm_cfg["template"], confirm_roi)
            if not confirm:
                yield "[RAID] 找不到确认弹窗的确定按钮，本圈放弃"
                continue
            self.maa.click(confirm)
            time.sleep(2.0)
            yield "[RAID] 出发，进入战斗循环"

            # 3.7 战斗循环：安全区跳动画 + OCR"战斗"连点，回联队战界面 = 一圈完
            for battle_msg in self.battle_loop_stream():
                yield battle_msg
            round_done, battles = self._battle_loop_result

            if round_done:
                yield f"[RAID] 第 {round_no} 圈结束，打了 {battles} 场"
            else:
                yield f"[RAID] ⚠️ 战斗循环超过安全上限，强制停（打了 {battles} 场），你去看看卡哪了"
                return

        yield "[RAID] 全部圈数跑完，收工"
        return

    # ---------- 战斗循环（独立公开，中途断线也能单独恢复）----------

    _battle_loop_result: tuple = (False, 0)

    def battle_loop_stream(self, cfg_key: str = "raid", tag: str = "[RAID]",
                           need_battle: bool = True, debug_dir: str = None):
        """
        战斗循环：OCR"战斗"连点下一场，安全区跳动画，回到活动界面算一圈完。
        结果放在 self._battle_loop_result = (是否完成, 打了几场)。

        出发后有短暂的过场，活动标题还留在屏幕上，
        此时一圈结束判定会误命中——冷静期内不判结束。

        cfg_key: 读哪段配置（raid / pumpkin 共用本循环）
        tag: 日志前缀
        need_battle: True=至少打过1场才算结束（联队战，防过场误命中）；
                     False=全自动战斗的活动（南瓜），靠冷静期就够
        debug_dir: 调试截图目录，给了就把每帧存下来（抓获得动画用）
        """
        cfg = self.config.get(cfg_key, {})
        battles = 0
        round_done = False
        end_cfg = cfg["round_end"]
        # roi 可留空：有的模板（RGBA 的 ui南瓜）在 MAA 的 roi 匹配下会神秘不中，
        # 全屏 + 高阈值一样稳，标题本身够独特
        end_roi = roi_4to4(*end_cfg["roi"]) if end_cfg.get("roi") else None
        battle_cfg = cfg["battle_ocr"]
        battle_roi = roi_4to4(*battle_cfg["roi"])

        if debug_dir:
            from pathlib import Path as _P
            _P(debug_dir).mkdir(parents=True, exist_ok=True)
        debug_idx = 0

        battle_loop_start = time.time()
        END_CHECK_GRACE_SEC = 20

        for _i in range(300):  # 安全上限，防死循环
            # 心跳日志：每 5 次报一次进度，卡死时能看到日志停在哪
            if _i % 5 == 0:
                yield f"{tag} 战斗循环心跳 {_i}/300（已打 {battles} 场）"
            self.maa.screenshot(force=True)

            if debug_dir:
                debug_idx += 1
                self.maa.save_screenshot(f"{debug_dir}/f{debug_idx:03d}.png", force=False)

            # 继续下一场？（右下角"战斗"按钮）
            battle_btn = self.maa.ocr(expected=battle_cfg["expected"], roi=battle_roi)
            if battle_btn:
                battles += 1
                yield f"{tag} 第 {battles} 场"
                self.maa.click(battle_btn)
                time.sleep(3.0)
                continue

            # 一圈结束？（活动标题回到屏幕上，高阈值防战斗中误认）
            if (battles >= 1 or not need_battle) and time.time() - battle_loop_start > END_CHECK_GRACE_SEC:
                if self.maa.template_match(end_cfg["template"], end_roi, end_cfg["threshold"]):
                    round_done = True
                    break

            # 都不是 → 点安全区跳对话/动画
            self._click_point(cfg["skip_tap"])
            time.sleep(0.8)

        self._battle_loop_result = (round_done, battles)

    # ---------- 手形补充（模板已就位）----------

    _recover_ok: bool = False

    def _recover_ticket_stream(self, cfg: dict):
        """
        手形不足：补充（模板）→ 恢复1个（模板）→ 确定（模板）
        会消耗小判，调用方负责计数和上限。
        结果放在 self._recover_ok。
        """
        self._recover_ok = False
        rec_cfg = cfg["ticket_recover"]

        # 点"补充"
        self.maa.screenshot(force=True)
        buchong = self.maa.template_match(rec_cfg["popup_button"]["template"])
        if not buchong:
            yield "[RAID] 找不到补充按钮"
            return
        self.maa.click(buchong)
        time.sleep(1.5)

        # 点"恢复1个"
        self.maa.screenshot(force=True)
        recover = self.maa.template_match(rec_cfg["recover_button"]["template"])
        if not recover:
            yield "[RAID] 找不到恢复1个按钮"
            return
        self.maa.click(recover)
        time.sleep(1.5)

        # 点恢复完毕的"确定"
        self.maa.screenshot(force=True)
        ok = self.maa.template_match(rec_cfg["confirm_button"]["template"])
        if not ok:
            yield "[RAID] 找不到恢复完毕的确定按钮"
            return
        self.maa.click(ok)
        time.sleep(2.0)

        self._recover_ok = True
        yield "[RAID] 手形补充完成"
