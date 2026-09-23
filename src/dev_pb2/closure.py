"""One module call from frozen video through approved repair and reinspection."""

from __future__ import annotations

import argparse
import json
import os
from pathlib import Path

from .decisions import decide
from .pipeline import run
from .repair_media import rebuild
from .review_resources import digest


def close_loop(request: dict, *, work_root: Path, unburned: Path,
               source_pack: Path, actor: str, edits: list[dict],
               output: Path, api_key: str, tts_endpoint: str,
               tts_profile: dict | None = None) -> dict:
    output.mkdir(parents=True, exist_ok=True)
    before = run(request, work_root)
    if before["status"] != "candidate":
        raise ValueError(f"repair_requires_candidate:{before['status']}")
    decision = decide(before, Path(request["source_path"]), actor,
                      "approve_repair", edits)
    (output / "decision.json").write_text(json.dumps(decision, ensure_ascii=False,
                                                    indent=2) + "\n")
    repaired = rebuild(before, decision, video=Path(request["video_path"]),
                       unburned=unburned, subtitle=Path(request["subtitle_path"]),
                       source_pack=source_pack, output=output / "repaired",
                       api_key=api_key, tts_endpoint=tts_endpoint,
                       tts_profile=tts_profile or request.get("tts_profile"))
    revised_request = {**request, "revision_id": request["revision_id"] + ":pb2:"
                       + decision["idempotency_key"][:12],
                       "video_path": repaired["video_path"],
                       "source_path": repaired["source_path"],
                       "subtitle_path": repaired["subtitle_path"],
                       "subtitle_sha256": repaired.get("subtitle_sha256") or digest(
                           Path(repaired["subtitle_path"])),
                       "video_sha256": repaired["video_sha256"],
                       "source_sha256": repaired["source_sha256"]}
    after = run(revised_request, work_root)
    result = {"schema_version": "dev-pb2.closure.v1", "item_id": before["item_id"],
              "before": before, "decision": decision,
              "repair": repaired, "after": after,
              "status": ("reinspection_clean" if after["status"] == "clean"
                         else "reinspection_needs_review")}
    (output / "closure.json").write_text(json.dumps(result, ensure_ascii=False,
                                                   indent=2) + "\n")
    return result


def main() -> None:
    parser = argparse.ArgumentParser(description="Inspect, approve, rebuild, and reinspect")
    for name in ("request", "work-root", "unburned", "source-pack", "edits", "output"):
        parser.add_argument("--" + name, type=Path, required=True)
    parser.add_argument("--actor", required=True)
    parser.add_argument("--tts-profile", type=Path)
    args = parser.parse_args()
    result = close_loop(json.loads(args.request.read_text()), work_root=args.work_root,
                        unburned=args.unburned, source_pack=args.source_pack,
                        actor=args.actor, edits=json.loads(args.edits.read_text()),
                        output=args.output, api_key=os.environ["DASHSCOPE_API_KEY"],
                        tts_endpoint=os.environ["DASHSCOPE_TTS_ENDPOINT"],
                        tts_profile=json.loads(args.tts_profile.read_text())
                        if args.tts_profile else None)
    print(json.dumps({"item_id": result["item_id"], "status": result["status"],
                      "before": result["before"]["status"],
                      "after": result["after"]["status"],
                      "video": result["repair"]["video_path"]}, ensure_ascii=False))


if __name__ == "__main__":
    main()
