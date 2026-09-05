"""按玩法估算次数、工时和门票预算；计算全部在服务端。

门票价、每日免费次数和本期加倍活动来自 touken/data/gameplay_meta.json
玩法数据卡（出处见卡内 note）；数据卡缺失时退回内置默认值。
"""
import json
import math
import statistics
from datetime import datetime, timezone, timedelta
from pathlib import Path

TZ = timezone(timedelta(hours=8))
_DATA_DIR = Path(__file__).resolve().parent / "data"
_FALLBACK_CAMPAIGN = {"name": "异去 · 宝物碎片掉落率 2 倍", "start_at": "2026-09-03T10:00:00+08:00",
                      "end_at": "2026-09-10T10:00:00+08:00", "source": "https://www.bilibili.com/read/cv52768115/"}
_FALLBACK_PRICE = 500


def load_gameplay_card(name="异去"):
    """读玩法数据卡；文件缺失或没有该玩法时返回空字典，由调用方兜底。"""
    try:
        cards = json.loads((_DATA_DIR / "gameplay_meta.json").read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return {}
    card = cards.get(name)
    return card if isinstance(card, dict) else {}


def estimate(store, values, now=None):
    now = now or datetime.now(TZ)
    def number(key, default, minimum, maximum, integer=False):
        try:
            value = float(values.get(key, default))
        except (ValueError, TypeError):
            raise ValueError(f"{key} 请输入有效数字")
        if not math.isfinite(value) or not minimum <= value <= maximum or (integer and value != int(value)):
            raise ValueError(f"{key} 超出可用范围")
        return int(value) if integer else value
    map_no = number("map_no", 1, 1, 4, True)
    hours = number("hours_per_day", 2, 0.01, 24)
    target = number("runs", 100, 0, 1000000, True)
    free_override = values.get("free_runs")
    current_free = number("current_free", 0, 0, 1000000, True)
    card = load_gameplay_card()
    campaign = card.get("campaign") or _FALLBACK_CAMPAIGN
    if values.get("price") in (None, ""):
        values = {**values, "price": card.get("paid_run_price") or _FALLBACK_PRICE}
    price = number("price", _FALLBACK_PRICE, 0, 1000000)
    budget = number("budget", 50000, 0, 1000000000)
    mode = values.get("mode", "time")
    if mode not in ("time", "runs"):
        raise ValueError("请选择按时间或目标次数规划")
    try:
        end = datetime.fromisoformat(values.get("deadline") or campaign["end_at"])
        if end.tzinfo is None:
            end = end.replace(tzinfo=TZ)
    except (ValueError, TypeError):
        raise ValueError("截止时间无效")
    now = now.astimezone(TZ)
    end = end.astimezone(TZ)
    remaining = max(0, (end - now).total_seconds())
    # 未核实刷新时刻：只自动计入明天起、截止日之前的完整日。
    full_days = max(0, (end.date() - now.date()).days - 1)
    daily_free = max(0, int(card.get("daily_free_runs") or 0))
    free = number("free_runs", 0, 0, 1000000, True) if free_override not in (None, "") else current_free + full_days * daily_free

    previous, samples = {}, []
    events = store.recent_events(limit=1000, event_type="sortie.completed", from_ts=now.timestamp()-14*86400)
    for event in sorted(events, key=lambda e: e["ts"]):
        data = event.get("payload", {})
        if data.get("mode") != "yosari" or not event.get("run_id"):
            continue
        old = previous.get(event["run_id"])
        if old:
            old_data = old["payload"]
            seconds = event["ts"] - old["ts"]
            if (data.get("map_no") == old_data.get("map_no") == map_no
                    and data.get("sequence", 0) == old_data.get("sequence", 0) + 1
                    and 0 < seconds <= 1800):
                samples.append(seconds)
        previous[event["run_id"]] = event
    manual = values.get("minutes_per_run")
    speed = number("minutes_per_run", 1, 0.01, 180) * 60 if manual not in (None, "") else (statistics.median(samples) if samples else None)
    result = {"campaign": campaign, "sample_count": len(samples), "seconds_per_run": speed,
              "speed_source": "手填估计" if manual not in (None, "") else "近 14 天连续圈实测中位数",
              "runs": None, "cost": None, "hours": None, "can_finish": None,
              "remaining_hours": remaining / 3600,
              "deadline": end.strftime("%Y-%m-%dT%H:%M"), "price": price,
              "daily_free_runs": daily_free, "free_days": full_days,
              "free_runs": free, "free_source": "手填总数" if free_override not in (None, "") else "完整日保守估算",
              "campaign_status": "已结束" if now >= datetime.fromisoformat(campaign["end_at"]) else ("未开始" if now < datetime.fromisoformat(campaign["start_at"]) else "进行中")}
    if speed is None:
        return result
    # 按剩余天数折算每日时长；最后不足一天按比例计入。
    available_seconds = remaining * hours / 24
    if free_override in (None, ""):
        free = current_free + full_days * min(daily_free, math.floor(hours * 3600 / speed))
        result["free_runs"] = free
    affordable = math.floor(budget / price) + free if price else 1000000000
    runs = target if mode == "runs" else min(math.floor(available_seconds / speed), affordable)
    result.update(runs=runs, cost=max(0, runs-free)*price, hours=runs*speed/3600,
                  can_finish=runs*speed <= available_seconds and max(0, runs-free)*price <= budget)
    return result
