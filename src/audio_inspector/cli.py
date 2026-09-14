"""Command-line interface for transcript inspection and review."""

from __future__ import annotations

import argparse
import json
from pathlib import Path

from .analyzer import analyze_video
from .batch import run_batch
from .server import serve


def parser() -> argparse.ArgumentParser:
    root = argparse.ArgumentParser(prog="audio-inspector")
    commands = root.add_subparsers(dest="command", required=True)
    one = commands.add_parser("inspect", help="inspect one rendered video")
    one.add_argument("video", type=Path)
    one.add_argument("--expected-text", default="")
    one.add_argument("--expected-text-file", type=Path)
    one.add_argument("--model", default="small")
    batch = commands.add_parser("batch", help="run a resumable JSON manifest")
    batch.add_argument("--manifest", type=Path, required=True)
    batch.add_argument("--output", type=Path, required=True)
    batch.add_argument("--model", default="small")
    batch.add_argument("--device", choices=("cpu", "cuda"), default="cpu")
    batch.add_argument("--compute-type", default="int8")
    batch.add_argument("--concurrency", type=int, default=1)
    batch.add_argument("--model-workers", type=int, default=1)
    batch.add_argument("--limit", type=int)
    web = commands.add_parser("serve", help="serve report and allowlisted videos")
    web.add_argument("--manifest", type=Path, required=True)
    web.add_argument("--output", type=Path, required=True)
    web.add_argument("--host", default="127.0.0.1")
    web.add_argument("--port", type=int, default=8765)
    return root


def main() -> None:
    args = parser().parse_args()
    if args.command == "inspect":
        expected = args.expected_text
        if args.expected_text_file:
            expected = args.expected_text_file.read_text(encoding="utf-8")
        payload, evidence = analyze_video(
            str(args.video.resolve(strict=True)), expected_text=expected, model_name=args.model
        )
        print(json.dumps({"payload": payload, "evidence": evidence}, ensure_ascii=False, indent=2))
    elif args.command == "batch":
        result = run_batch(
            args.manifest, args.output, model=args.model, device=args.device,
            compute_type=args.compute_type, concurrency=args.concurrency,
            model_workers=args.model_workers, limit=args.limit,
        )
        print(json.dumps({key: value for key, value in result.items() if key != "items"}, ensure_ascii=False))
    else:
        try:
            serve(args.manifest, args.output, args.host, args.port)
        except KeyboardInterrupt:
            return


if __name__ == "__main__":
    main()
