# -*- coding: utf-8 -*-
"""剪影识别终验：三块已知板子（五虎退/小竜景光/浦島虎徹）全视角混跑"""
from pathlib import Path
import sys
import time

import numpy as np
from PIL import Image

sys.path.insert(0, str(Path(__file__).parent))

from touken.silhouette import load_library, extract_observed, identify, is_confident

LIB_DIR = Path(__file__).parent / "Silhouette1.0.2 (2)" / "silhouette"

CASES = [
    ("board01", "silhouette_lab/board01a/board_after_b08.png", "五虎退"),
    ("board02", "silhouette_lab/board02a/b09/f016.png", "小竜景光"),
    ("board03", "silhouette_lab/board03a/board_after_b08.png", "浦島虎徹"),
]

print("加载素材库...")
lib = load_library(LIB_DIR)
print(f"库: {len(lib)} 个模板")

for label, shot, truth in CASES:
    img = np.array(Image.open(shot).convert("RGB"))
    obs = extract_observed(img)
    t0 = time.time()
    res = identify(obs, lib, top_n=5)
    dt = time.time() - t0
    print(f"\n=== {label}（真身: {truth}）  黑色像素 {obs.sum()}  耗时 {dt:.1f}s ===")
    if res is None:
        print("  （像素太少，拒答）")
        continue
    for score, name, view in res:
        mark = " ← 真身" if name == truth else ""
        print(f"  {score:.3f}  {name} ({view}){mark}")
    print(f"  置信判定: {'✅ 可信' if is_confident(res) else '⚠️ 不可信'}")
