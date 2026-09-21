# -*- coding: utf-8 -*-
"""头像认人：模板加载解析、match_avatar 阈值与形态结论的保守条件"""

import sys
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from touken import avatar_db  # noqa: E402


def _img(h, w, seed):
    """确定性伪随机 BGR 图（不同 seed 内容不相关，拼贴后能分出彼此）"""
    import numpy as np
    rng = np.random.default_rng(seed)
    return rng.integers(0, 255, (h, w, 3), dtype=np.uint8)


def _write_png(path, img):
    import cv2
    path.parent.mkdir(parents=True, exist_ok=True)
    cv2.imencode(".png", img)[1].tofile(str(path))


def _tpl(sword_id, name_zh, form="普", tag=None, seed=1, size=(56, 76)):
    return {"no": "0000", "form": form, "name": name_zh, "tag": tag,
            "sword_id": sword_id, "name_zh": name_zh, "path": None,
            "img": _img(size[0], size[1], seed)}


class LoadTemplateTests(unittest.TestCase):
    def _resource(self, files):
        tmp = tempfile.TemporaryDirectory(prefix="avatar_db_test_")
        self.addCleanup(tmp.cleanup)
        folder = Path(tmp.name) / "image" / "头像"
        for name, seed in files:
            _write_png(folder / name, _img(56, 76, seed))
        return tmp.name

    def test_parse_forms_and_chushou_tag(self):
        resource = self._resource([
            ("0003_普_三日月宗近.png", 1),
            ("0004_极_三日月宗近.png", 2),
            ("0131_极_鹤丸国永_中伤.png", 3),
        ])
        tpls, skipped = avatar_db.load_avatar_templates(resource)
        self.assertEqual(skipped, [])
        self.assertEqual(len(tpls), 3)
        by_no = {t["no"]: t for t in tpls}
        self.assertEqual(by_no["0003"]["form"], "普")
        self.assertIsNone(by_no["0003"]["tag"])
        self.assertEqual(by_no["0004"]["form"], "极")
        self.assertEqual(by_no["0131"]["tag"], "中伤")
        # 中文名过桥到 sword_id（sword_db 没有番号字段）
        self.assertEqual(by_no["0003"]["sword_id"],
                         by_no["0004"]["sword_id"])
        self.assertTrue(by_no["0003"]["sword_id"].startswith("touken_"))

    def test_bad_filename_and_unknown_name_are_skipped_honestly(self):
        resource = self._resource([
            ("0003_普_三日月宗近.png", 1),
            ("随便一张图.png", 2),
            ("0099_普_根本不存在的刀.png", 3),
        ])
        tpls, skipped = avatar_db.load_avatar_templates(resource)
        self.assertEqual(len(tpls), 1)
        self.assertEqual(len(skipped), 2)
        reasons = {name: why for name, why in skipped}
        self.assertIn("格式", reasons["随便一张图.png"])
        self.assertIn("名册接不住", reasons["0099_普_根本不存在的刀.png"])


class MatchAvatarTests(unittest.TestCase):
    def test_pasted_avatar_wins_with_margin(self):
        import numpy as np
        band = _img(100, 260, seed=99)
        face = _img(56, 76, seed=7)
        band[10:66, 20:96] = face
        templates = [{"no": "1", "form": "普", "name": "甲", "tag": None,
                      "sword_id": "sid_a", "name_zh": "甲", "path": None,
                      "img": face},
                     _tpl("sid_b", "乙", seed=8)]
        hit = avatar_db.match_avatar(band, templates)
        self.assertEqual(hit["sword_id"], "sid_a")
        self.assertGreaterEqual(hit["score"], 0.99)
        self.assertGreaterEqual(hit["margin"], 0.3)
        self.assertEqual(hit["form"], "普")

    def test_runner_up_of_same_sword_does_not_dilute_margin(self):
        import numpy as np
        band = _img(100, 260, seed=99)
        face = _img(56, 76, seed=7)
        band[10:66, 20:96] = face
        templates = [
            {"no": "1", "form": "极", "name": "甲", "tag": None,
             "sword_id": "sid_a", "name_zh": "甲", "path": None, "img": face},
            # 同刀普形态：与极同一张脸微调（高分但不该算次高压 margin）
            {"no": "2", "form": "普", "name": "甲", "tag": None,
             "sword_id": "sid_a", "name_zh": "甲", "path": None,
             "img": np.clip(face.astype(int) + 3, 0, 255).astype("uint8")},
            _tpl("sid_b", "乙", seed=8)]
        hit = avatar_db.match_avatar(band, templates)
        self.assertEqual(hit["sword_id"], "sid_a")
        self.assertEqual(hit["form"], "极")
        self.assertGreaterEqual(hit["margin"], 0.3)
        # 同刀另一形态的分单记，给形态结论用
        self.assertIsNotNone(hit["form_rival_score"])
        self.assertGreaterEqual(hit["form_rival_score"], 0.9)
        self.assertEqual(hit["forms_in_library"], ["普", "极"])

    def test_no_candidates_returns_none(self):
        import numpy as np
        self.assertIsNone(avatar_db.match_avatar(None, [_tpl("a", "甲")]))
        self.assertIsNone(avatar_db.match_avatar(np.zeros((0, 0, 3), "uint8"),
                                                 [_tpl("a", "甲")]))
        self.assertIsNone(avatar_db.match_avatar(_img(100, 260, 1), []))
        # 模板比搜索带还大 → 无候选
        self.assertIsNone(avatar_db.match_avatar(
            _img(40, 60, 1), [_tpl("a", "甲")]))


class ThresholdTests(unittest.TestCase):
    def _hit(self, score, margin, forms=("普", "极"), rival=0.80, form="普"):
        return {"sword_id": "sid", "name_zh": "甲", "form": form, "tag": None,
                "score": score, "margin": margin,
                "forms_in_library": sorted(forms),
                "form_rival_score": rival}

    def test_identity_adoption_thresholds(self):
        self.assertTrue(avatar_db.avatar_identity_adopted(
            self._hit(0.9355, 0.19)))
        self.assertFalse(avatar_db.avatar_identity_adopted(
            self._hit(0.87, 0.19)))      # 分差不够
        self.assertFalse(avatar_db.avatar_identity_adopted(
            self._hit(0.95, 0.05)))      # margin 不够
        self.assertFalse(avatar_db.avatar_identity_adopted(None))

    def test_form_status_conservative_conditions(self):
        # 总开关默认开（2026-09-21 校准 v2 满分上线）：双形态库 + 达标 +
        # 压过另一形态 ≥0.05 才下结论
        self.assertTrue(avatar_db.AVATAR_FORM_ENABLED)
        self.assertEqual(avatar_db.avatar_form_status(
            self._hit(0.95, 0.3, rival=0.80, form="普")), "normal")
        self.assertEqual(avatar_db.avatar_form_status(
            self._hit(0.95, 0.3, rival=0.80, form="极")), "kiwame")
        # 分差不够 0.05 → 只记观测
        self.assertIsNone(avatar_db.avatar_form_status(
            self._hit(0.95, 0.3, rival=0.92)))
        # 分数不够 → 只记观测
        self.assertIsNone(avatar_db.avatar_form_status(
            self._hit(0.80, 0.3, rival=0.60)))
        # 单形态库 → 永不下结论
        self.assertIsNone(avatar_db.avatar_form_status(
            self._hit(0.99, 0.9, forms=("普",), rival=None)))
        self.assertIsNone(avatar_db.avatar_form_status(None))

    def test_form_status_respects_master_switch(self):
        # 开关拨回 False 时（比如未来校准翻车要紧急下架），再漂亮的命中
        # 也不下形态结论
        with patch.object(avatar_db, "AVATAR_FORM_ENABLED", False):
            self.assertIsNone(avatar_db.avatar_form_status(
                self._hit(0.99, 0.9, rival=0.50)))


if __name__ == "__main__":
    unittest.main()
