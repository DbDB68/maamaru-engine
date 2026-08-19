# -*- coding: utf-8 -*-
"""touken.map_read 的回归测试：用实验室真机样本锁住已验证的识别结果。

样本期望值来自真机实测（5-4 全程 + 1-1 + 8-4 市街图白天），
与 lab/boss_distance.py 的输出一致。
注意：lab/samples/ 是 gitignored 的本地素材目录，CI 上没有这些图——
样本缺失时整个测试跳过（本地开发机仍然全量回归）。
没装 opencv 的环境同样跳过。
"""

import unittest
from pathlib import Path

from touken.map_read import CV2_AVAILABLE, boss_distance_from_image

SAMPLES = Path(__file__).resolve().parent.parent / "lab" / "samples"

# 样本 → 期望的"距王点步数"。None = 这帧认不出来（非决策屏/被遮挡），
# 生产语义里 None 必须被当成"不知道，继续走"，绝不能当撤退信号。
EXPECTED = {
    "5-4_step1.png": 6,
    "5-4_step2.png": 6,
    "5-4_step3.png": None,
    "5-4_step4.png": None,
    "5-4_step5.png": None,
    "5-4_step6.png": None,
    "5-4_step7.png": None,
    "5-4_step8.png": None,
    "5-4_step9.png": 1,   # 距王点一步：撤退扳机命中
    "5-4_step10.png": None,
    "map_1-1_node1.png": 1,
    "map_1-1_node2.png": None,
    "5-4_after_dice.png": None,
    "5-4_home.png": None,
    # 8-4 市街图（白天）：节点密集（相邻仅 24px）+ 云/河面假旗干扰
    "8-4_step1.png": 8,
    "8-4_step3.png": 6,
    "8-4_step5.png": 8,   # 岔路骰子带离王点，距离回涨是正常的
}


@unittest.skipUnless(CV2_AVAILABLE, "当前环境没装 opencv，跳过地图识别回归")
class TestMapRead(unittest.TestCase):
    def test_samples_match_validated_results(self):
        import cv2
        found = 0
        for name, want in EXPECTED.items():
            path = SAMPLES / name
            if not path.exists():
                continue  # 样本是本地素材，CI 上没有，缺哪张跳哪张
            found += 1
            img = cv2.imread(str(path))
            self.assertIsNotNone(img, f"样本读不了: {name}")
            with self.subTest(sample=name):
                self.assertEqual(boss_distance_from_image(img), want)
        if not found:
            self.skipTest("本地样本目录为空（lab/samples 不进 git），跳过回归")

    def test_none_image_is_safe(self):
        self.assertIsNone(boss_distance_from_image(None))


if __name__ == "__main__":
    unittest.main()
