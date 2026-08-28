# -*- coding: utf-8 -*-
"""
上层业务：江户城潜入调查（edocastle）

玩法（老大口述 + 踩点素材）：
  本丸→出阵→活动入口→江户城标题确认→难度四卡片→部队选择→即刻出阵
  →确认弹窗→地图屏→按巡游策略点节点→战斗/钥匙/空点分支→王点战胜
  →「调查完了！」横幅→结算→回入场屏→下一圈（令牌够的话）

安全规矩：
  - v1 只做难度四，不主动用道具，不主动返回本丸
  - 出阵走 BattleMixin 的通用安全出阵链（_safe_depart_stream）：选队验证、
    出阵前伤势检查、刀装未满处理、重伤弹窗拦截一个不少；二次确认用通用
    _confirm_departure。虚拟伤害活动不碎刀，默认只拦重伤（repair_threshold
    =heavy），中伤照跑
  - 步数/钥匙靠 HUD OCR；当前位置靠流程自己记账
  - 票尽不数令牌格：游戏自己会弹补票窗，安全链按 auto_refill 处理
    （确定补一张再出阵 / 取消收工，异去同款交互）
  - 败北/意外回入场屏按前后钥匙差记账并停
"""

import re
import time
from pathlib import Path

from ..edo_route import EDOCASTLE_TOUR, decide_next, load_archive
from ..maa_adapter import roi_4to4


class EdocastleMixin:
    """江户城潜入调查流程。依赖宿主类的 navigate_to_stream、_click_point、
    choose_formation、_safe_depart_stream、_confirm_departure。"""

    def edocastle_stream(
        self,
        team_no: int = None,
        use_koban_refill: bool = None,
        max_runs: int = None,
        formation_mode: str = "manual",
        formation: str = "鱼鳞阵",
        repair_threshold: str = None,
        auto_equip: bool = None,
        debug_dir: str = None,
        **kwargs,
    ):
        """
        流式刷江户城潜入调查（难度四·超难）

        Args:
            team_no: 部队编号，默认读配置 edocastle.team_no
            use_koban_refill: 票尽时是否用小判补票（走游戏自己的补票弹窗：
                出阵→确定补一张→再出阵），默认读配置 edocastle.use_koban_refill
            max_runs: 最多跑几圈（0=票尽为止），默认读配置 edocastle.max_runs
            formation_mode: "manual"/"auto"，复用合战场阵型选择
            formation: 固定阵型名
            repair_threshold: 出阵前伤势停止线（light/medium/heavy），
                默认读配置 edocastle.repair_threshold（"heavy"：虚拟伤害活动
                不碎刀，中伤照跑，只拦重伤）
            auto_equip: 刀装有空缺时是否用记录一自动补齐，
                默认读配置 edocastle.auto_equip（v1 保守默认 False=安全取消）
        """
        cfg = self.config.get("edocastle", {})
        if not cfg:
            yield "[江户城] 未配置江户城潜入调查"
            return

        team_no = team_no if team_no is not None else cfg.get("team_no", 3)
        if use_koban_refill is None:
            use_koban_refill = bool(cfg.get("use_koban_refill", False))
        if max_runs is None:
            max_runs = int(cfg.get("max_runs", 0))
        if repair_threshold is None:
            repair_threshold = str(cfg.get("repair_threshold", "heavy"))
        if auto_equip is None:
            auto_equip = bool(cfg.get("auto_equip", False))

        teams = self.config.get("team_select", {}).get("teams", {})
        if str(team_no) not in teams:
            yield f"[江户城] 配置里没有部队{team_no}的坐标"
            return

        archive_path = cfg.get("map_archive")
        if not archive_path:
            yield "[江户城] 未配置地图档案路径"
            return
        archive_path = Path(archive_path)
        if not archive_path.is_absolute():
            # 地图档案是程序资源（跟模板图一样捆在 bundle 里），
            # 不能拿用户数据目录当根（实测翻车：_root 是数据目录）
            from ..runtime_paths import BUNDLE_ROOT
            archive_path = BUNDLE_ROOT / archive_path
        try:
            archive = load_archive(archive_path)
        except Exception as exc:
            yield f"[江户城] 加载地图档案失败：{exc}"
            return

        tour = cfg.get("tour", EDOCASTLE_TOUR)
        boss = archive.get("boss", 2)
        skip_point = cfg.get("skip_tap", [775, 695])

        # ========== 1. 导航到出阵 ==========
        yield "[江户城] 正在导航到出阵…"
        for nav_msg in self.navigate_to_stream("出阵"):
            yield nav_msg
        if self.current_location != "出阵":
            yield "[江户城] 到达出阵失败"
            return

        # ========== 2. 进入活动界面 ==========
        entered = False
        for _ in range(8):
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
            yield "[江户城] 进不去活动界面，停"
            return
        yield "[江户城] 到达江户城潜入调查入口"
        self.set_progress("edocastle")

        # ========== 3. 主循环：一圈一圈跑 ==========
        runs_done = 0
        total_keys = 0
        team_record_saved = False
        while True:
            if max_runs > 0 and runs_done >= max_runs:
                yield f"[江户城] 已达最大圈数 {max_runs}，收工"
                break

            # 读入场屏钥匙总数（本圈 before）
            keys_before = self._read_key_total(cfg)
            if keys_before is None:
                yield "[江户城] 入场屏钥匙总数读不出，停"
                return
            yield f"[江户城] 本丸钥匙家底：{keys_before} 把"

            yield f"[江户城] ⚔️ 第 {runs_done + 1} 圈开场"

            # 每圈重新点难度四卡片→部队选择→通用安全出阵链→二次确认。
            # 票尽时游戏会自己弹补票窗，由安全链按 auto_refill 处理
            # （确定补一张再出阵 / 取消收工），不用提前数令牌。
            entered, team_record_saved = yield from self._enter_map_stream(
                cfg, team_no, skip_point,
                repair_threshold, auto_equip, team_record_saved,
                auto_refill=use_koban_refill)
            if not entered:
                yield "[江户城] 没能进地图，安全收工"
                break

            # ========== 4. 地图巡游 ==========
            run_keys, ok = yield from self._map_run_stream(
                cfg, archive, tour, boss, skip_point,
                formation_mode, formation,
                debug_dir,
            )

            # 无论正常结算还是败北/意外回城，都先尝试回到入场屏记账
            if not ok:
                yield "[江户城] 本圈异常，看看是不是还在地图里…"
                if self._in_map(cfg):
                    yield "[江户城] 还站在地图里，走「返回本丸」撤退"
                    yield from self._bail_out_stream(cfg)
                elif self._formation_mode_state() is not None:
                    # 卡在阵型选择页：战斗里没有撤退按钮，只能打完再走撤退。
                    # 这会页面早过了进场动画，再试一次选阵型通常能成。
                    yield "[江户城] 卡在阵型选择页，再试一次把这场打完"
                    if self._fight_one_battle(
                            cfg, formation_mode,
                            formation, skip_point):
                        if self._wait_map_landmark(cfg, timeout_s=30):
                            yield from self._bail_out_stream(cfg)
                        else:
                            yield "[江户城] 战斗打完没回到地图，停"
                    else:
                        yield "[江户城] 阵型还是选不动，停在战斗里了，需要手动看一眼"

            if not self._wait_entry_screen(cfg, skip_point, timeout_s=30):
                yield "[江户城] 结算后没回到入场屏，停"
                return

            keys_after = self._read_key_total(cfg)
            if keys_after is None:
                # 用流程内部估算兜底
                keys_after = keys_before + max(0, run_keys)
                yield f"[江户城] 结算后钥匙总数没读到，按 HUD 估算 {keys_after} 把"
            delta = keys_after - keys_before
            total_keys += delta
            period = f"江户城潜入调查@{time.strftime('%Y-%m-%d')}"
            if hasattr(self, "record_event"):
                self.record_event(
                    "edocastle.run_completed",
                    keys=delta,
                    period=period,
                    difficulty=4,
                    run_no=runs_done + 1,
                    team_no=team_no,
                )
            if ok:
                yield (
                    f"[江户城] ✓ 第 {runs_done + 1} 圈收工，本圈钥匙 {delta:+d} "
                    f"（累计 {total_keys} 把）"
                )
            else:
                yield (
                    f"[江户城] ⚠️ 第 {runs_done + 1} 圈意外结束，本圈钥匙 {delta:+d}，"
                    "先停下了"
                )
                return
            runs_done += 1

        yield (
            f"[江户城] 收工，跑了 {runs_done} 圈，合计带回 {total_keys} 把钥匙"
        )

    # ---------- 内部：入场 → 地图 ----------

    def _enter_map_stream(self, cfg: dict, team_no: int,
                          skip_point: list, repair_threshold: str,
                          auto_equip: bool, team_record_saved: bool,
                          auto_refill: bool = False):
        """在入场屏点击难度卡片→部队选择→通用安全出阵链→二次确认，直到地图屏。

        选队、伤势检查、刀装处理、重伤拦截全部走 BattleMixin 的
        _safe_depart_stream，江户城只负责入口导航和入图验证。
        返回 (entered, team_record_saved)。
        """        # 点难度四卡片
        self._click_point(cfg["difficulty_card"]["target"])
        time.sleep(1.5)

        # 部队选择按钮
        deploy = self.maa.template_match(cfg["deploy_button"]["template"])
        if not deploy:
            yield "[江户城] 没找到部队选择按钮"
            return False, team_record_saved
        self.maa.click(deploy)
        time.sleep(1.5)

        if not self._wait_for_team_select(cfg, attempts=10):
            yield "[江户城] 部队选择界面没打开"
            # 驱散可能弹窗
            self.skip_safe(2, point=skip_point)
            return False, team_record_saved

        ok, team_record_saved = yield from self._safe_depart_stream(
            cfg, team_no, "[江户城]",
            repair_threshold=repair_threshold,
            auto_equip=auto_equip,
            team_record_saved=team_record_saved,
            auto_refill=auto_refill)
        if not ok:
            return False, team_record_saved

        # 江户城没有手形和自动行军；通用二次确认（模板优先，未配兜底坐标）
        if not self._confirm_departure(cfg):
            yield "[江户城] 没看到出阵二次确认，停止点击"
            return False, team_record_saved

        # 验证进地图
        if not self._wait_map_landmark(cfg, timeout_s=15):
            yield "[江户城] 没进地图屏，停"
            return False, team_record_saved
        return True, team_record_saved

    # ---------- 内部：地图巡游核心 ----------

    def _map_run_stream(
        self,
        cfg: dict,
        archive: dict,
        tour: list,
        boss: int,
        skip_point: list,
        formation_mode: str,
        formation: str,
        debug_dir: str = None,
    ):
        """
        在地图屏走一圈，直到王点战胜。

        Yields 状态消息；返回 (run_keys_estimate, ok)。
        run_keys_estimate 是 HUD 读到的钥匙增量估算（结算差值优先，这里只是兜底）。
        """
        # 进场后当前点已经是 20；21 是视觉起点
        current = 20
        visited = {21, current}
        steps = self._read_hud_steps(cfg)
        if steps is None:
            yield "[江户城] 刚进地图就读不出剩余步数，停"
            return 0, False
        yield f"[江户城] 地图加载完成，当前在 {current}，剩余 {steps} 步"

        keys_start = self._read_hud_keys(cfg) or 0
        last_progress = time.monotonic()
        safe_steps = 0
        ocr_misses = 0

        while True:
            # 无进展看门狗：120 秒没走到下一步/没打完，停
            if time.monotonic() - last_progress > 120:
                yield (
                    f"[江户城] ⚠️ 已 {int(time.monotonic() - last_progress)} 秒没进展，"
                    "疑似卡住，停"
                )
                return 0, False

            visited.add(current)
            if current == boss:
                # 王点战斗已结束，等横幅
                yield "[江户城] 到王点了，等结算横幅…"
                if not self._wait_round_end(cfg, skip_point, timeout_s=30):
                    yield "[江户城] 没等到『调查完了！』横幅，停"
                    return 0, False
                # 点掉横幅和后续结算动画
                self.skip_safe(5, point=skip_point)
                keys_end = self._read_hud_keys(cfg)
                delta = (keys_end - keys_start) if keys_end is not None else 0
                return delta, True

            nxt, mode = decide_next(archive, tour, current, visited, steps)
            coord = self._node_coordinate(archive, nxt)
            if coord is None:
                yield f"[江户城] 档案里找不到节点 {nxt} 的坐标，停"
                return 0, False

            yield f"[江户城] 在 {current}（剩 {steps} 步），{mode} 去 {nxt} {coord}"
            self._click_point(coord)
            time.sleep(1.5)

            # 判断是战斗还是非战斗
            formation_appeared = self._wait_formation_page(
                cfg, timeout_s=5, skip_point=skip_point,
                formation_mode=formation_mode,
            )

            if formation_appeared:
                yield "[江户城] 紫点战斗，选阵型开打"
                if not self._fight_one_battle(
                    cfg, formation_mode, formation, skip_point
                ):
                    yield "[江户城] 战斗处理失败，停"
                    return 0, False

                if nxt == boss:
                    # 王点战结束等横幅
                    if not self._wait_round_end(cfg, skip_point, timeout_s=30):
                        yield "[江户城] 王点战后没等到『调查完了！』，停"
                        return 0, False
                    self.skip_safe(5, point=skip_point)
                    keys_end = self._read_hud_keys(cfg)
                    delta = (keys_end - keys_start) if keys_end is not None else 0
                    return delta, True

                # 非王点战斗后等回地图
                if not self._wait_map_landmark(cfg, timeout_s=20):
                    yield "[江户城] 战斗后没回到地图，停"
                    return 0, False
            else:
                # 钥匙/空点，等地图屏
                if not self._wait_map_landmark(cfg, timeout_s=12):
                    # 也可能formation出现得慢，再验一次
                    self.maa.screenshot(force=True)
                    if self._formation_mode_state(
                        allow_auto_without_title=formation_mode != "auto"
                    ) is not None:
                        yield "[江户城] 原来是战斗点，只是 formation 出现慢了"
                        if not self._fight_one_battle(
                            cfg, formation_mode, formation, skip_point
                        ):
                            yield "[江户城] 战斗处理失败，停"
                            return 0, False
                        if not self._wait_map_landmark(cfg, timeout_s=20):
                            yield "[江户城] 战斗后没回到地图，停"
                            return 0, False
                    else:
                        yield "[江户城] 点完节点地图没回来，停"
                        return 0, False
                else:
                    node_kind = "黄点钥匙" if self._looks_like_key_node(cfg) else "空点"
                    yield f"[江户城] {node_kind}，继续逛"

            current = nxt
            new_steps = self._read_hud_steps(cfg)
            if new_steps is None:
                # 悲观兜底：按"这一步没回步数"估算继续走。移动必扣 1、
                # 回步只加不减，所以 估算<=真实，低估只会提前收头奔王点，
                # 绝不会走死。连续 3 次都读不出说明真瞎了，停。
                ocr_misses += 1
                self._save_debug_shot(debug_dir, f"steps_ocr_miss{ocr_misses}")
                if ocr_misses >= 3:
                    yield "[江户城] 连续读不出剩余步数，太瞎了，停"
                    return 0, False
                new_steps = max(0, steps - 1)
                yield (
                    f"[江户城] 步数读不出，按悲观估算 {new_steps} 步继续"
                    "（现场截图已存）"
                )
            else:
                ocr_misses = 0
            steps = new_steps
            last_progress = time.monotonic()
            safe_steps += 1
            if safe_steps > 60:
                yield "[江户城] 单圈步数超过安全上限，停"
                return 0, False

    # ---------- 内部：单场战斗 ----------

    def _wait_formation_page(self, cfg: dict, timeout_s: float = 5.0,
                             skip_point: list = None,
                             formation_mode: str = "manual") -> bool:
        """等阵形选择页出现；等不到返回 False。
        formation_mode 必须传运行时值：配置文件 edocastle 段没有这个键，
        读 cfg 永远拿到默认 manual（曾导致自动模式下也放行无标题判定）。"""
        deadline = time.monotonic() + timeout_s
        while time.monotonic() < deadline:
            self.maa.screenshot(force=True)
            if self._formation_mode_state(
                allow_auto_without_title=formation_mode != "auto"
            ) is not None:
                return True
            if skip_point:
                self._click_point(skip_point)
            time.sleep(0.6)
        return False

    def _fight_one_battle(self, cfg: dict, formation_mode: str,
                          formation: str,
                          skip_point: list) -> bool:
        """处理一场合战场式战斗：索敌→选阵型→等战斗结束。"""
        # 等阵形页稳一点
        if not self._wait_formation_page(cfg, timeout_s=10, skip_point=skip_point,
                                         formation_mode=formation_mode):
            return False

        result = self.choose_formation(
            formation_name=formation,
            enable_auto=(formation_mode == "auto"),
        )
        if result == "failed":
            return False

        # 等阵形页消失
        for _ in range(10):
            time.sleep(0.5)
            self.maa.screenshot(force=True)
            if self._formation_mode_state() is None:
                return True
        return False

    # ---------- 内部：识别与 OCR ----------

    def _read_hud_steps(self, cfg: dict) -> int | None:
        """读取地图屏左上角剩余行动回数。HUD 数字只有十几像素高，
        原生分辨率下检测器处于临界：同值同屏时好时坏（实测剩 2 步连读
        4 次全空）；ROI 裁块放大 3 倍后 218 帧录像回放 100% 读出。
        仍加重试兜底。"""
        ocr_cfg = cfg.get("hud_step_ocr", {})
        roi = roi_4to4(*ocr_cfg.get("roi", [25, 8, 200, 60]))
        upscale = int(ocr_cfg.get("upscale", 3))
        for _ in range(4):
            val = self._ocr_digits(roi, upscale=upscale)
            if val is not None:
                return val
            time.sleep(0.8)
        return None

    def _read_hud_keys(self, cfg: dict) -> int | None:
        """读取地图屏左上角当前持有钥匙数（HUD，同样的小数字，放大识别）。"""
        ocr_cfg = cfg.get("hud_key_ocr", {})
        roi = roi_4to4(*ocr_cfg.get("roi", [230, 8, 360, 60]))
        upscale = int(ocr_cfg.get("upscale", 3))
        for _ in range(3):
            val = self._ocr_digits(roi, upscale=upscale)
            if val is not None:
                return val
            time.sleep(0.6)
        return None

    def _read_key_total(self, cfg: dict) -> int | None:
        """读取入场屏钥匙总数。"""
        ocr_cfg = cfg.get("key_total_ocr", {})
        roi = roi_4to4(*ocr_cfg.get("roi", [920, 185, 1085, 225]))
        return self._ocr_digits(roi)

    def _ocr_digits(self, roi, upscale: int = 0) -> int | None:
        """OCR 区域内所有文字并提取最长连续数字串。

        upscale > 1：先把 ROI 从新截图裁出来放大再识别（治小数字临界）。
        """
        try:
            if upscale > 1:
                import cv2
                img = self.maa.screenshot(force=True)
                if img is None:
                    return None
                crop = img[roi.y:roi.y + roi.h, roi.x:roi.x + roi.w]
                if crop.size == 0:
                    return None
                up = cv2.resize(crop, None, fx=upscale, fy=upscale,
                                interpolation=cv2.INTER_CUBIC)
                tokens = self.maa.ocr_all(
                    roi_4to4(0, 0, up.shape[1], up.shape[0]), image=up)
            else:
                tokens = self.maa.ocr_all(roi)
            ordered = sorted(tokens or [], key=lambda row: getattr(row[1], "x", 0))
            digits = "".join(
                re.sub(r"\D", "", str(text)) for text, _ in ordered
            )
            return int(digits) if digits else None
        except Exception:
            return None

    def _looks_like_key_node(self, cfg: dict) -> bool:
        """粗略判断刚踩的节点是不是黄点钥匙：HUD 钥匙数 +1 且步数 +1。

        因为非战斗点有两种，这里只给日志用，不影响决策。
        """
        # v1 不细究，返回 False 让日志显示"空点/钥匙"
        return False

    def _save_debug_shot(self, debug_dir: str | None, name: str):
        """异常现场存证：优先 debug_dir，否则用户数据目录 debug/。"""
        try:
            out = Path(debug_dir) if debug_dir else Path(self._root) / "debug"
            out.mkdir(parents=True, exist_ok=True)
            self.maa.save_screenshot(
                str(out / f"edo_{name}_{time.strftime('%H%M%S')}.png"))
        except Exception:
            pass

    def _node_coordinate(self, archive: dict, node_id: int) -> list | None:
        for node in archive.get("nodes", []):
            if node["id"] == node_id:
                return [node["x"], node["y"]]
        return None

    def _wait_map_landmark(self, cfg: dict, timeout_s: float = 15.0) -> bool:
        """等地标『地图难度标签』出现。"""
        return self.wait_landmark_skipping(
            template=cfg["map_landmark"]["template"],
            skip_point=cfg.get("skip_tap"),
            timeout_s=timeout_s,
            stable_hits=1,
            interval=0.8,
        )

    def _wait_round_end(self, cfg: dict, skip_point: list,
                        timeout_s: float = 30.0) -> bool:
        """等『调查完了！』结算横幅。"""
        return self.wait_landmark_skipping(
            template=cfg["round_end"]["template"],
            skip_point=skip_point,
            timeout_s=timeout_s,
            stable_hits=1,
            interval=0.8,
        )

    def _wait_entry_screen(self, cfg: dict, skip_point: list,
                           timeout_s: float = 30.0) -> bool:
        """等回到入场屏标题。"""
        return self.wait_landmark_skipping(
            template=cfg["ui_title"]["template"],
            skip_point=skip_point,
            timeout_s=timeout_s,
            stable_hits=1,
            interval=0.8,
        )

    # ---------- 内部：地图内撤退 ----------

    def _in_map(self, cfg: dict) -> bool:
        """当前是否还停在地图屏（右侧难度标签为地标）。"""
        self.maa.screenshot(force=True)
        return bool(self.maa.template_match(cfg["map_landmark"]["template"]))

    def _bail_out_stream(self, cfg: dict):
        """地图内主动撤退：行动选择 tab → 返回本丸 → 是 → 点掉回城结算。

        坐标已实测（2026-08-27）：tab (1240,595)、返回本丸 (1050,429)、
        确认「是」(497,470)。主动回城只带回了了了几把钥匙（按规则打折），
        但比卡死在地图里强。
        """
        retreat = cfg.get("retreat", {})
        self._click_point(retreat.get("tab_point", [1240, 595]))
        time.sleep(1.5)
        self._click_point(retreat.get("home_button", [1050, 429]))
        time.sleep(1.5)
        self._click_point(retreat.get("confirm_yes", [497, 470]))
        time.sleep(3.0)
        # 「主动回城」结算屏点掉
        self.skip_safe(4, point=cfg.get("skip_tap", [775, 695]))
        yield "[江户城] 已主动回城（钥匙按规则打折，认栽）"
