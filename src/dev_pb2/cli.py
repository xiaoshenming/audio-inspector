"""Stable command line boundary for standalone inspection and admin decisions."""

from __future__ import annotations

import argparse
import json
from pathlib import Path

from .decisions import decide
from .pipeline import publish, run


def main() -> None:
    parser = argparse.ArgumentParser(prog="dev-pb2")
    commands = parser.add_subparsers(dest="command", required=True)
    inspect = commands.add_parser("inspect", help="Run screening from a resource request")
    inspect.add_argument("--request", type=Path, required=True)
    inspect.add_argument("--work-root", type=Path, required=True)
    report = commands.add_parser("publish", help="Rebuild result from completed evidence")
    report.add_argument("--dataset", type=Path, required=True)
    decision = commands.add_parser("decide", help="Emit an audited BatchOps action command")
    decision.add_argument("--inspection", type=Path, required=True)
    decision.add_argument("--source", type=Path, required=True)
    decision.add_argument("--actor", required=True)
    decision.add_argument("--action", choices=("accept_as_is", "approve_repair"), required=True)
    decision.add_argument("--edits", type=Path)
    decision.add_argument("--note", default="")
    decision.add_argument("--output", type=Path, required=True)
    args = parser.parse_args()
    if args.command == "inspect":
        result = run(json.loads(args.request.read_text()), args.work_root)
    elif args.command == "publish":
        result = publish(args.dataset)
    else:
        edits = json.loads(args.edits.read_text()) if args.edits else None
        result = decide(json.loads(args.inspection.read_text()), args.source,
                        args.actor, args.action, edits, args.note)
        args.output.parent.mkdir(parents=True, exist_ok=True)
        args.output.write_text(json.dumps(result, ensure_ascii=False, indent=2) + "\n")
    print(json.dumps(result, ensure_ascii=False))


if __name__ == "__main__":
    main()
