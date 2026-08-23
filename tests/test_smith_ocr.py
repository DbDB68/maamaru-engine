import unittest
from unittest.mock import patch

from touken import sword_db
from touken.flows.smith import SmithMixin
from touken.maa_adapter import Point


class _FakeMaa:
    def __init__(self):
        self.rois = []

    def ocr_all(self, roi):
        self.rois.append(roi.to_list())
        if roi.to_list() == [120, 215, 240, 30]:
            return [("笑面青江", roi.center)]
        return []


class SmithOcrTests(unittest.TestCase):
    def test_scan_whitelist_reads_the_dedicated_name_strip(self):
        sword_id, _ = sword_db.find_by_name("笑面青江")
        flow = SmithMixin()
        flow.maa = _FakeMaa()

        result = flow._scan_whitelist_row({sword_id})

        self.assertEqual(result, ("笑面青江", 195))
        self.assertEqual(flow.maa.rois[0], [120, 215, 240, 30])


class _RevealFakeMaa:
    """收刀用：popup 区永远干净；整屏 OCR 出 reveal_tokens；锻刀状况标题按状态出"""

    def __init__(self, reveal_tokens, on_status_after=2):
        self.reveal_tokens = reveal_tokens
        self.on_status_after = on_status_after
        self.shots = 0
        self.clicked = []

    def screenshot(self, force=False):
        self.shots += 1

    def click(self, pt):
        self.clicked.append((pt.x, pt.y))

    def ocr(self, expected, roi, match_mode="exact"):
        if expected == "锻刀状况" and self.shots > self.on_status_after:
            return Point(640, 70)
        return None

    def ocr_all(self, roi):
        if roi.to_list() == [0, 90, 1280, 630]:  # 整屏认人区
            return list(self.reveal_tokens)
        return []  # 氪金弹窗区没字

    def template_match(self, template, roi=None, threshold=0.8):
        return None


class ForgeCollectRecognitionTests(unittest.TestCase):
    def test_read_forge_sword_strict_match(self):
        flow = SmithMixin()
        flow.maa = _RevealFakeMaa([("大和守安定", Point(500, 600))])

        sword = flow._read_forge_sword()

        self.assertEqual(sword["name"], "大和守安定")
        self.assertEqual(sword["sword_id"], "touken_087_yamato_no_kami_yasusada")

    def test_read_forge_sword_rejects_garbage_and_typos(self):
        flow = SmithMixin()
        # 界面杂字不含刀名；错一个字（大和守安走）不许靠模糊兜底乱认
        flow.maa = _RevealFakeMaa(
            [("刀位", Point(1, 1)), ("大和守安走", Point(2, 2))])

        self.assertIsNone(flow._read_forge_sword())

    def test_find_by_name_fuzzy_switch(self):
        self.assertIsNotNone(sword_db.find_by_name("源清磨"))  # 模糊兜底认对错字
        self.assertIsNone(sword_db.find_by_name("源清磨", fuzzy=False))

    def test_collect_slot_returns_recognized_sword(self):
        flow = SmithMixin()
        flow.maa = _RevealFakeMaa([("大和守安定", Point(500, 600))])

        with patch("touken.flows.smith.time.sleep"):
            collected, sword = flow._collect_slot(205)

        self.assertTrue(collected)
        self.assertEqual(sword["name"], "大和守安定")

    def test_collect_slot_without_name_still_collects(self):
        flow = SmithMixin()
        flow.maa = _RevealFakeMaa([])  # 获得画面没字（书法字认不出）照常收

        with patch("touken.flows.smith.time.sleep"):
            collected, sword = flow._collect_slot(205)

        self.assertTrue(collected)
        self.assertIsNone(sword)

    def test_read_countdown_parses_and_misses(self):
        flow = SmithMixin()

        class _TimerMaa:
            def __init__(self, tokens):
                self.tokens = tokens

            def screenshot(self, force=False):
                pass

            def ocr_all(self, roi):
                return self.tokens

        flow.maa = _TimerMaa([("01:27:30", Point(500, 300))])
        self.assertEqual(flow._read_countdown(205), ("1:27:30", 5250))
        flow.maa = _TimerMaa([("空闲中", Point(500, 300))])
        self.assertIsNone(flow._read_countdown(205))
        self.assertIsNone(flow._watch_hit(("1:27:30", 5250), set()))
        self.assertIsNone(flow._watch_hit(("1:27:30", 5250), {5400}))  # 差 150s 超出容忍
        self.assertEqual(flow._watch_hit(("1:27:30", 5250), {5340}), "1:27:30")


if __name__ == "__main__":
    unittest.main()
