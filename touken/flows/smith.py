# -*- coding: utf-8 -*-
"""
上层业务：锻刀 + 刀解（俩界面挨着，互相救场，放一起）

锻刀规矩（用户亲授）：
  1. 配比不用调，默认 700×4，点锻刀即可，加速符不勾（省着）
  2. 有"完成"的炉子顺手收刀；刀位满了会蹦氪金弹窗——
     关掉，去刀解一把白名单腾出位置，再回来收
  3. 每日锻 3 次做日课

刀解规矩（白名单模式）：
  1. 只解白名单里的不稀有刀（任务奖励加速符），每天一把
  2. 保护（上锁）的刀界面里根本不显示，天然安全
  3. 选中白名单 → 大刀解（灰变蓝）→ 二次确认点确认

坐标（真机校准）：
  锻刀状况三炉：y心 [208,334,460]，炉按钮 x[160,371]，锻刀按钮 x[794,909]
  配比界面：锻刀开始 (1146,608)，标题 OCR「锻刀资源投入」
  刀解选择：行顶 147 起、行距 96，选择按钮 (1046, 行顶+48)
  大刀解 (1200,615)，确认弹窗 确认 (785,630)
"""

import json
import re
import time
from pathlib import Path

from ..runtime_paths import STATUS_DIR

from ..maa_adapter import roi_4to4, Point
from .. import sword_db

_SLOT_CY = [205, 345, 475]
_ROW_TOP = 147
_ROW_PITCH = 96
_VISIBLE_ROWS = 6
# 刀名位于行底部的独立文字带；向上会读到头像，向右会混入「疲劳/生存」。
_NAME_ROI_X1 = 120
_NAME_ROI_X2 = 360
_NAME_ROI_DY1 = 68
_NAME_ROI_DY2 = 98

_STATUS_DIR = STATUS_DIR
_FLAGS_PATH = _STATUS_DIR / "daily_flags.json"


def _mark_dismantled_today():
    """今天已经刀解过了（锻刀收刀腾位置也会解）——日课的刀解步据此跳过"""
    try:
        _STATUS_DIR.mkdir(exist_ok=True)
        _FLAGS_PATH.write_text(json.dumps(
            {"date": time.strftime("%Y-%m-%d"), "dismantled": True},
            ensure_ascii=False), encoding="utf-8")
    except Exception:
        pass


def dismantled_today() -> bool:
    """今天是否已经成功刀解过（任何途径：日课、锻刀腾位置、手动单跑）"""
    try:
        d = json.loads(_FLAGS_PATH.read_text(encoding="utf-8"))
        return d.get("date") == time.strftime("%Y-%m-%d") and bool(d.get("dismantled"))
    except Exception:
        return False

# 刀解白名单（用户给的，不稀有的刀）
DISMANTLE_WHITELIST = [
    "山姥切国广", "陆奥守吉行", "宗三左文字", "加州清光", "歌仙兼定",
    "乱藤四郎", "小夜左文字", "五虎退", "秋田藤四郎", "药研藤四郎",
    "大和守安定", "鸣狐", "蜂须贺虎彻", "前田藤四郎", "今剑",
    "笑面青江", "鲶尾藤四郎", "骨喰藤四郎", "山伏国广", "狮子王",
    "大俱利伽罗", "烛台切光忠", "同田贯正国", "和泉守兼定",
]


def _dur_to_sec(s):
    """'3:20:00' / '03：20：00' → 秒数。认不出来返回 None"""
    m = re.match(r"^\s*(\d{1,2})\s*[:：]\s*(\d{1,2})\s*[:：]\s*(\d{1,2})\s*$", s or "")
    if not m:
        return None
    return int(m.group(1)) * 3600 + int(m.group(2)) * 60 + int(m.group(3))


class SmithMixin:
    """锻刀+刀解。依赖宿主类的 navigate_to_stream、maa。"""

    # ==================== 锻刀 ====================

    def forge_stream(self, times: int = 3, watch: list | None = None):
        """
        流式锻刀：收完成的炉，给空闲炉点火，一天锻 times 次

        Args:
            times: 点几炉
            watch: 目标时长清单（限锻刀的时间身份证，如 ["03:20:00"]）。
                   点火后倒计时命中（±90秒，倒计时会走字）就报喜+手机推送

        Yields:
            str: 执行状态消息
        """
        watch_secs = {s for s in (_dur_to_sec(w) for w in (watch or [])) if s}
        if watch_secs:
            yield f"[锻刀] 🎯 盯梢目标时长：{'、'.join(watch or [])}"
        yield "[锻刀] 正在导航到锻刀..."
        for nav_msg in self.navigate_to_stream("锻刀"):
            yield nav_msg
        if self.current_location != "锻刀":
            yield "[锻刀] 到达锻刀失败"
            return
        time.sleep(1.0)

        forged = 0
        for attempt in range(6):  # 收刀/点火来回倒腾，给个安全上限
            if forged >= times:
                break
            self.maa.screenshot(force=True)
            action = self._scan_slots()
            if action is None:
                break
            kind, cy = action

            if kind == "完成":
                yield f"[锻刀] 收一炉（y={cy}）"
                if not self._collect_slot(cy):
                    # 刀位满了：刀解一把白名单腾位置再收
                    yield "[锻刀] 刀位满了！去刀解一把白名单腾位置..."
                    freed = False
                    for msg in self.dismantle_stream(max_dismantle=1, _from_forge=True):
                        yield msg
                        if "分解完成" in msg:
                            freed = True
                    if not freed:
                        yield "[锻刀] 刀解腾位置失败，这炉先不收"
                        break
                    for nav_msg in self.navigate_to_stream("锻刀"):
                        yield nav_msg
                    time.sleep(1.0)
                elif hasattr(self, "record_event"):
                    self.record_event("forge.collected", slot=_SLOT_CY.index(cy) + 1)
                continue

            if kind == "空闲中":
                yield f"[锻刀] 给炉子点火（第 {forged + 1}/{times} 炉）"
                if self._start_forge(cy):
                    forged += 1
                    hit = self._check_watch(cy, watch_secs)
                    if hasattr(self, "record_event"):
                        self.record_event("forge.started",
                                          slot=_SLOT_CY.index(cy) + 1,
                                          sequence=forged, target_hit=hit)
                    if hit:
                        yield f"[锻刀] 🎉🎉🎉 喜报！这炉倒计时 {hit}，目标时长命中！快去看！"
                        try:
                            from ..notify import notify
                            # 标题必须 ASCII（http.client 按 latin-1 编码头，中文/emoji 会静默发不出去）
                            notify(f"锻刀命中目标时长 {hit}！快去看炉子",
                                   title="Forge Hit!", tags="tada,sword")
                        except Exception:
                            pass
                else:
                    yield "[锻刀] 点火失败，停"
                    break
                continue

        yield f"[锻刀] 收工：点了 {forged} 炉"
        # 人已经在锻刀页面了，顺手把家底拍了（完整快照含小判，零额外导航）。
        # 拍歪了也不耽误正事：顶栏数字不够 4 个 _capture_inventory 自己会吱声。
        for msg in self._capture_inventory(phase="forge"):
            yield msg

    def _scan_slots(self):
        """扫三炉状态，返回 (状态, y心)。优先收完成，其次点空闲。
        框要罩住整行：完成/空闲的字在左，锻造中显示剩余时间"""
        idle = None
        for cy in _SLOT_CY:
            tokens = self.maa.ocr_all(roi_4to4(150, cy - 55, 780, cy + 55))
            text = "".join(t for t, _ in tokens)
            if "完成" in text:
                return ("完成", cy)
            if "空闲" in text and idle is None:
                idle = ("空闲中", cy)
        return idle

    def _collect_slot(self, cy: int) -> bool:
        """收一炉。刀位满弹氪金窗则返回 False。
        获得动画要轮询着点穿：一口气连点会顺手把下一个完成的炉也开了，
        后面的步骤全踩在动画上（血泪）"""
        self.maa.click(Point(265, cy))
        time.sleep(2.5)
        for _ in range(10):
            self.maa.screenshot(force=True)
            # 刀位满的氪金弹窗特征（先查它，弹窗后面还露着状况标题）
            tokens = self.maa.ocr_all(roi_4to4(200, 150, 1080, 550))
            text = "".join(t for t, _ in tokens)
            if "刀位" in text or "所持数" in text or "购买详情" in text:
                pt = self.maa.template_match("通用_关闭.png", threshold=0.7)
                self.maa.click(pt if pt else Point(1062, 70))
                time.sleep(1.5)
                return False
            if self.maa.ocr("锻刀状况", roi_4to4(400, 45, 880, 110)):
                return True
            # 安全点：点穿获得动画；回到状况界面这点是空地，点不坏
            self.maa.click(Point(290, 600))
            time.sleep(1.5)
        return True  # 超时也当收了，别卡死

    def _start_forge(self, cy: int) -> bool:
        """给空闲炉点火：进配比界面 → 点锻刀 → 等回到状况界面"""
        self.maa.click(Point(850, cy))  # 该行锻刀按钮
        time.sleep(2.5)
        self.maa.screenshot(force=True)
        if not self.maa.ocr("锻刀资源投入", roi_4to4(400, 45, 880, 110)):
            return False
        self.maa.click(Point(1146, 608))  # 锻刀（默认700×4，不勾加速符）
        # 点火后回状况界面有过场，没等到就当作没点成（防连锁误操作）
        for _ in range(10):
            time.sleep(1.5)
            self.maa.screenshot(force=True)
            if self.maa.ocr("锻刀状况", roi_4to4(400, 45, 880, 110)):
                return True
        return False

    def _check_watch(self, cy: int, watch_secs: set):
        """点火后读这炉的倒计时，命中目标时长（倒计时走字，容忍少 90 秒）就报"""
        if not watch_secs:
            return None
        try:
            self.maa.screenshot(force=True)
            tokens = self.maa.ocr_all(roi_4to4(150, cy - 55, 780, cy + 55))
            text = "".join(t for t, _ in tokens)
            m = re.search(r"(\d{1,2})\s*[:：]\s*(\d{1,2})\s*[:：]\s*(\d{1,2})", text)
            if not m:
                return None
            shown = f"{int(m.group(1))}:{m.group(2)}:{m.group(3)}"
            secs = int(m.group(1)) * 3600 + int(m.group(2)) * 60 + int(m.group(3))
            for target in watch_secs:
                if target - 90 <= secs <= target:
                    return shown
        except Exception:
            pass
        return None

    # ==================== 刀解 ====================

    def dismantle_stream(self, max_dismantle: int = 1, dry_run: bool = False,
                         _from_forge: bool = False, whitelist: list = None):
        """
        流式刀解：扫列表找白名单，解 max_dismantle 把

        Args:
            max_dismantle: 解几把（日课=1）
            dry_run: 只报决策不动手
            _from_forge: 从锻刀界面直接切标签（跳过导航）
            whitelist: 运行时覆盖白名单，None 则读配置 / 默认常量

        Yields:
            str: 执行状态消息
        """
        # 白名单：运行时覆盖 > 配置 > 默认常量
        if whitelist is None:
            whitelist = self.config.get("dismantle", {}).get("whitelist", DISMANTLE_WHITELIST)
        # 白名单预解析：过一遍名册校正（OCR 错字有字典兜底）
        whitelist_ids = set()
        for zh in whitelist:
            r = sword_db.find_by_name(zh)
            if r:
                whitelist_ids.add(r[0])
        yield f"[刀解] 白名单 {len(whitelist)} 人（解析 {len(whitelist_ids)} 个ID）"

        if not _from_forge:
            yield "[刀解] 正在导航到锻刀..."
            for nav_msg in self.navigate_to_stream("锻刀"):
                yield nav_msg
            if self.current_location != "锻刀":
                yield "[刀解] 到达锻刀失败"
                return
            time.sleep(1.0)

        # 切到刀解标签
        self.maa.click(Point(26, 345))
        time.sleep(2.5)
        self.maa.screenshot(force=True)
        if not self.maa.ocr("刀解选择", roi_4to4(450, 45, 830, 110)):
            yield "[刀解] 没进到刀解选择界面，放弃"
            return

        dismantled = 0
        for page in range(8):  # 翻页安全上限
            self.maa.screenshot(force=True)
            hit = self._scan_whitelist_row(whitelist_ids)
            if hit is None:
                # 本页没有白名单，往下翻
                yield f"[刀解] 第{page + 1}页没有白名单，翻页"
                self.maa.swipe(640, 550, 640, 250, 800)
                time.sleep(2.0)
                continue

            name, cy = hit
            yield f"[刀解] 选中白名单: {name}"
            if dry_run:
                yield "[刀解] （演习模式：不点确认）"
                return

            self.maa.click(Point(1046, cy))  # 该行选择
            time.sleep(1.5)
            self.maa.click(Point(1200, 615))  # 大刀解（选中后灰变蓝）
            time.sleep(2.0)
            self.maa.screenshot(force=True)
            if not self.maa.ocr("是否确认", roi_4to4(350, 100, 930, 160)):
                yield "[刀解] 确认弹窗没出现，放弃"
                return
            self.maa.click(Point(785, 630))  # 确认
            time.sleep(2.5)
            dismantled += 1
            _mark_dismantled_today()
            yield f"[刀解] 分解完成: {name}（{dismantled}/{max_dismantle}）"
            if dismantled >= max_dismantle:
                return
            # 列表顶上来了，重扫（不翻页）

        yield f"[刀解] 收工：解了 {dismantled} 把" + ("（没找到够的白名单）" if dismantled < max_dismantle else "")

    def _scan_whitelist_row(self, whitelist_ids: set):
        """
        扫当前页每一行，找第一把白名单刀

        Returns:
            (名字, 行心y) 或 None
        """
        for i in range(_VISIBLE_ROWS):
            top = _ROW_TOP + i * _ROW_PITCH
            cy = top + 48
            tokens = self.maa.ocr_all(roi_4to4(
                _NAME_ROI_X1, top + _NAME_ROI_DY1,
                _NAME_ROI_X2, top + _NAME_ROI_DY2,
            ))
            if not tokens:
                continue
            raw = max((t for t, _ in tokens), key=len)
            if len(raw) < 2:
                continue
            found = sword_db.find_by_name(raw)
            if found and found[0] in whitelist_ids:
                name = found[1].get("name_zh") or found[1]["name"]
                return (name, cy)
        return None
