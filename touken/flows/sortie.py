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
from ..map_read import CV2_AVAILABLE, boss_distance_from_image


class SortieMixin:
    """合战场出阵。依赖宿主类的 navigate_to_stream、_click_point、_enable_auto_march。"""

    def sortie_stream(self, chapter: int, map_no: int, team_no: int = 3,
                      auto_march: bool = True, max_loops: int = 1,
                      formation_mode: str = "manual",
                      formation_strategy: str = "fixed",
                      formation: str = "鱼鳞阵",
                      repair_threshold: str = "light",
                      injury_action: str = "continue",
                      auto_equip: bool = True,
                      retreat_before_boss: bool = False):
        yield from self._map_sortie_stream(
            chapter=chapter, map_no=map_no, team_no=team_no,
            auto_march=auto_march, max_loops=max_loops,
            formation_mode=formation_mode,
            formation_strategy=formation_strategy, formation=formation,
            repair_threshold=repair_threshold, injury_action=injury_action,
            auto_equip=auto_equip,
            retreat_before_boss=retreat_before_boss,
        )

    def yosari_stream(self, map_no: int, team_no: int = 3,
                      auto_march: bool = True, max_loops: int = 1,
                      auto_refill: bool = False,
                      formation_mode: str = "manual",
                      formation_strategy: str = "fixed",
                      formation: str = "鱼鳞阵",
                      repair_threshold: str = "light",
                      injury_action: str = "continue",
                      auto_equip: bool = True):
        """流式跑常驻玩法“异去”；目前只有第一章。"""
        yield from self._map_sortie_stream(
            chapter=1, map_no=map_no, team_no=team_no,
            auto_march=auto_march, max_loops=max_loops,
            auto_refill=auto_refill,
            formation_mode=formation_mode,
            formation_strategy=formation_strategy, formation=formation,
            repair_threshold=repair_threshold, injury_action=injury_action,
            auto_equip=auto_equip,
            map_type="异去", cfg_key="yosari",
        )

    def _map_sortie_stream(self, chapter: int, map_no: int, team_no: int = 3,
                           auto_march: bool = True, max_loops: int = 1,
                           formation_mode: str = "manual",
                           formation_strategy: str = "fixed",
                           formation: str = "鱼鳞阵",
                           repair_threshold: str = "light",
                           injury_action: str = "continue",
                           auto_equip: bool = True,
                           auto_refill: bool = False,
                           retreat_before_boss: bool = False,
                           map_type: str = "合战场",
                           cfg_key: str = "sortie"):
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
        cfg = dict(self.config.get("sortie", {}))
        cfg.update(self.config.get(cfg_key, {}))
        if not cfg:
            yield f"[出阵] 未配置{map_type}"
            return

        map_cfg = self.config.get("map_select", {}).get(map_type, {})
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
        map_page_ready = False
        record_saved = False
        self._map_miss_count = 0
        auto_equip_active = bool(
            auto_equip and str(injury_action or "continue") == "continue")
        while loop_no <= max_loops:
            if self.current_location != "出阵":
                for nav_msg in self.navigate_to_stream("出阵"):
                    yield nav_msg
                if self.current_location != "出阵":
                    yield "[出阵] 重新进入出阵失败，停止"
                    return
            yield f"[出阵] ⚔️ 第 {loop_no}/{max_loops} 圈：{chapter}章-{map_no}图，部队{team_no}准备上场"

            if not map_page_ready:
                if cfg_key == "yosari" and not self._enter_yosari(cfg):
                    yield "[异去] 没能从过去切换到异去，停止"
                    return

                # 每日首次进异去会渐入剧情演出：进场前右下角“决定”按钮还看得见，
                # 动画一盖上来就被挡住，脚本在动画里乱点会彻底打乱卡死。
                # 只点安全区把动画跳完，直到“决定”按钮完整出现，再走章节选择。
                if cfg_key == "yosari":
                    # 火车切渐入演出会让"决定"按钮先露脸再被盖住、说完才回来，
                    # 必须连续命中才算真就绪；章节页点安全区验证过无害，边等边点加速推对话。
                    if not self.wait_landmark_skipping(
                            template=cfg["decide_button"]["template"],
                            skip_point=cfg.get("skip_tap"),
                            timeout_s=90, stable_hits=3,
                            tap_even_when_found=True):
                        yield "[异去] 剧情演出跳不完，没看到“决定”按钮，停止"
                        return

                # ========== 2. 选章节 → 决定 ==========
                self._click_point(map_cfg["chapters"][str(chapter)])
                time.sleep(0.5)
                self.maa.screenshot(force=True)
                decide = self.maa.template_match(cfg["decide_button"]["template"])
                if decide:
                    self.maa.click(decide)
                    time.sleep(1.5)

                # ========== 3. 等小图页 ==========
                area_ok = False
                for _ in range(10):
                    self.maa.screenshot(force=True)
                    if self.maa.template_match(cfg["area_select_ui"]["template"]):
                        area_ok = True
                        break
                    time.sleep(0.5)
                if not area_ok:
                    yield "[出阵] 没识别到小图页的部队选择按钮（章节坐标或页面状态不对），停止"
                    return
            else:
                yield "[异去] 已回到四张小图页，直接开始下一圈"
            self._click_point(map_cfg["maps"][str(map_no)])
            time.sleep(1.0)
            map_page_ready = False

            # ========== 4. 部队选择 → 选部队 ==========
            # 合战场点完小图会【直接】进部队选择界面，没有中间按钮；
            # 但保险起见：没在部队选择界面时才去找"部队选择"按钮点
            if not self._wait_for_team_select(cfg, attempts=12, open_after=2):
                yield "[出阵] 部队选择界面没打开，本圈放弃"
                continue

            self._pick_team(team_no)

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

            # 只在整轮任务第一次出阵前保存。战斗后刀装可能已碎，绝不能在
            # 下一圈覆盖记录一，否则保存下来的就是缺刀装状态。
            if auto_equip_active and not record_saved:
                yield "[出阵] 自动补充刀装已开启，先把当前部队保存到记录一"
                if self._save_team_record(cfg, record_no=1):
                    record_saved = True
                    yield "[出阵] ✓ 当前部队已保存到记录一"
                else:
                    yield "[出阵] ⚠️ 没能安全保存记录一，已停止；请查看是否有确认弹窗未处理"
                    return

            # ========== 6. 可选：委托自动行军 ==========
            delegated_march = False
            if auto_march:
                delegated_march = self._enable_auto_march()
                time.sleep(0.5)
                if not delegated_march:
                    yield "[出阵] ⚠️ 游戏自动行军没有挂成功，降级为脚本手动行军"

            # ========== 7. 即刻出阵 → 刀装恢复分支 ==========
            equip_retries = 0
            while True:
                if not self._click_depart(cfg):
                    yield "[出阵] 找不到即刻出阵按钮（队长重伤会变灰？），停"
                    return

                self.maa.screenshot(force=True)
                if auto_equip_active:
                    equip_result = self._restore_equipment_from_warning(cfg, record_no=1)
                    if equip_result is None:
                        break
                    if not equip_result:
                        yield "[出阵] ⚠️ 刀装未满警告；从记录一恢复失败，已停止出阵"
                        return
                    equip_retries += 1
                    yield "[出阵] 🛡️ 刀装有空缺，已使用记录一自动补齐"
                    if equip_retries >= 2:
                        yield "[出阵] 恢复刀装后仍出现空缺警告，停止重试"
                        return
                    # 使用记录后重新做保命检查；异常时绝不再次点出阵。
                    self.maa.screenshot(force=True)
                    restored_injury = self._team_injury_status(cfg)
                    if restored_injury and self._injury_reaches_threshold(
                            restored_injury, repair_threshold):
                        yield f"[出阵] 恢复刀装后检测到{restored_injury}，不再出阵"
                        return
                    if auto_march:
                        delegated_march = self._enable_auto_march()
                    continue

                # 未开启自动补充时保持原安全行为：点整备刀装退出，不碰继续出阵。
                equip_cancelled = self._cancel_equip_warning(cfg)
                if equip_cancelled is None:
                    break
                if equip_cancelled:
                    yield "[出阵] ⚠️ 刀装未满警告；已进入整备，本次跳过"
                else:
                    yield "[出阵] ⚠️ 刀装未满警告；没能安全进入整备，本次出阵停止"
                return

            # 队员重伤确认弹窗 → 教材规矩：永远点"否"
            if self._deny_heavy_injury_warning(cfg):
                yield "[出阵] 🛑 队员重伤确认弹窗，已点【否】。有重伤绝不出阵，停"
                return

            if cfg_key == "yosari":
                confirmed = yield from self._confirm_yosari_departure(
                    cfg, auto_refill=auto_refill)
                if confirmed == "refilled":
                    yield "[异去] 已补充归城提灯，重新点击即刻出阵"
                    if not self._click_depart(cfg):
                        yield "[异去] 补充后找不到即刻出阵按钮，收工"
                        return
                    confirmed = yield from self._confirm_yosari_departure(
                        cfg, auto_refill=auto_refill, refill_attempted=True)
                if not confirmed:
                    return

            yield f"[出阵] 🐎 部队{team_no}出发！行军监控开着呢，我全程盯着"

            # ========== 8. 行军监控：打完自动回本丸 / 中断则返回本丸 ==========
            march_done = False
            interrupted = False
            retreated = False
            for _ in range(300):  # 安全上限
                self.maa.screenshot(force=True)

                if self._deny_heavy_injury_warning(cfg):
                    yield "[出阵] 🛑 出现重伤行军警告，已点【否】，准备返回本丸"
                    self.maa.screenshot(force=True)
                    if not self._return_home_from_march(cfg):
                        yield "[出阵] 点否后找不到返回本丸按钮，已停止点击"
                        return
                    interrupted = True
                    break

                # 异去一圈结束后回到四张小图页，不会回本丸。
                if cfg_key == "yosari" and self._yosari_round_done(cfg):
                    march_done = True
                    map_page_ready = True
                    break

                # 普通合战场打完一圈会自动回本丸。
                if self.maa.template_match(cfg["home_ui"]["template"]):
                    march_done = True
                    break

                # 游戏自动行军确认挂上后，路线与阵形全交给游戏，不介入。
                # 行军停止必须认“自动行军停止”横幅；不能拿“返回本丸”按钮判定，
                # 因为那个按钮在行军区常驻，误认后点击就会变成脚本主动撤退。
                if delegated_march:
                    stop_ocr = cfg["march_stop_ocr"]
                    stop_roi = roi_4to4(*stop_ocr["roi"])
                    if self.maa.ocr(expected=stop_ocr["expected"], roi=stop_roi):
                        field_injury = self._team_injury_status(cfg)
                        detail = f"（检测到{field_injury}）" if field_injury else ""
                        yield f"[出阵] ⚠️ 游戏自动行军已经停止{detail}，准备安全返回本丸"
                        if not self._return_home_from_march(cfg):
                            yield "[出阵] 找不到返回本丸按钮，停止点击，等你手动处理"
                            return
                        interrupted = True
                        break
                    self._click_point(cfg["skip_tap"])
                    time.sleep(0.8)
                    continue

                # 只有自动委托没挂上，或用户明确选择脚本手动行军，才处理阵形和岔路。
                # ——刷花实测卡死在这的教训
                if self._formation_mode_state(
                        allow_auto_without_title=formation_mode != "auto") is not None:
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
                        if self._formation_mode_state() is None:
                            break
                    continue

                # 手动行军决策屏（委托没挂上时每个节点都问）：点"行军"继续
                # ——刷花实测：_enable_auto_march 会静默失败，不能全指望委托
                march_button = self._find_march_continue(cfg)
                if march_button:
                    field_injury = self._team_injury_status(cfg)
                    if field_injury and self._injury_reaches_threshold(
                            field_injury, repair_threshold):
                        yield f"[出阵] 🩹 局内检测到{field_injury}，已达到手入阈值，不再继续行军"
                        if not self._return_home_from_march(cfg):
                            yield "[出阵] 找不到返回本丸按钮，停止点击，等你手动处理"
                            return
                        interrupted = True
                        break
                    # 王点前撤退（仅合战场 + 脚本手动行军）：决策屏右上小地图
                    # 永远干净完整，距王点 1 步 = 下一脚就是王点，撤。
                    # 认不出来（None）绝不是撤退信号，继续正常行军。
                    if retreat_before_boss and cfg_key == "sortie":
                        if not CV2_AVAILABLE:
                            yield "[出阵] 🗺️ 王点前撤退需要 opencv，当前环境没装，本圈按普通行军跑"
                            retreat_before_boss = False
                        else:
                            boss_dist = boss_distance_from_image(
                                self.maa.screenshot())
                            if boss_dist == 1:
                                yield "[出阵] 🏳️ 小地图看明白了：下一脚就是王点，按约定撤退回本丸"
                                if not self._return_home_from_march(cfg):
                                    yield "[出阵] 找不到返回本丸按钮，停止点击，等你手动处理"
                                    return
                                retreated = True
                                break
                            if boss_dist is None:
                                yield "[出阵] 🗺️ 小地图这帧没认明白，这步先照常走"
                                self._save_map_miss(chapter, map_no, loop_no)
                            else:
                                yield f"[出阵] 🗺️ 距王点还有 {boss_dist} 步，继续行军"
                    yield "[出阵] 🚩 岔路口问我话呢，点「行军」继续"
                    self.maa.click(march_button)
                    time.sleep(1.0)
                    continue

                # 安全区跳动画
                self._click_point(cfg["skip_tap"])
                time.sleep(0.8)

            if march_done:
                if cfg_key == "yosari":
                    yield f"[异去] ✓ 第 {loop_no} 圈结束，已回到异去小图页"
                    self.current_location = "出阵"
                else:
                    yield f"[出阵] ✓ 第 {loop_no} 圈凯旋！已回本丸"
                    self.current_location = "本丸"
                if hasattr(self, "record_event"):
                    self.record_event(
                        "sortie.completed", mode=cfg_key, chapter=chapter,
                        map_no=map_no, team_no=team_no, sequence=loop_no)
                repair_attempts = 0
                loop_no += 1
            elif interrupted:
                yield "[出阵] ⚠️ 行军因伤势中断，已返回本丸；重新检查轻/中/重伤"
                self.current_location = "本丸"
                continue
            elif retreated:
                # 王点前主动撤退算完成一圈（练级打法），回满状态接着进下一圈
                yield f"[出阵] ✓ 第 {loop_no} 圈王点前撤退完成，已回本丸"
                self.current_location = "本丸"
                if hasattr(self, "record_event"):
                    self.record_event(
                        "sortie.retreated_before_boss", mode=cfg_key,
                        chapter=chapter, map_no=map_no, team_no=team_no,
                        sequence=loop_no)
                repair_attempts = 0
                loop_no += 1
            else:
                yield "[出阵] ⚠️ 行军监控超过安全上限，强制停，你去看看卡哪了"
                return

        yield f"[出阵] ✓ 全部 {max_loops} 圈跑完，部队{team_no}辛苦啦，收工！"
        return

    def _enter_yosari(self, cfg: dict) -> bool:
        """从默认的“过去”切换到右上角“异去”，并用文字复核。"""
        entry = cfg.get("entry", {})
        roi = roi_4to4(*entry.get("verify_roi", [285, 50, 850, 145]))
        expected = entry.get("expected", "归城提灯")
        self.maa.screenshot(force=True)
        if self.maa.ocr(expected, roi):
            return True
        self._click_point(entry.get("target", [978, 93]))
        # 异去是渐入进场的动画演出：进场途中归城提灯会被盖住/误认，
        # 先等 2 秒让页面稳定再认，别在动画里乱判
        time.sleep(2.0)
        for _ in range(6):
            self.maa.screenshot(force=True)
            if self.maa.ocr(expected, roi):
                return True
            time.sleep(0.5)
        return False

    def _confirm_yosari_departure(self, cfg: dict, auto_refill: bool = False,
                                  refill_attempted: bool = False):
        """处理新版归城提灯确认；缺灯时按四段确认链补充后返回部队选择。"""
        prompt = cfg.get("departure_confirm", {})
        roi = roi_4to4(*prompt.get("roi", [310, 155, 970, 330]))
        expected = prompt.get("expected", "归城提灯进行出阵")
        for _ in range(8):
            self.maa.screenshot(force=True)
            if self.maa.ocr(expected, roi):
                self._click_point(prompt.get("confirm_target", [640, 603]))
                time.sleep(1.5)
                break
            time.sleep(0.5)
        else:
            yield "[异去] 没看到归城提灯出阵确认框；停止"
            return False

        refill = cfg.get("ticket_refill", {})

        def _wait_text(step: dict, fallback_expected: str, fallback_roi: list) -> bool:
            text = step.get("expected", fallback_expected)
            text_roi = roi_4to4(*step.get("roi", fallback_roi))
            for _ in range(8):
                self.maa.screenshot(force=True)
                if self.maa.ocr(text, text_roi):
                    return True
                time.sleep(0.4)
            return False

        purchase_screen = refill.get("purchase_screen", {})
        if not _wait_text(purchase_screen, "补充所需", [270, 75, 1010, 555]):
            # 没进入购买页，说明现有提灯有效，第一次确认后已经真正出阵。
            yield "[异去] 已确认使用现有归城提灯（未勾选探索道具）"
            return True

        if refill_attempted:
            yield "[异去] 补充后仍进入购买页，停止，避免重复消费小判"
            return False
        if not auto_refill:
            self._click_point(purchase_screen.get("close_target", [1040, 48]))
            yield "[异去] 归城提灯不足；自动补充已关闭，不消耗小判，收工"
            return False

        yield "[异去] 归城提灯不足，开始四段确认中的补充步骤"
        self._click_point(purchase_screen.get("confirm_target", [638, 611]))
        time.sleep(1.2)

        spend_confirm = refill.get("spend_confirm", {})
        if not _wait_text(spend_confirm, "是否消耗", [300, 80, 1010, 560]):
            yield "[异去] 没看到消耗500小判的确认页，停止点击"
            return False
        self._click_point(spend_confirm.get("confirm_target", [784, 604]))
        time.sleep(1.2)

        completed = refill.get("completed", {})
        if not _wait_text(completed, "补充了归城提灯", [330, 120, 950, 460]):
            yield "[异去] 没看到归城提灯补充完成页，停止点击"
            return False
        self._click_point(completed.get("confirm_target", [638, 511]))
        time.sleep(1.2)
        yield "[异去] 归城提灯补充完成，已回到部队选择"
        return "refilled"

    def _yosari_round_done(self, cfg: dict) -> bool:
        """归城提灯标题与部队选择同时出现，才算确实回到异去小图页。"""
        marker = cfg.get("round_end_ocr", cfg.get("entry", {}))
        roi_raw = marker.get("roi", marker.get("verify_roi", [285, 50, 850, 145]))
        expected = marker.get("expected", "归城提灯")
        if not self.maa.ocr(expected, roi_4to4(*roi_raw)):
            return False
        deploy_cfg = cfg.get("deploy_button", {})
        template = deploy_cfg.get("template")
        return bool(template and self.maa.template_match(template))

    def _save_map_miss(self, chapter: int, map_no: int, loop_no: int):
        """小地图没认出来时留一张决策屏截图（每轮任务最多 5 张），
        攒起来给地图实验室调阈值用——市街图这类白黄底色的图很可能撞色。"""
        count = getattr(self, "_map_miss_count", 0)
        if count >= 5:
            return
        try:
            from ..runtime_paths import STATUS_DIR
            folder = STATUS_DIR / "map_miss"
            folder.mkdir(parents=True, exist_ok=True)
            name = (f"miss_{chapter}-{map_no}_loop{loop_no}_"
                    f"{time.strftime('%H%M%S')}.png")
            if self.maa.save_screenshot(str(folder / name), force=False):
                self._map_miss_count = count + 1
        except Exception:
            pass

    def _find_march_continue(self, cfg: dict):
        """只在右下角按钮区寻找完整“行军”按钮，避免命中自动行军横幅。"""
        march_cfg = cfg.get("march_continue_button", {})
        roi = roi_4to4(*march_cfg.get("roi", [990, 510, 1280, 720]))
        template = march_cfg.get("template", "battle/行军.png")
        return self.maa.template_match(template, roi)

    def _return_home_from_march(self, cfg) -> bool:
        """在行军选择/停止画面安全返回本丸，并等待本丸真正出现。

        长时间挂机后游戏回本丸偶尔会卡在加载过渡几十秒。这里必须等到本丸
        标志实际出现，不能只因点击了确认按钮就把后续盘点放出去。
        """
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
        deadline = time.monotonic() + 90.0
        while time.monotonic() < deadline:
            self.maa.screenshot(force=True)
            if self.maa.template_match(cfg["home_ui"]["template"]):
                return True
            time.sleep(0.8)
        return False
