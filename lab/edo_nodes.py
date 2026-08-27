"""江户城大地图节点扫描：跨帧汇总节点位置与颜色（白=未到访 黑=空 紫=战斗 黄=钥匙）。"""
import cv2
import numpy as np
import glob
import json
from collections import defaultdict

SAMPLE_DIR = "lab/samples/edocastle_0827"


def detect_nodes(img):
    """返回 [(kind, cx, cy)]，江户城全屏地图专用。"""
    hsv = cv2.cvtColor(img, cv2.COLOR_BGR2HSV)
    out = []

    def blobs(mask, kind, erode=0):
        if erode:
            k = cv2.getStructuringElement(cv2.MORPH_ELLIPSE, (erode, erode))
            mask = cv2.erode(mask, k)
        cnts, _ = cv2.findContours(mask, cv2.RETR_EXTERNAL, cv2.CHAIN_APPROX_SIMPLE)
        for c in cnts:
            x, y, w, h = cv2.boundingRect(c)
            area = cv2.contourArea(c)
            if not (60 < x < 1080 and 60 < y < 700):
                continue  # 屏蔽右侧难度标签/左边缘/顶部 HUD
            if 30 <= w <= 55 and 14 <= h <= 30 and area > 0.4 * w * h:
                out.append((kind, x + w // 2, y + h // 2))

    # 白节点：浅填充
    blobs(cv2.inRange(hsv, (0, 0, 190), (180, 70, 255)), "white")
    # 黑节点：实心黑，腐蚀 9px 甩掉连线
    blobs(cv2.inRange(hsv, (0, 0, 0), (180, 255, 70)), "black", erode=9)
    # 紫节点：深紫实心（当前位置）
    blobs(cv2.inRange(hsv, (130, 60, 40), (165, 255, 160)), "purple", erode=5)
    # 黄节点：钥匙点
    blobs(cv2.inRange(hsv, (18, 120, 150), (40, 255, 255)), "yellow", erode=5)
    return out


def main():
    # 位置聚类：同一点位跨帧合并（半径 18px）
    clusters = []  # {"x","y","n","colors":Counter}
    files = sorted(glob.glob(f"{SAMPLE_DIR}/seq_*.png"))
    for f in files:
        img = cv2.imread(f)
        if img is None or img.shape[:2] != (720, 1280):
            continue
        for kind, cx, cy in detect_nodes(img):
            hit = None
            for cl in clusters:
                if abs(cl["x"] - cx) <= 18 and abs(cl["y"] - cy) <= 18:
                    hit = cl
                    break
            if hit is None:
                hit = {"x": cx, "y": cy, "n": 0, "colors": defaultdict(int)}
                clusters.append(hit)
            hit["x"] = (hit["x"] * hit["n"] + cx) / (hit["n"] + 1)
            hit["y"] = (hit["y"] * hit["n"] + cy) / (hit["n"] + 1)
            hit["n"] += 1
            hit["colors"][kind] += 1

    clusters.sort(key=lambda c: (c["y"], c["x"]))
    for i, c in enumerate(clusters):
        c["id"] = i
        c["x"] = round(c["x"], 1)
        c["y"] = round(c["y"], 1)
        c["colors"] = dict(c["colors"])
    print(f"{len(files)} 帧 -> {len(clusters)} 个点位")
    for c in clusters:
        print(c["id"], (c["x"], c["y"]), "seen", c["n"], c["colors"])
    with open("tmp/edo_nodes_raw.json", "w", encoding="utf-8") as fp:
        json.dump(clusters, fp, ensure_ascii=False, indent=1)


if __name__ == "__main__":
    main()
