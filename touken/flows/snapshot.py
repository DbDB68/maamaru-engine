# -*- coding: utf-8 -*-
"""
上层业务：库存快照——日课收尾时把家底 OCR 一遍落盘，给看板吃

抓什么：
  锻刀界面：顶栏整条 木炭/玉钢/冷却材/砥石/甲州金（按 x 顺序认）
            右栏 委托符/加速符·极/所持刀剑
            三炉 完成/空闲/锻造中（剩多少时间）
  所持道具界面：右上「所持小判」（真小判只在这看，顶栏那个是甲州金！）

落盘 status/inventory.json，看板的读取任务自己算剩余时间。
写坏了不影响日课（调用方自己兜 try）。

坐标（真机校准）：
  顶栏条 (400,5,1100,52)，数字按 x 升序
  委托符 (1145,355,1255,390) 加速符 (1145,510,1255,550) 所持 (840,45,1080,85)
  炉行心 y [205,345,475]，状态/倒计时框 (150,cy-55,780,cy+55)
  所持小判 (940,20,1210,80) —— 目录→所持道具界面右上，读出 "672,416 枚"
"""

import json
import re
import time
from pathlib import Path

from ..runtime_paths import STATUS_DIR

from ..maa_adapter import roi_4to4

_STATUS_DIR = STATUS_DIR
_SLOT_CY = [205, 345, 475]
_RES_NAMES = ["木炭", "玉钢", "冷却材", "砥石", "甲州金"]


def _to_int(text: str):
    digits = re.sub(r"[^\d]", "", text or "")
    return int(digits) if digits else None


class SnapshotMixin:
    """库存快照。依赖宿主类的 navigate_to_stream、maa。"""

    def status_snapshot_stream(self, phase=None):
        """
        流式库存快照：导航锻刀 → OCR 家底 → 落盘 status/inventory.json

        Yields:
            str: 执行状态消息
        """
        # 收工回城可能在长时间挂机后加载几十秒。即使战斗流程自己的回城
        # 确认先超时了，盘点也要独立等到目录真正可用，不能马上撞导航失败。
        if phase == "after":
            yield "[快照] 等待本丸加载完成、目录恢复可用..."
            ready = False
            deadline = time.monotonic() + 90.0
            last_notice = time.monotonic()
            while time.monotonic() < deadline:
                self.maa.screenshot(force=True)
                if (self.maa.exists("menu/ui目录.png")
                        or self.maa.exists("目录.png", threshold=0.7)):
                    ready = True
                    break
                if time.monotonic() - last_notice >= 15.0:
                    yield "[快照] 游戏仍在回城加载，继续等待..."
                    last_notice = time.monotonic()
                time.sleep(1.0)
            if not ready:
                yield "[快照] 等待 90 秒后目录仍不可用，取消本次收工盘点"
                return

        yield "[快照] 正在导航到锻刀..."
        for nav_msg in self.navigate_to_stream("锻刀"):
            yield nav_msg
        if self.current_location != "锻刀":
            yield "[快照] 到达锻刀失败"
            return
        time.sleep(1.5)
        self.maa.screenshot(force=True)

        # ---- 顶栏五资源：整条 OCR，数字按 x 升序对应 木炭/玉钢/冷却材/砥石/小判 ----
        tokens = self.maa.ocr_all(roi_4to4(400, 5, 1100, 52))
        nums = sorted(
            ((t, pt.x) for t, pt in tokens if re.fullmatch(r"[\d,]+", t)),
            key=lambda p: p[1])
        resources = {}
        for i, name in enumerate(_RES_NAMES):
            resources[name] = _to_int(nums[i][0]) if i < len(nums) else None
        if len(nums) < 5:
            yield f"[快照] 顶栏只读出 {len(nums)}/5 个数字，部分资源缺失"

        # ---- 右栏：委托符/加速符/所持 ----
        def first_number(roi):
            ts = self.maa.ocr_all(roi_4to4(*roi))
            for t, _ in ts:
                v = _to_int(t)
                if v is not None:
                    return v
            return None

        resources["委托符"] = first_number((1145, 355, 1255, 390))
        resources["加速符"] = first_number((1145, 510, 1255, 550))

        doko = None
        ts = self.maa.ocr_all(roi_4to4(840, 45, 1080, 85))
        # OCR 会在数字间吃出杂物（"200./200"），允许斜杠两边夹非数字
        m = re.search(r"(\d+)\D{0,3}/\D{0,2}(\d+)", "".join(t for t, _ in ts))
        if m:
            doko = f"{m.group(1)}/{m.group(2)}"

        # ---- 三炉状态 ----
        furnaces = []
        for i, cy in enumerate(_SLOT_CY, 1):
            ts = self.maa.ocr_all(roi_4to4(150, cy - 55, 780, cy + 55))
            text = "".join(t for t, _ in ts)
            if "完成" in text:
                furnaces.append({"slot": i, "state": "完成", "remain": None})
            elif "空闲" in text:
                furnaces.append({"slot": i, "state": "空闲中", "remain": None})
            else:
                m2 = re.search(r"(\d{1,2})\s*[:：]\s*(\d{2})\s*[:：]\s*(\d{2})", text)
                remain = f"{m2.group(1)}:{m2.group(2)}:{m2.group(3)}" if m2 else None
                furnaces.append({"slot": i, "state": "锻造中", "remain": remain})

        # ---- 所持道具界面读真小判（顶栏那个是甲州金，真小判只在这看）----
        koban = self._read_koban()
        if koban is not None:
            resources["小判"] = koban
        else:
            yield "[快照] 小判读取失败（不影响其他数据）"

        payload = {
            "captured_at": time.strftime("%Y-%m-%d %H:%M:%S"),
            "phase": phase,
            "resources": resources,
            "doko": doko,
            "furnaces": furnaces,
        }
        _STATUS_DIR.mkdir(exist_ok=True)
        (_STATUS_DIR / "inventory.json").write_text(
            json.dumps(payload, ensure_ascii=False, indent=2), encoding="utf-8")
        if hasattr(self, "record_event"):
            self.record_event("inventory.captured", **payload)

        yield (f"[快照] 落盘：小判{resources.get('小判')} 甲州金{resources.get('甲州金')} "
               f"委托符{resources.get('委托符')} 加速符{resources.get('加速符')} 所持{doko} "
               f"炉:{'/'.join(f['state'] for f in furnaces)}")

    def _read_koban(self):
        """目录→所持道具→右上 OCR 所持小判。失败返回 None，绝不抛异常。"""
        try:
            # 打开目录
            if not self._open_menu():
                return None
            time.sleep(1.0)
            self.maa.screenshot(force=True)
            pt = self.maa.template_match("menu/目录_所持道具.png")
            if not pt:
                return None
            self.maa.click(pt)
            time.sleep(2.5)
            self.maa.screenshot(force=True)
            if not self.maa.exists("ui所持.png"):
                return None
            # 右上「所持小判 672,416 枚」：取最长数字串
            tokens = self.maa.ocr_all(roi_4to4(940, 20, 1210, 80))
            best = None
            for t, _ in tokens:
                v = _to_int(t)
                if v is not None and (best is None or v > best):
                    best = v
            # 点 X 关掉所持道具，别给后面的步骤留弹窗
            from ..maa_adapter import Point
            self.maa.click(Point(1248, 35))
            time.sleep(0.8)
            return best
        except Exception as e:  # noqa: BLE001 - 快照兜底，任何错都不许炸日课
            print(f"[快照] 小判读取异常: {e}")
            return None
