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
    # 王点门口真·撤退扳机帧：旗面和河岸亮色粘成 20.7px 宽的"胖旗"，
    # 宽度上限从 20 放到 24 才认得出（几何闸门负责挡假旗）。
    "8-4_boss_door.png": 1,
    # 6-2 三条大桥（夜战图）：连线是亮色、背景深蓝，逻辑和昼图相反。
    # 王点与隔壁紫点仅隔 14.8px（跨色去重半径 8px 才留得住）。
    # 期望值是真机跑图连续帧，距离随行军逐步逼近，并经 overlay 人工核对。
    "6-2_step1.png": 11,
    "6-2_step2.png": 10,
    "6-2_step3.png": 9,
    "6-2_step4.png": 8,
    "6-2_step5.png": 7,
    # 6-4 池田屋一楼（室内夜战）：连线沿房间网格走直角折线，直线采样
    # 打不通王点的唯一连线——肘形救援（仅捞落单节点）才把它接回图上。
    "6-4_step1.png": 9,
    "6-4_step2.png": 8,
    "6-4_step3.png": 7,
    "6-4_step4.png": 6,
    "6-4_step5.png": 5,
    # 7-1 江户・新桥（昼图）：中央建筑的白墙红瓦会伪造竖白块假旗，
    # 静止不动每帧都在。真旗靠旗面红日章含量认出（同帧闸门候选里
    # 红最多的是真旗）；这 5 帧同一条沟路线跑了两圈、读数逐帧一致，
    # 首尾帧旗标位置经 overlay 人工核对。
    "7-1_step1.png": 3,
    "7-1_step2.png": 5,
    "7-1_step3.png": 4,
    "7-1_step4.png": 3,
    "7-1_step5.png": 2,
    # 真·撤退扳机帧：短路 5 步到王点门口，dist==1 正常开火（次日实机验证）。
    "7-1_boss_door.png": 1,
    # 7-4 江户城内（夜图+渐进开图）：建筑蓝紫阴影曾伪造节点（H111-120），
    # 亮墙线再把幻影连成假边直插王点，读数全程少一格、提前撤退。
    # 紫点 H 收窄 124-150 + 蹭墙假边绞杀后读这条链 4→3→2，与实机一致。
    "7-4_step1.png": 4,
    "7-4_step2.png": 3,
    "7-4_step3.png": 2,  # 原bug帧：曾读 1 误撤退，真值 2（下一脚到王点隔壁）
    # 8-1 阿弥陀峰（昼图）：step4 的真旗和云絮粘成 19x15 扁块（AR1.32）
    # 曾被长宽比闸门误杀，假白块顶包读出 1 → 假撤退；带红日章的旗块
    # 放宽 AR 到 1.5 后回到真值 3。
    "8-1_step1.png": 6,
    "8-1_step2.png": 5,
    "8-1_step3.png": 4,
    "8-1_step4.png": 3,  # 原bug帧：曾读 1 误撤退，真值 3
    # 另一圈的原bug帧：这次真旗和沙地粘成 34x16（AR2.12、超宽度闸门），
    # 暗日章 H=12 漏出旧红档，旗面还被误检成白色节点骑在真节点头上
    # （跨色去重 8→12px 才救回）。读 1 误撤退；修复后读 6——
    # 与图拓扑逐边核对一致（同圈后段 5,4,3,2,1 链也验证过拓扑）。
    "8-1_step5.png": 6,
    # 8-3 美浓（雨雾夜图）：雾气本身够亮，朴素亮掩码密度 0.38（正常夜图
    # 0.09-0.17）把所有节点连成毛线团；换密度自适应的局部对比雾掩码
    # （21x21 中位核——9x9 会被 7-10px 的线自己灌满）+ 大 margin 跳端点
    # 空隙后读这条链 8→6→4（中间帧 7,5 留档复扫一致），王点不再孤立。
    "8-3_step1.png": 8,
    "8-3_step2.png": 6,
    "8-3_step3.png": 4,
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
