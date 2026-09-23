"""Build a private, reproducible DEV-PB2 source and Git-history handoff archive."""

from __future__ import annotations

import argparse
import gzip
import hashlib
import io
import json
import subprocess
import tarfile
import tempfile
from pathlib import Path

ROOT_FILES = {".env.example", ".gitignore", "README.md", "SECURITY.md", "pyproject.toml"}
SOURCE_PREFIXES = (".github/", "benchmarks/", "docs/", "examples/", "scripts/",
                   "src/", "tests/", "tools/")
FORBIDDEN_PARTS = {".env", ".venv", "input", "output", "media", "models", "__pycache__"}


def _git(repo: Path, *args: str, output: Path | None = None) -> bytes:
    command = ["git", "-C", str(repo), *args]
    if output is None:
        return subprocess.run(command, check=True, capture_output=True).stdout
    with output.open("wb") as stream:
        subprocess.run(command, check=True, stdout=stream, stderr=subprocess.PIPE)
    return b""


def _allowed(name: str) -> bool:
    path = Path(name)
    if path.is_absolute() or ".." in path.parts or FORBIDDEN_PARTS.intersection(path.parts):
        return False
    if path.name.startswith(".env") and name != ".env.example":
        return False
    return name in ROOT_FILES or name.startswith(SOURCE_PREFIXES)


def _entry(archive: tarfile.TarFile, name: str, content: bytes) -> None:
    info = tarfile.TarInfo(name)
    info.size = len(content)
    info.mode = 0o644
    info.uid = info.gid = 0
    info.uname = info.gname = ""
    info.mtime = 0
    archive.addfile(info, io.BytesIO(content))


def build(repo: Path, output_dir: Path, baseline_tag: str) -> tuple[Path, Path]:
    """Package only approved files in HEAD; refuse an uncommitted tracked baseline."""
    repo = repo.resolve()
    output_dir = output_dir.resolve()
    if _git(repo, "status", "--porcelain", "--untracked-files=no").strip():
        raise ValueError("commit_tracked_changes_before_handoff")
    commit = _git(repo, "rev-parse", "HEAD").decode().strip()
    branch = _git(repo, "symbolic-ref", "--short", "HEAD").decode().strip()
    if not baseline_tag or "/" in baseline_tag or ".." in baseline_tag:
        raise ValueError("baseline_tag_required")
    tagged_commit = _git(repo, "rev-parse", f"refs/tags/{baseline_tag}^{{commit}}")
    if tagged_commit.decode().strip() != commit:
        raise ValueError("baseline_tag_must_point_to_head")
    tracked = [name.decode() for name in
               _git(repo, "ls-tree", "-r", "-z", "--name-only", "HEAD").split(b"\0") if name]
    names = sorted(name for name in tracked if _allowed(name))
    if not {"pyproject.toml", "README.md", "src/dev_pb2/__init__.py"}.issubset(names):
        raise ValueError("required_source_files_missing")
    excluded = sorted(set(tracked) - set(names))
    if excluded:
        raise ValueError("unexpected_tracked_files:" + ",".join(excluded))

    output_dir.mkdir(parents=True, exist_ok=True)
    with tempfile.TemporaryDirectory(prefix="dev-pb2-handoff-") as temp:
        bundle = Path(temp) / "history.bundle"
        _git(repo, "bundle", "create", str(bundle), f"refs/heads/{branch}",
             f"refs/tags/{baseline_tag}")
        _git(repo, "bundle", "verify", str(bundle))
        source_tar = _git(repo, "archive", "--format=tar", "HEAD", "--", *names)
        contents: dict[str, bytes] = {}
        with tarfile.open(fileobj=io.BytesIO(source_tar), mode="r:") as source:
            for member in source:
                if member.isfile():
                    extracted = source.extractfile(member)
                    if extracted is None or member.name not in names:
                        raise ValueError("unexpected_git_archive_member")
                    contents[f"source/{member.name}"] = extracted.read()
                elif not member.isdir():
                    raise ValueError("non_regular_source_member")
        if len(contents) != len(names):
            raise ValueError("source_archive_file_count_mismatch")
        contents["git/history.bundle"] = bundle.read_bytes()
        checksums = "".join(
            f"{hashlib.sha256(data).hexdigest()}  {name}\n"
            for name, data in sorted(contents.items())
        ).encode()
        contents["SHA256SUMS"] = checksums
        contents["HANDOFF.txt"] = (
            "DEV-PB2 离线交接包\n"
            f"版本: {baseline_tag}\n提交: {commit}\n\n"
            "1. 在解压目录执行: shasum -a 256 -c SHA256SUMS\n"
            "2. 阅读: source/docs/module-handoff.md 和 "
            "source/docs/batchops-adapter-guide.md\n"
            f"3. 恢复 Git 历史: git clone --branch {branch} "
            "git/history.bundle dev-pb2-restored\n"
            "4. 在 source/ 或恢复的仓库中安装并运行 scripts/preflight.sh。\n"
            "真实密钥和客户视频未包含在本包。\n"
        ).encode()
        contents["manifest.json"] = (json.dumps({
            "schema_version": "dev-pb2.handoff.v1", "commit": commit,
            "branch": branch, "baseline_tag": baseline_tag, "source_files": len(names),
            "contents": "source/, git/history.bundle, SHA256SUMS, HANDOFF.txt",
        }, ensure_ascii=False, indent=2) + "\n").encode("utf-8")
        archive_path = output_dir / f"DEV-PB2-handoff-{commit[:12]}.tar.gz"
        with (archive_path.open("wb") as raw,
              gzip.GzipFile(fileobj=raw, mode="wb", mtime=0, filename="") as compressed,
              tarfile.open(fileobj=compressed, mode="w") as archive):
            for name, data in sorted(contents.items()):
                _entry(archive, name, data)
    digest = hashlib.sha256(archive_path.read_bytes()).hexdigest()
    checksum_path = archive_path.with_name(archive_path.name + ".sha256")
    checksum_path.write_text(f"{digest}  {archive_path.name}\n", encoding="ascii")
    return archive_path, checksum_path


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--repo", type=Path, default=Path(__file__).resolve().parents[1])
    parser.add_argument("--output-dir", type=Path, required=True)
    parser.add_argument("--baseline-tag", required=True)
    args = parser.parse_args()
    archive, checksum = build(args.repo, args.output_dir, args.baseline_tag)
    print(json.dumps({"archive": str(archive), "sha256_file": str(checksum)},
                     ensure_ascii=False))


if __name__ == "__main__":
    main()
