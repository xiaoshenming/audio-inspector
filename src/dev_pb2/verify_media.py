"""Verify every repaired MP4 has intact media and a matching receipt."""

from __future__ import annotations

import argparse
import json
import subprocess
from pathlib import Path

from .synthetic_tts import _digest


def _probe(path: Path) -> dict:
    result = subprocess.run(["ffprobe", "-v", "error", "-show_entries",
                             "format=duration:stream=codec_type,codec_name",
                             "-of", "json", str(path)], capture_output=True,
                            text=True, timeout=30, check=True)
    return json.loads(result.stdout)


def verify(summary: Path) -> dict:
    rows = json.loads(summary.read_text())["rows"]
    checked = 0
    failures = []
    for row in rows:
        path = Path(row.get("latest_video_path") or row.get("video_path") or "")
        try:
            if not path.is_file():
                raise ValueError("video_missing")
            receipt_name = ("receipt.json" if path.parent.name == "worker-render"
                            else "repair-receipt.json")
            receipt = json.loads((path.parent / receipt_name).read_text())
            if _digest(path) != receipt["video_sha256"]:
                raise ValueError("video_sha256_mismatch")
            probe = _probe(path)
            streams = probe.get("streams") or []
            if (float(probe["format"]["duration"]) <= 0
                    or not any(s.get("codec_type") == "video" for s in streams)
                    or not any(s.get("codec_type") == "audio" for s in streams)):
                raise ValueError("video_or_audio_stream_missing")
            checked += 1
        except Exception as exc:  # noqa: BLE001 - verify all outputs.
            failures.append({"item_id": row["item_id"],
                             "error": f"{type(exc).__name__}: {exc}"[:200]})
    result = {"schema_version": "dev-pb2.media-verification.v1",
              "expected": len(rows),
              "verified": checked, "failed": len(failures), "failures": failures}
    (summary.parent / "media-verification.json").write_text(json.dumps(
        result, ensure_ascii=False, indent=2) + "\n")
    return result


def main() -> None:
    parser = argparse.ArgumentParser(description="Verify final isolated MP4 artifacts")
    parser.add_argument("--summary", type=Path, required=True)
    args = parser.parse_args()
    print(json.dumps(verify(args.summary), ensure_ascii=False))


if __name__ == "__main__":
    main()
