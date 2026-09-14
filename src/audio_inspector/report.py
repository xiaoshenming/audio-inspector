"""Self-contained HTML report for transcript inspection results."""

from __future__ import annotations

import html
from pathlib import Path


def write_report(path: Path, summary: dict) -> None:
    rows = []
    for result in summary.get("items", []):
        item = result.get("item", {})
        item_id = str(item.get("item_id") or "")
        if result.get("status") != "completed":
            rows.append(_row(item_id, "failed_open", 0, "检测不可用", "", 0))
            continue
        findings = result.get("evidence", {}).get("findings", [])
        if not findings:
            rows.append(_row(item_id, "clean", 0, "未发现候选", "", 0))
        for finding in findings:
            rows.append(_row(
                item_id,
                str(finding.get("severity") or "low"),
                int(finding.get("start_ms") or 0),
                str(finding.get("reason") or finding.get("type") or "候选"),
                str(finding.get("transcript_text") or ""),
                int(finding.get("end_ms") or 0),
            ))
    path.write_text(_page(summary, "".join(rows)), encoding="utf-8")


def _row(item_id: str, severity: str, start: int, reason: str, transcript: str, end: int) -> str:
    seek = max(0, start / 1000 - 1.5)
    safe_id = html.escape(item_id, quote=True)
    return (
        "<tr>"
        f"<td>{html.escape(item_id)}</td><td><span class='tag {html.escape(severity)}'>{html.escape(severity)}</span></td>"
        f"<td><button data-item='{safe_id}' data-seek='{seek}' onclick='play(this.dataset.item, Number(this.dataset.seek))'>{start / 1000:.2f}s</button>"
        f"–{end / 1000:.2f}s</td><td>{html.escape(reason)}</td>"
        f"<td>{html.escape(transcript)}</td></tr>"
    )


def _page(summary: dict, rows: str) -> str:
    return f"""<!doctype html><html lang='zh-CN'><head><meta charset='utf-8'>
<meta name='viewport' content='width=device-width,initial-scale=1'><title>音频检测报告</title>
<style>body{{font:14px/1.5 system-ui;margin:0;background:#f5f7fb;color:#182230}}main{{max-width:1200px;margin:auto;padding:24px}}.stats{{display:flex;gap:12px;flex-wrap:wrap}}.stat,table{{background:#fff;border:1px solid #dfe4ea;border-radius:10px}}.stat{{padding:10px 16px}}table{{width:100%;border-collapse:collapse;margin-top:18px}}th,td{{padding:9px;border-bottom:1px solid #edf0f3;text-align:left}}button{{cursor:pointer}}.tag{{padding:2px 6px;border-radius:8px;background:#eef2f6}}.high{{color:#b42318}}.medium{{color:#b54708}}.low,.clean{{color:#475467}}dialog{{width:min(900px,90vw)}}video{{width:100%}}</style></head>
<body><main><h1>音频检测报告</h1><p>自动结果只作风险证据，必须人工核听后才能确认TTS错误。</p>
<div class='stats'><div class='stat'>总数 <b>{summary.get('total', 0)}</b></div><div class='stat'>完成 <b>{summary.get('succeeded', 0)}</b></div><div class='stat'>候选视频 <b>{summary.get('candidate_videos', 0)}</b></div><div class='stat'>降级 <b>{summary.get('failed_open', 0)}</b></div></div>
<table><thead><tr><th>视频</th><th>级别</th><th>时间</th><th>原因</th><th>转写片段</th></tr></thead><tbody>{rows}</tbody></table></main>
<dialog id='playerDialog'><button onclick='playerDialog.close()'>关闭</button><h3 id='videoTitle'></h3><video id='player' controls></video></dialog>
<script>const playerDialog=document.getElementById('playerDialog');function play(id,t){{document.getElementById('videoTitle').textContent=id;const p=document.getElementById('player');p.src='/media?item='+encodeURIComponent(id);p.onloadedmetadata=()=>{{p.currentTime=t;p.play().catch(()=>{{}})}};playerDialog.showModal()}}</script></body></html>"""
