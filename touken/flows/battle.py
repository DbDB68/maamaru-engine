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

    def _wait_for_team_record_page(self, record_config: dict,
                                   attempts: int = 10) -> bool:
        """部队记录页同时有“进行记录”和“使用记录”，认任意一个即可。"""
        for _ in range(attempts):
            self.maa.screenshot(force=True)
            for key in ("save_confirm", "load_confirm"):
                button = record_config.get(key, {})
                template = button.get("template")
                if template and self.maa.template_match(template):
                    return True
            time.sleep(0.4)
        return False

    def _wait_team_select_after_record(self, cfg: dict,
                                       attempts: int = 12) -> bool:
        """保存/使用记录后必须确认回到部队选择，不能靠固定睡眠猜。"""
        team_ui = cfg.get("team_ui_ocr", {})
        roi_raw = team_ui.get("roi")
        expected = team_ui.get("expected", "部队选择")
        if not roi_raw:
            return False
        roi = roi_4to4(*roi_raw)
        for _ in range(attempts):
            self.maa.screenshot(force=True)
            if self.maa.ocr(expected, roi):
                return True
            time.sleep(0.5)
        return False

    def _open_team_record(self) -> bool:
        """从部队选择/编成页打开共用部队记录。"""
        record = self.config.get("team_select", {}).get("team_record", {})
        button = record.get("button", {})
        if not button or not self._click_template_config(button):
            return False
        time.sleep(0.8)
        return self._wait_for_team_record_page(record)

    def _finish_team_record(self, cfg: dict, record: dict) -> bool:
        """确认回到部队选择；保存记录不自动退页时，安全点左上返回。"""
        if self._wait_team_select_after_record(cfg, attempts=4):
            return True
        if not self._wait_for_team_record_page(record, attempts=1):
            return False
        back = record.get("back", [73, 31])
        self._click_point(back.get("target", [73, 31])
                          if isinstance(back, dict) else back)
        time.sleep(0.8)
        return self._wait_team_select_after_record(cfg, attempts=8)

    def _confirm_team_record(self, record: dict, action: str,
                             record_no: int = 1) -> bool:
        """确认保存/使用记录；模板失败时只在验明弹窗正文后用固定按钮位。"""
        self.maa.screenshot(force=True)
        yes_cfg = record.get("yes_button", {})
        yes_roi_raw = yes_cfg.get("roi", [650, 430, 920, 590])
        yes_roi = roi_4to4(*yes_roi_raw)
        template = yes_cfg.get("template", "team/是.png")
        yes = self.maa.template_match(template, yes_roi, threshold=0.65)
        if yes:
            self.maa.click(yes)
            return True

        # 游戏更新会微调按钮皮肤，旧模板可能失效。固定坐标只能在 OCR 同时
        # 认出弹窗标题、动作和记录一时使用，绝不能见到任意“是”就点。
        modal_roi = roi_4to4(*record.get("confirm_ocr_roi", [330, 130, 950, 590]))
        tokens = self.maa.ocr_all(modal_roi)
        text = "".join(str(token) for token, _ in tokens).replace(" ", "")
        action_text = "记录到" if action == "save" else "使用"
        record_labels = ("记录部队一", "记录部队1") if record_no == 1 else (
            f"记录部队{record_no}",)
        guarded = ("部队记录" in text and "是否" in text
                   and action_text in text
                   and any(label in text for label in record_labels))
        if not guarded:
            return False

        ocr_yes = self.maa.ocr("是", yes_roi, match_mode="exact")
        self.maa.click(ocr_yes or Point(784, 510))
        return True

    def _save_team_record(self, cfg: dict, record_no: int = 1) -> bool:
        """把当前出阵部队保存到固定记录；目前产品只使用记录一。"""
        record = self.config.get("team_select", {}).get("team_record", {})
        if not self._open_team_record():
            return False
        target = record.get("records", {}).get(str(record_no))
        if target:
            self._click_point(target)
            time.sleep(0.3)
        if not self._click_template_config(record.get("save_confirm", {})):
            return False
        time.sleep(0.5)
        if not self._confirm_team_record(record, "save", record_no):
            return False
        if not self._finish_team_record(cfg, record):
            return False
        if hasattr(self, "record_event"):
            self.record_event("team_record.saved", record_no=record_no)
        return True

    def _restore_equipment_from_warning(self, cfg: dict,
                                        record_no: int = 1) -> bool | None:
        """空刀装警告 → 整备刀装 → 使用记录一 → 回部队选择。

        None 表示没有警告；False 表示确有警告但恢复链路失败。
        """
        warning = cfg.get("equip_warning_button", {}).get("template")
        if not warning or not self.maa.template_match(warning):
            return None
        prepare = cfg.get("equip_warning_prepare", {}).get(
            "template", "team/整备刀装.png")
        prepare_pt = self.maa.template_match(prepare)
        if not prepare_pt:
            return False
        self.maa.click(prepare_pt)
        time.sleep(1.0)

        record = self.config.get("team_select", {}).get("team_record", {})
        # “整备刀装”落在部队编成页，等右侧部队记录按钮真正可点。
        opened = False
        for _ in range(12):
            self.maa.screenshot(force=True)
            if self._click_template_config(record.get("button", {})):
                opened = True
                break
            time.sleep(0.5)
        if not opened or not self._wait_for_team_record_page(record):
            return False

        target = record.get("records", {}).get(str(record_no))
        if target:
            self._click_point(target)
            time.sleep(0.3)
        if not self._click_template_config(record.get("load_confirm", {})):
            return False
        time.sleep(0.5)
        if not self._confirm_team_record(record, "load", record_no):
            return False
        if not self._finish_team_record(cfg, record):
            return False
        if hasattr(self, "record_event"):
            self.record_event("equipment.restored", record_no=record_no)
        return True

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
        # 三种伤势章版式几乎一样：实测中伤章能以 0.704 擦线命中重伤模板。
        # 模板只搜六行头像右缘的伤势章窄栏，并使用分类阈值；下方 OCR 仍看
        # 完整我方区域，作为模板漏识别时的文字兜底。
        stamp_roi = roi_4to4(*cfg.get("injury_stamp_roi", [220, 90, 340, 690]))
        stamps = cfg.get("injury_stamps", {})
        for severity in ("重伤", "中伤", "轻伤"):
            stamp_cfg = stamps.get(severity, {})
            template = stamp_cfg.get("template")
            threshold = float(stamp_cfg.get("threshold", 0.88))
            if template and self.maa.template_match(
                    template, stamp_roi, threshold=threshold):
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

    def _deny_heavy_injury_warning(self, cfg: dict) -> bool:
        """识别重伤继续警告并永远点“否”；仅在战斗决策点调用。"""
        deny_cfg = cfg.get("injury_deny_button", {})
        template = deny_cfg.get("template")
        if not template:
            return False
        roi_raw = deny_cfg.get("roi", [330, 400, 650, 620])
        deny = self.maa.template_match(
            template, roi_4to4(*roi_raw),
            threshold=float(deny_cfg.get("threshold", 0.75)))
        if not deny:
            return False
        self.maa.click(deny)
        time.sleep(0.8)
        if hasattr(self, "record_event"):
            self.record_event("injury_warning.denied", severity="heavy")
        return True

    # ==================== 通用安全出阵链 ====================

    def _safe_depart_stream(self, cfg: dict, team_no: int, tag: str,
                            repair_threshold: str = "light",
                            auto_equip: bool = False,
                            team_record_saved: bool = False,
                            auto_refill: bool = False):
        """通用安全出阵链：部队选择页已打开之后调用，串起——

        选择部队 → 出阵前伤势检查 → （可选）保存记录一 → 即刻出阵 →
        票尽补票弹窗（可选，异去同款交互：点确定补一张 → 重新出阵）→
        刀装未满警告处理（自动恢复或安全取消）→ 重伤确认弹窗拦截。

        各玩法只负责把部队选择页打开、以及之后自己的二次确认与入图验证；
        中间的人身安全语义全在这里，不准各玩法再自己手搓一遍。

        补票弹窗认 cfg["ticket_refill"]：popup/confirm_button/cancel_button
        三个模板。没配 popup 模板就不认（票尽时二次确认会等不到，安全停）。
        每圈最多补一张（refill_done），补完又弹说明没补上，停手防重复消费。

        Yields 日志；返回 (ok, team_record_saved)。ok=False 表示已安全
        停下（没出发），调用方直接收工，不要再点任何确认。
        """
        # 调用方已经通过 _wait_for_team_select 确认进入部队选择页，并在
        # 启动时检查过部队坐标。_pick_team 只负责按坐标点两次，本身无法
        # 观察游戏是否真的选中；不要把它的返回值冒充真机选队验证。
        self._pick_team(team_no)
        self.maa.screenshot(force=True)
        injury = self._team_injury_status(cfg)
        if injury and self._injury_reaches_threshold(
                injury, repair_threshold):
            yield f"{tag} 出阵前检测到{injury}，已达到停止条件，本次不出阵"
            return False, team_record_saved
        if auto_equip and not team_record_saved:
            yield f"{tag} 自动补充刀装已开启，先把当前部队保存到记录一"
            if self._save_team_record(cfg, record_no=1):
                team_record_saved = True
                yield f"{tag} ✓ 当前部队已保存到记录一"
            else:
                yield (f"{tag} ⚠️ 没能安全保存记录一，已停止；"
                       "请查看是否有确认弹窗未处理")
                return False, team_record_saved

        equip_retries = 0
        refill_done = False
        while True:
            if not self._click_depart(cfg):
                yield f"{tag} 找不到即刻出阵按钮"
                return False, team_record_saved
            self.maa.screenshot(force=True)

            # 票尽时游戏自己弹补票窗（不用提前数票）：认出来才处理，
            # 不补就点取消收工；补就点确定，然后重新点即刻出阵。
            refill = cfg.get("ticket_refill", {})
            popup_template = refill.get("popup", {}).get("template")
            if popup_template and self.maa.template_match(popup_template):
                if not auto_refill or refill_done:
                    if refill_done:
                        yield (f"{tag} 补票后仍弹补票窗，停止点击，"
                               "防止重复消费小判")
                        return False, team_record_saved
                    cancel_template = refill.get(
                        "cancel_button", {}).get("template")
                    cancel = (self.maa.template_match(cancel_template)
                              if cancel_template else None)
                    if cancel:
                        self.maa.click(cancel)
                        time.sleep(1.0)
                        yield f"{tag} 票用完了，不补票，已取消出阵，收工"
                    else:
                        yield (f"{tag} 票用完了，不补票；已停止点击，"
                               "请手动关掉购票弹窗")
                    return False, team_record_saved
                confirm_template = refill.get(
                    "confirm_button", {}).get("template")
                confirm = (self.maa.template_match(confirm_template)
                           if confirm_template else None)
                if not confirm:
                    yield (f"{tag} 补票弹窗的确定按钮没认出，停止点击，"
                           "请手动看一眼")
                    return False, team_record_saved
                self.maa.click(confirm)
                time.sleep(1.5)
                refill_done = True
                if hasattr(self, "record_event"):
                    self.record_event("ticket.refilled",
                                      source=tag.strip("[]"))
                yield f"{tag} 🎫 票已用小判补上一张，重新点即刻出阵"
                continue

            if auto_equip:
                equip_result = self._restore_equipment_from_warning(
                    cfg, record_no=1)
                if equip_result is None:
                    break
                if not equip_result:
                    yield f"{tag} 刀装有空缺，但从记录一恢复失败，停止出阵"
                    return False, team_record_saved
                equip_retries += 1
                yield f"{tag} 🛡️ 刀装有空缺，已使用记录一自动补齐"
                if equip_retries >= 2:
                    yield f"{tag} 恢复刀装后仍出现空缺警告，停止重试"
                    return False, team_record_saved
                self.maa.screenshot(force=True)
                restored_injury = self._team_injury_status(cfg)
                if restored_injury and self._injury_reaches_threshold(
                        restored_injury, repair_threshold):
                    yield f"{tag} 恢复刀装后检测到{restored_injury}，不再出阵"
                    return False, team_record_saved
                continue
            equip_cancelled = self._cancel_equip_warning(cfg)
            if equip_cancelled is None:
                break
            yield (f"{tag} 刀装未满，已进入整备，本次停止" if equip_cancelled
                   else f"{tag} 刀装未满且无法安全进入整备，停止")
            return False, team_record_saved
        if self._deny_heavy_injury_warning(cfg):
            yield f"{tag} 队员重伤确认弹窗，已点【否】；有重伤绝不出阵"
            return False, team_record_saved
        return True, team_record_saved

    def _confirm_departure(self, cfg: dict) -> bool:
        """通用出阵二次确认：认弹窗标题后点确认按钮。

        已用专属标题确认弹窗后，模板失配时才允许点实测坐标兜底
        （比如大阪城确认窗的绿色“确定”与通用灰按钮不是同一皮肤）；
        没配 target 的玩法只用模板，绝不盲点。
        """
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
                target = confirm.get("target")
                if target:
                    self._click_point(target)
                    time.sleep(1.5)
                    return True
            time.sleep(0.5)
        return False

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
        """旧调用兼容：加载部队记录（新战斗流程使用带验证的恢复方法）。"""
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

    def choose_formation(self, formation_name: str = "逆行阵",
                         enable_auto: bool = False) -> str:
        """读取右上角状态，按需要切换自动/手动；轮到脚本选阵形时：
        手动模式固定点指定阵形；自动模式（游戏抓瞎、脚本兜底时）先认
        「有利」标记，认不出再点指定阵形。"""
        cfg = self.config.get("formation", {})
        mode = cfg.get("auto_mode", {})
        current = self._formation_mode_state(
            allow_auto_without_title=not enable_auto)
        if current is None:
            # 阵形页进场动画里，顶部红色大标题比右上角模式按钮晚渲染一两秒，
            # 刚侦测到页面就读状态会空手而归（江户城实测：页面明明卡在
            # 选择页，标题未到 → 一秒误判 failed 中止战斗）。给几秒重试。
            deadline = time.monotonic() + 5.0
            while current is None and time.monotonic() < deadline:
                time.sleep(0.5)
                self.maa.screenshot(force=True)
                current = self._formation_mode_state(
                    allow_auto_without_title=not enable_auto)
            if current is None:
                return "failed"
        wanted = "auto" if enable_auto else "manual"
        toggled = False
        if current != wanted:
            self._click_point(mode.get("toggle", [910, 32]))
            time.sleep(0.6)
            toggled = True
            if wanted == "manual":
                # 拨成手动后阵型页会重绘，等红色大标题稳定两帧再点卡，
                # 否则点击全落在重绘动画上（江户城实测：双击被吞、页面卡死）。
                # 等不到说明游戏已经自动选完开打，这时再点卡面就是盲点
                # 战斗画面，如实交给调用方按"游戏自动阵形"处理。
                if not self._wait_formation_title_stable():
                    return "auto"
        if enable_auto:
            if toggled:
                # 刚拨成自动，剩下的交给游戏，不插手。
                return "auto"
            # 已经是自动、选择页却还挂着：索敌失败时敌方阵形「不明」，
            # 游戏没东西可选，会卡在页面上等手动（索敌看数值，白天图也会
            # 失败，不是夜战专利）。这时脚本兜底：先认「有利」标记，
            # 认不出（没有利可认）再点兜底阵形。
            verify = cfg.get("verify", {})
            title_visible = bool(self.maa.template_match(
                verify.get("template", "battle/ui阵形选择.png"),
                roi_4to4(*verify.get("roi", [571, 5, 707, 44]))))
            if not title_visible:
                return "auto"
            point = self.maa.template_match(
                cfg.get("advantage_template", "battle/ui有利.png"),
                threshold=0.7,
            )
            if point:
                self.maa.click(Point(point.x, point.y))
                time.sleep(0.6)
                self.maa.click(Point(point.x, point.y))
                return "advantage"

        return ("fixed" if self.select_formation(
            self._formation_name(formation_name), verified=True) else "failed")

    def _wait_formation_title_stable(self, timeout_s: float = 6.0,
                                     stable_hits: int = 2) -> bool:
        """等顶部红色「阵形选择」大标题连续命中，确认页面真加载完了。

        进战斗/切模式时页面有进场和重绘动画，单帧命中或未命中都可能是
        动画中间态（江户城实测：动画期截图标题未命中，被误判成"已离开"）。
        """
        verify = self.config.get("formation", {}).get("verify", {})
        template = verify.get("template", "battle/ui阵形选择.png")
        roi = roi_4to4(*verify.get("roi", [571, 5, 707, 44]))
        hits = 0
        deadline = time.monotonic() + timeout_s
        while time.monotonic() < deadline:
            self.maa.screenshot(force=True)
            if self.maa.template_match(template, roi):
                hits += 1
                if hits >= stable_hits:
                    return True
            else:
                hits = 0
            time.sleep(0.4)
        return False

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

    def select_formation(self, formation_name: str, verified: bool = False) -> bool:
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
        if not verified and self._formation_mode_state() is None:
            print("[ERROR] 不在阵形选择界面")
            return False

        # 选择阵形
        formations = formation_config.get("formations", {})
        if formation_name in formations:
            target = formations[formation_name]
            if not formation_config.get("double_click"):
                self._click_point(target)
                time.sleep(0.3)
                return True

            # 点两下同一张阵形卡：第一下选中、第二下即确定（和部队选择同一交互，
            # 选中不联网、确定才发送）。不再戳卡内"确定"热点的偏移坐标——
            # 旧偏移实测擦着按钮下沿点空，阵形页不走导致整场卡死。
            # 两下之间留 0.6s 给页面响应：快速双击会被当成一下吞掉（老大实测）。
            # 每轮点完验证页面是否离开，要求连续两帧都看不到阵形页才算真走——
            # 单帧未命中可能只是页面还在动画里（江户城实测误判翻车）。
            # 三轮还不走如实报错，交给调用方停止这场，绝不盲信一次必中。
            for _ in range(3):
                self._click_point(target)
                time.sleep(0.6)
                self._click_point(target)
                time.sleep(0.8)
                gone = True
                for _ in range(2):
                    self.maa.screenshot(force=True)
                    if self._formation_mode_state() is not None:
                        gone = False
                        break
                    time.sleep(0.4)
                if gone:
                    return True
            print(f"[ERROR] 阵形 {formation_name} 点两下后仍未离开选择页")
            return False

        print(f"[ERROR] 未知阵形: {formation_name}")
        return False
