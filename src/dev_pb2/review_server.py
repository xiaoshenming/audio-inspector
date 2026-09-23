"""Admin-session protected review desk with seekable MP4 and durable labels."""

from __future__ import annotations

import argparse
import csv
import hashlib
import io
import json
import re
import urllib.error
import urllib.request
from collections.abc import Callable
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from urllib.parse import urlsplit

from .review_store import ReviewStore

MEDIA_PATH = re.compile(r"^/media/([0-9a-f-]{36})\.mp4$")
RANGE = re.compile(r"^bytes=(\d*)-(\d*)$")
STATIC = {"/": ("index.html", "text/html; charset=utf-8"),
          "/review.js": ("review.js", "text/javascript; charset=utf-8"),
          "/review.css": ("review.css", "text/css; charset=utf-8")}


def _issue_id(item_id: str, issue: dict) -> str:
    values = [item_id, issue.get("kind"), issue.get("line"),
              issue.get("source_quote"), issue.get("asr_quote")]
    digest = hashlib.sha256(json.dumps(values, ensure_ascii=False).encode()).hexdigest()[:24]
    return f"issue:{digest}"


def _load_candidates(data_root: Path) -> tuple[list[dict], dict[str, str]]:
    items = json.loads((data_root / "candidates.json").read_text(encoding="utf-8"))
    if not isinstance(items, list):
        raise TypeError("candidates.json must contain a list")
    allowed = {}
    for item in items:
        item_id = str(item["item_id"])
        if not re.fullmatch(r"[0-9a-f-]{36}", item_id):
            raise ValueError("invalid item id")
        allowed[f"video:{item_id}"] = item_id
        for issue in item.get("source_issues", []) + item.get("audio_issues", []):
            issue["issue_id"] = _issue_id(item_id, issue)
            allowed[issue["issue_id"]] = item_id
    return items, allowed


def _authenticate(url: str, cookie: str) -> int:
    if not cookie:
        return 401
    request = urllib.request.Request(url, headers={"Cookie": cookie})
    opener = urllib.request.build_opener(urllib.request.ProxyHandler({}))
    try:
        with opener.open(request, timeout=4) as response:
            return 200 if response.status == 200 else 503
    except urllib.error.HTTPError as exc:
        return 401 if exc.code in {401, 403} else 503
    except (OSError, TimeoutError):
        return 503


class ReviewHandler(BaseHTTPRequestHandler):
    data_root: Path
    candidates: list[dict]
    media: dict[str, Path]
    store: ReviewStore
    auth_url: str
    auth_check: Callable[[str], int] | None = None

    def _authorized(self, *, page: bool = False) -> bool:
        cookie = self.headers.get("Cookie", "")[:8192]
        status = (self.auth_check(cookie) if self.auth_check is not None
                  else _authenticate(self.auth_url, cookie))
        if status != 200:
            if status == 401 and page:
                body = ("<!doctype html><html lang='zh-CN'><meta charset='utf-8'>"
                        "<title>请先登录</title><body style='font:16px system-ui;padding:40px'>"
                        "<h1>请先登录 B2B 管理后台</h1><p>登录后返回此页刷新即可评审。</p>"
                        "<a id='login'>前往 8085 登录页</a><script>document.getElementById('login').href="
                        "location.protocol+'//'+location.hostname+':8085/login'</script></body></html>")
                self._send(401, body.encode("utf-8"), "text/html; charset=utf-8")
            else:
                self._send(status, b"administrator session required" if status == 401
                           else b"authentication unavailable", "text/plain")
            return False
        return True

    def _send(self, status: int, body: bytes, mime: str, *, head: bool = False,
              extra: dict[str, str] | None = None) -> None:
        self.send_response(status)
        self.send_header("Content-Type", mime)
        self.send_header("Content-Length", str(len(body)))
        self.send_header("Cache-Control", "private, no-store")
        self.send_header("X-Content-Type-Options", "nosniff")
        for key, value in (extra or {}).items():
            self.send_header(key, value)
        self.end_headers()
        if not head:
            self.wfile.write(body)

    def _json(self, status: int, value: object, *, head: bool = False) -> None:
        self._send(status, json.dumps(value, ensure_ascii=False).encode("utf-8"),
                   "application/json; charset=utf-8", head=head)

    def _media(self, item_id: str, *, head: bool) -> None:
        path = self.media.get(item_id)
        if path is None or not path.is_file():
            self._send(404, b"media not found", "text/plain", head=head)
            return
        size = path.stat().st_size
        start, end, partial = 0, size - 1, False
        header = self.headers.get("Range", "")
        if header:
            match = RANGE.fullmatch(header.strip())
            if not match or size == 0:
                self._range_error(size, head=head)
                return
            left, right = match.groups()
            if not left and not right:
                self._range_error(size, head=head)
                return
            if left:
                start = int(left)
                end = min(int(right), size - 1) if right else size - 1
            else:
                count = int(right)
                start = max(0, size - count)
                end = size - 1
            if start >= size or end < start:
                self._range_error(size, head=head)
                return
            partial = True
        length = end - start + 1
        self.send_response(206 if partial else 200)
        for key, value in {
            "Content-Type": "video/mp4", "Content-Length": str(length),
            "Accept-Ranges": "bytes", "Cache-Control": "private, no-store",
            "X-Content-Type-Options": "nosniff",
        }.items():
            self.send_header(key, value)
        if partial:
            self.send_header("Content-Range", f"bytes {start}-{end}/{size}")
        self.end_headers()
        if head:
            return
        with path.open("rb") as stream:
            stream.seek(start)
            remaining = length
            while remaining:
                chunk = stream.read(min(1024 * 1024, remaining))
                if not chunk:
                    break
                self.wfile.write(chunk)
                remaining -= len(chunk)

    def _range_error(self, size: int, *, head: bool) -> None:
        self._send(416, b"invalid range", "text/plain", head=head,
                   extra={"Content-Range": f"bytes */{size}", "Accept-Ranges": "bytes"})

    def _export(self, *, head: bool) -> None:
        stream = io.StringIO()
        writer = csv.writer(stream)
        writer.writerow(["target_id", "item_id", "reviewer", "verdict", "note", "updated_at"])
        for row in self.store.list():
            writer.writerow([row[key] for key in
                             ("target_id", "item_id", "reviewer", "verdict", "note", "updated_at")])
        self._send(200, ("\ufeff" + stream.getvalue()).encode("utf-8"),
                   "text/csv; charset=utf-8", head=head,
                   extra={"Content-Disposition": "attachment; filename=audio-screening-reviews.csv"})

    def _get(self, *, head: bool = False) -> None:
        path = urlsplit(self.path).path
        if path == "/healthz":
            self._json(200, {"ok": True}, head=head)
            return
        if not self._authorized(page=path == "/"):
            return
        if path == "/api/state":
            self._json(200, {"items": self.candidates, "reviews": self.store.list()}, head=head)
        elif path == "/api/export":
            self._export(head=head)
        elif match := MEDIA_PATH.fullmatch(path):
            self._media(match.group(1), head=head)
        elif path in STATIC:
            name, mime = STATIC[path]
            self._send(200, (Path(__file__).with_name("review_static") / name).read_bytes(),
                       mime, head=head)
        else:
            self._send(404, b"not found", "text/plain", head=head)

    def do_GET(self) -> None:
        self._get()

    def do_HEAD(self) -> None:
        self._get(head=True)

    def do_POST(self) -> None:
        if not self._authorized():
            return
        if urlsplit(self.path).path != "/api/reviews":
            self._json(404, {"error": "not_found"})
            return
        if self.headers.get("Content-Type", "").split(";", 1)[0].lower() != "application/json":
            self._json(415, {"error": "application_json_required"})
            return
        origin = self.headers.get("Origin")
        if origin and urlsplit(origin).netloc != self.headers.get("Host"):
            self._json(403, {"error": "invalid_origin"})
            return
        try:
            length = int(self.headers.get("Content-Length", "0"))
            if length <= 0 or length > 16 * 1024:
                raise ValueError("invalid_body_size")
            body = json.loads(self.rfile.read(length))
            review = self.store.save(
                str(body.get("target_id", "")), str(body.get("item_id", "")),
                str(body.get("reviewer", "")), str(body.get("verdict", "")),
                str(body.get("note", "")),
            )
        except (ValueError, TypeError, json.JSONDecodeError) as exc:
            self._json(400, {"error": str(exc)})
            return
        self._json(200, {"review": review})


def make_handler(data_root: Path, auth_url: str,
                 auth_check: Callable[[str], int] | None = None) -> type[ReviewHandler]:
    root = data_root.resolve()
    candidates, allowed = _load_candidates(root)
    media = {item["item_id"]: root / "videos" / f"{item['item_id']}.mp4"
             for item in candidates}
    handler = type("ConfiguredReviewHandler", (ReviewHandler,), {})
    handler.data_root = root
    handler.candidates = candidates
    handler.media = media
    handler.store = ReviewStore(root / "reviews.sqlite", allowed)
    handler.auth_url = auth_url
    handler.auth_check = staticmethod(auth_check) if auth_check is not None else None
    return handler


def main() -> None:
    parser = argparse.ArgumentParser(description="Admin-protected audio screening review desk")
    parser.add_argument("--data-root", type=Path, required=True)
    parser.add_argument("--auth-url", required=True)
    parser.add_argument("--host", default="127.0.0.1")
    parser.add_argument("--port", type=int, default=8115)
    args = parser.parse_args()
    ThreadingHTTPServer((args.host, args.port),
                        make_handler(args.data_root, args.auth_url)).serve_forever()


if __name__ == "__main__":
    main()
