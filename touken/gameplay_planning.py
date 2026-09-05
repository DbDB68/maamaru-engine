"""按玩法估算次数、工时和门票预算；计算全部在服务端。"""
import math
import statistics
from datetime import datetime, timezone, timedelta

TZ = timezone(timedelta(hours=8))
CAMPAIGN = {"name": "异去 · 宝物碎片掉落率 2 倍", "start_at": "2026-09-03T10:00:00+08:00",
            "end_at": "2026-09-10T10:00:00+08:00", "source": "https://www.bilibili.com/read/cv52768115/"}


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
    free = number("free_runs", 0, 0, 1000000, True)
    price = number("price", 500, 0, 1000000)
    budget = number("budget", 50000, 0, 1000000000)
    mode = values.get("mode", "time")
    if mode not in ("time", "runs"):
        raise ValueError("请选择按时间或目标次数规划")
    try:
        end = datetime.fromisoformat(values.get("deadline") or CAMPAIGN["end_at"])
        if end.tzinfo is None:
            end = end.replace(tzinfo=TZ)
    except (ValueError, TypeError):
        raise ValueError("截止时间无效")
    remaining = max(0, (end - now).total_seconds())
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
    result = {"campaign": CAMPAIGN, "sample_count": len(samples), "seconds_per_run": speed,
              "speed_source": "手填估计" if manual not in (None, "") else "近 14 天连续圈实测中位数",
              "runs": None, "cost": None, "hours": None, "can_finish": None,
              "remaining_hours": remaining / 3600}
    if speed is None:
        return result
    # 按剩余天数折算每日时长；最后不足一天按比例计入。
    available_seconds = remaining * hours / 24
    affordable = math.floor(budget / price) + free if price else 1000000000
    runs = target if mode == "runs" else min(math.floor(available_seconds / speed), affordable)
    result.update(runs=runs, cost=max(0, runs-free)*price, hours=runs*speed/3600,
                  can_finish=runs*speed <= available_seconds and max(0, runs-free)*price <= budget)
    return result
