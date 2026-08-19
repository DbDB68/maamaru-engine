# -*- coding: utf-8 -*-
"""
地图实验室 · 当前位置（旗标）识别

小地图上有一面白色小旗插在队伍当前所在节点的正上方。
旗 = 竖直白色小块（约 8x13 px），跟白点（横椭圆）靠形状区分；
旗底正下方 8-20px 内、左右偏 12px 内的节点 = 当前节点。
白门楼也是竖白块，但它是大门楼的一部分、底下没有节点，靠这条规则挡掉。

用法：
    .venv/Scripts/python.exe -m lab.position lab/samples/5-4_step1.png
输出：当前节点编号 + lab/out/<图名>_flag.png 标注图
"""

import sys
from pathlib import Path

import cv2
import numpy as np

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))
OUT = ROOT / "lab" / "out"

from lab.detect_nodes import detect, NODE_RULES  # noqa: E402
from lab.topology import MINIMAP_ROI  # noqa: E402

FLAG_SCALE = 3
# 旗子的物理尺寸（原图 px）：约 8x13，竖的
FLAG_MIN_W, FLAG_MAX_W = 5, 20
FLAG_MIN_H, FLAG_MAX_H = 8, 28
# 旗底到节点中心：下 8-22px、左右 ±12px
FLAG_DX, FLAG_DY_MIN, FLAG_DY_MAX = 12, 6, 22


def find_flag(img, roi=MINIMAP_ROI, scale=FLAG_SCALE):
    """返回旗子中心（原图坐标）或 None"""
    x0, y0, x1, y1 = roi
    sub = img[y0:y1, x0:x1]
    work = cv2.resize(sub, None, fx=scale, fy=scale,
                      interpolation=cv2.INTER_CUBIC)
    hsv = cv2.cvtColor(work, cv2.COLOR_BGR2HSV)
    white = ((hsv[:, :, 1] < 60) & (hsv[:, :, 2] > 180)).astype(np.uint8) * 255
    contours, _ = cv2.findContours(white, cv2.RETR_EXTERNAL,
                                   cv2.CHAIN_APPROX_SIMPLE)
    best = None
    for c in contours:
        x, y, w, h = cv2.boundingRect(c)
        w0, h0 = w / scale, h / scale
        if not (FLAG_MIN_W < w0 < FLAG_MAX_W
                and FLAG_MIN_H < h0 < FLAG_MAX_H):
            continue
        if w0 / max(h0, 1) >= 0.9:  # 要竖的，横椭圆是白点
            continue
        cx = x0 + (x + w / 2) / scale
        cy = y0 + (y + h / 2) / scale
        if best is None or h0 > best[2]:
            best = (cx, cy, h0)
    return (best[0], best[1]) if best else None


def current_node(img, roi=MINIMAP_ROI, scale=FLAG_SCALE):
    """返回 (nodes, flag_xy, current_index)。认不出旗或底下没节点就为 None。"""
    nodes = detect(img, roi=roi, scale=scale)
    flag = find_flag(img, roi=roi, scale=scale)
    if not flag:
        return nodes, None, None
    fx, fy = flag
    cur = None
    for i, n in enumerate(nodes):
        dx = n["cx"] - fx
        dy = n["cy"] - fy
        if abs(dx) <= FLAG_DX and FLAG_DY_MIN <= dy <= FLAG_DY_MAX:
            cur = i
            break
    return nodes, flag, cur


def main():
    src = Path(sys.argv[1])
    img = cv2.imread(str(src))
    if img is None:
        print(f"读不了图: {src}")
        sys.exit(1)
    nodes, flag, cur = current_node(img)
    print(f"节点 {len(nodes)} 个，旗标: {flag and (round(flag[0]), round(flag[1]))}")
    if cur is not None:
        n = nodes[cur]
        print(f"当前节点: [{cur}] {n['label']} ({n['cx']},{n['cy']})")
    else:
        print("当前节点: 没认出来（旗底下没节点）")

    out = img.copy()
    color_of = {r["name"]: r["color"] for r in NODE_RULES}
    for idx, n in enumerate(nodes):
        c = (0, 200, 255) if idx == cur else color_of[n["name"]]
        thick = 3 if idx == cur else 1
        cv2.circle(out, (n["cx"], n["cy"]), 10, c, thick)
        cv2.putText(out, str(idx), (n["cx"] + 11, n["cy"] + 4),
                    cv2.FONT_HERSHEY_SIMPLEX, 0.4, c, 1, cv2.LINE_AA)
    if flag:
        cv2.circle(out, (int(flag[0]), int(flag[1])), 8, (255, 128, 0), 2)
    OUT.mkdir(parents=True, exist_ok=True)
    out_path = OUT / f"{src.stem}_flag.png"
    cv2.imwrite(str(out_path), out)
    print(f"标注图: {out_path}")


if __name__ == "__main__":
    main()
