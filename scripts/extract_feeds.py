import json
import re
import sys
from pathlib import Path
from typing import Dict, List


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


def parse_reply_rows(payload: Dict) -> List[Dict]:
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
    return rows


def parse_detail_payload(payload: Dict) -> Dict:
    data = payload.get("data")
    if not isinstance(data, dict):
        return {}
    feed_id = data.get("id")
    if not feed_id:
        return {}

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


def extract_feeds(har_path: Path) -> Dict:
    har = json.loads(har_path.read_text(encoding="utf-8"))
    feeds = []
    seen = set()
    comments_by_feed_id = {}
    details_by_feed_id = {}

    for entry in har.get("log", {}).get("entries", []):
        url = entry.get("request", {}).get("url", "")
        response_text = entry.get("response", {}).get("content", {}).get("text", "{}")
        try:
            payload = json.loads(response_text)
        except json.JSONDecodeError:
            continue

        if "api.coolapk.com/v6/page/dataList" in url and "tagFeedList" in url:
            for feed in parse_feed_cards(payload):
                feed_id = feed.get("id")
                if not feed_id or feed_id in seen:
                    continue
                seen.add(feed_id)
                feeds.append(feed)

        if "api2.coolapk.com/v6/feed/replyList" in url:
            feed_id_match = re.search(r"[?&]id=(\d+)", url)
            if not feed_id_match:
                continue
            feed_id = feed_id_match.group(1)
            rows = parse_reply_rows(payload)
            if rows:
                comments_by_feed_id[feed_id] = rows[:20]

        if "api2.coolapk.com/v6/feed/detail" in url:
            detail = parse_detail_payload(payload)
            if detail:
                details_by_feed_id[str(detail["id"])] = detail

    feeds.sort(key=lambda x: (x.get("dateline", 0), x.get("id", 0)), reverse=True)

    tag_count = {}
    for feed in feeds:
        for tag in feed.get("tags", []):
            t = tag.strip()
            if t:
                tag_count[t] = tag_count.get(t, 0) + 1

    trending_tags = [
        {"name": k, "count": v}
        for k, v in sorted(tag_count.items(), key=lambda kv: (-kv[1], kv[0]))[:12]
    ]

    return {
        "updatedAt": "2026-04-14T00:00:00",
        "source": har_path.name,
        "feedCount": len(feeds),
        "trendingTags": trending_tags,
        "feeds": feeds,
        "commentsByFeedId": comments_by_feed_id,
        "detailsByFeedId": details_by_feed_id,
    }


def main() -> None:
    if len(sys.argv) < 2:
        raise SystemExit("Usage: python scripts/extract_feeds.py <har_path>")

    har_path = Path(sys.argv[1])
    if not har_path.exists():
        raise SystemExit(f"HAR file not found: {har_path}")

    result = extract_feeds(har_path)
    data_dir = Path("data")
    data_dir.mkdir(parents=True, exist_ok=True)

    json_path = data_dir / "feeds.json"
    js_path = data_dir / "feeds.js"

    json_path.write_text(json.dumps(result, ensure_ascii=False, indent=2), encoding="utf-8")
    js_path.write_text(
        "window.COOLAPK_FEED_DATA = " + json.dumps(result, ensure_ascii=False) + ";\n",
        encoding="utf-8",
    )
    print(f"Wrote {json_path} and {js_path} ({result['feedCount']} feeds)")


if __name__ == "__main__":
    main()
