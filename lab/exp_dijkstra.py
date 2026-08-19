# -*- coding: utf-8 -*-
"""试验：暗色图上跑 Dijkstra 沿暗路找边，验证真边/假边的代价比。临时脚本。"""
import heapq

import cv2
import numpy as np

from touken.runtime_paths import STATUS_DIR
import touken.map_read as mr

img = cv2.imread(str(STATUS_DIR / "map_miss" / "miss_8-4_loop1_193002.png"))
x0, y0, x1, y1 = mr.MINIMAP_ROI
sub = img[y0:y1, x0:x1]
SCALE = 2  # 实验用2倍省算力
work = cv2.resize(sub, None, fx=SCALE, fy=SCALE, interpolation=cv2.INTER_CUBIC)
V = cv2.cvtColor(work, cv2.COLOR_BGR2HSV)[:, :, 2].astype(np.float32)
COST = 1.0 + V / 25.0  # 死黑≈1，暗建筑≈4-6，亮草地≈9
H, W = V.shape

nodes = mr._detect_nodes(img, roi=mr.MINIMAP_ROI, scale=3)
pts = {i: ((n["cx"] - x0) * SCALE, (n["cy"] - y0) * SCALE)
       for i, n in enumerate(nodes)}


def path_cost(a, b):
    """a→b 的最省暗路代价 / 直线距离。沿路有暗走廊就低，没有就高。"""
    ax, ay = pts[a]
    bx, by = pts[b]
    straight = float(np.hypot(bx - ax, by - ay))
    # 局部窗口
    pad = 40
    mx0 = max(0, int(min(ax, bx)) - pad)
    mx1 = min(W, int(max(ax, bx)) + pad)
    my0 = max(0, int(min(ay, by)) - pad)
    my1 = min(H, int(max(ay, by)) + pad)
    start = (int(ay), int(ax))
    goal = (int(by), int(bx))
    dist = {start: 0.0}
    pq = [(0.0, start)]
    while pq:
        d, (y, x) = heapq.heappop(pq)
        if (y, x) == goal:
            return d / straight
        if d > dist.get((y, x), 1e18):
            continue
        for dy, dx in ((0, 1), (0, -1), (1, 0), (-1, 0),
                       (1, 1), (1, -1), (-1, 1), (-1, -1)):
            ny2, nx2 = y + dy, x + dx
            if not (my0 <= ny2 < my1 and mx0 <= nx2 < mx1):
                continue
            step = 1.414 if dy and dx else 1.0
            nd = d + COST[ny2, nx2] * step
            if nd < dist.get((ny2, nx2), 1e18):
                dist[(ny2, nx2)] = nd
                heapq.heappush(pq, (nd, (ny2, nx2)))
    return float("inf")


# 建节点名下标方便对照
name = {i: f"{n['name']}({n['cx']},{n['cy']})" for i, n in enumerate(nodes)}
boss = next(i for i, n in enumerate(nodes) if n["name"] == "boss")
pairs = [
    # 真边（目视确认）
    ((940, 213), (919, 197), "真 B-A 左上"),
    ((940, 213), (952, 254), "真 B-E 左枝"),
    ((959, 228), (952, 254), "真 C-E"),
    ((979, 244), (952, 254), "真 D-E"),
    ((972, 273), (995, 293), "真 F-G 死角"),
    ((1004, 234), (1026, 250), "真 H-K 田野"),
    ((1073, 287), (1138, 305), "真 M-W 绕城堡(曲线!)"),
    ((1138, 305), (1165, 331), "真 W-X"),
    ((1165, 331), (1221, 326), "真 X-boss"),
    ((1216, 299), (1221, 326), "真 U-boss"),
    ((1190, 240), (1194, 277), "真 桥S-T"),
    # 假边（目视确认没路）
    ((1194, 277), (1163, 259), "假 T-R 穿桥"),
    ((1165, 331), (1096, 321), "假 X-Y 穿房区"),
    ((1216, 299), (1138, 305), "假 U-W 长横"),
    ((1194, 277), (1138, 305), "假 T-W"),
    ((1163, 259), (1165, 331), "假 R-X"),
]
for p1, p2, label in pairs:
    a = next(i for i, n in enumerate(nodes)
             if (n["cx"], n["cy"]) == tuple(p1))
    b = next(i for i, n in enumerate(nodes)
             if (n["cx"], n["cy"]) == tuple(p2))
    print(f"{label}: 代价比 = {path_cost(a, b):.2f}")
