"""Optional BatchOps worker adapter for repairs that need a full scene render."""

from __future__ import annotations

import argparse
import hashlib
import hmac
import json
import os
import time
import urllib.error
import urllib.request
from pathlib import Path
from urllib.parse import urlparse
from uuid import NAMESPACE_URL, UUID, uuid5

from .pipeline import run as inspect_video
from .synthetic_tts import _digest, _duration


def _json_request(url: str, token: str, payload: dict | None = None) -> dict:
    request = urllib.request.Request(
        url, data=(json.dumps(payload, ensure_ascii=False).encode() if payload else None),
        method="POST" if payload else "GET",
        headers={"Authorization": "Bearer " + token, "Content-Type": "application/json"},
    )
    try:
        with urllib.request.urlopen(request, timeout=30) as response:
            return json.load(response)
    except urllib.error.HTTPError as exc:
        raise RuntimeError(f"render_api_http_{exc.code}:"
                           + exc.read(500).decode(errors="replace")) from exc


def _capability(generation_id: UUID, secret: str, locator: str | None = None) -> str:
    message = str(generation_id) if locator is None else f"{generation_id}:{locator}"
    signature = hmac.new(secret.encode(), message.encode(), hashlib.sha256).hexdigest()
    return f"{generation_id}.{signature}"


def build_job(generation_id: UUID, item_id: str, source_uri: str,
              source_sha: str, main_sha: str, *, tenant_id: str,
              intake_url: str, signing_secret: str, bucket: str) -> dict:
    endpoint = f"{intake_url.rstrip('/')}/v1/internal/render/{generation_id}"
    return {"tenant_id": tenant_id, "idempotency_key": f"dev-pb2-render:{generation_id}",
            "source": {"uri": source_uri, "sha256": source_sha,
                       "role": "teacher_confirmed_source", "locked": True,
                       "download_signing_url": endpoint + "/source-download",
                       "download_signing_token": _capability(
                           generation_id, signing_secret, source_uri)},
            "batch_id": f"dev-pb2-{item_id}", "profile": "delivery_high",
            "priority": -100,
            "runtime": {"image": "mathpi-render:stable", "entrypoint": "main.py",
                        "timeout_seconds": 3600},
            "render": {"aspect_ratio": "16:9", "quality": "m",
                       "pixel_width": 1280, "pixel_height": 720, "frame_rate": 30},
            "tts": {"enabled": True, "provider": "qwen_audio",
                    "model": "qwen-audio-3.0-tts-plus", "voice": "longanlufeng",
                    "speech_rate": 0.9},
            "branding": {"mode": "source"},
            "resources": {"cpu_cores": 4, "memory_mb": 8192, "slots": 1},
            "selected_content_version_id": str(generation_id),
            "selected_content_source_sha256": main_sha,
            "output": {"uri_prefix": f"tos://{bucket}/batchops-render/{generation_id}",
                       "upload_signing_url": endpoint + "/artifact-upload",
                       "upload_signing_token": _capability(generation_id, signing_secret),
                       "include_logs": True, "include_manifest": True}}


def _object_store():
    import tos

    bucket = os.environ["DEV_PB2_TOS_BUCKET"]
    client = tos.TosClientV2(
        os.environ["DEV_PB2_TOS_ACCESS_KEY"],
        os.environ["DEV_PB2_TOS_SECRET_KEY"],
        os.environ["DEV_PB2_TOS_ENDPOINT"],
        os.environ.get("DEV_PB2_TOS_REGION", "cn-beijing"),
    )
    return client, bucket


def _download(client, bucket: str, artifact: dict, target: Path) -> None:
    uri = str(artifact.get("uri") or "")
    parsed = urlparse(uri)
    if parsed.scheme != "tos" or parsed.netloc != bucket:
        raise ValueError("render_artifact_uri_outside_expected_bucket")
    response = client.get_object(bucket, parsed.path.lstrip("/"))
    target.write_bytes(response.content.read())
    if _digest(target) != artifact["sha256"]:
        raise ValueError("render_artifact_sha256_mismatch")


def render_full(source_pack: Path, source_main: Path, item_id: str,
                output: Path, *, timeout_seconds: int = 3600) -> dict:
    output.mkdir(parents=True, exist_ok=True)
    source_sha = _digest(source_pack)
    main_sha = _digest(source_main)
    receipt = output / "receipt.json"
    if receipt.is_file():
        previous = json.loads(receipt.read_text())
        video = Path(previous.get("video_path") or "")
        if (previous.get("source_pack_sha256") == source_sha
                and previous.get("source_sha256") == main_sha and video.is_file()
                and _digest(video) == previous.get("video_sha256")):
            return previous
    generation_id = uuid5(NAMESPACE_URL, f"dev-pb2:{item_id}:{source_sha}")
    client, bucket = _object_store()
    key = f"dev-pb2/closures/{item_id}/{source_sha}/source.tar"
    client.put_object(bucket, key, content=source_pack.read_bytes(),
                      content_type="application/x-tar")
    locator = f"tos://{bucket}/{key}"
    job = build_job(
        generation_id, item_id, locator, source_sha, main_sha,
        tenant_id=os.environ["DEV_PB2_TENANT_ID"],
        intake_url=os.environ["DEV_PB2_INTAKE_URL"],
        signing_secret=os.environ["DEV_PB2_SIGNING_SECRET"], bucket=bucket)
    api = os.environ["DEV_PB2_RENDER_API_URL"].rstrip("/")
    tenant_token = os.environ["DEV_PB2_TENANT_TOKEN"]
    created = _json_request(api + "/v1/jobs", tenant_token, job)
    job_id = created["job_id"]
    started = time.monotonic()
    while True:
        state = _json_request(api + f"/v1/jobs/{job_id}", tenant_token)
        (output / "job-state.json").write_text(json.dumps(state, ensure_ascii=False,
                                                      indent=2) + "\n")
        if state["status"] in {"succeeded", "failed", "cancelled"}:
            break
        if time.monotonic() - started > timeout_seconds:
            raise TimeoutError("render_job_timeout")
        time.sleep(10)
    if state["status"] != "succeeded":
        raise RuntimeError(f"render_job_{state['status']}")
    attempts = state.get("attempts") or []
    selected = next((row for row in attempts
                     if row["attempt_id"] == state.get("selected_attempt_id")), None)
    artifacts = (selected or {}).get("result", {}).get("artifacts") or []
    video = next((row for row in artifacts
                  if str(row.get("logical_path") or "").endswith("video-subtitled.mp4")
                  and row.get("uri")), None)
    if video is None:
        video = next((row for row in artifacts if row.get("playable") and row.get("uri")), None)
    if video is None:
        raise RuntimeError("render_video_artifact_missing")
    final = output / "final.mp4"
    _download(client, bucket, video, final)
    subtitle = next((row for row in artifacts
                     if str(row.get("logical_path") or "").endswith(".srt")
                     and row.get("uri")), None)
    subtitle_path = output / "final.srt"
    if subtitle:
        _download(client, bucket, subtitle, subtitle_path)
    if _duration(final) <= 0:
        raise RuntimeError("render_video_empty")
    result = {"schema_version": "dev-pb2.worker-render.v1", "status": "completed",
              "item_id": item_id, "generation_id": str(generation_id),
              "render_job_id": job_id, "source_pack_sha256": source_sha,
              "source_sha256": main_sha, "source_path": str(source_main),
              "video_path": str(final), "video_sha256": _digest(final),
              "subtitle_path": str(subtitle_path) if subtitle else "",
              "duration_seconds": _duration(final)}
    receipt.write_text(json.dumps(result, ensure_ascii=False, indent=2) + "\n")
    return result


def render_and_inspect(request: dict, source_pack: Path, source_main: Path,
                       output: Path, work_root: Path,
                       job_item_id: str | None = None) -> dict:
    output.mkdir(parents=True, exist_ok=True)
    rendered = render_full(source_pack, source_main, job_item_id or request["item_id"], output)
    revised_request = {**request, "revision_id": request["revision_id"]
                       + ":worker:" + rendered["render_job_id"],
                       "video_path": rendered["video_path"],
                       "video_sha256": rendered["video_sha256"],
                       "source_path": rendered["source_path"],
                       "source_sha256": rendered["source_sha256"],
                       "subtitle_path": rendered["subtitle_path"]}
    after = inspect_video(revised_request, work_root)
    result = {"schema_version": "dev-pb2.worker-closure.v1",
              "render": rendered, "reinspection": after,
              "status": ("reinspection_clean" if after["status"] == "clean"
                         else "reinspection_needs_review")}
    (output / "closure.json").write_text(json.dumps(result, ensure_ascii=False,
                                                   indent=2) + "\n")
    return result


def main() -> None:
    parser = argparse.ArgumentParser(description="Render approved source on BatchOps worker")
    parser.add_argument("--source-pack", type=Path, required=True)
    parser.add_argument("--source-main", type=Path, required=True)
    parser.add_argument("--item-id", required=True)
    parser.add_argument("--output", type=Path, required=True)
    parser.add_argument("--request", type=Path)
    parser.add_argument("--batch", type=Path)
    parser.add_argument("--work-root", type=Path)
    args = parser.parse_args()
    if (args.request or args.batch) and args.work_root:
        if args.request and args.batch:
            parser.error("choose --request or --batch")
        if args.batch:
            cases = json.loads(args.batch.read_text())["cases"]
            matches = [row["request"] for row in cases
                       if row["request"]["item_id"] == args.item_id]
            if len(matches) != 1:
                parser.error("item_id must appear exactly once in batch")
            request = matches[0]
        else:
            request = json.loads(args.request.read_text())
        result = render_and_inspect(request,
                                    args.source_pack, args.source_main,
                                    args.output, args.work_root)
        print(json.dumps({"status": result["status"],
                          "render_job_id": result["render"]["render_job_id"],
                          "video_path": result["render"]["video_path"],
                          "reinspection": result["reinspection"]["status"]},
                         ensure_ascii=False))
    elif args.request or args.batch or args.work_root:
        parser.error("--work-root is required with --request or --batch")
    else:
        print(json.dumps(render_full(args.source_pack, args.source_main, args.item_id,
                                     args.output), ensure_ascii=False))


if __name__ == "__main__":
    main()
