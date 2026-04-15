import argparse
import json
import re
import time
import urllib.error
import urllib.parse
import urllib.request
import uuid
from datetime import datetime
from pathlib import Path
from typing import Dict, List, Optional


SKIP_HEADERS = {"host", "accept-encoding", "connection", "content-length"}


def extract_headers(request_headers: List[Dict]) -> Dict[str, str]:
    headers = {}
    for h in request_headers:
        name = h.get("name", "")
        value = h.get("value", "")
        if not name or name.lower() in SKIP_HEADERS:
            continue
        headers[name] = value
    return headers


def ensure_ddid_cookie(headers: Dict[str, str]) -> Dict[str, str]:
    out = dict(headers)
    cookie = out.get("Cookie", "") or out.get("cookie", "")
    if "ddid=" in cookie:
        if "cookie" in out and "Cookie" not in out:
            out["Cookie"] = out.pop("cookie")
        return out

    ddid = f"ddid={uuid.uuid4()}"
    if cookie:
        cookie = cookie.rstrip("; ") + "; " + ddid
    else:
        cookie = ddid

    out.pop("cookie", None)
    out["Cookie"] = cookie
    return out


def read_har_specs(har_path: Path) -> Dict:
    har = json.loads(har_path.read_text(encoding="utf-8"))
    feed_specs = []
    seen_feed_urls = set()
    reply_spec = None
    detail_spec = None
    hot_topic_spec = None

    for entry in har.get("log", {}).get("entries", []):
        request = entry.get("request", {})
        url = request.get("url", "")

        if "api.coolapk.com/v6/page/dataList" in url and "tagFeedList" in url:
            if url in seen_feed_urls:
                continue
            seen_feed_urls.add(url)
            feed_specs.append({"url": url, "headers": extract_headers(request.get("headers", []))})

        if reply_spec is None and "api2.coolapk.com/v6/feed/replyList" in url:
            headers = ensure_ddid_cookie(extract_headers(request.get("headers", [])))
            reply_spec = {"url": url, "headers": headers}

        if detail_spec is None and "api2.coolapk.com/v6/feed/detail" in url:
            detail_spec = {"url": url, "headers": ensure_ddid_cookie(extract_headers(request.get("headers", [])))}

        if hot_topic_spec is None and "api.coolapk.com/v6/page/dataList" in url and "V11_VERTICL_TOPIIC_HOT_TAB" in url:
            hot_topic_spec = {"url": url, "headers": extract_headers(request.get("headers", []))}

    return {"feed_specs": feed_specs, "reply_spec": reply_spec, "detail_spec": detail_spec, "hot_topic_spec": hot_topic_spec}


def fetch_json(url: str, headers: Dict[str, str], timeout: int) -> Dict:
    req = urllib.request.Request(url=url, headers=headers, method="GET")
    with urllib.request.urlopen(req, timeout=timeout) as resp:
        raw = resp.read()
        charset = resp.headers.get_content_charset() or "utf-8"
        text = raw.decode(charset, errors="replace")
        return json.loads(text)


def parse_feed_cards(payload: Dict) -> List[Dict]:
    feeds = []
    for card in payload.get("data", []):
        items = []
        if isinstance(card, dict) and card.get("entityType") == "feed":
            items.append(card)
        entities = card.get("entities") if isinstance(card, dict) else None
        if isinstance(entities, list):
            items.extend(
                it for it in entities if isinstance(it, dict) and it.get("entityType") == "feed"
            )

        for feed in items:
            message = feed.get("message") or ""
            tags = re.findall(r"#([^#\n]+)#", message)
            pics = feed.get("picArr")
            if not isinstance(pics, list):
                pics = []
            pic = feed.get("pic") or ""
            if pic and pic not in pics:
                pics.insert(0, pic)

            feeds.append(
                {
                    "id": feed.get("id"),
                    "uid": feed.get("uid"),
                    "username": feed.get("username") or "酷友",
                    "avatar": feed.get("userAvatar") or "",
                    "device": feed.get("device_title") or "",
                    "message": message,
                    "topic": feed.get("ttitle") or "",
                    "pics": pics,
                    "dateline": feed.get("dateline") or 0,
                    "lastupdate": feed.get("lastupdate") or 0,
                    "likenum": feed.get("likenum") or 0,
                    "replynum": feed.get("replynum") or 0,
                    "forwardnum": feed.get("forwardnum") or 0,
                    "tags": tags,
                }
            )
    return feeds


def parse_reply_rows(payload: Dict, max_rows: int) -> List[Dict]:
    rows = []
    for row in payload.get("data", []):
        if not isinstance(row, dict):
            continue
        rows.append(
            {
                "id": row.get("id"),
                "uid": row.get("uid"),
                "username": row.get("username") or "酷友",
                "avatar": row.get("userAvatar") or "",
                "message": row.get("message") or "",
                "dateline": row.get("dateline") or 0,
                "likenum": row.get("likenum") or 0,
                "replynum": row.get("replynum") or 0,
                "pic": row.get("pic") or "",
            }
        )
        if len(rows) >= max_rows:
            break
    return rows


def merge_feeds(feeds: List[Dict]) -> List[Dict]:
    unique = {}
    for feed in feeds:
        feed_id = feed.get("id")
        if not feed_id:
            continue
        unique[feed_id] = feed

    merged = list(unique.values())
    merged.sort(key=lambda x: (x.get("lastupdate", x.get("dateline", 0)), x.get("id", 0)), reverse=True)
    return merged


def build_trending_tags(feeds: List[Dict]) -> List[Dict]:
    tag_count = {}
    for feed in feeds:
        for tag in feed.get("tags", []):
            t = (tag or "").strip()
            if not t:
                continue
            tag_count[t] = tag_count.get(t, 0) + 1
    return [
        {"name": k, "count": v}
        for k, v in sorted(tag_count.items(), key=lambda kv: (-kv[1], kv[0]))[:12]
    ]


def build_reply_url(template_url: str, feed_id: int) -> str:
    parts = urllib.parse.urlsplit(template_url)
    query = dict(urllib.parse.parse_qsl(parts.query, keep_blank_values=True))
    query["id"] = str(feed_id)
    query.setdefault("page", "1")
    query.setdefault("listType", "lastupdate_desc")
    query.setdefault("discussMode", "1")
    query.setdefault("feedType", "feed")
    query.setdefault("blockStatus", "0")
    query.setdefault("fromFeedAuthor", "0")
    new_query = urllib.parse.urlencode(query)
    return urllib.parse.urlunsplit((parts.scheme, parts.netloc, parts.path, new_query, parts.fragment))


def build_reply_url_with_page(template_url: str, feed_id: int, page: int) -> str:
    parts = urllib.parse.urlsplit(template_url)
    query = dict(urllib.parse.parse_qsl(parts.query, keep_blank_values=True))
    query["id"] = str(feed_id)
    query["page"] = str(max(1, page))
    query.setdefault("listType", "lastupdate_desc")
    query.setdefault("discussMode", "1")
    query.setdefault("feedType", "feed")
    query.setdefault("blockStatus", "0")
    query.setdefault("fromFeedAuthor", "0")
    new_query = urllib.parse.urlencode(query)
    return urllib.parse.urlunsplit((parts.scheme, parts.netloc, parts.path, new_query, parts.fragment))


def build_detail_url(template_url: str, feed_id: int) -> str:
    parts = urllib.parse.urlsplit(template_url)
    query = dict(urllib.parse.parse_qsl(parts.query, keep_blank_values=True))
    query["id"] = str(feed_id)
    query.setdefault("fromApi", "/topic/tagFeedList")
    new_query = urllib.parse.urlencode(query)
    return urllib.parse.urlunsplit((parts.scheme, parts.netloc, parts.path, new_query, parts.fragment))


def parse_detail_payload(payload: Dict) -> Optional[Dict]:
    data = payload.get("data")
    if not isinstance(data, dict):
        return None
    feed_id = data.get("id")
    if not feed_id:
        return None

    pics = data.get("picArr")
    if not isinstance(pics, list):
        pics = []
    pic = data.get("pic") or ""
    if pic and pic not in pics:
        pics.insert(0, pic)

    return {
        "id": feed_id,
        "uid": data.get("uid"),
        "username": data.get("username") or "酷友",
        "avatar": data.get("userAvatar") or "",
        "device": data.get("device_title") or "",
        "message": data.get("message") or "",
        "message_title": data.get("message_title") or "",
        "topic": data.get("ttitle") or "",
        "pics": pics,
        "dateline": data.get("dateline") or 0,
        "lastupdate": data.get("lastupdate") or 0,
        "likenum": data.get("likenum") or 0,
        "replynum": data.get("replynum") or 0,
    }


def build_tag_feed_url(topic_id: int, title: str) -> str:
    inner_query = urllib.parse.urlencode(
        {
            "cacheExpires": "60",
            "type": "feed",
            "withSortCard": "1",
            "id": str(topic_id),
            "title": title,
            "sortField": "lastupdate_desc",
        },
        quote_via=urllib.parse.quote,
    )
    inner_url = f"#/topic/tagFeedList?{inner_query}"
    outer_query = urllib.parse.urlencode(
        {"url": inner_url, "title": "讨论", "subTitle": "", "page": "1"},
        quote_via=urllib.parse.quote,
    )
    return f"https://api.coolapk.com/v6/page/dataList?{outer_query}"


def discover_topic_feed_specs(
    hot_topic_spec: Optional[Dict],
    timeout: int,
    topics_max: int,
    headers_fallback: Dict[str, str],
) -> List[Dict]:
    if not hot_topic_spec or topics_max <= 0:
        return []
    try:
        payload = fetch_json(hot_topic_spec["url"], hot_topic_spec["headers"], timeout=timeout)
    except (urllib.error.URLError, urllib.error.HTTPError, TimeoutError, json.JSONDecodeError) as exc:
        print(f"[WARN] hot topics fetch failed: {exc}")
        return []

    topics = []
    for item in payload.get("data", []):
        if not isinstance(item, dict):
            continue
        topic_id = item.get("id")
        title = item.get("title") or ""
        if isinstance(topic_id, str) and topic_id.isdigit():
            topic_id = int(topic_id)
        if not isinstance(topic_id, int) or topic_id <= 0:
            continue
        if not title:
            continue
        topics.append({"id": topic_id, "title": title})
        if len(topics) >= topics_max:
            break

    base_headers = hot_topic_spec.get("headers") or headers_fallback
    out = []
    for topic in topics:
        out.append({"url": build_tag_feed_url(topic["id"], topic["title"]), "headers": base_headers})
    if out:
        print(f"[INFO] discovered {len(out)} hot topic feed endpoint(s)")
    return out


def fetch_comments_map(
    feeds: List[Dict],
    reply_spec: Optional[Dict],
    timeout: int,
    comments_limit: int,
    comment_rows: int,
    comment_pages: int,
) -> Dict[str, List[Dict]]:
    if not reply_spec or comments_limit <= 0:
        return {}

    page_limit = max(1, comment_pages)
    comments_by_feed_id = {}
    for feed in feeds[:comments_limit]:
        feed_id = feed.get("id")
        if not feed_id:
            continue
        merged_rows = []
        seen_ids = set()
        for page in range(1, page_limit + 1):
            url = build_reply_url_with_page(reply_spec["url"], feed_id, page)
            try:
                payload = fetch_json(url, reply_spec["headers"], timeout=timeout)
            except (urllib.error.URLError, urllib.error.HTTPError, TimeoutError, json.JSONDecodeError) as exc:
                print(f"[WARN] comments fetch failed: {feed_id} page={page} -> {exc}")
                if page == 1:
                    merged_rows = []
                break

            rows = parse_reply_rows(payload, max_rows=comment_rows)
            for row in rows:
                row_id = row.get("id")
                if row_id in seen_ids:
                    continue
                seen_ids.add(row_id)
                merged_rows.append(row)
            if len(rows) < comment_rows:
                break

        if merged_rows:
            comments_by_feed_id[str(feed_id)] = merged_rows
    return comments_by_feed_id


def fetch_details_map(
    feeds: List[Dict],
    detail_spec: Optional[Dict],
    timeout: int,
    detail_limit: int,
) -> Dict[str, Dict]:
    if not detail_spec or detail_limit <= 0:
        return {}

    details_by_feed_id = {}
    for feed in feeds[:detail_limit]:
        feed_id = feed.get("id")
        if not feed_id:
            continue
        url = build_detail_url(detail_spec["url"], feed_id)
        try:
            payload = fetch_json(url, detail_spec["headers"], timeout=timeout)
            detail = parse_detail_payload(payload)
            if detail:
                details_by_feed_id[str(feed_id)] = detail
        except (urllib.error.URLError, urllib.error.HTTPError, TimeoutError, json.JSONDecodeError) as exc:
            print(f"[WARN] detail fetch failed: {feed_id} -> {exc}")
    return details_by_feed_id


def build_output(
    feeds: List[Dict],
    source: str,
    comments_by_feed_id: Dict[str, List[Dict]],
    details_by_feed_id: Dict[str, Dict],
) -> Dict:
    return {
        "updatedAt": datetime.now().isoformat(timespec="seconds"),
        "source": source,
        "feedCount": len(feeds),
        "trendingTags": build_trending_tags(feeds),
        "feeds": feeds,
        "commentsByFeedId": comments_by_feed_id,
        "detailsByFeedId": details_by_feed_id,
    }


def write_outputs(output_dir: Path, payload: Dict) -> None:
    output_dir.mkdir(parents=True, exist_ok=True)
    json_path = output_dir / "feeds.json"
    js_path = output_dir / "feeds.js"

    json_text = json.dumps(payload, ensure_ascii=False, indent=2)
    js_text = "window.COOLAPK_FEED_DATA = " + json.dumps(payload, ensure_ascii=False) + ";\n"

    tmp_json = json_path.with_suffix(".json.tmp")
    tmp_js = js_path.with_suffix(".js.tmp")
    tmp_json.write_text(json_text, encoding="utf-8")
    tmp_js.write_text(js_text, encoding="utf-8")
    tmp_json.replace(json_path)
    tmp_js.replace(js_path)


def write_live_specs(output_dir: Path, specs: Dict) -> None:
    output_dir.mkdir(parents=True, exist_ok=True)
    specs_path = output_dir / "live_specs.json"
    safe = {
        "reply_spec": specs.get("reply_spec"),
        "detail_spec": specs.get("detail_spec"),
        "hot_topic_spec": specs.get("hot_topic_spec"),
        "feed_specs": specs.get("feed_specs", [])[:3],
    }
    specs_path.write_text(json.dumps(safe, ensure_ascii=False, indent=2), encoding="utf-8")


def run_once(
    feed_specs: List[Dict],
    reply_spec: Optional[Dict],
    detail_spec: Optional[Dict],
    hot_topic_spec: Optional[Dict],
    discover_topics: bool,
    topics_max: int,
    timeout: int,
    output_dir: Path,
    comments_limit: int,
    comment_rows: int,
    comment_pages: int,
    detail_limit: int,
) -> bool:
    effective_specs = list(feed_specs)
    if discover_topics:
        fallback_headers = feed_specs[0]["headers"] if feed_specs else {}
        discovered_specs = discover_topic_feed_specs(
            hot_topic_spec=hot_topic_spec,
            timeout=timeout,
            topics_max=topics_max,
            headers_fallback=fallback_headers,
        )
        known = {spec["url"] for spec in effective_specs}
        for spec in discovered_specs:
            if spec["url"] not in known:
                effective_specs.append(spec)
                known.add(spec["url"])

    feeds = []
    ok_count = 0

    for spec in effective_specs:
        try:
            payload = fetch_json(spec["url"], spec["headers"], timeout=timeout)
            feeds.extend(parse_feed_cards(payload))
            ok_count += 1
        except (urllib.error.URLError, urllib.error.HTTPError, TimeoutError, json.JSONDecodeError) as exc:
            print(f"[WARN] feed fetch failed: {spec['url']} -> {exc}")

    if ok_count == 0:
        print("[ERROR] no feed request succeeded, keep old data")
        return False

    merged_feeds = merge_feeds(feeds)
    comments_by_feed_id = fetch_comments_map(
        merged_feeds,
        reply_spec=reply_spec,
        timeout=timeout,
        comments_limit=comments_limit,
        comment_rows=comment_rows,
        comment_pages=comment_pages,
    )
    details_by_feed_id = fetch_details_map(
        merged_feeds,
        detail_spec=detail_spec,
        timeout=timeout,
        detail_limit=detail_limit,
    )

    output = build_output(
        merged_feeds,
        source="live_sync",
        comments_by_feed_id=comments_by_feed_id,
        details_by_feed_id=details_by_feed_id,
    )
    write_outputs(output_dir, output)
    print(
        f"[OK] {datetime.now().strftime('%Y-%m-%d %H:%M:%S')} updated feeds: {output['feedCount']} "
        f"(from {ok_count}/{len(effective_specs)} endpoints), comments: {len(comments_by_feed_id)}, details: {len(details_by_feed_id)}"
    )
    return True


def main() -> None:
    parser = argparse.ArgumentParser(description="Live sync Coolapk tagFeedList into data/feeds.json")
    parser.add_argument("--har", required=True, help="HAR path used to extract URL + headers")
    parser.add_argument("--interval", type=int, default=20, help="poll interval in seconds")
    parser.add_argument("--timeout", type=int, default=15, help="request timeout in seconds")
    parser.add_argument("--output", default="data", help="output directory")
    parser.add_argument("--comments-limit", type=int, default=25, help="max feeds to fetch comments for")
    parser.add_argument("--comment-rows", type=int, default=20, help="max comment rows per feed")
    parser.add_argument("--comment-pages", type=int, default=3, help="max comment pages per feed")
    parser.add_argument("--detail-limit", type=int, default=40, help="max feeds to fetch detail for")
    parser.add_argument("--discover-topics", dest="discover_topics", action="store_true", default=True, help="auto discover multiple hot topics")
    parser.add_argument("--no-discover-topics", dest="discover_topics", action="store_false", help="disable hot topics discovery")
    parser.add_argument("--topics-max", type=int, default=12, help="max discovered hot topics per poll")
    parser.add_argument("--once", action="store_true", help="run only once")
    args = parser.parse_args()

    har_path = Path(args.har)
    if not har_path.exists():
        raise SystemExit(f"HAR not found: {har_path}")

    specs = read_har_specs(har_path)
    feed_specs = specs.get("feed_specs", [])
    reply_spec = specs.get("reply_spec")
    detail_spec = specs.get("detail_spec")
    hot_topic_spec = specs.get("hot_topic_spec")

    if not feed_specs:
        raise SystemExit("No tagFeedList request found in HAR")

    output_dir = Path(args.output)
    write_live_specs(output_dir, specs)
    print(f"[INFO] loaded {len(feed_specs)} feed endpoint(s) from {har_path.name}")
    if hot_topic_spec and args.discover_topics:
        print("[INFO] hot topic endpoint detected, multi-topic discovery enabled")
    elif not hot_topic_spec and args.discover_topics:
        print("[WARN] hot topic endpoint not found, multi-topic discovery disabled")
    if reply_spec:
        print("[INFO] replyList endpoint detected, comments sync enabled")
    else:
        print("[WARN] replyList endpoint not found, comments sync disabled")
    if detail_spec:
        print("[INFO] detail endpoint detected, detail sync enabled")
    else:
        print("[WARN] detail endpoint not found, detail sync disabled")

    if args.once:
        run_once(
            feed_specs,
            reply_spec,
            detail_spec=detail_spec,
            hot_topic_spec=hot_topic_spec,
            discover_topics=args.discover_topics,
            topics_max=args.topics_max,
            timeout=args.timeout,
            output_dir=output_dir,
            comments_limit=args.comments_limit,
            comment_rows=args.comment_rows,
            comment_pages=args.comment_pages,
            detail_limit=args.detail_limit,
        )
        return

    while True:
        run_once(
            feed_specs,
            reply_spec,
            detail_spec=detail_spec,
            hot_topic_spec=hot_topic_spec,
            discover_topics=args.discover_topics,
            topics_max=args.topics_max,
            timeout=args.timeout,
            output_dir=output_dir,
            comments_limit=args.comments_limit,
            comment_rows=args.comment_rows,
            comment_pages=args.comment_pages,
            detail_limit=args.detail_limit,
        )
        time.sleep(max(5, args.interval))


if __name__ == "__main__":
    main()
