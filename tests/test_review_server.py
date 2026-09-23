import json
import sqlite3
import threading
import urllib.error
import urllib.request
from http.server import ThreadingHTTPServer

import pytest

from audio_inspector.review_server import make_handler


@pytest.fixture
def site(tmp_path):
    item_id = "01234567-89ab-cdef-0123-456789abcdef"
    (tmp_path / "videos").mkdir()
    (tmp_path / "videos" / f"{item_id}.mp4").write_bytes(b"0123456789")
    (tmp_path / "candidates.json").write_text(json.dumps([{
        "item_id": item_id, "priority": "A", "source_issues": [{
            "kind": "source", "line": 12, "source_quote": "已知向量与 b 不共线",
            "time_seconds": 1.2,
        }], "audio_issues": [],
    }]))
    handler = make_handler(tmp_path, "http://127.0.0.1:1/unused",
                           auth_check=lambda cookie: 200 if cookie == "valid=1" else 401)
    server = ThreadingHTTPServer(("127.0.0.1", 0), handler)
    thread = threading.Thread(target=server.serve_forever, daemon=True)
    thread.start()
    try:
        yield f"http://127.0.0.1:{server.server_address[1]}", item_id, tmp_path
    finally:
        server.shutdown()
        server.server_close()
        thread.join(timeout=3)


def request(url, *, cookie="valid=1", body=None, range_header=None):
    headers = {"Cookie": cookie}
    if body is not None:
        headers["Content-Type"] = "application/json"
    if range_header:
        headers["Range"] = range_header
    return urllib.request.urlopen(urllib.request.Request(
        url, data=json.dumps(body).encode() if body is not None else None,
        headers=headers), timeout=3)


def test_auth_allowlist_and_media_range(site):
    url, item_id, _ = site
    with urllib.request.urlopen(url + "/healthz") as response:
        assert response.status == 200
    with pytest.raises(urllib.error.HTTPError) as denied:
        request(url + "/api/state", cookie="")
    assert denied.value.code == 401
    with pytest.raises(urllib.error.HTTPError) as denied_media:
        request(url + f"/media/{item_id}.mp4", cookie="")
    assert denied_media.value.code == 401
    with request(url + "/api/state") as response:
        state = json.load(response)
    assert state["items"][0]["source_issues"][0]["issue_id"].startswith("issue:")
    with request(url + f"/media/{item_id}.mp4", range_header="bytes=2-5") as response:
        assert response.status == 206
        assert response.headers["Content-Range"] == "bytes 2-5/10"
        assert response.read() == b"2345"
    with pytest.raises(urllib.error.HTTPError) as missing:
        request(url + "/media/11111111-1111-1111-1111-111111111111.mp4")
    assert missing.value.code == 404


def test_review_buttons_persist_and_keep_audit(site):
    url, item_id, root = site
    with request(url + "/api/state") as response:
        issue_id = json.load(response)["items"][0]["source_issues"][0]["issue_id"]
    for verdict in ("missing", "correct"):
        with request(url + "/api/reviews", body={
            "target_id": issue_id, "item_id": item_id, "reviewer": "同事甲",
            "verdict": verdict, "note": "已核听",
        }) as response:
            assert json.load(response)["review"]["verdict"] == verdict
    with request(url + "/api/state") as response:
        reviews = json.load(response)["reviews"]
    assert len(reviews) == 1 and reviews[0]["verdict"] == "correct"
    with sqlite3.connect(root / "reviews.sqlite") as db:
        assert db.execute("SELECT count(*) FROM review_audit").fetchone()[0] == 2
    with pytest.raises(urllib.error.HTTPError) as invalid:
        request(url + "/api/reviews", body={
            "target_id": "issue:unknown", "item_id": item_id,
            "reviewer": "同事甲", "verdict": "missing", "note": "",
        })
    assert invalid.value.code == 400
    cross_origin = urllib.request.Request(
        url + "/api/reviews", data=json.dumps({
            "target_id": issue_id, "item_id": item_id, "reviewer": "同事甲",
            "verdict": "missing", "note": "",
        }).encode(), headers={"Cookie": "valid=1", "Content-Type": "application/json",
                             "Origin": "http://other.example"},
    )
    with pytest.raises(urllib.error.HTTPError) as forbidden:
        urllib.request.urlopen(cross_origin, timeout=3)
    assert forbidden.value.code == 403
