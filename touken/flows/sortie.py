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
                      auto_march: bool = True, max_loops: int = 1):
        """
        流式跑合战场

        Args:
            chapter: 章节编号（1-8，对应 map_select.合战场.chapters）
            map_no: 小图编号（1-4，对应 map_select.合战场.maps）
            team_no: 部队编号
            auto_march: 是否委托自动行军（True=全自动打完一圈回本丸）
            max_loops: 连续打几圈

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

        for loop_no in range(1, max_loops + 1):
            yield f"[出阵] ===== 第 {loop_no}/{max_loops} 圈：{chapter}章-{map_no}图，部队{team_no} ====="

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
            if self.maa.template_match(cfg["injury_stamp"]["template"]):
                yield "[出阵] 🛑 检测到重伤标记！按规矩绝不出阵，停。去修刀吧"
                return

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

            # 刀装未满警告 → 教材规矩：停
            if self.maa.template_match(cfg["equip_warning_button"]["template"]):
                yield "[出阵] ⚠️ 刀装未满警告！按规矩停下来了，你去看看要不要整备刀装"
                return

            # 队员重伤确认弹窗 → 教材规矩：永远点"否"
            deny = self.maa.template_match(cfg["injury_deny_button"]["template"])
            if deny:
                self.maa.click(deny)
                yield "[出阵] 🛑 队员重伤确认弹窗，已点【否】。有重伤绝不出阵，停"
                return

            yield "[出阵] 出发，进入行军监控"

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
                    self.select_formation(cfg.get("formation", "鱼鳞阵"))
                    time.sleep(1.0)
                    continue

                # 手动行军决策屏（委托没挂上时每个节点都问）：点"行军"继续
                # ——刷花实测：_enable_auto_march 会静默失败，不能全指望委托
                if self.maa.ocr("行军", roi_4to4(1080, 550, 1215, 680)):
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
                    self.maa.screenshot(force=True)
                    stop_btn = self.maa.template_match(cfg["march_stop_button"]["template"])
                    if stop_btn:
                        self.maa.click(stop_btn)
                    interrupted = True
                    time.sleep(1.5)
                    # 点返回本丸后游戏会二次确认"确认返回本丸？"→ 点"是"
                    self.maa.screenshot(force=True)
                    yes = self.maa.template_match(cfg["return_home_confirm"]["template"])
                    if yes:
                        self.maa.click(yes)
                    time.sleep(2.0)
                    # 等回本丸
                    for _ in range(15):
                        self.maa.screenshot(force=True)
                        if self.maa.template_match(cfg["home_ui"]["template"]):
                            break
                        time.sleep(0.8)
                    break

                # 安全区跳动画
                self._click_point(cfg["skip_tap"])
                time.sleep(0.8)

            if march_done:
                yield f"[出阵] 第 {loop_no} 圈打完，已回本丸"
            elif interrupted:
                yield "[出阵] ⚠️ 行军中断（可能有人中伤），已返回本丸。去看看伤势，本次停止"
                return
            else:
                yield "[出阵] ⚠️ 行军监控超过安全上限，强制停，你去看看卡哪了"
                return

        yield "[出阵] 全部圈数跑完，收工"
        return
