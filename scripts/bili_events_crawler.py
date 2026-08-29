#!/usr/bin/env python3
"""刀剑乱舞国服 B 站官方号公告爬虫 → events.json

数据源：bilibili「刀剑乱舞-ONLINE-中文版」(UID 396483168) 的专栏公告列表。
每周二固定发「X月X日更新公告」，标题里带活动名（「…」）和更新日期。

无第三方依赖（stdlib only），免登录：buvid cookie + WBI 签名。
风控对策：调用方（cron）保证低频（一天一次）；失败时保留旧文件不覆盖。

用法：
    python3 bili_events_crawler.py --output /path/to/events.json
"""
from __future__ import annotations

import argparse
import hashlib
import html
import http.cookiejar
import json
import os
import re
import sys
import tempfile
import time
import urllib.parse
import urllib.request
from datetime import date, datetime, timedelta

OFFICIAL_MID = 396483168  # 刀剑乱舞-ONLINE-中文版
USER_AGENT = ("Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 "
              "(KHTML, like Gecko) Chrome/126.0 Safari/537.36")
WBI_MIXIN_TAB = [46, 47, 18, 2, 53, 8, 23, 32, 15, 50, 10, 31, 58, 3, 45, 35,
                 27, 43, 5, 49, 33, 9, 42, 19, 29, 28, 14, 39, 12, 38, 41, 13,
                 37, 48, 7, 16, 24, 55, 40, 61, 26, 17, 0, 1, 60, 51, 30, 4,
                 22, 25, 54, 21, 56, 59, 6, 63, 57, 62, 11, 36, 20, 34, 44, 52]
KEEP_WEEKS = 12
CANDIDATE_SCHEMA_VERSION = 2

_UPDATE_RE = re.compile(r"(\d{1,2})月(\d{1,2})日更新公告")
_EVENT_RE = re.compile(r"「([^」]+)」")
_TIME_RANGE_RE = re.compile(
    r"(\d{1,2})月(\d{1,2})日(\d{1,2}):(\d{2})\s*[-~—–～]\s*"
    r"(\d{1,2})月(\d{1,2})日(\d{1,2}):(\d{2})")
_SECTION_RE = re.compile(r"^(\d+)、(.+)$")


def _open_session():
    """buvid cookie + WBI 密钥。免登录，但被风控时这里会失败（抛异常）。"""
    cj = http.cookiejar.CookieJar()
    opener = urllib.request.build_opener(urllib.request.HTTPCookieProcessor(cj))
    opener.addheaders = [("User-Agent", USER_AGENT),
                         ("Referer", f"https://space.bilibili.com/{OFFICIAL_MID}/article")]
    opener.open("https://www.bilibili.com", timeout=15).read(100)
    nav = json.loads(opener.open(
        "https://api.bilibili.com/x/web-interface/nav", timeout=15).read())
    wbi = nav["data"]["wbi_img"]
    img_key = wbi["img_url"].rsplit("/", 1)[1].split(".")[0]
    sub_key = wbi["sub_url"].rsplit("/", 1)[1].split(".")[0]
    mixin = "".join((img_key + sub_key)[i] for i in WBI_MIXIN_TAB)[:32]
    return opener, mixin


def _signed_get(opener, mixin, url, params):
    params = dict(sorted(params.items()))
    params["wts"] = int(time.time())
    query = urllib.parse.urlencode(params)
    params["w_rid"] = hashlib.md5((query + mixin).encode()).hexdigest()
    full = url + "?" + urllib.parse.urlencode(params)
    return json.loads(opener.open(full, timeout=15).read())


def fetch_announcements(pages: int = 2, page_size: int = 20) -> list[dict]:
    opener, mixin = _open_session()
    articles = []
    for page in range(1, pages + 1):
        resp = _signed_get(
            opener, mixin,
            "https://api.bilibili.com/x/space/wbi/article",
            {"mid": OFFICIAL_MID, "ps": page_size, "pn": page,
             "sort": "publish_time"})
        if resp.get("code") != 0:
            raise RuntimeError(f"B站接口返回 code={resp.get('code')} "
                               f"{resp.get('message')}（可能被风控，明天再试）")
        batch = (resp.get("data") or {}).get("articles") or []
        if not batch:
            break
        articles.extend(batch)
        time.sleep(1)  # 低频礼貌
    return articles


def fetch_article_text(cvid: int | str) -> str:
    """抓公告正文纯文本。read 网页版已 302 到 opus（正文靠 JS 渲染拿不到），
    改用 x/article/view 接口，免登录免 WBI。"""
    req = urllib.request.Request(
        f"https://api.bilibili.com/x/article/view?id={cvid}",
        headers={"User-Agent": USER_AGENT,
                 "Referer": "https://www.bilibili.com/"})
    data = json.loads(urllib.request.urlopen(req, timeout=15).read())
    if data.get("code") != 0:
        raise RuntimeError(f"正文接口返回 code={data.get('code')} "
                           f"{data.get('message')}")
    raw = (data.get("data") or {}).get("content") or ""
    raw = re.sub(r"<script[^>]*>.*?</script>", " ", raw, flags=re.S)
    raw = re.sub(r"<style[^>]*>.*?</style>", " ", raw, flags=re.S)
    raw = re.sub(r"<[^>]+>", "\n", raw)
    return html.unescape(raw)


def _to_iso(pub: date, month: int, day: int, hour: int, minute: int) -> str | None:
    """月日时分 + 发布日 → ISO(+08:00)。跨年规则同 _infer_update_date。"""
    try:
        candidate = date(pub.year, month, day)
    except ValueError:
        return None
    if candidate < pub - timedelta(days=20):
        candidate = date(pub.year + 1, month, day)
    return f"{candidate.isoformat()}T{hour:02d}:{minute:02d}:00+08:00"


def extract_schedule_candidates(text: str, publish_time: float) -> list[dict]:
    """从正文里找「【活动时间】X月X日H:MM - Y月Y日H:MM」，活动名取最近的
    「N、…」小节里最后一个「…」。定位是待核对候选，不进业务数据。"""
    pub = datetime.fromtimestamp(publish_time).date() if publish_time else date.today()
    lines = [line.strip() for line in text.splitlines()]
    candidates = []
    for idx, line in enumerate(lines):
        if "【活动时间】" not in line:
            continue
        # 时间范围可能在同一行或紧随其后
        window = " ".join(lines[idx:idx + 3])
        match = _TIME_RANGE_RE.search(window)
        if not match:
            continue
        m1, d1, h1, mi1, m2, d2, h2, mi2 = (int(g) for g in match.groups())
        start = _to_iso(pub, m1, d1, h1, mi1)
        end = _to_iso(pub, m2, d2, h2, mi2)
        if not start or not end:
            continue
        section, section_title, name = None, None, None
        for prev in reversed(lines[:idx]):
            sec = _SECTION_RE.match(prev)
            if sec:
                section = sec.group(1)
                section_title = sec.group(2).strip()
                names = _EVENT_RE.findall(section_title)
                if names:
                    name = names[-1]
                break
        candidates.append({"section": section,
                           "section_title": section_title,
                           "name": name,
                           "start_at": start, "end_at": end})
    return candidates



def _infer_update_date(title: str, publish_time: float) -> str | None:
    """「8月27日更新公告」→ 2026-08-27。年份按发布时间推，跨年往回绕。"""
    match = _UPDATE_RE.search(title)
    if not match:
        return None
    month, day = int(match.group(1)), int(match.group(2))
    pub = datetime.fromtimestamp(publish_time).date()
    try:
        candidate = date(pub.year, month, day)
    except ValueError:
        return None
    if candidate < pub - timedelta(days=20):  # 公告发布时间贴近更新日
        candidate = date(pub.year + 1, month, day)
    return candidate.isoformat()


def parse_announcement(article: dict) -> dict:
    title = str(article.get("title") or "").strip()
    publish_time = float(article.get("publish_time") or 0)
    cvid = article.get("id") or article.get("cvid")
    return {
        "title": title,
        "publish_time": publish_time,
        "publish_date": datetime.fromtimestamp(publish_time).date().isoformat()
        if publish_time else None,
        "update_date": _infer_update_date(title, publish_time),
        "events": _EVENT_RE.findall(title),
        "url": f"https://www.bilibili.com/read/cv{cvid}" if cvid else None,
    }


# 候选重抓间隔：公告可能修订、解析规则会升级，候选不是终身制；
# 但也别每天骚扰同一篇，一周一轮够了
CANDIDATES_TTL = 7 * 86400


def _needs_schedule_fetch(item: dict, now: float) -> bool:
    """这篇公告要不要（重）抓正文找活动时间。

    没有候选的要抓；有候选但提取时间超过一周的也要重抓
    （公告修订/解析规则升级后自愈），新鲜候选不重复请求。
    """
    if not item.get("update_date") or not item.get("url"):
        return False
    candidates = item.get("schedule_candidates")
    if not candidates:
        return True
    if item.get("candidate_schema_version") != CANDIDATE_SCHEMA_VERSION:
        return True
    return now - float(item.get("candidates_extracted_at") or 0) > CANDIDATES_TTL


def merge_history(old: list[dict], new: list[dict]) -> list[dict]:
    """按标题去重合并，只保留近 KEEP_WEEKS 周的公告。"""
    cutoff = time.time() - KEEP_WEEKS * 7 * 86400
    merged = {}
    for item in old + new:
        if item.get("publish_time", 0) >= cutoff and item.get("title"):
            prev = merged.get(item["title"])
            if (prev and "schedule_candidates" not in item
                    and prev.get("schedule_candidates")):
                item = {**item,
                        "schedule_candidates": prev["schedule_candidates"],
                        "candidates_extracted_at":
                            prev.get("candidates_extracted_at")}
            merged[item["title"]] = item
    return sorted(merged.values(), key=lambda x: x.get("publish_time", 0),
                  reverse=True)


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--output", required=True, help="events.json 输出路径")
    args = parser.parse_args()

    try:
        articles = fetch_announcements()
    except Exception as exc:
        print(f"[爬虫] 抓取失败：{exc}", file=sys.stderr)
        return 1
    new_items = [parse_announcement(a) for a in articles]
    try:
        with open(args.output, encoding="utf-8") as fh:
            old_items = json.load(fh).get("announcements", [])
    except (OSError, ValueError):
        old_items = []
    merged = merge_history(old_items, new_items)
    # 抓正文找活动时间候选。对合并后的全量做：老公告上次没抓到的这次补票，
    # 候选超过一周的重抓（公告会修订、规则会升级），新鲜候选跳过
    for item in merged:
        if not _needs_schedule_fetch(item, time.time()):
            continue
        cvid = item["url"].rsplit("cv", 1)[-1]
        try:
            text = fetch_article_text(cvid)
            found = extract_schedule_candidates(text, item["publish_time"])
            if found:
                item["schedule_candidates"] = found
                item["candidate_schema_version"] = CANDIDATE_SCHEMA_VERSION
                item["candidates_extracted_at"] = time.time()
        except Exception as exc:  # 单篇失败不拖垮整批
            print(f"[爬虫] cv{cvid} 正文抓取失败：{exc}", file=sys.stderr)
        time.sleep(3)  # 正文接口风控敏感，宁可慢不可 429
    payload = {
        "generated_at": time.time(),
        "source": f"bilibili:{OFFICIAL_MID}",
        "announcements": merged,
    }
    # 原子写：先临时文件再替换，面板读到一半的概率归零
    out_dir = os.path.dirname(os.path.abspath(args.output))
    os.makedirs(out_dir, exist_ok=True)
    with tempfile.NamedTemporaryFile("w", encoding="utf-8", dir=out_dir,
                                     delete=False, suffix=".tmp") as fh:
        json.dump(payload, fh, ensure_ascii=False, indent=1)
        tmp = fh.name
    os.replace(tmp, args.output)
    print(f"[爬虫] {len(new_items)} 篇公告入库，"
          f"历史共 {len(payload['announcements'])} 条 → {args.output}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
