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


class FetchArticleRetryTests(unittest.TestCase):
    """正文抓取退避重试：-509/网络错误重试，永久错误码不重试。纯逻辑不碰网。"""

    def test_retry_until_success(self):
        calls = []

        def fake_fetch(cvid):
            calls.append(cvid)
            if len(calls) < 3:
                return {"code": -509, "message": "请求过于频繁"}
            return {"code": 0, "message": "ok",
                    "data": {"content": "<p>正文</p>"}}

        sleeps = []
        text = crawler.fetch_article_text("42", fetch=fake_fetch,
                                          sleep=sleeps.append)
        self.assertEqual(text.strip(), "正文")
        self.assertEqual(calls, ["42", "42", "42"])
        self.assertEqual(sleeps, [10.0, 30.0])

    def test_final_failure_raises_after_full_backoff(self):
        def fake_fetch(cvid):
            return {"code": -509, "message": "请求过于频繁"}

        sleeps = []
        with self.assertRaises(RuntimeError) as ctx:
            crawler.fetch_article_text(7, fetch=fake_fetch,
                                       sleep=sleeps.append)
        self.assertIn("-509", str(ctx.exception))
        self.assertEqual(sleeps, [10.0, 30.0, 60.0])

    def test_permanent_error_code_not_retried(self):
        def fake_fetch(cvid):
            return {"code": -404, "message": "文章不存在"}

        sleeps = []
        with self.assertRaises(RuntimeError) as ctx:
            crawler.fetch_article_text(7, fetch=fake_fetch,
                                       sleep=sleeps.append)
        self.assertIn("-404", str(ctx.exception))
        self.assertEqual(sleeps, [])

    def test_network_error_retried(self):
        attempts = [0]

        def fake_fetch(cvid):
            attempts[0] += 1
            if attempts[0] == 1:
                raise OSError("connection reset")
            return {"code": 0, "message": "ok", "data": {"content": "x"}}

        text = crawler.fetch_article_text(7, fetch=fake_fetch,
                                          sleep=lambda s: None)
        self.assertEqual(text.strip(), "x")
        self.assertEqual(attempts[0], 2)


class FillScheduleCandidatesTests(unittest.TestCase):
    """单篇正文补抓：成功记候选并清旧错，最终失败记 last_fetch_error 留痕。"""

    PUB = datetime(2026, 9, 22, 12, 0).timestamp()
    NOW = 1758000000.0

    def _item(self, **extra):
        item = {"title": "9月22日更新公告", "publish_time": self.PUB,
                "update_date": "2026-09-24",
                "url": "https://www.bilibili.com/read/cv999"}
        item.update(extra)
        return item

    def test_success_records_candidates_and_clears_old_error(self):
        item = self._item(last_fetch_error="旧错", last_fetch_error_at=1.0)
        text = ("1、全新活动「联队战 ~海边之阵~」开启\n"
                "【活动时间】9月24日10:00 - 10月15日5:00")

        def fake_fetch(cvid):
            self.assertEqual(cvid, "999")
            return text

        crawler.fill_schedule_candidates([item], now=self.NOW,
                                         fetch=fake_fetch,
                                         sleep=lambda s: None)
        self.assertEqual(item["schedule_candidates"][0]["name"],
                         "联队战 ~海边之阵~")
        self.assertEqual(item["candidate_schema_version"],
                         crawler.CANDIDATE_SCHEMA_VERSION)
        self.assertEqual(item["candidates_extracted_at"], self.NOW)
        self.assertNotIn("last_fetch_error", item)
        self.assertNotIn("last_fetch_error_at", item)

    def test_final_failure_records_last_fetch_error(self):
        def fake_fetch(cvid):
            raise RuntimeError("正文接口限流 code=-509 请求过于频繁")

        item = self._item()
        crawler.fill_schedule_candidates([item], now=self.NOW,
                                         fetch=fake_fetch,
                                         sleep=lambda s: None)
        self.assertIn("-509", item["last_fetch_error"])
        self.assertEqual(item["last_fetch_error_at"], self.NOW)
        self.assertNotIn("schedule_candidates", item)

    def test_fresh_candidates_skip_fetch(self):
        item = self._item(schedule_candidates=[{"name": "秘宝之里"}],
                          candidate_schema_version=crawler.CANDIDATE_SCHEMA_VERSION,
                          candidates_extracted_at=time.time())
        calls = []

        crawler.fill_schedule_candidates([item], now=self.NOW,
                                         fetch=lambda cvid: calls.append(cvid)
                                         or "不该抓",
                                         sleep=lambda s: None)
        self.assertEqual(calls, [])
        self.assertEqual(item["schedule_candidates"], [{"name": "秘宝之里"}])


if __name__ == "__main__":
    unittest.main()
