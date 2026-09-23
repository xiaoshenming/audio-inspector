"""Verify the distributable archive contains a committed baseline and no local data."""

from __future__ import annotations

import hashlib
import importlib.util
import json
import subprocess
import tarfile
from pathlib import Path


def _builder():
    path = Path(__file__).resolve().parents[1] / "tools/build_handoff.py"
    spec = importlib.util.spec_from_file_location("build_handoff", path)
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def test_handoff_is_clean_reproducible_and_has_history(tmp_path):
    repo = tmp_path / "repo"
    (repo / "src/dev_pb2").mkdir(parents=True)
    (repo / "docs").mkdir()
    (repo / "examples").mkdir()
    (repo / "input").mkdir()
    (repo / "pyproject.toml").write_text("[project]\nname='dev-pb2'\n")
    (repo / "README.md").write_text("handoff\n")
    (repo / "src/dev_pb2/__init__.py").write_text("__version__='test'\n")
    (repo / "docs/integration.md").write_text("integration\n")
    (repo / "examples/manifest.example.json").write_text("{}\n")
    (repo / "input/customer.mp4").write_bytes(b"private video")
    (repo / ".env").write_text("KEY=private\n")
    subprocess.run(["git", "init", "-q", str(repo)], check=True)
    subprocess.run(["git", "-C", str(repo), "add", "pyproject.toml", "README.md",
                    "src", "docs", "examples"], check=True)
    subprocess.run(["git", "-C", str(repo), "-c", "user.name=Test", "-c",
                    "user.email=test@example.com", "commit", "-qm", "baseline"], check=True)

    tag = "DEV-PB2-baseline-test"
    subprocess.run(["git", "-C", str(repo), "tag", tag], check=True)
    build = _builder().build
    archive, checksum = build(repo, tmp_path / "out", tag)
    first_hash = hashlib.sha256(archive.read_bytes()).hexdigest()
    assert checksum.read_text().startswith(first_hash)
    with tarfile.open(archive, "r:gz") as tar:
        names = {member.name for member in tar.getmembers()}
        assert "source/docs/integration.md" in names
        assert "source/examples/manifest.example.json" in names
        assert "git/history.bundle" in names
        assert "HANDOFF.txt" in names
        assert "git clone --branch" in tar.extractfile("HANDOFF.txt").read().decode()
        assert "source/input/customer.mp4" not in names
        assert "source/.env" not in names
        manifest = json.load(tar.extractfile("manifest.json"))
        assert manifest["source_files"] == 5
        assert manifest["baseline_tag"] == tag
        bundle = tmp_path / "history.bundle"
        bundle.write_bytes(tar.extractfile("git/history.bundle").read())
    clone = tmp_path / "clone"
    branch = subprocess.run(["git", "-C", str(repo), "branch", "--show-current"],
                            capture_output=True, text=True, check=True).stdout.strip()
    subprocess.run(["git", "clone", "-q", "--branch", branch, str(bundle), str(clone)],
                   check=True)
    assert (clone / "src/dev_pb2/__init__.py").is_file()
    assert subprocess.run(["git", "-C", str(clone), "tag", "--list", tag],
                          capture_output=True, text=True, check=True).stdout.strip() == tag
    second, _ = build(repo, tmp_path / "out", tag)
    assert hashlib.sha256(second.read_bytes()).hexdigest() == first_hash
