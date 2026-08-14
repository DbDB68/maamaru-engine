# -*- coding: utf-8 -*-
"""大阪城地下活动：从活动入口出阵，并逐层手动行军。"""

import re
import time

from ..maa_adapter import roi_4to4


class OsakaMixin:
    """大阪城挖地流程。依赖导航、共用部队选择和阵形组件。"""

    def osaka_stream(self, max_floors: int = 1, team_no: int = 3,
                     select_floor: bool = False, target_floor: int = 81,
                     formation_mode: str = "manual",
                     formation_strategy: str = "fixed",
                     formation: str = "鱼鳞阵",
                     repair_threshold: str = "light",
                     injury_action: str = "continue",
                     _target_floors: int = None,
                     _completed_floors: int = 0,
                     _repair_count: int = 0,
                     _speedups_used: int = 0):
        if _target_floors is None:
            _target_floors = max_floors
        cfg = self.config.get("osaka", {})
        if not cfg:
            yield "[挖地] 未配置大阪城"
            return
        teams = self.config.get("team_select", {}).get("teams", {})
        if str(team_no) not in teams:
            yield f"[挖地] 配置里没有部队{team_no}的坐标"
            return

        yield "[挖地] 正在从目录进入出阵 → 活动 → 大阪城..."
        for msg in self.navigate_to_stream("出阵"):
            yield msg
        if self.current_location != "出阵":
            yield "[挖地] 到达出阵失败"
            return

        if not self._open_osaka(cfg):
            yield "[挖地] 没找到大阪城活动入口"
            return
        if select_floor:
            target_floor = max(1, min(99, int(target_floor)))
            current_floor = self._read_osaka_floor(cfg)
            if current_floor is None:
                yield "[挖地] 没读到活动页左上角的当前层数，未点击层数箭头"
                return
            yield f"[挖地] 当前选择第 {current_floor} 层，准备切换到第 {target_floor} 层"
            selected_floor = self._select_osaka_floor(cfg, target_floor)
            if selected_floor != target_floor:
                shown = "无法识别" if selected_floor is None else f"第 {selected_floor} 层"
                yield f"[挖地] 层数没有成功切到目标（现在是{shown}），已停止出阵"
                return
            yield f"[挖地] 已确认指定第 {target_floor} 层"
        if not self._wait_for_team_select(cfg, attempts=15, open_after=5):
            yield "[挖地] 部队选择界面没打开"
            return

        self._pick_team(team_no)
        self.maa.screenshot(force=True)
        initial_injury = self._team_injury_status(cfg)
        if initial_injury and self._injury_reaches_threshold(
                initial_injury, repair_threshold):
            yield f"[挖地] 出阵前检测到{initial_injury}，已达到停止条件，本次不出阵"
            return
        if not self._click_depart(cfg):
            yield "[挖地] 找不到即刻出阵按钮"
            return

        self.maa.screenshot(force=True)
        equip_cancelled = self._cancel_equip_warning(cfg)
        if equip_cancelled is not None:
            yield "[挖地] 刀装未满，已取消出阵" if equip_cancelled else "[挖地] 刀装未满且无法安全取消，停止"
            return
        deny_cfg = cfg.get("injury_deny_button", {})
        deny = self.maa.template_match(deny_cfg.get("template"))
        if deny:
            self.maa.click(deny)
            yield "[挖地] 队员重伤确认弹窗，已点【否】；有重伤绝不出阵"
            return

        # 大阪城没有手形，也没有自动行军；即刻出阵后只有普通二次确认。
        if not self._confirm_osaka_departure(cfg):
            yield "[挖地] 没看到出阵二次确认，停止点击"
            return
        yield f"[挖地] 部队{team_no}出发，狐之助的废话交给安全区慢慢跳过"

        floors = 0
        idle_checks = 0
        while idle_checks < 300:
            self.maa.screenshot(force=True)

            # 道中和层末都有“部队恢复 / 返回本丸 / 行军”，三者全部是常驻操作，
            # 不能参与层末判断。只认结算页专有的“当前层数 + 传送凭证”。
            if self._osaka_floor_done(cfg):
                idle_checks = 0
                floors += 1
                total_completed = _completed_floors + floors
                yield f"[挖地] ✓ 已完成 {total_completed}/{_target_floors} 层"
                injury = self._team_injury_status(cfg)
                goal_reached = total_completed >= _target_floors
                injury_reached = bool(
                    injury and self._injury_reaches_threshold(
                        injury, repair_threshold))
                if injury and not injury_reached:
                    yield f"[挖地] 部队出现{injury}，尚未达到停止条件，继续向下挖"
                if goal_reached or injury_reached:
                    reasons = []
                    if goal_reached:
                        reasons.append("目标层数已完成")
                    if injury_reached:
                        reasons.append(f"部队出现{injury}")
                    yield f"[挖地] {'，'.join(reasons)}，准备返回本丸收尾"
                    returned = self._return_home_from_march(cfg)
                    if returned:
                        self.current_location = "本丸"
                        yield "[挖地] ✓ 已安全返回本丸"
                    else:
                        yield "[挖地] 没能确认返回本丸；已停止点击，请手动查看"
                        return
                    if goal_reached:
                        yield (f"[挖地] 目标层数完成，收工；期间手入 {_repair_count} 次，"
                               f"累计使用加速符 {_speedups_used} 个")
                        return

                    action = str(injury_action or "continue")
                    if action == "stop":
                        yield "[挖地] 按设置只返回本丸，不进行手入，收工"
                        return
                    repair_and_stop = action == "repair_stop"
                    yield ("[挖地] 开始手入，完成后收工" if repair_and_stop
                           else "[挖地] 开始手入并加速当前部队，之后继续剩余层数")
                    for repair_msg in self.repair_stream(
                            dry_run=False,
                            use_speedup=False if repair_and_stop else None,
                            speedup_teams=None if repair_and_stop else [team_no]):
                        yield repair_msg
                    stats = getattr(self, "last_repair_stats", {})
                    repaired = int(stats.get("repaired", 0))
                    speedups = int(stats.get("speedups", 0))
                    _repair_count += 1
                    _speedups_used += speedups
                    yield (f"[挖地] 🩹 第 {_repair_count} 次手入：修复 {repaired} 把，"
                           f"使用加速符 {speedups} 个；累计使用 {_speedups_used} 个")
                    if repair_and_stop:
                        yield "[挖地] 手入已安排，收工"
                        return
                    remaining = _target_floors - total_completed
                    yield (f"[挖地] 手入结束，当前总进度 {total_completed}/{_target_floors}，"
                           f"继续剩余 {remaining} 层")
                    yield from self.osaka_stream(
                        max_floors=remaining,
                        team_no=team_no,
                        select_floor=select_floor,
                        target_floor=target_floor,
                        formation_mode=formation_mode,
                        formation_strategy=formation_strategy,
                        formation=formation,
                        repair_threshold=repair_threshold,
                        injury_action=injury_action,
                        _target_floors=_target_floors,
                        _completed_floors=total_completed,
                        _repair_count=_repair_count,
                        _speedups_used=_speedups_used,
                    )
                    return
                march = self._wait_for_osaka_march(cfg)
                if not march:
                    yield "[挖地] 层末找不到行军按钮，停止点击"
                    return
                self.maa.click(march)
                time.sleep(1.2)
                continue

            if self._formation_mode_state(
                    allow_auto_without_title=formation_mode != "auto") is not None:
                idle_checks = 0
                result = self.choose_formation(
                    strategy=formation_strategy,
                    formation_name=formation,
                    enable_auto=formation_mode == "auto",
                )
                if result == "auto":
                    yield "[挖地] 已开启游戏自动阵形"
                else:
                    chosen = "有利阵形" if result == "advantage" else formation
                    yield f"[挖地] 已选择「{chosen}」"
                time.sleep(1.0)
                continue

            march = self._find_osaka_march(cfg)
            if march:
                idle_checks = 0
                # 大阪城没有自动行军：每次战斗结果页出现“行军”时都先查伤势。
                # 达到停止条件就绝不点击行军，避免拖到整层结束才发现伤员。
                field_injury = self._team_injury_status(cfg)
                if field_injury and self._injury_reaches_threshold(
                        field_injury, repair_threshold):
                    yield f"[挖地] 道中检测到{field_injury}，不再继续行军"
                    if not self._return_home_from_march(cfg):
                        yield "[挖地] 没能确认返回本丸；已停止点击，请手动查看"
                        return
                    self.current_location = "本丸"
                    yield "[挖地] ✓ 已安全返回本丸"
                    action = str(injury_action or "continue")
                    if action == "stop":
                        yield "[挖地] 按设置不进行手入，收工"
                        return
                    repair_and_stop = action == "repair_stop"
                    yield ("[挖地] 开始手入，完成后收工" if repair_and_stop
                           else "[挖地] 开始手入并加速当前部队，之后继续剩余层数")
                    for repair_msg in self.repair_stream(
                            dry_run=False,
                            use_speedup=False if repair_and_stop else None,
                            speedup_teams=None if repair_and_stop else [team_no]):
                        yield repair_msg
                    stats = getattr(self, "last_repair_stats", {})
                    repaired = int(stats.get("repaired", 0))
                    speedups = int(stats.get("speedups", 0))
                    _repair_count += 1
                    _speedups_used += speedups
                    yield (f"[挖地] 🩹 第 {_repair_count} 次手入：修复 {repaired} 把，"
                           f"使用加速符 {speedups} 个；累计使用 {_speedups_used} 个")
                    if repair_and_stop:
                        yield "[挖地] 手入已安排，收工"
                        return
                    total_completed = _completed_floors + floors
                    remaining = _target_floors - total_completed
                    yield (f"[挖地] 手入结束，当前总进度 {total_completed}/{_target_floors}，"
                           f"继续剩余 {remaining} 层")
                    yield from self.osaka_stream(
                        max_floors=remaining,
                        team_no=team_no,
                        select_floor=select_floor,
                        target_floor=target_floor,
                        formation_mode=formation_mode,
                        formation_strategy=formation_strategy,
                        formation=formation,
                        repair_threshold=repair_threshold,
                        injury_action=injury_action,
                        _target_floors=_target_floors,
                        _completed_floors=total_completed,
                        _repair_count=_repair_count,
                        _speedups_used=_speedups_used,
                    )
                    return
                yield "[挖地] 行军，继续向下挖"
                self.maa.click(march)
                time.sleep(1.0)
                continue

            # 狐之助对话和战斗过场都用右下安全区驱散；没有目标时绝不盲点按钮区。
            self._click_point(cfg.get("skip_tap", [775, 695]))
            idle_checks += 1
            time.sleep(0.8)

        yield (f"[挖地] 连续 {idle_checks} 次没有识别到阵形、行军或层末"
               f"（总进度 {_completed_floors + floors}/{_target_floors}），"
               f"停止点击，请查看卡在哪个画面")

    def _open_osaka(self, cfg: dict) -> bool:
        activity = cfg.get("activity_entry", {})
        entry = cfg.get("event_entry", {})
        for step in (activity, entry):
            template = step.get("template")
            target = self.maa.template_match(template) if template else None
            if not target:
                return False
            self.maa.click(target)
            time.sleep(1.5)
            self.maa.screenshot(force=True)
        return True

    def _confirm_osaka_departure(self, cfg: dict) -> bool:
        prompt = cfg.get("confirm_ui", {})
        prompt_template = prompt.get("template")
        for _ in range(10):
            self.maa.screenshot(force=True)
            if not prompt_template or self.maa.template_match(prompt_template):
                confirm = cfg.get("confirm_button", {})
                template = confirm.get("template")
                roi_raw = confirm.get("roi")
                button = self.maa.template_match(
                    template, roi_4to4(*roi_raw) if roi_raw else None)
                if button:
                    self.maa.click(button)
                    time.sleep(1.5)
                    return True
                # 大阪城确认窗的绿色“确定”与通用灰按钮不是同一皮肤。
                # 已用专属标题确认弹窗后，模板失配时才允许点实测坐标兜底。
                target = confirm.get("target")
                if target:
                    self._click_point(target)
                    time.sleep(1.5)
                    return True
            time.sleep(0.5)
        return False

    def _read_osaka_floor(self, cfg: dict):
        """读取活动页标题中的层数；不用滚轮数字，避免两个 OCR 结果错序。"""
        title = cfg.get("floor_title_ocr", {})
        roi = roi_4to4(*title.get("roi", [75, 155, 555, 225]))
        tokens = self.maa.ocr_all(roi)
        text = "".join(str(token[0]) for token in tokens)
        text = re.sub(r"\s+", "", text)
        match = re.search(r"大阪城地下(\d{1,2})层", text)
        if not match:
            # OCR 偶尔会漏掉固定标题，但数字两侧仍有“地下/层”可作护栏。
            match = re.search(r"地下(\d{1,2})层", text)
        if not match:
            return None
        floor = int(match.group(1))
        return floor if 1 <= floor <= 99 else None

    def _select_osaka_floor(self, cfg: dict, target_floor: int):
        """逐位调节层数；每次点击后复读标题，灰色箭头不会被连续盲点。"""
        arrows = cfg.get("floor_arrows", {})
        points = {
            "tens_up": arrows.get("tens_up", [1014, 284]),
            "ones_up": arrows.get("ones_up", [1084, 284]),
            "tens_down": arrows.get("tens_down", [1014, 420]),
            "ones_down": arrows.get("ones_down", [1084, 420]),
        }
        current = self._read_osaka_floor(cfg)
        for _ in range(20):
            if current is None or current == target_floor:
                return current
            current_tens, current_ones = divmod(current, 10)
            target_tens, target_ones = divmod(target_floor, 10)
            if current_tens != target_tens:
                key = "tens_up" if target_tens > current_tens else "tens_down"
            else:
                key = "ones_up" if target_ones > current_ones else "ones_down"
            self._click_point(points[key])
            time.sleep(0.45)
            self.maa.screenshot(force=True)
            updated = self._read_osaka_floor(cfg)
            if updated is None or updated == current:
                # 灰色（不可用）箭头的表现就是标题层数没有变化。
                return updated if updated is not None else current
            current = updated
        return current

    def _osaka_floor_done(self, cfg: dict) -> bool:
        """只用层末专有文字判断；故意不查看三个道中常驻按钮。"""
        marker = cfg.get("floor_end_ocr", {})
        roi = roi_4to4(*marker.get("roi", [825, 270, 1280, 355]))
        if not self.maa.ocr(marker.get("expected", "当前层数"), roi):
            return False
        witness = cfg.get("floor_end_witness_ocr", {})
        witness_roi = roi_4to4(*witness.get("roi", [825, 85, 1280, 285]))
        return bool(self.maa.ocr(
            witness.get("expected", "传送凭证"), witness_roi))

    def _find_osaka_march(self, cfg: dict):
        march = cfg.get("march_button", {})
        roi = roi_4to4(*march.get("roi", [1030, 500, 1280, 720]))
        return self.maa.template_match(
            march.get("template", "battle/行军.png"), roi)

    def _wait_for_osaka_march(self, cfg: dict, attempts: int = 8):
        """层末文字通常先于按钮出现；等按钮动画落稳，不因单帧抢跑停机。"""
        for _ in range(attempts):
            self.maa.screenshot(force=True)
            march = self._find_osaka_march(cfg)
            if march:
                return march
            time.sleep(0.5)
        return None
