import unittest

from touken import sword_db
from touken.flows.smith import SmithMixin


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


if __name__ == "__main__":
    unittest.main()
