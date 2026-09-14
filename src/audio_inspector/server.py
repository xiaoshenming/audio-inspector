"""Small review server with an allowlisted media route and Range support."""

from __future__ import annotations

import json
import mimetypes
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from urllib.parse import parse_qs, urlsplit

from .batch import load_manifest


def serve(manifest: Path, output: Path, host: str, port: int) -> None:
    media = {row["item_id"]: Path(row["video_path"]) for row in load_manifest(manifest)}
    report = (output / "report.html").resolve(strict=True)

    class Handler(BaseHTTPRequestHandler):
        def do_GET(self) -> None:
            request = urlsplit(self.path)
            if request.path in {"/", "/report.html"}:
                return self._file(report, allow_range=False)
            if request.path == "/media":
                item_id = parse_qs(request.query).get("item", [""])[0]
                target = media.get(item_id)
                if target and target.is_file():
                    return self._file(target, allow_range=True)
            self.send_error(404)

        def _file(self, path: Path, *, allow_range: bool) -> None:
            size = path.stat().st_size
            start, end, partial = 0, size - 1, False
            header = self.headers.get("Range", "") if allow_range else ""
            if header.startswith("bytes="):
                try:
                    left, right = header[6:].split("-", 1)
                    start = int(left or 0)
                    end = min(size - 1, int(right)) if right else size - 1
                    partial = 0 <= start <= end < size
                except ValueError:
                    partial = False
            self.send_response(206 if partial else 200)
            self.send_header("Content-Type", mimetypes.guess_type(path.name)[0] or "application/octet-stream")
            self.send_header("Content-Length", str(end - start + 1 if partial else size))
            self.send_header("Accept-Ranges", "bytes")
            if partial:
                self.send_header("Content-Range", f"bytes {start}-{end}/{size}")
            self.end_headers()
            with path.open("rb") as stream:
                stream.seek(start if partial else 0)
                remaining = end - start + 1 if partial else size
                while remaining:
                    chunk = stream.read(min(1 << 20, remaining))
                    if not chunk:
                        break
                    self.wfile.write(chunk)
                    remaining -= len(chunk)

        def log_message(self, format: str, *args: object) -> None:
            print(f"review-server: {format % args}")

    print(json.dumps({"url": f"http://{host}:{port}/", "items": len(media)}, ensure_ascii=False))
    ThreadingHTTPServer((host, port), Handler).serve_forever()
