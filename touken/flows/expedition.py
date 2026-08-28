# -*- coding: utf-8 -*-
"""
上层业务：远征（派遣）

流程（用户亲授教材）：
  目录 → 远征 → 选时代卡（固定坐标，一行五个，左右可翻页）
  → OCR 点小图名字（小图卡一行四张，名字是文字，不玩固定坐标）
  → 点"部队选择"按钮 → 常规部队选择界面 → 选部队 tab
  → 【保命】重伤检查，有重伤绝不派遣
  → 点"远征开始" → 二次确认弹窗点"确认"（道具复选框默认不勾）
  → "出发远征"卷轴过场（不用跳过，几秒自己完）
  → 验证：小图卡上"远征时间"变成红色"远征中"

备注：
  - 时代卡/小图卡坐标已实测校准；OCR 点名字和按卡位坐标点两种选图方式都支持。
  - 收菜（collect_expedition_stream）支持"收完顺手再派"：读结算界面上的
    "第X部队"和"时代-小图"编号，把回来的队派回去；也可按资源目标
    （小判/加速符等）自动挑时薪最高的图，数据来自 data/expedition_maps.json。
  - 远征界面底部右侧的"部队选择"按钮用右下角 OCR 双词确认，避免和
    "即刻出阵"按钮的相似皮肤串台。
"""

import json
import re
import time
from pathlib import Path

from ..runtime_paths import STATUS_DIR

from ..maa_adapter import roi_4to4

_MAPS_TABLE = Path(__file__).parent.parent / "data" / "expedition_maps.json"
_STATUS_DIR = STATUS_DIR
_EXP_RECORD = _STATUS_DIR / "expeditions.json"

_NUMERALS = {"一": 1, "二": 2, "三": 3, "四": 4, "五": 5}


def _load_exp_record() -> dict:
    try:
        if _EXP_RECORD.exists():
            return json.loads(_EXP_RECORD.read_text(encoding="utf-8"))
    except Exception:
        pass
    return {}


def _save_exp_record(rec: dict):
    try:
        _STATUS_DIR.mkdir(exist_ok=True)
        _EXP_RECORD.write_text(json.dumps(rec, ensure_ascii=False, indent=2),
                               encoding="utf-8")
    except Exception:
        pass


def _map_meta(era, slot):
    """按时代+卡位查收益表，拿图名和时长"""
    try:
        with open(_MAPS_TABLE, encoding="utf-8") as f:
            maps = json.load(f)["maps"]
        for code, v in maps.items():
            if v.get("era") == era and v.get("slot") == slot:
                return code, v.get("name"), v.get("duration_min")
    except Exception:
        pass
    return None, None, None


class ExpeditionMixin:
    """远征派遣。依赖宿主类的 navigate_to_stream、_click_point。"""

    def expedition_stream(self, era: int, map_name: str = None, team_no: int = 2,
                          map_slot: int = None):
        """
        流式派遣一支部队去远征

        Args:
            era: 时代编号（1-5，对应当前页一行五张时代卡；更多时代以后加翻页）
            map_name: 小图名字（OCR 匹配，如 "鸟羽·伏见"，包含匹配不用写全）
            team_no: 部队编号（1-5）。注意别派正在远征/有重伤的部队
            map_slot: 小图卡位（1-4，从左到右）。给了就按坐标点，
                      不给就走 OCR 点名字——算法派图用卡位，人点图用名字

        Yields:
            str: 执行状态消息
        """
        cfg = self.config.get("expedition", {})
        if not cfg:
            yield "[远征] 未配置远征"
            return

        teams = self.config.get("team_select", {}).get("teams", {})
        if str(era) not in cfg.get("eras", {}):
            yield f"[远征] 配置里没有时代{era}的坐标"
            return
        if str(team_no) not in teams:
            yield f"[远征] 配置里没有部队{team_no}的坐标"
            return

        # ========== 1. 导航到远征 ==========
        yield "[远征] 正在导航到远征..."
        for nav_msg in self.navigate_to_stream("远征"):
            yield nav_msg
        if self.current_location != "远征":
            yield "[远征] 到达远征失败"
            return
        time.sleep(1.0)

        # ========== 2. 选时代卡 ==========
        yield f"[远征] 🗺️ 翻去时代{era}..."
        self._click_point(cfg["eras"][str(era)])
        time.sleep(1.0)

        # ========== 3. 选小图：给了卡位按坐标点，没给就 OCR 点名字 ==========
        if map_slot is not None:
            slots = cfg.get("map_slots", {})
            if str(map_slot) not in slots:
                yield f"[远征] 配置里没有小图卡位{map_slot}的坐标"
                return
            yield f"[远征] 🗺️ 点小图卡位{map_slot}..."
            self._click_point(slots[str(map_slot)])
            time.sleep(1.0)
        elif map_name:
            yield f"[远征] 🔍 找小图「{map_name}」..."
            map_roi = roi_4to4(*cfg["map_ocr_roi"])
            map_pt = None
            for _ in range(6):
                self.maa.screenshot(force=True)
                map_pt = self.maa.ocr(expected=map_name, roi=map_roi)
                if map_pt:
                    break
                time.sleep(0.5)
            if not map_pt:
                yield f"[远征] 没找到小图「{map_name}」（名字写错了？时代不对？要翻页？），停"
                return
            self.maa.click(map_pt)
            time.sleep(1.0)
        else:
            yield "[远征] 既没给地图名字也没给卡位，不知道去哪，停"
            return

        # ========== 4. 点"部队选择" → 等部队选择界面 ==========
        ocr_cfg = cfg["team_ui_ocr"]
        team_roi = roi_4to4(*ocr_cfg["roi"])
        team_ui_ok = False
        for attempt in range(12):
            self.maa.screenshot(force=True)
            if self.maa.ocr(expected=ocr_cfg["expected"], roi=team_roi):
                team_ui_ok = True
                break
            # 前两次还没进就找"部队选择"按钮点（远征界面是按钮进入，不是直通）
            if attempt <= 3:
                deploy = self._find_deploy_button(cfg)
                if deploy:
                    self.maa.click(deploy)
                    time.sleep(1.5)
            time.sleep(0.5)
        if not team_ui_ok:
            yield "[远征] 部队选择界面没打开（条件不满足按钮可能是灰的？），停"
            return

        # ========== 5. 选部队 ==========
        self._click_point(teams[str(team_no)])
        time.sleep(0.3)
        self._click_point(teams[str(team_no)])
        time.sleep(0.5)

        # ========== 6. 【保命】重伤检查 ==========
        self.maa.screenshot(force=True)
        if self.maa.template_match(cfg["injury_stamp"]["template"]):
            yield "[远征] 🛑 检测到重伤标记！按规矩绝不派遣，停。去修刀吧"
            return

        # ========== 7. 点"远征开始" ==========
        start = self.maa.template_match(cfg["start_button"]["template"])
        if not start:
            start_ocr = cfg["start_ocr"]
            start = self.maa.ocr(expected=start_ocr["expected"],
                                 roi=roi_4to4(*start_ocr["roi"]))
        if not start:
            yield "[远征] 找不到远征开始按钮（条件不满足/部队已在远征？），停"
            return
        self.maa.click(start)
        time.sleep(1.5)

        # ========== 8. 二次确认弹窗：点"确认"（道具复选框不碰，默认不用） ==========
        confirm_ocr = cfg["confirm_ocr"]
        confirm = None
        for _ in range(8):
            self.maa.screenshot(force=True)
            confirm = self.maa.ocr(expected=confirm_ocr["expected"],
                                   roi=roi_4to4(*confirm_ocr["roi"]))
            if confirm:
                break
            time.sleep(0.5)
        if not confirm:
            yield "[远征] 确认弹窗没出现，停，你去看看卡哪了"
            return
        self.maa.click(confirm)
        yield "[远征] 🐎 确认完毕，出发远征！过场动画跑着..."

        # ========== 9. 过场自动完 → 验证"远征中" ==========
        running_ocr = cfg["running_ocr"]
        running_roi = roi_4to4(*running_ocr["roi"])
        for _ in range(20):  # 过场几秒，给足 10 秒
            time.sleep(0.5)
            self.maa.screenshot(force=True)
            if self.maa.ocr(expected=running_ocr["expected"], roi=running_roi):
                yield f"[远征] ✅ 部队{team_no}已出发：时代{era}「{map_name}」，收工"
                # 落盘派遣记录，看板倒计时用（写砸不影响派遣）
                try:
                    code, name, dur = _map_meta(era, map_slot)
                    rec = _load_exp_record()
                    rec[str(team_no)] = {
                        "map_code": code, "map_name": map_name or name,
                        "era": era, "slot": map_slot,
                        "duration_min": dur,
                        "dispatched_at": time.strftime("%Y-%m-%d %H:%M:%S"),
                    }
                    _save_exp_record(rec)
                except Exception:
                    pass
                if hasattr(self, "record_event"):
                    code, name, _ = _map_meta(era, map_slot)
                    self.record_event("expedition.dispatched", team_no=team_no,
                                      map_code=code, map_name=map_name or name,
                                      era=era, slot=map_slot)
                return

        # 过场后可能回了本丸也可能还在目的地界面，找不到"远征中"就截个图让人看
        yield "[远征] ⚠️ 没看到「远征中」字样，可能派遣失败也可能已回本丸，你去看一眼"
        return

    def collect_expedition_stream(self, redispatch=None):
        """
        流式收菜：领取远征完成的奖励

        原理（用户亲授）：远征完成后，【重新进入本丸场景】会自动播放
        「远征归来」横幅 → 点一下进「远征结果」结算 → 再点翻页，
        多支队伍同时回来就多张结算连翻，翻完回到本丸。

        所以流程：远征界面 → 回本丸（强制换场景触发动画）→ 循环
        识别横幅/结算并点过，直到确认站在本丸且无事发生。

        Args:
            redispatch: 收完顺手再派的模式
                None   = 只收不派（默认）
                "same" = 哪支队回来就把哪支队派回原来那张图
                资源名  = "小判"/"加速符"/"委托符"/"木炭"/"玉钢"/"冷却材"/"砥石"
                          回来的队全部派去该资源时薪最高的图
                          （收益表 data/expedition_maps.json）

        Yields:
            str: 执行状态消息
        """
        cfg = self.config.get("expedition", {})
        if not cfg:
            yield "[收菜] 未配置远征"
            return

        banner_ocr = cfg["return_banner_ocr"]
        banner_roi = roi_4to4(*banner_ocr["roi"])
        title_ocr = cfg["result_title_ocr"]
        title_roi = roi_4to4(*title_ocr["roi"])
        tap = cfg["collect_tap"]
        home_tpl = cfg["home_ui"]["template"]

        # ========== 1. 换场景回本丸，触发归来动画 ==========
        yield "[收菜] 🧺 先绕去远征界面再回本丸，勾一下归来动画..."
        for nav_msg in self.navigate_to_stream("远征"):
            yield nav_msg
        if self.current_location != "远征":
            yield "[收菜] 没能到达远征界面，停"
            return
        for nav_msg in self.navigate_to_stream("本丸"):
            yield nav_msg
        if self.current_location != "本丸":
            yield "[收菜] 没能回到本丸，停"
            return

        # ========== 2. 收菜循环 ==========
        collected = 0        # 点掉的结算界面的数量
        settlements = []     # 每份结算的归来信息（第几部队、哪张图）
        home_streak = 0      # 连续看到本丸的次数
        unknown_streak = 0   # 连续认不出画面的次数
        time.sleep(2.0)      # 等归来动画冒出来

        for _ in range(30):  # 安全上限
            self.maa.screenshot(force=True)

            # 结算界面 → 先读归来信息，再点一下翻页
            if self.maa.ocr(expected=title_ocr["expected"], roi=title_roi):
                collected += 1
                info = self._read_settlement_info(cfg)
                rewards, result = self._read_settlement_rewards(cfg)
                if hasattr(self, "record_event"):
                    self.record_event("expedition.settled", sequence=collected,
                                      result=result, rewards=rewards, **info)
                    for resource, amount in rewards.items():
                        self.record_event(
                            "resource.change",
                            resource=resource,
                            delta=amount,
                            source="expedition.settlement",
                            attribution="confirmed",
                            evidence="settlement_ocr",
                            note=(info["header"] or info["map_name"]
                                  or f"第{collected}份远征结算"),
                            settlement_sequence=collected,
                            team_no=info["team_no"],
                            result=result,
                        )
                if info["team_no"]:
                    settlements.append(info)
                    # 这支队回来了，派遣记录销掉
                    rec = _load_exp_record()
                    if rec.pop(str(info["team_no"]), None) is not None:
                        _save_exp_record(rec)
                    yield (f"[收菜] 远征结果结算（第{collected}份）："
                           f"部队{info['team_no']} 从 {info['header'] or '未知地图'} 回来")
                else:
                    yield f"[收菜] 远征结果结算（第{collected}份），翻页"
                self._click_point(tap)
                home_streak = 0
                unknown_streak = 0
                time.sleep(1.2)
                continue

            # 归来横幅 → 点一下进结算
            if self.maa.ocr(expected=banner_ocr["expected"], roi=banner_roi):
                yield "[收菜] 远征归来横幅，点过"
                self._click_point(tap)
                home_streak = 0
                unknown_streak = 0
                time.sleep(1.2)
                continue

            # 确认站在本丸：连续两次看到且无横幅/结算，收工
            if self.maa.template_match(home_tpl):
                home_streak += 1
                if home_streak >= 2:
                    break
                time.sleep(1.0)
                continue

            # 认不出的画面（过场动画途中等）→ 点一下安全区帮忙快进
            home_streak = 0
            unknown_streak += 1
            if unknown_streak > 5:
                yield "[收菜] ⚠️ 连续认不出画面，停，你去看看卡哪了"
                return
            self._click_point(tap)
            time.sleep(1.0)

        if collected > 0:
            yield f"[收菜] ✅ 收了 {collected} 份远征奖励"
        else:
            yield "[收菜] ✓ 没有远征回来，本丸风平浪静～"
            return

        # ========== 3. 顺手再派 ==========
        if not redispatch or not settlements:
            return

        if redispatch != "same":
            pick = self._pick_map_for_goal(redispatch)
            if not pick:
                yield f"[收菜] 收益表里没有产「{redispatch}」的图，再派跳过"
                return
            goal_code, goal_era, goal_slot = pick
            yield f"[收菜] 目标「{redispatch}」时薪最高的图：{goal_code}"

        dispatched = set()
        for info in settlements:
            team = info["team_no"]
            if not team or team in dispatched:
                continue
            dispatched.add(team)

            if redispatch == "same":
                era, slot, name = info["era"], info["slot"], info["map_name"]
                if not era or (not slot and not name):
                    yield f"[收菜] 部队{team}的归来信息没读全，这队跳过"
                    continue
                yield f"[收菜] 顺手把部队{team}派回原图（时代{era}卡位{slot}）..."
            else:
                era, slot, name = goal_era, goal_slot, None
                yield f"[收菜] 把部队{team}派去 {goal_code}（时代{era}卡位{slot}）..."

            for dis_msg in self.expedition_stream(era=era, map_name=name,
                                                  team_no=team, map_slot=slot):
                yield dis_msg

        yield f"[收菜] 再派完毕，共处理 {len(dispatched)} 支队"
        return

    # ==================== 收菜辅助 ====================

    def _read_settlement_rewards(self, cfg) -> tuple[dict, str | None]:
        """读取结算页四行基础资源；任何一行没读清就只跳过该行。"""
        reward_cfg = cfg.get("settlement_rewards", {})
        resources = ("木炭", "玉钢", "冷却材", "砥石")
        fallback_rois = (
            [875, 470, 920, 525], [875, 520, 920, 575],
            [875, 570, 920, 625], [875, 620, 920, 680],
        )
        rewards = {}
        ocr_all = getattr(self.maa, "ocr_all", None)
        if callable(ocr_all):
            for resource, fallback in zip(resources, fallback_rois):
                roi = reward_cfg.get("resource_rois", {}).get(resource, fallback)
                try:
                    rows = ocr_all(roi_4to4(*roi)) or []
                except Exception:
                    continue
                ordered = sorted(rows, key=lambda row: getattr(row[1], "x", 0))
                digits = "".join(re.sub(r"\D", "", str(text))
                                 for text, _point in ordered)
                if digits:
                    amount = int(digits)
                    if amount > 0:
                        rewards[resource] = amount

        result = None
        result_cfg = reward_cfg.get("result", {})
        if callable(ocr_all):
            try:
                rows = ocr_all(roi_4to4(*result_cfg.get(
                    "roi", [680, 35, 940, 150]))) or []
                result_text = "".join(str(text) for text, _point in rows)
                if "大成功" in result_text:
                    result = "大成功"
                elif "成功" in result_text:
                    result = "成功"
            except Exception:
                pass
        return rewards, result

    def _read_settlement_info(self, cfg) -> dict:
        """
        读结算界面上的归来信息：
          左上「第2部队」→ 哪支队
          右上「一-一 鸟羽·伏见之战」→ 时代-卡位 + 图名
        """
        info = {"team_no": None, "era": None, "slot": None,
                "map_name": None, "header": None}

        team_texts = self.maa.ocr_all(roi_4to4(*cfg["settlement_team_roi"]))
        team_join = "".join(t for t, _ in team_texts)
        m = re.search(r"第\s*([1-5一二三四五])\s*部队", team_join)
        if m:
            ch = m.group(1)
            info["team_no"] = int(ch) if ch.isdigit() else _NUMERALS.get(ch)

        map_texts = self.maa.ocr_all(roi_4to4(*cfg["settlement_map_roi"]))
        map_join = "".join(t for t, _ in map_texts)
        info["header"] = map_join or None
        m2 = re.search(r"([一二三四五])\s*[-—–一]\s*([一二三四五])", map_join)
        if m2:
            info["era"] = _NUMERALS.get(m2.group(1))
            info["slot"] = _NUMERALS.get(m2.group(2))
            # 编号后面的文字就是图名，洗掉分隔符和空白
            name = map_join[m2.end():]
            name = re.sub(r"[\s\-—–]+", "", name)
            info["map_name"] = name or None
        else:
            # 小框里的编号汉字 OCR 认不出（实测会漏）→ 整段当图名
            info["map_name"] = re.sub(r"[\s\-—–]+", "", map_join) or None

        # 编号没读到就拿图名去收益表里反查时代/卡位（名字只留汉字再比对）
        if (not info["era"] or not info["slot"]) and info["map_name"]:
            hit = self._lookup_map_by_name(info["map_name"])
            if hit:
                info["era"], info["slot"] = hit

        return info

    @staticmethod
    def _lookup_map_by_name(name: str):
        """用结算界面的图名反查收益表，返回 (时代, 卡位) 或 None"""
        def cjk(s):
            return re.sub(r"[^一-鿿]", "", s or "")

        target = cjk(name)
        if not target:
            return None
        try:
            with open(_MAPS_TABLE, encoding="utf-8") as f:
                maps = json.load(f)["maps"]
        except Exception:
            return None
        for v in maps.values():
            table_name = cjk(v.get("name"))
            if table_name and (target in table_name or table_name in target):
                return v["era"], v["slot"]
        return None

    def _pick_map_for_goal(self, resource: str):
        """
        按资源目标挑时薪最高的图（大成功收益 / 时长）

        Returns:
            (地图编号, 时代, 卡位) 或 None
        """
        try:
            with open(_MAPS_TABLE, encoding="utf-8") as f:
                maps = json.load(f)["maps"]
        except Exception:
            return None

        best_code, best_rate = None, 0.0
        for code, v in maps.items():
            gain = v.get(resource, 0)
            if gain <= 0:
                continue
            rate = gain / (v["duration_min"] / 60)
            if rate > best_rate:
                best_code, best_rate = code, rate

        if not best_code:
            return None
        v = maps[best_code]
        return best_code, v["era"], v["slot"]
