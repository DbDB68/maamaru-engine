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
                    use_triple: bool = True, max_buys: int = None,
                    difficulty_no: int = 4, auto_buy_ticket: bool = None):
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
        if auto_buy_ticket is not None:
            cfg = dict(cfg)
            cfg["auto_buy_ticket"] = bool(auto_buy_ticket)

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

            # 3.1 选难度。旧配置只有图4坐标；其他图未标定时安全停止。
            targets = cfg.get("difficulty_targets", {})
            target = targets.get(str(difficulty_no))
            if target is None and difficulty_no == 4:
                target = cfg.get("difficulty_target")
            if target is None:
                yield f"[RAID] 联队战{difficulty_no}图坐标尚未配置，本次不出阵"
                return
            self._click_point(target)
            time.sleep(0.8)

            # 3.2 点"部队选择"，OCR 验证标题
            deploy = self._find_deploy_button(cfg)
            if not deploy:
                yield "[RAID] 找不到部队选择按钮，本圈放弃"
                continue
            self.maa.click(deploy)
            time.sleep(1.5)

            if not self._wait_for_team_select(cfg, attempts=10):
                yield "[RAID] 部队选择界面没打开，本圈放弃"
                continue

            # 3.3 选部队（固定坐标，点两下确认）
            self._pick_team(team_no)

            # 3.4 点"即刻出阵"
            if not self._click_depart(cfg):
                yield "[RAID] 找不到即刻出阵按钮，本圈放弃"
                continue

            # 3.5 出阵后的分支：刀装警告 / 确认弹窗 / 手形不足
            self.maa.screenshot(force=True)

            # 刀装未满警告 → 安全取消整备，给后续日课让路
            equip_cancelled = self._cancel_equip_warning(cfg)
            if equip_cancelled is not None:
                if equip_cancelled:
                    yield "[RAID] ⚠️ 刀装未满警告；已取消出阵并返回部队选择，本次跳过"
                else:
                    yield "[RAID] ⚠️ 刀装未满警告；没能安全取消整备，本次出阵停止"
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
                for rec_msg in self._recover_ticket_stream(cfg, tag="[RAID]"):
                    yield rec_msg
                if not self._recover_ok:
                    yield "[RAID] 手形补充失败，停"
                    return
                self._ticket_buys = buys + 1
                # 当前没有同源画面证据能确认这套 UI 的实际小判金额；先保留
                # “确实补过票”的玩法事实，等活动开放实测后再接标准流水。
                self._record_ticket_refill(cfg, "[RAID]")

                # 补充完重新点即刻出阵
                self._click_depart(cfg)
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
                if hasattr(self, "record_event"):
                    self.record_event("raid.round_completed",
                                      difficulty=difficulty_no,
                                      sequence=round_no, battles=battles,
                                      triple=bool(use_triple))
                yield f"[RAID] 第 {round_no} 圈结束，打了 {battles} 场"
            else:
                yield f"[RAID] ⚠️ 战斗循环超过安全上限，强制停（打了 {battles} 场），你去看看卡哪了"
                return

        yield "[RAID] 全部圈数跑完，收工"
        return

    # ---------- 战斗循环（独立公开，中途断线也能单独恢复）----------

    _battle_loop_result: tuple = (False, 0)

    def battle_loop_stream(self, cfg_key: str = "raid", tag: str = "[RAID]",
                           need_battle: bool = True, debug_dir: str = None,
                           fought: int = None):
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
        fought: 心跳里显示的场数。内部 battles 数的是"点过几次战斗按钮"，
                全自动战斗（南瓜）永远点不到按钮、恒为 0，会吓人，
                所以全自动模式由外层把已出阵次数传进来显示。
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
            # 场数显示：全自动战斗（南瓜）内部 battles 恒 0，用外层传的 fought
            if _i % 5 == 0:
                shown = fought if fought is not None else battles
                yield f"{tag} 战斗循环心跳 {_i}/300（已打 {shown} 场）"
                self.quick_peek(tag=cfg_key)  # 顺路拍顶栏家底，零导航（60s 节流）
            self.maa.screenshot(force=True)

            if debug_dir:
                debug_idx += 1
                self.maa.save_screenshot(f"{debug_dir}/f{debug_idx:03d}.png", force=False)

            # 网络超时弹窗（MuMu 断网）：点确定没用就重启模拟器续打
            net = yield from self.recover_network_stream()
            if net is None:
                yield f"{tag} ⚠️ 断网恢复失败，战斗循环安全停止（已打 {battles} 场）"
                break
            if net == "home":
                yield f"{tag} ⚠️ 断网恢复后落在本丸，这一圈打到哪不明，安全停止（已打 {battles} 场）"
                break
            if net == "resumed":
                battle_loop_start = time.time()  # 续打回来重新给冷静期
                continue

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
