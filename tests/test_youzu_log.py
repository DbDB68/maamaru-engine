# -*- coding: utf-8 -*-
"""youzu_log：国服 HttpRequestCollect 日志解析测试（全部合成数据）"""

import json

from touken import youzu_log


def _c2s(ts, method, url, data=""):
    return f"【{ts}】【C->S】[{method}] {url} Data:[{data}]"


def _s2c(ts, url, payload):
    return (f"【{ts}】【S->C】{url} readyState:4 status:200 "
            f"data:{json.dumps(payload, ensure_ascii=False)}")


SAMPLE = "\n".join([
    _c2s("2026-09-28 11:34:37", "GET",
         "https://mp-djlw.youzu.com/enter",
         "op_id=2106&opgame_id=2297"),
    _s2c("2026-09-28 11:34:38", "https://s39-ios-djlw.youzu.com/login/start?uid=1",
         {"user_id": 1, "name": "测试婶", "level": "290", "exp": "100",
          "server_name": "备前国", "created_at": "2017-06-03 22:50:37",
          "secretary": "119", "status": 0, "t": "x" * 128}),
    _s2c("2026-09-28 11:34:39", "https://s39-ios-djlw.youzu.com/home?uid=1",
         {"resource": {"charcoal": 100, "steel": 200, "coolant": 300,
                       "file": 400, "bill": 5},
          "currency": {"money": "999"},
          "duty": {"type": "3"}, "season_id": "25",
          "season_end_at": "2026-12-17 10:00:00",
          "status": 0, "now": "2026-09-28 11:34:39"}),
    _s2c("2026-09-28 11:34:40", "https://s39-ios-djlw.youzu.com/party/list?uid=1",
         {"sword": {"111": {"serial_id": "111", "sword_id": "118",
                            "rarity": "2", "level": "99", "hp": "45",
                            "hp_max": "45", "fatigue": "100",
                            "evol_num": "0", "protect": "1"}},
          "party": {"1": {"party_no": "1", "status": "1",
                          "party_name": "主力",
                          "slot": {"1": {"serial_id": "111"},
                                   "2": {"serial_id": None}},
                          "finished_at": None}},
          "status": 0}),
    _s2c("2026-09-28 11:34:41", "https://s39-ios-djlw.youzu.com/home/situation?uid=1",
         {"party": {"1": {"status": "1", "equip_full": 1, "member_full": 1}},
          "repair": [], "forge": {"1": {"slot_no": "1",
                                        "finished_at": "2026-09-28 12:00:00"}},
          "status": 0}),
    # 后来的 /home 覆盖先前的（latest-wins）
    _s2c("2026-09-28 11:35:00", "https://s39-ios-djlw.youzu.com/home?uid=1",
         {"resource": {"charcoal": 50, "steel": 60, "coolant": 70,
                       "file": 80, "bill": 6},
          "currency": {"money": "1000"}, "status": 0,
          "now": "2026-09-28 11:35:00"}),
    "这不是日志行，应该被计进坏行",
])


def test_parse_events(tmp_path):
    f = tmp_path / "log.txt"
    f.write_text(SAMPLE, encoding="utf-8")
    events = youzu_log.parse_events(f)
    meta = events[-1]["payload"]
    assert meta["bad_lines"] == 1
    assert meta["event_count"] == 6  # 6 条收发，META 条不计入

    c2s = events[0]
    assert c2s["direction"] == "C->S"
    assert c2s["method"] == "GET"
    assert c2s["endpoint"] == "/enter"
    assert c2s["payload"] == {"op_id": "2106", "opgame_id": "2297"}

    s2c = events[1]
    assert s2c["endpoint"] == "/login/start"
    assert s2c["payload"]["name"] == "测试婶"


def test_snapshot_latest_wins(tmp_path):
    f = tmp_path / "log.txt"
    f.write_text(SAMPLE, encoding="utf-8")
    snap = youzu_log.build_snapshot(youzu_log.parse_events(f))

    # 敏感字段一律不进快照（盗号两件套防御）
    assert "name" not in snap["profile"]
    assert "server_name" not in snap["profile"]
    assert "user_id" not in snap["profile"]
    assert snap["profile"]["level"] == 290
    # 后一条 /home 的资源覆盖前一条
    assert snap["resources"]["charcoal"] == 50
    assert snap["resources"]["koban"] == 1000

    assert snap["sword_count"] == 1
    party1 = snap["parties"][0]
    assert party1["party_name"] == "主力"
    assert party1["status"] == 1
    assert len(party1["members"]) == 1
    assert party1["members"][0]["serial_id"] == 111
    assert party1["members"][0]["level"] == 99

    assert snap["forge_slots"] == [
        {"slot_no": 1, "finished_at": "2026-09-28 12:00:00"}]
    assert snap["season"]["end_at"] == "2026-12-17 10:00:00"
    assert snap["server_time"] == "2026-09-28 11:35:00"


def test_snapshot_without_swords(tmp_path):
    f = tmp_path / "log.txt"
    f.write_text(SAMPLE, encoding="utf-8")
    snap = youzu_log.build_snapshot(youzu_log.parse_events(f),
                                    with_swords=False)
    assert "swords" not in snap
    assert snap["sword_count"] == 1


def test_format_summary_runs(tmp_path):
    f = tmp_path / "log.txt"
    f.write_text(SAMPLE, encoding="utf-8")
    snap = youzu_log.build_snapshot(youzu_log.parse_events(f))
    text = youzu_log.format_summary(snap)
    assert "测试婶" not in text
    assert "第1部队" in text
    assert "Lv.290" in text


LEDGER_SAMPLE = "\n".join([
    _s2c("2026-09-28 11:00:00", "https://s39-ios-djlw.youzu.com/home?uid=1",
         {"resource": {"charcoal": 1000, "steel": 2000, "coolant": 3000,
                       "file": 4000, "bill": 10},
          "currency": {"money": "500", "point": "100", "point_free": "50"},
          "status": 0, "now_time": 1790545200}),
    # 远征完成：收入木炭
    _c2s("2026-09-28 11:05:00", "POST",
         "https://s39-ios-djlw.youzu.com/conquest/complete?uid=1", "party_no=2"),
    _s2c("2026-09-28 11:05:01",
         "https://s39-ios-djlw.youzu.com/conquest/complete?uid=1",
         {"resource": {"charcoal": 1250, "steel": 2000, "coolant": 3000,
                       "file": 4000, "bill": 10},
          "currency": {"money": "500"}, "status": 0,
          "now_time": 1790545501}),
    # 锻刀开炉：四项资源 + 委托符一起扣
    _c2s("2026-09-28 11:06:00", "POST",
         "https://s39-ios-djlw.youzu.com/forge/startmultiple?uid=1", "slot_no=1"),
    _s2c("2026-09-28 11:06:01",
         "https://s39-ios-djlw.youzu.com/forge/startmultiple?uid=1",
         {"resource": {"charcoal": 550, "steel": 1300, "coolant": 2300,
                       "file": 3300, "bill": 9},
          "currency": {"money": "500"}, "status": 0,
          "now_time": 1790545561}),
    # keepalive 不带资源块，不该产生读数
    _s2c("2026-09-28 11:06:30", "https://s39-ios-djlw.youzu.com/keepalive?uid=1",
         {"status": 0, "now_time": 1790545590}),
])


def test_build_ledger(tmp_path):
    f = tmp_path / "log.txt"
    f.write_text(LEDGER_SAMPLE, encoding="utf-8")
    ledger = youzu_log.build_ledger(youzu_log.parse_events(f))

    # 三次带资源的响应 → 三条读数（keepalive 不算）
    assert len(ledger["observations"]) == 3
    # 首条读数含甲州金合并（100+50）与小判
    first = ledger["observations"][0]["reading"]
    assert first["甲州金"] == 150
    assert first["小判"] == 500
    assert first["委托符?"] == 10

    assert len(ledger["changes"]) == 2
    c1, c2 = ledger["changes"]
    assert c1["delta"] == {"木炭": 250}
    assert c1["via"] == ["远征完成"]
    assert c2["delta"] == {"木炭": -700, "玉钢": -700, "冷却材": -700,
                           "砥石": -700, "委托符?": -1}
    assert c2["via"] == ["锻刀开炉"]
    # 时间戳用的是响应体里的服务器 now_time
    assert c1["ts"] == 1790545501


def test_format_ledger_runs(tmp_path):
    f = tmp_path / "log.txt"
    f.write_text(LEDGER_SAMPLE, encoding="utf-8")
    text = youzu_log.format_ledger(
        youzu_log.build_ledger(youzu_log.parse_events(f)))
    assert "远征完成" in text
    assert "木炭+250" in text
    assert "2 笔收支" in text
