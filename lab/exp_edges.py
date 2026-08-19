# -*- coding: utf-8 -*-
"""试验：更严黑线阈值(V<55) + 边长上限110 对 8-4/5-4/1-1 的影响。临时脚本。"""
import glob
import os
from collections import deque
from itertools import combinations

import cv2
import numpy as np

from touken.runtime_paths import STATUS_DIR
import touken.map_read as mr


def build(img, roi, scale, edge_threshold=0.7, vmax=80, maxlen=9999,
          fill_max=0.26):
    x0, y0, x1, y1 = roi
    sub = img[y0:y1, x0:x1]
    work = cv2.resize(sub, None, fx=scale, fy=scale,
                      interpolation=cv2.INTER_CUBIC)
    nodes = mr._detect_nodes(img, roi=roi, scale=scale)
    dark = cv2.cvtColor(work, cv2.COLOR_BGR2HSV)[:, :, 2] < vmax
    H, W = dark.shape
    pts = [((n["cx"] - x0) * scale, (n["cy"] - y0) * scale) for n in nodes]
    edges = []
    for i, j in combinations(range(len(nodes)), 2):
        d = float(np.hypot(pts[i][0] - pts[j][0], pts[i][1] - pts[j][1]))
        if d > maxlen * scale:
            continue
        # 命中 = 横带里有暗像素 且 横带暗像素占比够低（细线）；
        # 房区/桥是整片暗（占比 0.27-0.37），真路是细线（占比 0.12-0.17）
        ax, ay = pts[i]
        bx, by = pts[j]
        dx, dy = bx - ax, by - ay
        L = float(np.hypot(dx, dy))
        if L < 20:
            continue
        nx, ny = -dy / L, dx / L
        hits = total = 0
        for t in np.linspace(0, 1, 24):
            if min(t, 1 - t) * L < 8:
                continue
            xa, ya = ax + dx * t, ay + dy * t
            row = []
            for off in range(-24, 25, 2):
                x = int(round(xa + nx * off))
                y = int(round(ya + ny * off))
                if 0 <= x < W and 0 <= y < H:
                    row.append(bool(dark[y, x]))
            if not row:
                continue
            # 连续暗段（run）分析：真路 = 窄段（2-16 样本 ≈ 4-32px）；
            # 房区/桥 = 一整条宽段；路贴房子 = 窄段+宽段各一，窄段算数
            runs = []
            run = 0
            for v in row:
                if v:
                    run += 1
                else:
                    if run:
                        runs.append(run)
                    run = 0
            if run:
                runs.append(run)
            total += 1
            if any(2 <= r <= 16 for r in runs):
                hits += 1
        s = hits / total if total else 0.0
        if s < edge_threshold:
            continue
        L2 = dx * dx + dy * dy
        blocked = False
        for k, (xk, yk) in enumerate(pts):
            if k in (i, j):
                continue
            t = max(0.0, min(1.0, ((xk - ax) * dx + (yk - ay) * dy) / L2))
            if np.hypot(xk - (ax + dx * t), yk - (ay + dy * t)) < 12 * scale:
                blocked = True
                break
        if not blocked:
            edges.append((i, j, round(s, 2)))

    def _d(a, b):
        return float(np.hypot(pts[a][0] - pts[b][0], pts[a][1] - pts[b][1]))
    es = {(i, j) for i, j, _ in edges} | {(j, i) for i, j, _ in edges}
    edges = [(i, j, s) for i, j, s in edges
             if not any(k not in (i, j) and (i, k) in es and (k, j) in es
                        and (_d(i, k) + _d(k, j)) < _d(i, j) * 1.18
                        for k in range(len(nodes)))]
    if edges:
        keep = sorted({i for i, _, _ in edges} | {j for _, j, _ in edges})
        remap = {o: n for n, o in enumerate(keep)}
        nodes = [nodes[o] for o in keep]
        edges = [(remap[i], remap[j], s) for i, j, s in edges]
    return nodes, edges


def dist(img, **kw):
    nodes, edges = build(img, mr.MINIMAP_ROI, 3, **kw)
    boss = next((i for i, n in enumerate(nodes) if n["name"] == "boss"), None)
    cur = None
    for flag in mr._find_flag_candidates(img, mr.MINIMAP_ROI, 3):
        cur = mr._node_under_flag(nodes, flag)
        if cur is not None:
            break
    if cur is None or boss is None:
        return len(nodes), len(edges), None
    adj = {i: [] for i in range(len(nodes))}
    for i, j, _ in edges:
        adj[i].append(j)
        adj[j].append(i)
    d = {cur: 0}
    q = deque([cur])
    while q:
        u = q.popleft()
        for v in adj[u]:
            if v not in d:
                d[v] = d[u] + 1
                q.append(v)
    return len(nodes), len(edges), d.get(boss)


print("== 8-4 ==")
for p in sorted(glob.glob(str(STATUS_DIR / "map_miss" / "miss_*.png"))):
    print(os.path.basename(p), dist(cv2.imread(p)))
print("== 5-4 / 1-1 ==")
for p in sorted(glob.glob("lab/samples/5-4_step*.png")) + [
        "lab/samples/map_1-1_node1.png", "lab/samples/map_1-1_node2.png",
        "lab/samples/5-4_after_dice.png", "lab/samples/5-4_home.png"]:
    print(os.path.basename(p), dist(cv2.imread(p)))
