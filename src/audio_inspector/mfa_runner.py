"""按需运行 MFA 全句对齐，为发音清单生成声学证据。"""

from __future__ import annotations

import fcntl
import os
import subprocess
import tempfile
from pathlib import Path

from .mfa_evidence import compare_manifest


def analyze_pronunciation(
    media_path: str,
    *,
    expected_text: str,
    manifest: dict,
) -> tuple[list[dict], dict]:
    """返回 findings 和可审计的 lane 状态；环境缺失由调用方转成待复核。"""
    executable = os.getenv("STT_MFA_EXECUTABLE", "mfa")
    dictionary = _required_path("STT_MFA_DICTIONARY")
    acoustic_model = os.getenv("STT_MFA_ACOUSTIC_MODEL", "mandarin_mfa")
    if not expected_text.strip():
        raise ValueError("pronunciation manifest requires expected_text")
    with tempfile.TemporaryDirectory(prefix="stt-mfa-") as directory:
        root = Path(directory)
        wav = root / "audio.wav"
        transcript = root / "audio.txt"
        textgrid = root / "audio.TextGrid"
        _run([
            "ffmpeg", "-v", "error", "-y", "-i", media_path,
            "-ac", "1", "-ar", "16000", str(wav),
        ], timeout=180)
        transcript.write_text(expected_text.strip(), encoding="utf-8")
        lock_path = Path(os.getenv("STT_MFA_LOCK_PATH", "/tmp/audio-inspector-mfa.lock"))
        with lock_path.open("w", encoding="utf-8") as lock:
            fcntl.flock(lock, fcntl.LOCK_EX)
            _run([
                executable, "align_one", str(wav), str(transcript),
                dictionary, acoustic_model, str(textgrid),
            ], timeout=int(os.getenv("STT_MFA_TIMEOUT_SECONDS", "600")))
        if not textgrid.is_file():
            raise RuntimeError("MFA did not create TextGrid")
        findings = compare_manifest(textgrid, manifest)
    return findings, {
        "lane": "pronunciation",
        "status": "completed",
        "engine": "montreal-forced-aligner",
        "manifest_schema": str(manifest.get("schema_version") or ""),
    }


def _required_path(name: str) -> str:
    value = os.getenv(name, "").strip()
    if not value:
        raise RuntimeError(f"missing {name}")
    path = Path(value).expanduser().resolve()
    if not path.exists():
        raise RuntimeError(f"{name} does not exist: {path}")
    return str(path)


def _run(command: list[str], *, timeout: int) -> None:
    environment = os.environ.copy()
    executable = Path(command[0])
    if executable.parent != Path("."):
        environment["PATH"] = f"{executable.parent}:{environment.get('PATH', '')}"
    result = subprocess.run(
        command,
        capture_output=True,
        text=True,
        timeout=timeout,
        check=False,
        env=environment,
    )
    if result.returncode:
        message = (result.stderr or result.stdout).strip()[-1000:]
        raise RuntimeError(f"command failed ({result.returncode}): {message}")
