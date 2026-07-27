# -*- coding: utf-8 -*-
"""
上层业务：演练（演习场）——认人避战版

规矩（用户亲授）：
  1. 对手列表显示的队长的极化状态不代表全队，必须点进去看配置
  2. 躲避名单：
     - 极化短刀：全游强度第一，打赢也难看，绕
     - 丙子椒林剑：让第一个出手的人无效，配极短无解，绕
  3. 优先打：没配满 6 人的"好心人"、全普刀队
  4. 每天只需赢 3 场，对手 3 点/15 点刷新，一次 5 队，挑软的捏
  5. 出战用部队二（极短队），阵形选逆行阵（抢机动先手）

技术要点（血泪校准）：
  - 极短判定 = 名册刀种是短刀 + 机动 >= 100
    （普刀全数值封顶两位数；极短机动 110+，隔了一个数量级）
  - 极化樱花在情报界面会被白底肖像骗（一文字则宗的花瓣背景 0.84 误报），
    所以在情报界面不靠樱花，只信名册 + 机动
  - 数值条每格 55.7px 宽，机动是第 4 格 x[754,806]——窗口偏 1px 都会
    把隔壁防御的尾数读进来，别改
  - 图标中心行距 94px，第一行 cy=152
"""

import time

from ..maa_adapter import roi_4to4, Point
from .. import sword_db

# 情报界面 6 个成员行的图标中心 y
_ROW_CY = [152, 246, 340, 434, 528, 622]
# 对手列表 5 行的队长卡点击点 y（真机校准：行距 112，不是 135！）
_LIST_CY = [179, 290, 402, 514, 626]

_HEISHI_ID = "touken_208_heishi_shourinken"  # 丙子椒林剑

# 刀种模板（内芯裁剪版，resource/base/image/刀种2/）
_ICON_TEMPLATES = ["短_银", "打_银", "太_金"]


class PracticeMixin:
    """演练。依赖宿主类的 navigate_to_stream、maa、config。"""

    def practice_stream(self, dry_run: bool = True, max_wins: int = None):
        """
        流式演练：扫描 5 个对手，逐个认人，挑软柿子打

        Args:
            dry_run: True=只认人报决策，不动手（认人考试模式）
            max_wins: 赢够几场收工，默认读配置 practice.max_wins（3）

        Yields:
            str: 执行状态消息
        """
        cfg = self.config.get("practice", {})
        if max_wins is None:
            max_wins = cfg.get("max_wins", 3)

        yield f"[演练] {'认人演习' if dry_run else '真打'} 模式，目标赢 {max_wins} 场"

        # ========== 1. 导航到演练 ==========
        yield "[演练] 正在导航到演练..."
        for nav_msg in self.navigate_to_stream("演练"):
            yield nav_msg
        if self.current_location != "演练":
            yield "[演练] 到达演练失败"
            return
        time.sleep(1.0)
        self.maa.screenshot(force=True)

        # ========== 2. 列表扫描：樱花标记的队长靠后看 ==========
        order = self._scan_list_order()
        yield f"[演练] 扫描顺序（普刀队长优先）: {[i + 1 for i in order]}"

        # ========== 3. 逐个进情报界面认人 ==========
        wins = 0
        for row_idx in order:
            if wins >= max_wins:
                break
            opponent = self._inspect_opponent(row_idx)
            if opponent is None:
                yield f"[演练] 对手{row_idx + 1}: 进情报界面失败，跳过"
                continue

            members = opponent["members"]
            verdict, reasons = self._judge(members)
            roster = "、".join(
                f"{m['name']}({m['type']}{' 机动' + str(m['mobility']) if m.get('mobility') else ''})"
                for m in members
            ) or "（空）"
            yield f"[演练] 对手{row_idx + 1} [{opponent['title']}]: {verdict} —— {'；'.join(reasons)}"
            yield f"[演练]   阵容({len(members)}/6): {roster}"

            if verdict != "打":
                self._back_to_list()
                continue

            if dry_run:
                yield f"[演练]   （演习模式：不动手）"
                self._back_to_list()
                continue

            # ===== 真打 =====
            result = yield from self._fight_one(cfg, row_idx)
            if result.startswith("win"):
                wins += 1
                yield f"[演练] 胜场 {wins}/{max_wins}（{result}）"
            else:
                yield f"[演练] 这场结果: {result}"
            # 打完回到列表（结算后一般自动回，保险起见导航校验）
            if not self._ensure_on_list():
                yield "[演练] 打完没回到对手列表，重新导航"
                for nav_msg in self.navigate_to_stream("演练"):
                    yield nav_msg
                time.sleep(1.0)

        yield f"[演练] 收工：赢 {wins} 场" + ("（演习模式，未真打）" if dry_run else "")

    # ========== 列表层 ==========

    def _scan_list_order(self):
        """返回扫描顺序（行号列表）：没打过的行才扫，队长没樱花的优先"""
        no_sakura, has_sakura = [], []
        for i, cy in enumerate(_LIST_CY):
            # 打过的行没有挑战按钮（盖着结算章），直接跳过
            if not self.maa.ocr("挑战", roi_4to4(1110, cy - 30, 1275, cy + 30)):
                continue
            y1, y2 = cy - 60, cy + 55
            pt = self.maa.template_match("极化樱花.png", roi=roi_4to4(0, y1, 500, y2),
                                         threshold=0.9)
            (has_sakura if pt else no_sakura).append(i)
        return no_sakura + has_sakura

    def _on_list(self) -> bool:
        self.maa.screenshot(force=True)
        return bool(self.maa.ocr("演练对手选择", roi_4to4(450, 60, 830, 110)))

    def _ensure_on_list(self) -> bool:
        for _ in range(3):
            if self._on_list():
                return True
            time.sleep(1.5)
        return False

    def _back_to_list(self):
        """从情报界面返回对手列表"""
        for _ in range(3):
            self.maa.click(Point(150, 38))
            time.sleep(2.0)
            if self._on_list():
                return

    # ========== 情报界面层 ==========

    def _inspect_opponent(self, row_idx: int):
        """
        点进第 row_idx 个对手的情报界面并认人

        Returns:
            {"title": 对手名, "members": [...]} 或 None（没进去）
        """
        cy = _LIST_CY[row_idx]
        self.maa.click(Point(190, cy))  # 队长卡
        time.sleep(2.5)
        self.maa.screenshot(force=True)
        if not self.maa.ocr("演练对手情报", roi_4to4(450, 10, 830, 60)):
            return None

        # 对手名（审神者 xxx级 名字）
        title_tokens = self.maa.ocr_all(roi_4to4(400, 90, 750, 120))
        title = " ".join(t for t, _ in title_tokens)

        members = []
        for cy in _ROW_CY:
            member = self._scan_member(cy)
            if member:
                members.append(member)
        return {"title": title, "members": members}

    def _scan_member(self, cy: int):
        """
        扫一行成员：OCR 名字 → 名册校验；短刀加读机动

        Returns:
            {"name", "type", "mobility"或None, "id"} 或 None（空位/认不出）
        """
        name_tokens = self.maa.ocr_all(roi_4to4(95, cy + 38, 250, cy + 65))
        if not name_tokens:
            return None
        # 取最长 token 当名字（防碎字）
        raw = max((t for t, _ in name_tokens), key=len)
        if len(raw) < 2:
            return None

        found = sword_db.find_by_name(raw)
        if not found:
            return {"name": raw, "type": "未知", "mobility": None, "id": None}
        sid, info = found

        member = {
            "name": info.get("name_zh") or info["name"],
            "type": info.get("type", "未知"),
            "mobility": None,
            "id": sid,
        }
        # 短刀必须读机动判断极化（普短机动 <=65，极短 110+）
        if member["type"] == "短刀":
            member["mobility"] = self._read_mobility(cy)
        return member

    def _read_mobility(self, cy: int):
        """读机动格数字（第 4 格，x[754,806]——别动窗口）"""
        for _ in range(2):  # OCR 偶尔翻车，给两次机会
            tokens = self.maa.ocr_all(roi_4to4(754, cy + 26, 806, cy + 48))
            for t, _ in tokens:
                t = t.strip()
                if t.isdigit():
                    return int(t)
            self.maa.screenshot(force=True)
        return None

    # ========== 决策 ==========

    def _judge(self, members: list):
        """
        返回 (verdict, reasons)，verdict ∈ {"打", "躲"}
        """
        if not members:
            return "躲", ["一个人都没认出来，怂"]

        dodge = []
        for m in members:
            if m["id"] == _HEISHI_ID:
                dodge.append(f"有丙子椒林剑（第1出手无效，无解）")
            if m["type"] == "短刀":
                mob = m.get("mobility")
                if mob is None:
                    dodge.append(f"{m['name']}是短刀但机动读不出，当极短处理")
                elif mob >= 100:
                    dodge.append(f"极化短刀 {m['name']}（机动{mob}）")
            if m["type"] == "未知":
                dodge.append(f"{m['name']} 名册查无此人，认不清不敢打")

        if dodge:
            return "躲", dodge

        reasons = []
        if len(members) < 6:
            reasons.append(f"只配了{len(members)}人，好心人")
        else:
            reasons.append("无极短无丙子，全是可以打的")
        return "打", reasons

    # ========== 战斗 ==========

    # 阵形卡中心坐标（阵形选择界面，2行×3列固定布局）
    _FORMATION_POS = {
        "鱼鳞": (224, 220), "横队": (640, 220), "雁行": (1050, 220),
        "鹤翼": (224, 425), "方阵": (640, 425), "逆行": (1050, 425),
    }
    # 部队标签 x 中心（部队选择界面顶部）
    _TEAM_TAB_X = {1: 155, 2: 272, 3: 390, 4: 510, 5: 630}

    def _fight_one(self, cfg, row_idx: int):
        """
        真打一场：进入演练 → 部队选择 → 阵形选择 → 自动战斗 → 回列表读结算章

        路径要点（真机校准）：
          - 阵形卡第1点是选中，确定按钮出现在卡内左下 (卡心x-115, 卡心y+13)，第2点才确认
          - 索敌失败时不出现阵形选择，直接开打——轮询时两种结局都要等
          - 战斗 x2 速度自动播完，自动回对手列表，结算章（胜利/败北+评级）盖在打过的那行

        Returns:
            生成器，最后 return "win" / "lose" / "unknown"
        """
        team_no = cfg.get("team_no", 2)
        formation = cfg.get("formation", "逆行")
        yield f"[演练] 动手！（部队{_CN_NUM.get(team_no, team_no)}，{formation or '有利'}阵）"

        # ---- 部队选择 ----
        self.maa.click(Point(1200, 630))  # 进入演练
        time.sleep(2.5)
        self.maa.screenshot(force=True)
        if not self.maa.ocr("部队选择", roi_4to4(500, 10, 780, 60)):
            yield "[演练] 没进到部队选择界面，放弃这场"
            return "unknown"

        self.maa.click(Point(self._TEAM_TAB_X.get(team_no, 272), 93))
        time.sleep(1.5)
        self.maa.click(Point(1200, 630))  # 演练开始
        time.sleep(2.0)

        # ---- 阵形选择（索敌失败则跳过此界面直接打）----
        got_formation = False
        for _ in range(10):  # 最多等 20s
            self.maa.screenshot(force=True)
            if self.maa.exists("battle/ui阵形选择.png", threshold=0.7):
                got_formation = True
                break
            if self._on_list():
                break
            time.sleep(2.0)

        if got_formation:
            if formation and formation in self._FORMATION_POS:
                cx, cy = self._FORMATION_POS[formation]
                yield f"[演练] 选 {formation}阵"
            else:
                # 没设固定阵形：点带"有利"标的卡
                pt = self.maa.template_match("battle/ui有利.png", threshold=0.7)
                if pt:
                    cx, cy = pt.x, pt.y
                    yield "[演练] 没设固定阵形，点有利阵"
                else:
                    cx, cy = self._FORMATION_POS["方阵"]
                    yield "[演练] 有利标也没找到，盲点方阵"
            self.maa.click(Point(cx, cy))       # 第1点：选中
            time.sleep(1.2)
            self.maa.click(Point(cx - 115, cy + 13))  # 第2点：确定
            yield "[演练] 阵形已确认，战斗中..."

        # ---- 等战斗播完回列表（途中每3秒点一下屏幕中央，翻结算页/跳动画）----
        for _ in range(60):  # 最多 180s
            if self._on_list():
                break
            self.maa.click(Point(640, 400))
            time.sleep(3.0)
        else:
            yield "[演练] 等战斗结束超时"
            return "unknown"

        # ---- 读结算章 ----
        time.sleep(1.0)
        return self._read_result(row_idx)

    def _read_result(self, row_idx: int):
        """读打过的那行的结算章：胜利/败北 + 评级（章比列表晚弹出，多试几次）"""
        cy = _LIST_CY[row_idx]
        text = ""
        for _ in range(4):
            time.sleep(1.5)
            self.maa.screenshot(force=True)
            tokens = self.maa.ocr_all(roi_4to4(1050, cy - 40, 1280, cy + 40))
            text = "".join(t for t, _ in tokens)
            if "胜利" in text or "败北" in text:
                break
        if "胜利" in text:
            rating = text.replace("完全", "").replace("胜利", "")
            return "win" if not rating else f"win({rating})"
        if "败北" in text:
            return "lose"
        return "unknown"


_CN_NUM = {1: "一", 2: "二", 3: "三", 4: "四", 5: "五"}
