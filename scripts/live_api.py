import argparse
import json
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from urllib.parse import parse_qs, urlsplit

from live_sync import (
    build_detail_url,
    build_reply_url_with_page,
    ensure_ddid_cookie,
    fetch_json,
    parse_detail_payload,
    parse_reply_rows,
    read_har_specs,
)


def load_json(path: Path):
    try:
        return json.loads(path.read_text(encoding="utf-8"))
    except Exception:
        return {}


def load_specs(har_path: Path, specs_path: Path):
    specs = {}
    if har_path and har_path.exists():
        try:
            specs = read_har_specs(har_path)
            print("[INFO] specs loaded from HAR")
            return specs
        except Exception as exc:
            print(f"[WARN] parse HAR failed: {exc}")

    specs = load_json(specs_path)
    if specs:
        print(f"[INFO] specs loaded from {specs_path}")
    else:
        print(f"[WARN] specs file missing or invalid: {specs_path}")
    return specs


def ensure_runtime_specs(specs: dict) -> dict:
    out = dict(specs or {})
    reply_spec = out.get("reply_spec")
    detail_spec = out.get("detail_spec")
    feed_specs = out.get("feed_specs") or []
    headers = {}
    if isinstance(feed_specs, list) and feed_specs:
        headers = feed_specs[0].get("headers") or {}
    headers = ensure_ddid_cookie(headers) if headers else headers

    if not reply_spec and headers:
        reply_spec = {
            "url": "https://api2.coolapk.com/v6/feed/replyList?id=0&listType=lastupdate_desc&page=1&discussMode=1&feedType=feed&blockStatus=0&fromFeedAuthor=0",
            "headers": headers,
        }
    if not detail_spec and headers:
        detail_spec = {
            "url": "https://api2.coolapk.com/v6/feed/detail?id=0&fromApi=/topic/tagFeedList",
            "headers": headers,
        }
    out["reply_spec"] = reply_spec
    out["detail_spec"] = detail_spec
    return out


class Handler(BaseHTTPRequestHandler):
    server_version = "CoolapkLiveAPI/1.1"

    def log_message(self, format, *args):
        return

    def _send_json(self, status: int, payload: dict):
        body = json.dumps(payload, ensure_ascii=False).encode("utf-8")
        self.send_response(status)
        self.send_header("Content-Type", "application/json; charset=utf-8")
        self.send_header("Content-Length", str(len(body)))
        self.send_header("Cache-Control", "no-store")
        self.send_header("Access-Control-Allow-Origin", "*")
        self.send_header("Access-Control-Allow-Methods", "GET,OPTIONS")
        self.send_header("Access-Control-Allow-Headers", "Content-Type")
        self.end_headers()
        self.wfile.write(body)

    def _load_cache(self):
        return load_json(self.server.cache_path)

    def _reply_total_from_cache(self, cache: dict, feed_id: str) -> int:
        try:
            wanted = str(int(feed_id))
        except Exception:
            wanted = str(feed_id)
        for row in cache.get("feeds", []):
            if str(row.get("id")) != wanted:
                continue
            try:
                return max(0, int(row.get("replynum") or 0))
            except Exception:
                return 0
        return 0

    def _ensure_specs(self):
        if self.server.reply_spec and self.server.detail_spec:
            return
        specs = ensure_runtime_specs(load_json(self.server.specs_path))
        if not specs:
            return
        if not self.server.reply_spec:
            self.server.reply_spec = specs.get("reply_spec")
        if not self.server.detail_spec:
            self.server.detail_spec = specs.get("detail_spec")

    def do_OPTIONS(self):
        self._send_json(200, {"ok": True})

    def do_GET(self):
        parsed = urlsplit(self.path)
        path = parsed.path.rstrip("/")
        query = parse_qs(parsed.query)

        if path == "/health":
            return self._send_json(200, {"ok": True})

        if path == "/replies":
            return self._handle_replies(query)

        if path == "/detail":
            return self._handle_detail(query)

        return self._send_json(404, {"ok": False, "error": "not found"})

    def _handle_replies(self, query):
        self._ensure_specs()
        feed_id = (query.get("id") or [""])[0].strip()
        rows_limit = int((query.get("rows") or ["20"])[0] or "20")
        rows_limit = max(1, min(rows_limit, 80))
        page = int((query.get("page") or ["1"])[0] or "1")
        page = max(1, page)

        if not feed_id.isdigit():
            return self._send_json(400, {"ok": False, "error": "invalid id"})

        spec = self.server.reply_spec
        start = (page - 1) * rows_limit

        if spec:
            try:
                url = build_reply_url_with_page(spec["url"], int(feed_id), page)
                payload = fetch_json(url, spec["headers"], timeout=self.server.timeout_sec)
                rows = parse_reply_rows(payload, max_rows=rows_limit)
                has_more = len(rows) >= rows_limit
                cache = self._load_cache()
                total_by_feed = self._reply_total_from_cache(cache, feed_id)
                return self._send_json(
                    200,
                    {
                        "ok": True,
                        "id": int(feed_id),
                        "page": page,
                        "rows": rows,
                        "hasMore": has_more,
                        "total": max(total_by_feed, (page - 1) * rows_limit + len(rows)),
                        "source": "live",
                    },
                )
            except Exception as exc:
                cache = self._load_cache()
                comments = cache.get("commentsByFeedId", {}).get(str(feed_id), [])
                total_by_feed = self._reply_total_from_cache(cache, feed_id)
                known_total = max(len(comments), total_by_feed)
                rows = comments[start : start + rows_limit]
                has_more = start + rows_limit < known_total
                return self._send_json(
                    200,
                    {
                        "ok": True,
                        "id": int(feed_id),
                        "page": page,
                        "rows": rows,
                        "hasMore": has_more,
                        "total": known_total,
                        "source": "cache",
                        "warning": str(exc),
                    },
                )

        cache = self._load_cache()
        comments = cache.get("commentsByFeedId", {}).get(str(feed_id), [])
        total_by_feed = self._reply_total_from_cache(cache, feed_id)
        known_total = max(len(comments), total_by_feed)
        rows = comments[start : start + rows_limit]
        has_more = start + rows_limit < known_total
        return self._send_json(
            200,
            {
                "ok": True,
                "id": int(feed_id),
                "page": page,
                "rows": rows,
                "hasMore": has_more,
                "total": known_total,
                "source": "cache",
            },
        )

    def _handle_detail(self, query):
        self._ensure_specs()
        feed_id = (query.get("id") or [""])[0].strip()
        if not feed_id.isdigit():
            return self._send_json(400, {"ok": False, "error": "invalid id"})

        spec = self.server.detail_spec

        if spec:
            try:
                url = build_detail_url(spec["url"], int(feed_id))
                payload = fetch_json(url, spec["headers"], timeout=self.server.timeout_sec)
                detail = parse_detail_payload(payload) or {}
                return self._send_json(200, {"ok": True, "id": int(feed_id), "detail": detail, "source": "live"})
            except Exception as exc:
                cache = self._load_cache()
                detail = cache.get("detailsByFeedId", {}).get(str(feed_id), {})
                return self._send_json(
                    200,
                    {
                        "ok": True,
                        "id": int(feed_id),
                        "detail": detail,
                        "source": "cache",
                        "warning": str(exc),
                    },
                )

        cache = self._load_cache()
        detail = cache.get("detailsByFeedId", {}).get(str(feed_id), {})
        return self._send_json(200, {"ok": True, "id": int(feed_id), "detail": detail, "source": "cache"})


def main():
    parser = argparse.ArgumentParser(description="Live API for on-demand replies and feed detail")
    parser.add_argument("--har", default="", help="HAR file path (optional)")
    parser.add_argument("--specs", default="data/live_specs.json", help="specs json path")
    parser.add_argument("--cache", default="data/feeds.json", help="cache data path")
    parser.add_argument("--host", default="0.0.0.0")
    parser.add_argument("--port", type=int, default=8090)
    parser.add_argument("--timeout", type=int, default=12)
    args = parser.parse_args()

    har_path = Path(args.har) if args.har else None
    specs_path = Path(args.specs)
    cache_path = Path(args.cache)

    specs = ensure_runtime_specs(load_specs(har_path, specs_path))
    reply_spec = specs.get("reply_spec")
    detail_spec = specs.get("detail_spec")

    print(f"[INFO] live api start, reply={'on' if reply_spec else 'off'}, detail={'on' if detail_spec else 'off'}")

    server = ThreadingHTTPServer((args.host, args.port), Handler)
    server.reply_spec = reply_spec
    server.detail_spec = detail_spec
    server.timeout_sec = args.timeout
    server.cache_path = cache_path
    server.specs_path = specs_path
    server.serve_forever()


if __name__ == "__main__":
    main()
