"""事件时间轴的分组/排序/去重规则。契约：touken/event_timeline.py。"""
import unittest
from datetime import datetime, timezone, timedelta

from touken import event_timeline

_TZ = timezone(timedelta(hours=8))
NOW = datetime(2026, 8, 26, 15, 0, tzinfo=_TZ)  # 江户城开打前一天下午


def _card(**kw):
    return kw


def _abacus(event, **kw):
    return {"event": event, "message": "", **kw}


class GroupingTests(unittest.TestCase):
    def test_ongoing_upcoming_later_sorted(self):
        cards = {
            "老活动": _card(start_date="2026-08-20", end_date="2026-08-30"),
            "快结束": _card(start_date="2026-08-25", end_date="2026-08-27"),
            "明天开": _card(start_date="2026-08-27", end_date="2026-09-10"),
            "下周开": _card(start_date="2026-09-02", end_date="2026-09-16"),
            "下个月": _card(start_date="2026-09-20", end_date="2026-09-30"),
        }
        tl = event_timeline.build_timeline(cards, [], [], now=NOW)
        # 进行中：谁最先结束谁排前面
        self.assertEqual([e["name"] for e in tl["ongoing"]],
                         ["快结束", "老活动"])
        # 7 天内开始（明天 8-27、9-02 距现在都是 7 天内）
        self.assertEqual([e["name"] for e in tl["upcoming"]],
                         ["明天开", "下周开"])
        self.assertEqual([e["name"] for e in tl["later"]], ["下个月"])

    def test_ended_events_stay_off_axis(self):
        cards = {"已结束": _card(start_date="2026-08-01",
                               end_date="2026-08-25")}
        tl = event_timeline.build_timeline(cards, [], [], now=NOW)
        self.assertEqual(tl["ongoing"], [])
        self.assertEqual(tl["upcoming"], [])
        self.assertEqual(tl["later"], [])

    def test_date_only_card_counts_ongoing_through_end_date(self):
        # 没时刻的卡：结束日当天一整天都算进行中
        cards = {"当天结束": _card(start_date="2026-08-20",
                                 end_date="2026-08-26")}
        tl = event_timeline.build_timeline(cards, [], [], now=NOW)
        self.assertEqual([e["name"] for e in tl["ongoing"]], ["当天结束"])
        self.assertEqual(tl["ongoing"][0]["days_left"], 0)
        self.assertFalse(tl["ongoing"][0]["precise"])

    def test_cardless_dates_stay_off_axis(self):
        # 休眠卡（没日期）不上轴
        cards = {"休眠大阪城": _card(start_date=None, end_date=None)}
        tl = event_timeline.build_timeline(cards, [], [], now=NOW)
        self.assertEqual(tl["ongoing"], [])


class EntryContentTests(unittest.TestCase):
    def test_precise_card_carries_times_and_budget(self):
        cards = {"江户城潜入调查": _card(
            start_at="2026-08-27T10:00:00+08:00",
            end_at="2026-09-10T05:00:00+08:00",
            start_date="2026-08-27", end_date="2026-09-10",
            note="四库全开")}
        abacuses = [_abacus("江户城潜入调查", koban_cost=39600,
                            available_now=9000, shortfall=30600,
                            sufficient=False)]
        tl = event_timeline.build_timeline(cards, abacuses, [], now=NOW)
        entry = tl["upcoming"][0]
        self.assertTrue(entry["precise"])
        self.assertEqual(entry["start_at"], "2026-08-27T10:00:00+08:00")
        self.assertEqual(entry["days_until_start"], 1)  # 明天开
        self.assertEqual(entry["budget"]["shortfall"], 30600)
        self.assertFalse(entry["budget"]["sufficient"])

    def test_event_appears_once_with_both_ends(self):
        # 规则：一场活动只出现一次，开始和结束写在同一张卡上
        cards = {"单场": _card(start_at="2026-08-25T10:00:00+08:00",
                               end_at="2026-09-05T05:00:00+08:00")}
        tl = event_timeline.build_timeline(cards, [], [], now=NOW)
        total = sum(len(tl[k]) for k in ("ongoing", "upcoming", "later"))
        self.assertEqual(total, 1)
        entry = tl["ongoing"][0]
        self.assertEqual(entry["start_date"], "2026-08-25")
        self.assertEqual(entry["end_date"], "2026-09-05")


class UnverifiedTests(unittest.TestCase):
    def test_candidate_matching_card_is_verified(self):
        cards = {"江户城潜入调查": _card(start_date="2026-08-27",
                                       end_date="2026-09-10")}
        anns = [{"title": "8月27日更新公告", "url": "u1",
                 "schedule_candidates": [
                     {"section": "1", "name": "江户城潜入调查",
                      "start_at": "2026-08-27T10:00:00+08:00",
                      "end_at": "2026-09-10T05:00:00+08:00"}]}]
        tl = event_timeline.build_timeline(cards, [], anns, now=NOW)
        self.assertEqual(tl["unverified"], [])

    def test_unknown_candidate_stays_unverified(self):
        anns = [{"title": "8月27日更新公告", "url": "u1",
                 "schedule_candidates": [
                     {"section": "6", "name": "幸运草",
                      "start_at": "2026-08-27T10:00:00+08:00",
                      "end_at": "2026-09-03T10:00:00+08:00"}]}]
        tl = event_timeline.build_timeline({}, [], anns, now=NOW)
        self.assertEqual(len(tl["unverified"]), 1)
        self.assertEqual(tl["unverified"][0]["name"], "幸运草")
        self.assertEqual(tl["unverified"][0]["announcement"], "8月27日更新公告")

    def test_ended_candidates_dropped(self):
        anns = [{"title": "老公告", "url": "u0",
                 "schedule_candidates": [
                     {"section": "1", "name": "老活动",
                      "start_at": "2026-08-13T10:00:00+08:00",
                      "end_at": "2026-08-20T10:00:00+08:00"}]}]
        tl = event_timeline.build_timeline({}, [], anns, now=NOW)
        self.assertEqual(tl["unverified"], [])

    def test_duplicate_candidates_across_announcements_kept_once(self):
        cand = {"section": "9", "name": "夏夜庭院·七夕",
                "start_at": "2026-08-13T10:00:00+08:00",
                "end_at": "2026-09-10T10:00:00+08:00"}
        anns = [{"title": "公告甲", "url": "u1",
                 "schedule_candidates": [cand]},
                {"title": "公告乙", "url": "u2",
                 "schedule_candidates": [dict(cand)]}]
        tl = event_timeline.build_timeline({}, [], anns, now=NOW)
        self.assertEqual(len(tl["unverified"]), 1)


class HiddenEventScriptsTests(unittest.TestCase):
    """概览页常用功能联动隐藏：封闭式判断，没「正在开放」证据就收起来。"""

    def test_ongoing_card_keeps_script_visible(self):
        cards = {"江户城潜入调查": _card(start_date="2026-08-20",
                                       end_date="2026-09-10")}
        hidden = event_timeline.hidden_event_scripts(cards, [], now=NOW)
        self.assertNotIn("edocastle", hidden)

    def test_ended_card_hides_script(self):
        # 大阪城 8-27 收摊，8-26 还在、9-01 就该藏了
        cards = {"大阪城": _card(start_date="2026-08-13",
                               end_date="2026-08-27")}
        self.assertNotIn("osaka",
                         event_timeline.hidden_event_scripts(cards, [], now=NOW))
        later = datetime(2026, 9, 1, 15, 0, tzinfo=_TZ)
        self.assertIn("osaka",
                      event_timeline.hidden_event_scripts(cards, [], now=later))

    def test_no_card_no_candidate_hides(self):
        # 联队战/南瓜现状：啥数据都没有 → 藏
        hidden = event_timeline.hidden_event_scripts({}, [], now=NOW)
        self.assertEqual(sorted(hidden),
                         sorted(event_timeline.SCRIPT_EVENT_MAP.keys()))

    def test_candidate_window_counts_as_evidence(self):
        # 没知识卡，但公告候选的窗口盖住了现在 → 算开放
        anns = [{"title": "更新公告", "url": "u1",
                 "schedule_candidates": [
                     {"section": "1", "name": "联队战",
                      "start_at": "2026-08-25T10:00:00+08:00",
                      "end_at": "2026-09-08T05:00:00+08:00"}]}]
        hidden = event_timeline.hidden_event_scripts({}, anns, now=NOW)
        self.assertNotIn("raid", hidden)
        self.assertIn("pumpkin", hidden)

    def test_future_candidate_does_not_open_early(self):
        anns = [{"title": "预告", "url": "u1",
                 "schedule_candidates": [
                     {"section": "1", "name": "南瓜大作战",
                      "start_at": "2026-10-20T10:00:00+08:00",
                      "end_at": "2026-11-03T05:00:00+08:00"}]}]
        hidden = event_timeline.hidden_event_scripts({}, anns, now=NOW)
        self.assertIn("pumpkin", hidden)


if __name__ == "__main__":
    unittest.main()
