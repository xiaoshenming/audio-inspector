"""Apply only administrator-approved voiceover replacements to a source pack."""

from __future__ import annotations

import ast
import copy
import io
import tarfile
from pathlib import Path


def revise_source(source: str, overrides: list[dict]) -> str:
    tree = ast.parse(source)
    lines = source.encode("utf-8").splitlines(keepends=True)
    starts = [0]
    for line in lines:
        starts.append(starts[-1] + len(line))
    replacements: list[tuple[int, int, bytes]] = []
    for override in overrides:
        matched = []
        for node in ast.walk(tree):
            if not isinstance(node, ast.Call) or not isinstance(node.func, ast.Attribute):
                continue
            if node.func.attr != "voiceover" or node.lineno != override["source_line"]:
                continue
            for keyword in node.keywords:
                value = keyword.value
                if (keyword.arg == "text" and isinstance(value, ast.Constant)
                        and value.value == override["old_voiceover"]):
                    matched.append(value)
        if len(matched) != 1:
            raise ValueError("approved_voiceover_not_unique_in_source")
        value = matched[0]
        start = starts[value.lineno - 1] + value.col_offset
        end = starts[value.end_lineno - 1] + value.end_col_offset
        replacements.append((start, end, repr(override["new_voiceover"]).encode("utf-8")))
    if len({(start, end) for start, end, _ in replacements}) != len(replacements):
        raise ValueError("duplicate_voiceover_replacement")
    changed = source.encode("utf-8")
    for start, end, value in sorted(replacements, reverse=True):
        changed = changed[:start] + value + changed[end:]
    result = changed.decode("utf-8")
    ast.parse(result)
    return result


def revise_pack(archive: Path, overrides: list[dict], output: Path) -> Path:
    output.mkdir(parents=True, exist_ok=True)
    patched_main = output / "main.py"
    target_archive = output / "source.tar"
    with tarfile.open(archive, "r:*") as source, tarfile.open(target_archive, "w") as target:
        members = source.getmembers()
        if sum(member.name == "main.py" and member.isfile() for member in members) != 1:
            raise ValueError("source_pack_requires_one_main_py")
        for member in members:
            path = Path(member.name)
            if (path.is_absolute() or ".." in path.parts
                    or not (member.isfile() or member.isdir())):
                raise ValueError("unsafe_source_pack_member")
            data = source.extractfile(member).read() if member.isfile() else None
            if member.name == "main.py":
                data = revise_source(data.decode("utf-8"), overrides).encode("utf-8")
                patched_main.write_bytes(data)
            item = copy.copy(member)
            if data is not None:
                item.size = len(data)
            target.addfile(item, io.BytesIO(data) if data is not None else None)
    return patched_main
