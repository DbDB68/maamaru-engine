# -*- coding: utf-8 -*-
"""
上层业务：出阵（合战场）——自动行军版

流程（教材 + 旧脚本思路）：
  出阵 → 合战场选章节（固定坐标）→ 决定 → 地域选择 → 选小图（固定坐标）
  → 部队选择 → 选部队 → （可选）委托自动行军
  → 【重伤检查】有重伤绝不出阵
  → 即刻出阵 → 分支：刀装警告停 / 队员重伤点否停 / 进入行军
  → 自动行军打完自动回本丸；行军中断（中伤）→ 返回本丸

教材安全规矩（写死，不商量）：
  - 只要有重伤就绝对不能出阵（会碎刀）
  - 刀装未满：没要求自动补充就停脚本上报
  - 战斗内发现重伤（自动行军停止）：直接返回本丸
  - 队员重伤确认弹窗：永远点"否"

备注：章节/小图坐标是老配置里估的，首次用新章节前要实测校准。
"""

import time

from ..maa_adapter import roi_4to4


class SortieMixin:
    """合战场出阵。依赖宿主类的 navigate_to_stream、_click_point、_enable_auto_march。"""

    def sortie_stream(self, chapter: int, map_no: int, team_no: int = 3,
                      auto_march: bool = True, max_loops: int = 1,
                      formation_mode: str = "manual",
                      formation_strategy: str = "fixed",
                      formation: str = "鱼鳞阵",
                      repair_threshold: str = "light",
                      injury_action: str = "continue"):
        """
        流式跑合战场

        Args:
            chapter: 章节编号（1-8，对应 map_select.合战场.chapters）
            map_no: 小图编号（1-4，对应 map_select.合战场.maps）
            team_no: 部队编号
            auto_march: 是否委托自动行军（True=全自动打完一圈回本丸）
            max_loops: 连续打几圈
            repair_threshold: 自动手入阈值（light / medium / heavy）

        Yields:
            str: 执行状态消息
        """
        cfg = self.config.get("sortie", {})
        if not cfg:
            yield "[出阵] 未配置合战场"
            return

        map_cfg = self.config.get("map_select", {}).get("合战场", {})
        teams = self.config.get("team_select", {}).get("teams", {})
        if str(chapter) not in map_cfg.get("chapters", {}):
            yield f"[出阵] 配置里没有章节{chapter}的坐标"
            return
        if str(map_no) not in map_cfg.get("maps", {}):
            yield f"[出阵] 配置里没有小图{map_no}的坐标"
            return
        if str(team_no) not in teams:
            yield f"[出阵] 配置里没有部队{team_no}的坐标"
            return

        # ========== 1. 导航到出阵（默认就在合战场） ==========
        yield "[出阵] 正在导航到出阵..."
        for nav_msg in self.navigate_to_stream("出阵"):
            yield nav_msg
        if self.current_location != "出阵":
            yield "[出阵] 到达出阵失败"
            return

        loop_no = 1
        repair_attempts = 0
        while loop_no <= max_loops:
            if self.current_location != "出阵":
                for nav_msg in self.navigate_to_stream("出阵"):
                    yield nav_msg
                if self.current_location != "出阵":
                    yield "[出阵] 重新进入出阵失败，停止"
                    return
            yield f"[出阵] ⚔️ 第 {loop_no}/{max_loops} 圈：{chapter}章-{map_no}图，部队{team_no}准备上场"

            # ========== 2. 选章节 → 决定 ==========
            self._click_point(map_cfg["chapters"][str(chapter)])
            time.sleep(0.5)
            self.maa.screenshot(force=True)
            decide = self.maa.template_match(cfg["decide_button"]["template"])
            if decide:
                self.maa.click(decide)
                time.sleep(1.5)

            # ========== 3. 等地域选择 → 选小图 ==========
            area_ok = False
            for _ in range(10):
                self.maa.screenshot(force=True)
                if self.maa.template_match(cfg["area_select_ui"]["template"]):
                    area_ok = True
                    break
                time.sleep(0.5)
            if not area_ok:
                yield "[出阵] 地域选择界面没出现（章节坐标不对？），本圈放弃"
                continue
            self._click_point(map_cfg["maps"][str(map_no)])
            time.sleep(1.0)

            # ========== 4. 部队选择 → 选部队 ==========
            # 合战场点完小图会【直接】进部队选择界面，没有中间按钮；
            # 但保险起见：没在部队选择界面时才去找"部队选择"按钮点
            ocr_cfg = cfg["team_ui_ocr"]
            roi = roi_4to4(*ocr_cfg["roi"])
            team_ui_ok = False
            for attempt in range(12):
                self.maa.screenshot(force=True)
                if self.maa.ocr(expected=ocr_cfg["expected"], roi=roi):
                    team_ui_ok = True
                    break
                # 第 3 次还没进，试着找部队选择按钮点一下（兼容其他入口）
                if attempt == 2:
                    deploy = self.maa.template_match(cfg["deploy_button"]["template"])
                    if deploy:
                        self.maa.click(deploy)
                        time.sleep(1.5)
                time.sleep(0.5)
            if not team_ui_ok:
                yield "[出阵] 部队选择界面没打开，本圈放弃"
                continue

            self._click_point(teams[str(team_no)])
            time.sleep(0.3)
            self._click_point(teams[str(team_no)])
            time.sleep(0.5)

            # ========== 5. 【保命】重伤检查（先于一切出阵准备） ==========
            self.maa.screenshot(force=True)
            injury = self._team_injury_status(cfg)
            if injury:
                threshold = str(repair_threshold or "light")
                severity_rank = {"轻伤": 1, "中伤": 2, "重伤": 3}
                threshold_rank = {"light": 1, "medium": 2, "heavy": 3}.get(threshold, 1)
                must_repair = injury == "重伤"
                if not must_repair and severity_rank.get(injury, 3) < threshold_rank:
                    yield f"[出阵] 部队{team_no}{injury}，尚未达到手入阈值，继续本圈"
                    injury = None
            if injury:
                must_repair = injury == "重伤"
                action = str(injury_action or "continue")
                if action in ("true", "1"):
                    action = "continue"
                elif action in ("false", "0"):
                    action = "stop"
                if not must_repair and action == "stop":
                    yield f"[出阵] 检测到部队{team_no}{injury}；自动手入已关闭，本次收工"
                    return
                # 重伤必须尝试手入；即便用户选择“不手入”，也改为普通手入后收工。
                repair_and_stop = action == "repair_stop" or (must_repair and action == "stop")
                suffix = "，不用加速符，手入后收工" if repair_and_stop else "，转去手入后重试本圈"
                yield f"[出阵] 检测到部队{team_no}{injury}{suffix}"
                for repair_msg in self.repair_stream(
                        dry_run=False,
                        use_speedup=False if repair_and_stop else None,
                        # 继续原定出阵时，本次出阵队必须即时修好；
                        # 手入列表里的其他队仍会送修，但不会使用加速符。
                        speedup_teams=None if repair_and_stop else [team_no]):
                    yield repair_msg
                if repair_and_stop:
                    yield "[出阵] 已安排手入（黑名单已跳过、未使用加速符），本次收工"
                    return
                repair_attempts += 1
                if repair_attempts >= 2:
                    yield "[出阵] 手入后仍检测到伤势（可能是黑名单或未加速成员），停止"
                    return
                continue

            # ========== 6. 可选：委托自动行军 ==========
            if auto_march:
                self._enable_auto_march()
                time.sleep(0.5)

            # ========== 7. 即刻出阵 → 分支 ==========
            depart = self.maa.template_match(cfg["depart_button"]["template"])
            if not depart:
                yield "[出阵] 找不到即刻出阵按钮（队长重伤会变灰？），停"
                return
            self.maa.click(depart)
            time.sleep(1.5)

            self.maa.screenshot(force=True)

            # 刀装未满警告 → 安全取消整备，给后续日课让路
            equip_cancelled = self._cancel_equip_warning(cfg)
            if equip_cancelled is not None:
                if equip_cancelled:
                    yield "[出阵] ⚠️ 刀装未满警告；已取消出阵并返回部队选择，本次跳过"
                else:
                    yield "[出阵] ⚠️ 刀装未满警告；没能安全取消整备，本次出阵停止"
                return

            # 队员重伤确认弹窗 → 教材规矩：永远点"否"
            deny = self.maa.template_match(cfg["injury_deny_button"]["template"])
            if deny:
                self.maa.click(deny)
                yield "[出阵] 🛑 队员重伤确认弹窗，已点【否】。有重伤绝不出阵，停"
                return

            yield f"[出阵] 🐎 部队{team_no}出发！行军监控开着呢，我全程盯着"

            # ========== 8. 行军监控：打完自动回本丸 / 中断则返回本丸 ==========
            march_done = False
            interrupted = False
            for _ in range(300):  # 安全上限
                self.maa.screenshot(force=True)

                # 阵形选择蹦出来（没委托上自动行军时会问）：选一个再继续
                # ——刷花实测卡死在这的教训
                fcfg = self.config.get("formation", {})
                fv = fcfg.get("verify", {})
                if fv and self.maa.exists(fv["template"], roi_4to4(*fv["roi"])):
                    if auto_march:
                        yield "[出阵] ⚠️ 已选自动行军但仍出现阵形页，按兜底阵形继续"
                    result = self.choose_formation(
                        strategy=formation_strategy,
                        formation_name=formation,
                        enable_auto=formation_mode == "auto",
                    )
                    chosen = "有利阵形" if result == "advantage" else formation
                    yield f"[出阵] 🛡️ 已选择「{chosen}」继续"
                    # 阵形确认后的转场略慢；等页面真正消失，避免下一轮重复点阵。
                    for _ in range(8):
                        time.sleep(0.4)
                        self.maa.screenshot(force=True)
                        if not self.maa.exists(
                                fv["template"], roi_4to4(*fv["roi"])):
                            break
                    continue

                # 手动行军决策屏（委托没挂上时每个节点都问）：点"行军"继续
                # ——刷花实测：_enable_auto_march 会静默失败，不能全指望委托
                if self.maa.ocr("行军", roi_4to4(1080, 550, 1215, 680)):
                    field_injury = self._team_injury_status(cfg)
                    if field_injury and self._injury_reaches_threshold(
                            field_injury, repair_threshold):
                        yield f"[出阵] 🩹 局内检测到{field_injury}，已达到手入阈值，不再继续行军"
                        if not self._return_home_from_march(cfg):
                            yield "[出阵] 找不到返回本丸按钮，停止点击，等你手动处理"
                            return
                        interrupted = True
                        break
                    yield "[出阵] 🚩 岔路口问我话呢，点「行军」继续"
                    self._click_point([1146, 617])
                    time.sleep(1.0)
                    continue

                # 打完一圈自动回本丸
                if self.maa.template_match(cfg["home_ui"]["template"]):
                    march_done = True
                    break

                # 行军停止（中伤等）→ 判定依据是"自动行军停止"横幅（OCR），
                # 不是返回本丸按钮——那玩意在行军区常驻，点了就是手动撤退
                stop_ocr = cfg["march_stop_ocr"]
                stop_roi = roi_4to4(*stop_ocr["roi"])
                if self.maa.ocr(expected=stop_ocr["expected"], roi=stop_roi):
                    yield "[出阵] ⚠️ 检测到自动行军停止横幅"
                    if not self._return_home_from_march(cfg):
                        yield "[出阵] 找不到返回本丸按钮，停止点击，等你手动处理"
                        return
                    interrupted = True
                    break

                # 安全区跳动画
                self._click_point(cfg["skip_tap"])
                time.sleep(0.8)

            if march_done:
                yield f"[出阵] ✓ 第 {loop_no} 圈凯旋！已回本丸"
                self.current_location = "本丸"
                repair_attempts = 0
                loop_no += 1
            elif interrupted:
                yield "[出阵] ⚠️ 行军因伤势中断，已返回本丸；重新检查轻/中/重伤"
                self.current_location = "本丸"
                continue
            else:
                yield "[出阵] ⚠️ 行军监控超过安全上限，强制停，你去看看卡哪了"
                return

        yield f"[出阵] ✓ 全部 {max_loops} 圈跑完，部队{team_no}辛苦啦，收工！"
        return

    @staticmethod
    def _injury_reaches_threshold(injury: str, threshold: str) -> bool:
        severity_rank = {"轻伤": 1, "中伤": 2, "重伤": 3}
        threshold_rank = {"light": 1, "medium": 2, "heavy": 3}.get(
            str(threshold or "light"), 1)
        return severity_rank.get(injury, 3) >= threshold_rank

    def _return_home_from_march(self, cfg) -> bool:
        """在行军选择/停止画面安全返回本丸，并等待本丸真正出现。"""
        stop_btn = None
        for _ in range(6):
            self.maa.screenshot(force=True)
            stop_btn = self.maa.template_match(cfg["march_stop_button"]["template"])
            if stop_btn:
                break
            time.sleep(0.5)
        if not stop_btn:
            return False
        self.maa.click(stop_btn)
        time.sleep(1.5)
        self.maa.screenshot(force=True)
        yes = self.maa.template_match(cfg["return_home_confirm"]["template"])
        if yes:
            self.maa.click(yes)
        time.sleep(2.0)
        for _ in range(15):
            self.maa.screenshot(force=True)
            if self.maa.template_match(cfg["home_ui"]["template"]):
                return True
            time.sleep(0.8)
        return False

    def _team_injury_status(self, cfg):
        """在部队选择页识别最高伤势；重伤模板与文字 OCR 双保险。"""
        stamps = cfg.get("injury_stamps", {})
        for severity in ("重伤", "中伤", "轻伤"):
            stamp = stamps.get(severity, {})
            template = stamp.get("template")
            if template and self.maa.template_match(template):
                return severity
        # 兼容尚未升级 injury_stamps 的旧配置。
        if not stamps and self.maa.template_match(cfg["injury_stamp"]["template"]):
            return "重伤"
        roi = roi_4to4(*cfg.get("injury_status_roi", [0, 90, 1280, 560]))
        for severity in ("重伤", "中伤", "轻伤"):
            if self.maa.ocr(severity, roi):
                return severity
        return None
