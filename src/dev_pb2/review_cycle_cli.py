"""Command line interface for the persistent human review cycle."""

from __future__ import annotations

import argparse
import json
import os
from pathlib import Path

from .review_cycle import apply, load, resume_repair, retry_inspection, start, view


def main() -> None:
    parser = argparse.ArgumentParser(description="Run the standalone human TTS review cycle")
    actions = parser.add_subparsers(dest="command", required=True)
    begin = actions.add_parser("start")
    begin.add_argument("--request", type=Path, required=True)
    begin.add_argument("--session", type=Path, required=True)
    begin.add_argument("--work-root", type=Path, required=True)
    begin.add_argument("--unburned", type=Path)
    begin.add_argument("--source-pack", type=Path)
    begin.add_argument("--repair-mode", choices=("local", "worker"), default="local")
    review = actions.add_parser("decide")
    review.add_argument("--session", type=Path, required=True)
    review.add_argument("--actor", required=True)
    review.add_argument("--action", choices=("accept_as_is", "approve_repair"), required=True)
    review.add_argument("--edits", type=Path)
    review.add_argument("--note", default="")
    status = actions.add_parser("status")
    status.add_argument("--session", type=Path, required=True)
    retry = actions.add_parser("retry")
    retry.add_argument("--session", type=Path, required=True)
    resume = actions.add_parser("resume")
    resume.add_argument("--session", type=Path, required=True)
    args = parser.parse_args()
    if args.command == "start":
        state = start(json.loads(args.request.read_text(encoding="utf-8")),
                      session=args.session, work_root=args.work_root,
                      unburned=args.unburned, source_pack=args.source_pack,
                      repair_mode=args.repair_mode)
    elif args.command == "decide":
        edits = json.loads(args.edits.read_text(encoding="utf-8")) if args.edits else None
        state = apply(args.session, actor=args.actor, action=args.action,
                      edits=edits, note=args.note,
                      api_key=os.environ.get("DASHSCOPE_API_KEY", ""),
                      tts_endpoint=os.environ.get("DASHSCOPE_TTS_ENDPOINT", ""))
    elif args.command == "retry":
        state = retry_inspection(args.session)
    elif args.command == "resume":
        state = resume_repair(args.session,
                              api_key=os.environ.get("DASHSCOPE_API_KEY", ""),
                              tts_endpoint=os.environ.get("DASHSCOPE_TTS_ENDPOINT", ""))
    else:
        state = load(args.session)
    print(json.dumps(view(state), ensure_ascii=False))
