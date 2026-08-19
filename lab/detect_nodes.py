# -*- coding: utf-8 -*-
"""
地图实验室 · 节点检测器 v0

从地图截图里抠节点：实心填色椭圆 + 黑描边。
按填充色分类：红=BOSS，白=当前/起点，深色=战斗点（待验），
其他颜色（黄资源点之类）见到了再补。

用法：
    .venv/Scripts/python.exe -m lab.detect_nodes lab/samples/march_172918.png
输出：终端打印节点列表 + lab/out/<图名>_nodes.png 标注图
"""

import sys
from pathlib import Path

import cv2
import numpy as np

ROOT = Path(__file__).resolve().parent.parent
OUT = ROOT / "lab" / "out"

# 每类节点的填充色 HSV 阈值 + 显示色 + 中文标签（真机采样，别瞎改）：
#   BOSS  红  H>165 或 H<10，S>150，V>120   （采样 HSV 176,241,185）
#   紫点  战斗 H110-160，S>100，V>60        （采样 HSV 132,168,143）
#   白点  当前/起点 低饱和高亮 S<60，V>180   （采样 HSV 0,0,211）
# 山影 V 只有 40 几、木盘 H=15、草地 H≈34，都被阈值天然挡掉。
# 黄点（资源）等见到真图再加，草地的色相正好撞黄区，别 preemptively 加。
NODE_RULES = [
    {"name": "boss",   "label": "BOSS", "color": (0, 0, 255)},
    {"name": "battle", "label": "紫点", "color": (255, 0, 255)},
    {"name": "white",  "label": "白点", "color": (255, 255, 0)},
]


def _masks(img):
    hsv = cv2.cvtColor(img, cv2.COLOR_BGR2HSV)
    h, s, v = hsv[:, :, 0], hsv[:, :, 1], hsv[:, :, 2]
    red = (((h > 165) | (h < 10)) & (s > 150) & (v > 120))
    purple = ((h > 110) & (h < 160) & (s > 100) & (v > 60))
    white = ((s < 60) & (v > 180))
    # 开运算：核比连线粗（连线约6-8px），细线消失，节点填充留下
    k = cv2.getStructuringElement(cv2.MORPH_ELLIPSE, (11, 11))
    return {
        name: cv2.morphologyEx(mask.astype(np.uint8) * 255, cv2.MORPH_OPEN, k)
        for name, mask in (("boss", red), ("battle", purple),
                           ("white", white))
    }


def _outline_ratio(img, x, y, w, h, band=6):
    """外圈暗像素占比：真节点有一圈黑描边，白墙/白建筑碎片没有。"""
    hsv = cv2.cvtColor(img, cv2.COLOR_BGR2HSV)
    v = hsv[:, :, 2]
    H, W = v.shape
    x1, y1 = max(0, x - band), max(0, y - band)
    x2, y2 = min(W, x + w + band), min(H, y + h + band)
    outer = v[y1:y2, x1:x2]
    if outer.size == 0:
        return 0.0
    ring = np.ones(outer.shape, bool)
    ix1, iy1 = x - x1, y - y1
    ring[iy1:iy1 + h, ix1:ix1 + w] = False
    ring_px = outer[ring]
    return float((ring_px < 100).mean()) if ring_px.size else 0.0


def detect(img, roi=None, scale=1):
    """返回 [{name,label,cx,cy,w,h,area}]，坐标是原图坐标。

    roi=(x1,y1,x2,y2) 限定地图区域；scale>1 先把裁区放大再检测
    （右上迷你地图的节点太小，11x11 开运算是会把它当线吃掉的，
    放大 3 倍后再走同一套阈值）。
    """
    x0, y0 = 0, 0
    sub = img
    if roi:
        x0, y0, x1, y1 = roi
        sub = img[y0:y1, x0:x1]
    if scale != 1:
        sub = cv2.resize(sub, None, fx=scale, fy=scale,
                         interpolation=cv2.INTER_CUBIC)
    nodes = []
    for rule in NODE_RULES:
        mask = _masks(sub)[rule["name"]]
        contours, _ = cv2.findContours(mask, cv2.RETR_EXTERNAL,
                                       cv2.CHAIN_APPROX_SIMPLE)
        for c in contours:
            area = cv2.contourArea(c)
            if not 200 < area < 4000 * scale * scale:
                continue
            x, y, w, h = cv2.boundingRect(c)
            aspect = w / max(h, 1)
            solidity = area / max(w * h, 1)
            if not (1.1 < aspect < 3.5 and solidity > 0.55):
                continue
            # 真节点有一圈黑描边（占比≈0.6），白墙碎片只有≈0.18——0.35 卡中间
            if _outline_ratio(sub, x, y, w, h) < 0.35:
                continue
            nodes.append({
                "name": rule["name"], "label": rule["label"],
                "cx": x0 + int((x + w / 2) / scale),
                "cy": y0 + int((y + h / 2) / scale),
                "w": int(w / scale), "h": int(h / scale),
                "area": int(area / (scale * scale)),
            })
    # 不同颜色的掩码可能圈到同一个点（白点里的阴影等），中心太近的去重
    nodes.sort(key=lambda n: -n["area"])
    deduped = []
    for n in nodes:
        if all((n["cx"] - m["cx"]) ** 2 + (n["cy"] - m["cy"]) ** 2 > 30 ** 2
               for m in deduped):
            deduped.append(n)
    return deduped


def annotate(img, nodes):
    out = img.copy()
    color_of = {r["name"]: r["color"] for r in NODE_RULES}
    for n in nodes:
        x, y = n["cx"] - n["w"] // 2, n["cy"] - n["h"] // 2
        cv2.rectangle(out, (x, y), (x + n["w"], y + n["h"]),
                      color_of[n["name"]], 2)
        cv2.putText(out, f'{n["label"]}({n["cx"]},{n["cy"]})',
                    (x, max(y - 6, 14)), cv2.FONT_HERSHEY_SIMPLEX,
                    0.5, color_of[n["name"]], 1, cv2.LINE_AA)
    return out


def main():
    src = Path(sys.argv[1])
    img = cv2.imread(str(src))
    if img is None:
        print(f"读不了图: {src}")
        sys.exit(1)
    nodes = detect(img)
    print(f"检测到 {len(nodes)} 个节点:")
    for n in nodes:
        print(f"  {n['label']:4s} 中心=({n['cx']},{n['cy']}) "
              f"尺寸={n['w']}x{n['h']} 面积={n['area']}")
    OUT.mkdir(parents=True, exist_ok=True)
    out_path = OUT / f"{src.stem}_nodes.png"
    cv2.imwrite(str(out_path), annotate(img, nodes))
    print(f"标注图: {out_path}")


if __name__ == "__main__":
    main()
