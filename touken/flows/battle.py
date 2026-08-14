# -*- coding: utf-8 -*-
"""
上层业务：出战相关——选地图、选部队、选阵形
（从 touken_agent_engine_v2.py 原样搬家，逻辑未改）
"""

import time

from ..maa_adapter import roi_4to4, Point


class BattleMixin:
    """地图/部队/阵形选择。依赖宿主类的 _click_point、_click_template_config。"""

    def _cancel_equip_warning(self, cfg):
        """安全退出“刀装未满”弹窗；返回 None 表示当前没有该弹窗。"""
        warning_cfg = cfg.get("equip_warning_button", {})
        warning_template = warning_cfg.get("template")
        if not warning_template or not self.maa.template_match(warning_template):
            return None

        # 绝不点“继续出阵”。“整备刀装”会关闭警告并回到部队选择。
        prepare_cfg = cfg.get("equip_warning_prepare", {})
        prepare_template = prepare_cfg.get("template", "team/整备刀装.png")
        prepare = self.maa.template_match(prepare_template)
        if not prepare:
            return False
        self.maa.click(prepare)
        time.sleep(0.8)

        team_ui = cfg.get("team_ui_ocr", {})
        team_roi_raw = team_ui.get("roi")
        team_roi = roi_4to4(*team_roi_raw) if team_roi_raw else None
        for _ in range(6):
            self.maa.screenshot(force=True)
            if (team_roi and team_ui.get("expected")
                    and self.maa.ocr(team_ui["expected"], team_roi)):
                return True
            time.sleep(0.4)
        return False

    _recover_ok: bool = False

    def _recover_ticket_stream(self, cfg: dict, tag: str = "[出阵]"):
        """通用手形补充：补充 → 恢复1个 → 确定。"""
        self._recover_ok = False
        rec_cfg = cfg["ticket_recover"]

        self.maa.screenshot(force=True)
        refill = self.maa.template_match(rec_cfg["popup_button"]["template"])
        if not refill:
            yield f"{tag} 找不到补充按钮"
            return
        self.maa.click(refill)
        time.sleep(1.5)

        self.maa.screenshot(force=True)
        recover = self.maa.template_match(rec_cfg["recover_button"]["template"])
        if not recover:
            yield f"{tag} 找不到恢复1个按钮"
            return
        self.maa.click(recover)
        time.sleep(1.5)

        self.maa.screenshot(force=True)
        confirm = self.maa.template_match(rec_cfg["confirm_button"]["template"])
        if not confirm:
            yield f"{tag} 找不到恢复完毕的确定按钮"
            return
        self.maa.click(confirm)
        time.sleep(2.0)

        self._recover_ok = True
        yield f"{tag} 手形补充完成"

    # ==================== 地图选择 ====================

    def select_map(self, map_type: str, chapter: str = None,
                   map_no: str = None) -> bool:
        """
        通用地图选择

        Args:
            map_type: 地图类型，如 "合战场", "活动", "远征"
            chapter: 章节编号
            map_no: 小图编号

        Returns:
            是否选择成功
        """
        map_config = self.config.get("map_select", {}).get(map_type)
        if not map_config:
            print(f"[ERROR] 未知地图类型: {map_type}")
            return False

        print(f"[MAP] 选择地图: {map_type}, 章节={chapter}, 图={map_no}")

        # 活动类型特殊处理
        if map_type == "活动":
            entry = map_config["entry"]
            self._click_template_config(entry)

            # 验证是否到达活动界面
            for template in map_config.get("verify_templates", []):
                roi_raw = map_config["verify_roi"]
                roi = roi_4to4(roi_raw[0], roi_raw[1], roi_raw[2], roi_raw[3])
                if self.maa.exists(template, roi):
                    print(f"[MAP] 到达活动界面")
                    return True
            return False

        # 选择章节
        if "chapters" in map_config and chapter:
            chapter_key = str(chapter)
            if chapter_key in map_config["chapters"]:
                self._click_point(map_config["chapters"][chapter_key])
                time.sleep(0.3)

        # 选择小图
        if "maps" in map_config and map_no:
            map_key = str(map_no)
            if map_key in map_config["maps"]:
                self._click_point(map_config["maps"][map_key])
                time.sleep(0.3)

        # 点击决定/确认
        if "confirm" in map_config:
            self._click_point(map_config["confirm"])

        return True

    # ==================== 部队选择 ====================

    def _wait_for_team_select(self, cfg: dict, attempts: int = 10,
                              open_after: int = None) -> bool:
        """等待部队选择页；需要时点击玩法页上的“部队选择”按钮。"""
        ocr_cfg = cfg.get("team_ui_ocr", {})
        roi_raw = ocr_cfg.get("roi")
        expected = ocr_cfg.get("expected", "部队选择")
        if not roi_raw:
            return False
        roi = roi_4to4(*roi_raw)

        for attempt in range(attempts):
            self.maa.screenshot(force=True)
            if self.maa.ocr(expected=expected, roi=roi):
                return True
            if open_after is not None and attempt == open_after:
                deploy_cfg = cfg.get("deploy_button", {})
                template = deploy_cfg.get("template")
                deploy = self.maa.template_match(template) if template else None
                if deploy:
                    self.maa.click(deploy)
                    time.sleep(1.5)
            time.sleep(0.5)
        return False

    def _pick_team(self, team_no: int) -> bool:
        """在部队选择页切换部队；第二次点击用于确认当前标签。"""
        teams = self.config.get("team_select", {}).get("teams", {})
        target = teams.get(str(team_no))
        if not target:
            return False
        self._click_point(target)
        time.sleep(0.3)
        self._click_point(target)
        time.sleep(0.5)
        return True

    def _click_depart(self, cfg: dict) -> bool:
        """点击各玩法共用的“即刻出阵”按钮。"""
        depart_cfg = cfg.get("depart_button", {})
        template = depart_cfg.get("template")
        depart = self.maa.template_match(template) if template else None
        if not depart:
            return False
        self.maa.click(depart)
        time.sleep(1.5)
        return True

    @staticmethod
    def _injury_reaches_threshold(injury: str, threshold: str) -> bool:
        """共用伤势阈值：轻伤 < 中伤 < 重伤。"""
        severity = {"轻伤": 1, "中伤": 2, "重伤": 3}
        limits = {"light": 1, "medium": 2, "heavy": 3}
        return severity.get(injury, 3) >= limits.get(str(threshold or "light"), 1)

    def _team_injury_status(self, cfg):
        """在部队列表或战斗结果页识别当前最高伤势。"""
        # 只看左侧我方六人。大阪城结果页右侧敌军会出现红色“破坏”章，
        # 全屏模板匹配会把它误认成同为红底的“重伤”，进而错误触发手入。
        roi = roi_4to4(*cfg.get("injury_status_roi", [0, 90, 570, 690]))
        stamps = cfg.get("injury_stamps", {})
        for severity in ("重伤", "中伤", "轻伤"):
            template = stamps.get(severity, {}).get("template")
            if template and self.maa.template_match(template, roi):
                return severity
        if not stamps:
            legacy = cfg.get("injury_stamp", {}).get("template")
            if legacy and self.maa.template_match(legacy, roi):
                return "重伤"
        # 通用 ocr(expected) 允许模糊匹配，曾把单独一个“伤”以高分命中“重伤”，
        # 导致本应保持中伤挨打的极化太刀被错误送回手入。这里读取原始文字，
        # 只有完整出现伤势名称才成立；“伤”这种残片不能推断等级。
        tokens = self.maa.ocr_all(roi)
        texts = [str(text).replace(" ", "") for text, _ in tokens]
        for severity in ("重伤", "中伤", "轻伤"):
            if any(severity in text for text in texts):
                return severity
        return None

    def select_team(self, team_no: int, auto_march: bool = False,
                    load_record: int = None, equip: bool = False) -> bool:
        """
        通用部队选择

        Args:
            team_no: 部队编号 1-5
            auto_march: 是否启用自动行军
            load_record: 加载第几号记录（None 表示不加载）
            equip: 是否补充刀装

        Returns:
            是否成功出发
        """
        team_config = self.config.get("team_select", {})

        # 1. 点击"部队选择"按钮
        enter = team_config["enter_button"]
        self._click_template_config(enter)
        time.sleep(1.5)

        # 2. 选择部队
        team_key = str(team_no)
        if team_key in team_config["teams"]:
            self._click_point(team_config["teams"][team_key])
            time.sleep(0.3)
            # 双击确认
            self._click_point(team_config["teams"][team_key])
            time.sleep(0.5)

        # 3. 可选：加载记录
        if load_record:
            self._load_team_record(load_record)

        # 4. 可选：补充刀装
        if equip:
            self._equip_swords()

        # 5. 可选：自动行军
        if auto_march:
            self._enable_auto_march()

        # 6. 出发
        self._click_point(team_config["depart"])
        return True

    def _load_team_record(self, record_no: int) -> bool:
        """加载部队记录"""
        record_config = self.config["team_select"]["team_record"]

        # 点击部队记录按钮
        self._click_template_config(record_config["button"])
        time.sleep(0.5)

        # 选择记录
        record_key = str(record_no)
        if record_key in record_config["records"]:
            self._click_point(record_config["records"][record_key])
            time.sleep(0.3)

        # 点击使用记录
        self._click_template_config(record_config["load_confirm"])
        time.sleep(0.3)

        # 确认弹窗
        self._click_template_config(record_config["yes_button"])
        return True

    def _equip_swords(self) -> bool:
        """补充刀装"""
        record_config = self.config["team_select"]["team_record"]

        # 点击部队记录
        self._click_template_config(record_config["button"])
        time.sleep(0.5)

        # 点击使用记录
        self._click_template_config(record_config["load_confirm"])
        time.sleep(0.3)

        # 确认
        self._click_template_config(record_config["yes_button"])
        return True

    def _enable_auto_march(self) -> bool:
        """启用自动行军（委托）
        真机校准的完整流程：点"自动行军"开弹窗 → 等"委托"按钮出现 →
        点它只是【选中单选框】→ 必须再点 X 关闭弹窗才生效。
        每步都验证绝不盲点——旧版 0.3s 短睡，弹窗没开就点 X，
        把部队选择面板关掉的 bug 就是这么来的。
        """
        march_config = self.config["team_select"]["auto_march"]
        check_roi_raw = march_config["check_delegated"]["roi"]
        check_roi = roi_4to4(check_roi_raw[0], check_roi_raw[1],
                             check_roi_raw[2], check_roi_raw[3])

        # 检查是否已经在委托中
        delegated = self.maa.exists(
            march_config["check_delegated"]["template"],
            check_roi
        )
        if delegated:
            print("[AUTO_MARCH] 已经在委托中，跳过")
            return True

        # 点击自动行军
        if not self._click_template_config(march_config["enable_button"]):
            print("[AUTO_MARCH] 没找到自动行军按钮")
            return False

        # 等弹窗里的"委托"按钮出现（弹窗动画要时间，旧版 0.3s 必漏）
        delegate_tpl = march_config["delegate_button"]["template"]
        pt = None
        for _ in range(10):
            time.sleep(0.5)
            self.maa.screenshot(force=True)
            pt = self.maa.template_match(delegate_tpl)
            if pt:
                break
        if not pt:
            print("[AUTO_MARCH] 委托弹窗没开，放弃（不盲点关闭）")
            return False

        # 点"委托"只是选中单选框，点 X 关闭弹窗才生效
        self.maa.click(pt)
        time.sleep(0.5)
        self._click_point(march_config["close_window"])
        time.sleep(1.0)

        # 验证结果
        self.maa.screenshot(force=True)
        ok = self.maa.exists(march_config["check_delegated"]["template"], check_roi)
        print(f"[AUTO_MARCH] 委托{'成功' if ok else '失败（标记没出现）'}")
        return ok

    # ==================== 阵形选择 ====================

    @staticmethod
    def _formation_name(name: str) -> str:
        """同时兼容旧配置中的“逆行”和标准名称“逆行阵”."""
        value = str(name or "逆行阵")
        return value if value.endswith("阵") else value + "阵"

    def choose_formation(self, strategy: str = "fixed",
                         formation_name: str = "逆行阵",
                         enable_auto: bool = False) -> str:
        """读取右上角状态，按需要切换自动/手动；手动时再选择阵形。"""
        cfg = self.config.get("formation", {})
        mode = cfg.get("auto_mode", {})
        current = self._formation_mode_state(
            allow_auto_without_title=not enable_auto)
        if current is None:
            return "failed"
        wanted = "auto" if enable_auto else "manual"
        if current != wanted:
            self._click_point(mode.get("toggle", [910, 32]))
            time.sleep(0.6)
        if enable_auto:
            return "auto"

        if strategy == "advantage":
            point = self.maa.template_match(
                cfg.get("advantage_template", "battle/ui有利.png"),
                threshold=0.7,
            )
            if point:
                self.maa.click(Point(point.x, point.y))
                time.sleep(0.35)
                self.maa.click(Point(point.x, point.y))
                return "advantage"

        return ("fixed" if self.select_formation(
            self._formation_name(formation_name)) else "failed")

    def _formation_mode_state(self, allow_auto_without_title: bool = False):
        """先确认阵形选择页，再读取右上角当前模式。"""
        formation = self.config.get("formation", {})
        verify = formation.get("verify", {})
        verify_template = verify.get("template", "battle/ui阵形选择.png")
        verify_roi = roi_4to4(*verify.get("roi", [571, 5, 707, 44]))
        # 右上角模式按钮在整场战斗中常驻，不能单独作为阵形页判据。
        # 只有顶部红色“阵形选择”标题出现时，才允许切模式或点击阵形卡。
        mode = formation.get("auto_mode", {})
        roi = roi_4to4(*mode.get("roi", [840, 0, 980, 68]))
        auto_template = mode.get("auto_template", "battle/阵形选择自动.png")
        manual_template = mode.get("manual_template", "battle/阵形选择手动.png")
        threshold = float(mode.get("threshold", 0.9))
        title_visible = bool(self.maa.template_match(verify_template, verify_roi))
        # 两张图的上半截完全相同，实测整图相关度约 0.879；旧阈值 0.7 会让
        # “手动”继续命中“自动”，于是脚本在战斗中反复拨动按钮。
        if self.maa.template_match(auto_template, roi, threshold=threshold) and (
                title_visible or allow_auto_without_title):
            # 自动阵形会跳过选择页，因此切回手动时只能抓住常驻的自动状态按钮。
            # 调用方仅在“想要手动”时开启此例外；想保持自动时不会在战斗中反复处理。
            return "auto"
        if title_visible and self.maa.template_match(
                manual_template, roi, threshold=threshold):
            return "manual"
        return None

    def select_formation(self, formation_name: str) -> bool:
        """
        选择阵形

        Args:
            formation_name: 阵形名称，如 "鱼鳞阵", "雁行阵"

        Returns:
            是否选择成功
        """
        formation_name = self._formation_name(formation_name)
        formation_config = self.config.get("formation", {})

        # 必须同时看到顶部阵形页标题和右上角模式状态。
        if self._formation_mode_state() is None:
            print("[ERROR] 不在阵形选择界面")
            return False

        # 选择阵形
        formations = formation_config.get("formations", {})
        if formation_name in formations:
            self._click_point(formations[formation_name])
            time.sleep(0.3)

            # 如果需要双击
            if formation_config.get("double_click"):
                self._click_point(formations[formation_name])

            return True

        print(f"[ERROR] 未知阵形: {formation_name}")
        return False
