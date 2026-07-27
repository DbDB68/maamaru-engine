# -*- coding: utf-8 -*-
"""
上层业务：库存快照——日课收尾时把家底 OCR 一遍落盘，给看板吃

抓什么（都在锻刀界面一屏搞定）：
  顶栏整条：木炭/玉钢/冷却材/砥石/小判（按 x 顺序认）
  右栏：委托符/加速符·极/所持刀剑
  三炉：完成/空闲/锻造中（剩多少时间）

落盘 status/inventory.json，看板的读取任务自己算剩余时间。
写坏了不影响日课（调用方自己兜 try）。

坐标（真机校准）：
  顶栏条 (400,5,1100,52)，数字按 x 升序
  委托符 (1145,355,1255,390) 加速符 (1145,510,1255,550) 所持 (840,45,1080,85)
  炉行心 y [205,345,475]，状态/倒计时框 (150,cy-55,780,cy+55)
"""

import json
import re
import time
from pathlib import Path

from ..maa_adapter import roi_4to4

_STATUS_DIR = Path(__file__).resolve().parent.parent.parent / "status"
_SLOT_CY = [205, 345, 475]
_RES_NAMES = ["木炭", "玉钢", "冷却材", "砥石", "小判"]


def _to_int(text: str):
    digits = re.sub(r"[^\d]", "", text or "")
    return int(digits) if digits else None


class SnapshotMixin:
    """库存快照。依赖宿主类的 navigate_to_stream、maa。"""

    def status_snapshot_stream(self):
        """
        流式库存快照：导航锻刀 → OCR 家底 → 落盘 status/inventory.json

        Yields:
            str: 执行状态消息
        """
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

        payload = {
            "captured_at": time.strftime("%Y-%m-%d %H:%M:%S"),
            "resources": resources,
            "doko": doko,
            "furnaces": furnaces,
        }
        _STATUS_DIR.mkdir(exist_ok=True)
        (_STATUS_DIR / "inventory.json").write_text(
            json.dumps(payload, ensure_ascii=False, indent=2), encoding="utf-8")

        yield (f"[快照] 落盘：小判{resources.get('小判')} 委托符{resources.get('委托符')} "
               f"加速符{resources.get('加速符')} 所持{doko} "
               f"炉:{'/'.join(f['state'] for f in furnaces)}")
