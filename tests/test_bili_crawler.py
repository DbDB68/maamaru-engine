"""B 站公告爬虫的纯函数单测：正文候选提取、跨年推断、合并与重抓策略。
网络部分（fetch_*）不在单测范围，真抓取走手动验证。"""
import sys
import time
import unittest
from datetime import datetime
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent / "scripts"))

import bili_events_crawler as crawler  # noqa: E402


_SAMPLE_TEXT = """
一些开场白
1、全新活动「江户城潜入调查」开启
【活动时间】8月27日10:00 - 9月10日5:00
活动详情 blah blah
2、宝库奖励开箱时间
【活动时间】8月27日10:00-9月17日5:00
3、登录领取景趣
【活动时间】这里没有区间
"""


class ExtractScheduleTests(unittest.TestCase):
    PUB = datetime(2026, 8, 26, 12, 0).timestamp()

    def test_extracts_ranges_with_section_names(self):
        cands = crawler.extract_schedule_candidates(_SAMPLE_TEXT, self.PUB)
        self.assertEqual(len(cands), 2)
        self.assertEqual(cands[0]["section"], "1")
        self.assertEqual(cands[0]["section_title"],
                         "全新活动「江户城潜入调查」开启")
        self.assertEqual(cands[0]["name"], "江户城潜入调查")
        self.assertEqual(cands[0]["start_at"], "2026-08-27T10:00:00+08:00")
        self.assertEqual(cands[0]["end_at"], "2026-09-10T05:00:00+08:00")
        self.assertEqual(cands[1]["section"], "2")
        self.assertIsNone(cands[1]["name"])  # 小节标题没有「」，名就空着

    def test_time_range_on_next_line(self):
        text = "1、活动「异去」\n【活动时间】\n8月13日10:00 ~ 8月27日5:00 结束"
        cands = crawler.extract_schedule_candidates(text, self.PUB)
        self.assertEqual(len(cands), 1)
        self.assertEqual(cands[0]["start_at"], "2026-08-13T10:00:00+08:00")

    def test_year_rolls_forward_across_new_year(self):
        # 12 月底发的公告写「1月5日」，年份要 +1
        pub = datetime(2026, 12, 28, 12, 0).timestamp()
        text = "1、活动「连队战」\n【活动时间】1月5日10:00 - 1月19日5:00"
        cands = crawler.extract_schedule_candidates(text, pub)
        self.assertEqual(cands[0]["start_at"], "2027-01-05T10:00:00+08:00")

    def test_no_marker_no_candidates(self):
        self.assertEqual(crawler.extract_schedule_candidates(
            "纯文本没有任何时间", self.PUB), [])


class InferUpdateDateTests(unittest.TestCase):
    def test_basic(self):
        pub = datetime(2026, 8, 26, 12, 0).timestamp()
        self.assertEqual(crawler._infer_update_date("8月27日更新公告", pub),
                         "2026-08-27")

    def test_not_update_notice(self):
        pub = datetime(2026, 8, 26, 12, 0).timestamp()
        self.assertIsNone(crawler._infer_update_date("随便什么标题", pub))


class NeedsFetchTests(unittest.TestCase):
    NOW = time.time()

    def test_no_candidates_needs_fetch(self):
        item = {"update_date": "2026-08-27",
                "url": "https://www.bilibili.com/read/cv1"}
        self.assertTrue(crawler._needs_schedule_fetch(item, self.NOW))

    def test_fresh_candidates_skip(self):
        item = {"update_date": "2026-08-27",
                "url": "https://www.bilibili.com/read/cv1",
                "schedule_candidates": [{"name": "x"}],
                "candidate_schema_version": crawler.CANDIDATE_SCHEMA_VERSION,
                "candidates_extracted_at": self.NOW - 3600}
        self.assertFalse(crawler._needs_schedule_fetch(item, self.NOW))

    def test_old_candidate_schema_refetches_immediately(self):
        item = {"update_date": "2026-08-27",
                "url": "https://www.bilibili.com/read/cv1",
                "schedule_candidates": [{"name": "x"}],
                "candidates_extracted_at": self.NOW - 3600}
        self.assertTrue(crawler._needs_schedule_fetch(item, self.NOW))

    def test_stale_candidates_refetch(self):
        # 候选超过一周：公告可能修订过，重抓自愈
        item = {"update_date": "2026-08-27",
                "url": "https://www.bilibili.com/read/cv1",
                "schedule_candidates": [{"name": "x"}],
                "candidate_schema_version": crawler.CANDIDATE_SCHEMA_VERSION,
                "candidates_extracted_at": self.NOW - 8 * 86400}
        self.assertTrue(crawler._needs_schedule_fetch(item, self.NOW))

    def test_no_update_date_never_fetches(self):
        item = {"url": "https://www.bilibili.com/read/cv1"}
        self.assertFalse(crawler._needs_schedule_fetch(item, self.NOW))


class MergeHistoryTests(unittest.TestCase):
    NOW = time.time()

    def _item(self, title, **extra):
        return {"title": title, "publish_time": self.NOW, **extra}

    def test_old_candidates_carry_forward_with_timestamp(self):
        old = [self._item("公告A", schedule_candidates=[{"name": "x"}],
                          candidates_extracted_at=self.NOW - 100)]
        new = [self._item("公告A")]  # 本轮没抓到（比如风控）
        merged = crawler.merge_history(old, new)
        self.assertEqual(merged[0]["schedule_candidates"], [{"name": "x"}])
        self.assertEqual(merged[0]["candidates_extracted_at"], self.NOW - 100)

    def test_new_candidates_win(self):
        old = [self._item("公告A", schedule_candidates=[{"name": "old"}],
                          candidates_extracted_at=self.NOW - 100)]
        new = [self._item("公告A", schedule_candidates=[{"name": "new"}],
                          candidates_extracted_at=self.NOW)]
        merged = crawler.merge_history(old, new)
        self.assertEqual(merged[0]["schedule_candidates"], [{"name": "new"}])

    def test_expired_announcements_dropped(self):
        ancient = {"title": "老黄历",
                   "publish_time": self.NOW - (crawler.KEEP_WEEKS + 1) * 7 * 86400}
        merged = crawler.merge_history([ancient], [])
        self.assertEqual(merged, [])


if __name__ == "__main__":
    unittest.main()
