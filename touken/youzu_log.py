# -*- coding: utf-8 -*-
"""国服客户端 HttpRequestCollect 日志读取 · 只读事实层（原型）

背景（2026-09-28 实测）：国服 APK（com.youzu.djlw，游族）把每一次
HTTP 请求的完整收发明文写进
  /data/data/com.youzu.djlw/files/userdata/HttpRequestCollect
响应体是不加密的 JSON（128 位的 t 字段只是签名）。MuMu 上 `adb root`
之后 adb pull 即可拿到，对游戏进程完全无感（无注入/无改包/无网络接触）。

特性（都已实测）：
  - 每次启动游戏时日志被清空重写——想留记录必须在下次启动前 pull；
  - 启动进本丸会自动拉全量（login/start、party/list、sally），
    开局即快照，不用翻任何界面；
  - 每 30 秒左右一条 keepalive。

本模块只做两件事：pull 日志、解析出本丸状态快照。不读写游戏、
不重放请求（拿 session 直接调 API 是另一条有风险的路，没走）。
"""

from __future__ import annotations

import json
import re
import subprocess
import time
from datetime import datetime
from pathlib import Path
from urllib.parse import parse_qsl

PACKAGE = "com.youzu.djlw"
REMOTE_LOG = f"/data/data/{PACKAGE}/files/userdata/HttpRequestCollect"

DEFAULT_ADB = r"D:\MUMU\MuMuPlayer\nx_device\12.0\shell\adb.exe"
DEFAULT_ADDRESS = "127.0.0.1:16384"

# 行格式（实测）：
#   【2026-09-28 11:34:37】【C->S】[POST] <url> Data:[k=v&k=v]
#   【2026-09-28 11:34:37】【S->C】<url> readyState:4 status:200 data:{...}
_LINE_RE = re.compile(
    r"^【(?P<ts>\d{4}-\d{2}-\d{2} \d{2}:\d{2}:\d{2})】"
    r"【(?P<direction>C->S|S->C)】(?P<rest>.*)$")

# party.status 的含义是按日服 API 惯例推的（1=待命 2=远征中 3=出阵中），
# 国服还没逐项实测校准，显示时保留原始值，别拿这个标签做自动化判断。
_PARTY_STATUS_LABEL = {"0": "未知", "1": "待命", "2": "远征中?", "3": "出阵中?"}


# ---------------------------------------------------------------- pull

def _adb_run(adb_path: str, address: str, args: list, timeout: int = 30):
    flags = getattr(subprocess, "CREATE_NO_WINDOW", 0)
    return subprocess.run([adb_path, "-s", address] + args,
                          capture_output=True, timeout=timeout,
                          creationflags=flags)


def pull_log(adb_path: str = DEFAULT_ADB, address: str = DEFAULT_ADDRESS,
             dest_dir: Path | str = Path(".tmp") / "youzu") -> Path:
    """把设备上的 HttpRequestCollect 拉到本地，返回本地路径。

    adb root 是幂等的（已是 root 时秒回）；adbd 重启后 root 会掉，
    所以每次 pull 前都补一刀。
    """
    dest_dir = Path(dest_dir)
    dest_dir.mkdir(parents=True, exist_ok=True)
    _adb_run(adb_path, address, ["root"], timeout=15)
    time.sleep(1.5)  # root 重启 adbd，给它一口气的工夫
    stamp = datetime.now().strftime("%Y%m%d-%H%M%S")
    dest = dest_dir / f"HttpRequestCollect-{stamp}.log"
    r = _adb_run(adb_path, address, ["pull", REMOTE_LOG, str(dest)],
                 timeout=120)
    if r.returncode != 0 or not dest.exists():
        raise RuntimeError(f"adb pull 失败: {r.stderr or r.stdout}")
    return dest


# ---------------------------------------------------------------- parse

def parse_events(path: Path | str) -> list[dict]:
    """把日志解析成事件列表 [{ts, direction, method, url, endpoint, payload}]。

    S->C 的 payload 是响应 JSON（解析失败时 payload=None 并记 raw 长度）；
    C->S 的 payload 是请求参数 dict。解析失败的行不静默吞——记进
    返回列表的 bad_lines 统计里（挂事件末尾的元信息条）。
    """
    events: list[dict] = []
    bad = 0
    with open(path, encoding="utf-8", errors="replace") as f:
        for line in f:
            line = line.rstrip("\n")
            m = _LINE_RE.match(line)
            if not m:
                if line.strip():
                    bad += 1
                continue
            rest = m.group("rest")
            ev = {"ts": m.group("ts"), "direction": m.group("direction"),
                  "method": None, "url": None, "endpoint": None,
                  "payload": None}
            if ev["direction"] == "C->S":
                mm = re.match(r"\[(?P<method>\w+)\]\s+(?P<url>\S+)"
                              r"(?:\s+Data:\[(?P<data>.*)\])?\s*$", rest)
                if mm:
                    ev["method"] = mm.group("method")
                    ev["url"] = mm.group("url")
                    data = mm.group("data")
                    if data:
                        ev["payload"] = dict(parse_qsl(data, keep_blank_values=True))
                else:
                    bad += 1
                    continue
            else:
                mm = re.match(r"(?P<url>\S+)\s+readyState:(?P<rs>\d+)"
                              r"\s+status:(?P<sc>\d+)\s+data:(?P<data>.*)$", rest)
                if not mm:
                    bad += 1
                    continue
                ev["url"] = mm.group("url")
                ev["status"] = int(mm.group("sc"))
                try:
                    ev["payload"] = json.loads(mm.group("data"))
                except ValueError:
                    bad += 1
            if ev["url"]:
                path_part = re.sub(r"^https?://[^/]+", "", ev["url"])
                ev["endpoint"] = path_part.split("?", 1)[0]
            events.append(ev)
    events.append({"ts": None, "direction": "META",
                   "endpoint": None, "url": None, "method": None,
                   "payload": {"bad_lines": bad, "event_count": len(events)}})
    return events


def _latest(events: list[dict], endpoint: str) -> dict | None:
    """某个端点最后一次响应的 payload（没有则 None）。"""
    for ev in reversed(events):
        if ev["direction"] == "S->C" and ev["endpoint"] == endpoint \
                and isinstance(ev["payload"], dict):
            return ev["payload"]
    return None


def _latest_merged(events: list[dict], endpoint: str) -> dict:
    """某个端点所有响应的逐键合并（旧的先铺，新的覆盖同名字段）。

    同一个端点的响应不一定每次都带全字段（比如 /home 后续心跳式
    调用可能只回变化的键），只取最后一条会丢字段。
    """
    merged: dict = {}
    for ev in events:
        if ev["direction"] == "S->C" and ev["endpoint"] == endpoint \
                and isinstance(ev["payload"], dict):
            merged.update(ev["payload"])
    return merged


# ---------------------------------------------------------------- snapshot

def _int(v, default=0):
    try:
        return int(v)
    except (TypeError, ValueError):
        return default


def _sword_name(sword_id, db) -> str:
    """sword_id → 名字。极化刀帐号 = 通常番号 + 1（如 3 三日月→4 三月极），
    名册只收了通常形态；查不到就试前一个号并补「极」标。
    （国服的 evol_num 字段不是极化标记，实测极化刀它也是 0，别踩。）"""
    sid = _int(sword_id)
    try:
        found = db.find_by_id(sid)
        if not found and sid > 1:
            prev = db.find_by_id(sid - 1)
            if prev:
                info = prev[1]
                base = info.get("name_zh") or info.get("name") or f"刀帐{sid - 1}"
                return base + "·极"
            return f"刀帐{sid}"
    except Exception:
        return f"刀帐{sid}"
    info = found[1]
    return info.get("name_zh") or info.get("name") or f"刀帐{sid}"


def build_snapshot(events: list[dict], with_swords: bool = True) -> dict:
    """把事件流汇总成本丸状态快照（latest-wins）。

    返回 dict 可直接 json.dump；swords 全量默认带上（它是事实层，
    展示层自己决定切多少）。
    """
    from . import sword_db  # 延迟 import，解析逻辑单测可以不碰名册

    login = _latest(events, "/login/start") or {}
    home = _latest_merged(events, "/home")
    situation = _latest(events, "/home/situation") or {}
    party_list = _latest(events, "/party/list") or {}
    sally = _latest(events, "/sally") or {}
    forge = _latest(events, "/forge") or {}
    conquest = _latest(events, "/conquest") or {}

    swords = party_list.get("sword") or sally.get("sword_all") or {}
    parties = party_list.get("party") or login.get("party") or {}

    # 资源：home/forge/conquest 里都带 resource，谁新用谁（此处按端点
    # 优先级取第一个非空，同一局内差异不大；要精确到时刻就查事件流）
    resource = home.get("resource") or forge.get("resource") \
        or conquest.get("resource") or {}
    currency = home.get("currency") or login.get("currency") or {}

    def _sword_brief(s):
        return {
            "serial_id": _int(s.get("serial_id")),
            "sword_id": _int(s.get("sword_id")),
            "name": _sword_name(s.get("sword_id"), sword_db),
            "level": _int(s.get("level")),
            "rarity": _int(s.get("rarity")),
            "hp": _int(s.get("hp")), "hp_max": _int(s.get("hp_max")),
            "fatigue": _int(s.get("fatigue")),
            "evol_num": _int(s.get("evol_num")),  # >0 一般是极化
            "protected": bool(_int(s.get("protect"))),
        }

    party_status = situation.get("party") or {}
    party_rows = []
    for no in sorted(parties, key=lambda x: _int(x)):
        p = parties[no]
        members = []
        for slot_no in sorted((p.get("slot") or {}), key=lambda x: _int(x)):
            sid = (p["slot"][slot_no] or {}).get("serial_id")
            if sid and str(sid) in swords:
                members.append(_sword_brief(swords[str(sid)]))
        st = str((party_status.get(str(no)) or {}).get("status")
                 if party_status else p.get("status") or "")
        party_rows.append({
            "party_no": _int(no),
            "party_name": p.get("party_name") or "",
            "status": _int(st, -1),
            "status_label": _PARTY_STATUS_LABEL.get(st, f"未知({st})"),
            "finished_at": p.get("finished_at"),
            "members": members,
        })

    forge_rows = []
    for slot_no, slot in sorted((situation.get("forge")
                                 or forge.get("forge") or {}).items(),
                                key=lambda kv: _int(kv[0])):
        forge_rows.append({"slot_no": _int(slot_no),
                           "finished_at": slot.get("finished_at")})

    snap = {
        "schema": 1,
        "generated_at": datetime.now().strftime("%Y-%m-%d %H:%M:%S"),
        "profile": {
            "user_id": login.get("user_id"),
            "name": login.get("name") or "",
            "level": _int(login.get("level")),
            "exp": _int(login.get("exp")),
            "server_name": login.get("server_name") or "",
            "created_at": login.get("created_at") or "",
            "secretary": _sword_name(login.get("secretary"), sword_db)
            if login.get("secretary") else "",
        },
        "resources": {
            "charcoal": _int(resource.get("charcoal")),   # 木炭
            "steel": _int(resource.get("steel")),         # 玉钢
            "coolant": _int(resource.get("coolant")),     # 冷却材
            "whetstone": _int(resource.get("file")),      # 砥石
            "bill": _int(resource.get("bill")),           # 手伝い札
            "koban": _int(currency.get("money")),         # 小判
        },
        "sword_count": len(swords),
        "sword_capacity": _int(login.get("sword_max_slot")
                               or login.get("max_sword")),
        "parties": party_rows,
        "forge_slots": forge_rows,
        "repair": situation.get("repair") or [],
        "duty": home.get("duty") or {},
        "conquest_summary": conquest.get("summary") or [],
        "event_points": sally.get("point") or {},
        "season": {"season_id": home.get("season_id"),
                   "end_at": home.get("season_end_at")},
        "server_time": home.get("now") or login.get("now"),
    }
    if with_swords:
        snap["swords"] = [_sword_brief(s) for s in swords.values()]
    return snap


# ---------------------------------------------------------------- display

def format_summary(snap: dict) -> str:
    p = snap["profile"]
    r = snap["resources"]
    lines = [
        f"本丸快照（数据时间 {snap.get('server_time') or '?'}，"
        f"生成于 {snap['generated_at']}）",
        f"  审神者：{p['name'] or '?'}  Lv.{p['level']}  "
        f"服务器：{p['server_name'] or '?'}  近侍：{p['secretary'] or '?'}",
        f"  资源：木炭 {r['charcoal']} / 玉钢 {r['steel']} / "
        f"冷却材 {r['coolant']} / 砥石 {r['whetstone']}",
        f"        手伝い札 {r['bill']} / 小判 {r['koban']}",
        f"  刀剑：{snap['sword_count']} / {snap['sword_capacity'] or '?'} 振",
    ]
    for party in snap["parties"]:
        mem = "、".join(f"{m['name']}Lv{m['level']}"
                        + (f"(伤{m['hp']}/{m['hp_max']})"
                           if m['hp'] < m['hp_max'] else "")
                        for m in party["members"]) or "（空）"
        lines.append(f"  第{party['party_no']}部队 [{party['status_label']}] "
                     f"{party['party_name']}：{mem}")
    busy = [f"槽{f['slot_no']}→{f['finished_at']}" for f in snap["forge_slots"]
            if f.get("finished_at")]
    if busy:
        lines.append("  锻刀槽：" + "，".join(busy))
    if snap.get("event_points"):
        pts = "，".join(f"活动{k}:{v}" for k, v in snap["event_points"].items())
        lines.append(f"  活动点数：{pts}")
    if snap.get("season", {}).get("end_at"):
        lines.append(f"  赛季 {snap['season']['season_id']}  "
                     f"截止 {snap['season']['end_at']}")
    return "\n".join(lines)


# ---------------------------------------------------------------- cli

def main(argv=None):
    import argparse
    ap = argparse.ArgumentParser(description="国服 HttpRequestCollect 日志 → 本丸快照")
    ap.add_argument("--file", help="解析本地日志文件（不给则从模拟器 pull）")
    ap.add_argument("--adb", default=DEFAULT_ADB)
    ap.add_argument("--address", default=DEFAULT_ADDRESS)
    ap.add_argument("--out", help="快照 JSON 输出路径（默认 .tmp/youzu/snapshot.json）")
    ap.add_argument("--no-swords", action="store_true", help="快照不带全刀帐明细")
    args = ap.parse_args(argv)

    src = Path(args.file) if args.file else pull_log(args.adb, args.address)
    print(f"[日志] {src} ({src.stat().st_size:,} 字节)")
    events = parse_events(src)
    meta = events[-1]["payload"]
    print(f"[解析] 事件 {meta['event_count']} 条，坏行 {meta['bad_lines']} 条")
    snap = build_snapshot(events, with_swords=not args.no_swords)
    out = Path(args.out) if args.out else Path(".tmp") / "youzu" / "snapshot.json"
    out.parent.mkdir(parents=True, exist_ok=True)
    out.write_text(json.dumps(snap, ensure_ascii=False, indent=2),
                   encoding="utf-8")
    print(f"[快照] {out}")
    print()
    print(format_summary(snap))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
