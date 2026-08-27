"""江户城地图草稿档案生成：节点（人工清洗后）+ 直线带采样推边 + 标注图。"""
import cv2
import numpy as np
import json
import math

# 人工清洗后的节点表（来自 edo_nodes.py 聚类 + 标注图核对）
# (x, y, 备注)
NODES = [
    (346, 183, ""),      # 0
    (469, 187, ""),      # 1
    (708, 155, ""),      # 2
    (817, 193, ""),      # 3
    (880, 170, ""),      # 4
    (959, 230, ""),      # 5
    (999, 258, ""),      # 6
    (1090, 265, ""),     # 7 右缘
    (614, 217, ""),      # 8
    (267, 251, ""),      # 9
    (122, 309, ""),      # 10 左缘
    (797, 254, ""),      # 11
    (339, 347, ""),      # 12
    (460, 286, ""),      # 13
    (664, 353, ""),      # 14
    (833, 362, ""),      # 15
    (472, 396, ""),      # 16
    (218, 452, ""),      # 17
    (734, 459, ""),      # 18
    (1010, 452, ""),     # 19 (原 19/20 合并)
    (531, 498, ""),      # 20
    (748, 574, ""),      # 21 一圈起点旁（紫点高发）
    (804, 681, "entry"), # 22 入口（城下）
]
BOSS_FLAME = (758, 95)  # 王点火焰，目估，待程序复核


def edge_score(img, a, b, half_band=6, margin=30):
    """沿线段法向宽带采样暗像素比例。连线是粗黑线，命中有底气。"""
    gray = cv2.cvtColor(img, cv2.COLOR_BGR2GRAY)
    ax, ay = a
    bx, by = b
    dx, dy = bx - ax, by - ay
    L = math.hypot(dx, dy)
    if L < margin * 2 + 10:
        return 0.0
    ux, uy = dx / L, dy / L
    nx, ny = -uy, ux
    hits = total = 0
    steps = int(L - margin * 2)
    for t in range(margin, margin + steps, 3):
        cx, cy = ax + ux * t, ay + uy * t
        band_hit = False
        for off in range(-half_band, half_band + 1, 2):
            x, y = int(cx + nx * off), int(cy + ny * off)
            if 0 <= x < 1280 and 0 <= y < 720 and gray[y, x] < 90:
                band_hit = True
                break
        hits += band_hit
        total += 1
    return hits / total if total else 0.0


def main():
    img = cv2.imread("lab/samples/edocastle_0827/seq_0017.png")
    pts = [(x, y) for x, y, _ in NODES]
    n = len(pts)
    edges = []
    for i in range(n):
        for j in range(i + 1, n):
            d = math.hypot(pts[i][0] - pts[j][0], pts[i][1] - pts[j][1])
            if d > 340:
                continue
            s = edge_score(img, pts[i], pts[j])
            if s > 0.5:
                edges.append((i, j, round(s, 2), round(d)))
    edges.sort(key=lambda e: -e[2])
    for e in edges:
        print(e)
    # 标注图
    for i, j, s, d in edges:
        cv2.line(img, pts[i], pts[j], (0, 0, 255), 2)
    for i, (x, y) in enumerate(pts):
        cv2.circle(img, (x, y), 15, (255, 0, 0), 2)
        cv2.putText(img, str(i), (x - 9, y + 5), cv2.FONT_HERSHEY_SIMPLEX, 0.55, (255, 0, 0), 2)
    cv2.circle(img, BOSS_FLAME, 18, (0, 255, 255), 2)
    cv2.imwrite("tmp/edo_edges_draft.png", img)


if __name__ == "__main__":
    main()
