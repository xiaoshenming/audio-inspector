"""把多音字批量结果生成可点击时间点的视频审计页。"""

from __future__ import annotations

import argparse
import html
import json
from collections import Counter
from pathlib import Path


def generate(results_path: Path, output: Path, *, title: str) -> dict:
    rows = [
        json.loads(line)
        for line in results_path.read_text(encoding="utf-8").splitlines()
        if line.strip()
    ]
    findings = [
        (row["item_id"], row["item"], finding)
        for row in rows if row.get("status") == "completed"
        for finding in row.get("findings", [])
        if finding.get("status") == "confirmed_issue"
    ]
    grouped: dict[str, tuple[dict, list[dict]]] = {}
    for item_id, item, finding in findings:
        grouped.setdefault(str(item_id), (item, []))[1].append(finding)
    stats = {
        "videos_checked": len(rows),
        "processing_failed": sum(row.get("status") != "completed" for row in rows),
        "candidate_count": sum(int(row.get("candidate_count") or 0) for row in rows),
        "confirmed_issue": len(findings),
        "problem_videos": len(grouped),
        "uncertain": sum(
            finding.get("status") == "uncertain"
            for row in rows for finding in row.get("findings", [])
        ),
        "characters": dict(Counter(finding["char"] for _, _, finding in findings)),
    }
    cards = "\n".join(
        _card(item_id, item, values)
        for item_id, (item, values) in sorted(grouped.items())
    )
    output.write_text(_page(title, stats, cards), encoding="utf-8")
    summary = dict(stats, report=str(output))
    output.with_suffix(".json").write_text(
        json.dumps(summary, ensure_ascii=False, indent=2), encoding="utf-8",
    )
    return summary


def _card(item_id: str, item: dict, findings: list[dict]) -> str:
    safe_id = html.escape(item_id, quote=True)
    rows = "".join(_finding_row(item_id, finding) for finding in findings)
    label = str(item.get("template") or "")
    return f"""<section class="card">
<div class="head"><div><span class="template">分组 {html.escape(label)}</span>
<code>{html.escape(item_id)}</code></div><span class="badge">{len(findings)} 处声学冲突</span></div>
<table><thead><tr><th>定位</th><th>原句附近</th><th>应读</th><th>实际异读</th><th>三窗证据</th></tr></thead>
<tbody>{rows}</tbody></table>
<div class="actions"><button data-item="{safe_id}" onclick="playAt(this.dataset.item,0)">从头播放</button></div></section>"""


def _finding_row(item_id: str, finding: dict) -> str:
    start = float(finding.get("start") or 0)
    expected = str(finding.get("expected_pinyin") or "")
    alternative = _observed_pinyin(finding)
    windows = finding.get("observed_windows") or []
    observed = str(finding.get("observed_alternative") or "")
    votes = sum(observed and observed in str(value) for value in windows)
    safe_id = html.escape(item_id, quote=True)
    return f"""<tr>
<td><button data-item="{safe_id}" data-seek="{start:.3f}" onclick="playAt(this.dataset.item,Number(this.dataset.seek))">{_clock(start)}</button></td>
<td class="context">{html.escape(str(finding.get("context") or ""))}</td>
<td><b>{html.escape(str(finding.get("char") or ""))}</b> <span class="good">{html.escape(expected)}</span></td>
<td><span class="bad">{html.escape(alternative)}</span></td>
<td><span class="ok">{votes}/{len(windows)} 窗</span></td></tr>"""


def _observed_pinyin(finding: dict) -> str:
    observed = str(finding.get("observed_alternative") or "")
    zhuyin = list(finding.get("alternative_zhuyin") or [])
    pinyin = list(finding.get("alternative_pinyin") or [])
    for index, value in enumerate(zhuyin):
        if value == observed and index < len(pinyin):
            return str(pinyin[index])
    return observed or "未解析"


def _clock(value: float) -> str:
    return f"{int(value // 60):02d}:{int(value % 60):02d}"


def _page(title: str, stats: dict, cards: str) -> str:
    chars = "、".join(f"{key}×{value}" for key, value in stats["characters"].items()) or "无"
    safe_title = html.escape(title)
    return f"""<!doctype html><html lang="zh-CN"><head><meta charset="utf-8">
<meta name="viewport" content="width=device-width,initial-scale=1"><title>{safe_title}</title>
<style>
:root{{--bg:#f5f7fb;--card:#fff;--line:#e1e5eb;--text:#172033;--blue:#2457d6;--red:#c9363e;--green:#16835f;--muted:#667085}}
*{{box-sizing:border-box}}body{{margin:0;background:var(--bg);color:var(--text);font:14px/1.6 system-ui,"Microsoft YaHei",sans-serif}}
main{{max-width:1280px;margin:auto;padding:28px 20px 80px}}h1{{margin:0}}.sub{{color:var(--muted)}}.notice{{background:#fff7e6;border-left:5px solid #f59e0b;padding:15px;border-radius:9px;margin:18px 0}}
.stats{{display:flex;gap:12px;flex-wrap:wrap}}.stat{{background:#fff;border:1px solid var(--line);border-radius:10px;padding:12px 18px}}.stat b{{display:block;font-size:24px}}
.card{{background:var(--card);border:1px solid var(--line);border-radius:12px;margin:16px 0;padding:15px}}.head{{display:flex;justify-content:space-between;gap:12px;margin-bottom:10px}}
.template{{background:#eef4ff;color:var(--blue);padding:3px 8px;border-radius:999px;font-weight:700}}.badge{{background:#fff1f0;color:var(--red);padding:3px 9px;border-radius:999px;font-weight:700}}
code{{word-break:break-all}}table{{width:100%;border-collapse:collapse}}th,td{{text-align:left;vertical-align:top;padding:10px;border-bottom:1px solid var(--line)}}th{{background:#f8fafc}}.context{{min-width:240px}}
button{{border:0;border-radius:7px;background:var(--blue);color:#fff;padding:7px 11px;cursor:pointer}}.good{{color:var(--green);font-weight:800}}.bad{{color:var(--red);font-weight:800}}.ok{{color:var(--green)}}.actions{{display:flex;gap:14px;margin-top:12px}}a{{color:var(--blue)}}
.modal{{display:none;position:fixed;inset:0;background:#101828df;z-index:10;align-items:center;justify-content:center;padding:20px}}.modal.open{{display:flex}}.dialog{{width:min(1000px,96vw);background:#111827;color:#fff;border-radius:14px;padding:14px}}.bar{{display:flex;justify-content:space-between;margin-bottom:10px}}video{{width:100%;max-height:76vh;background:#000}}
@media(max-width:760px){{table{{display:block;overflow:auto}}th,td{{min-width:130px}}}}
</style></head><body><main><h1>{safe_title}</h1>
<p class="sub">点击时间直接跳转视频；自动结果仅作人工复核证据</p>
<div class="notice"><b>口径：</b>页面列出三窗多数读成另一合法异读的声学冲突。它们是高置信排查对象；标准读音终审可继续剔除词法边界、轻声和变调争议。字符分布：{html.escape(chars)}。</div>
<div class="stats"><div class="stat"><b>{stats["videos_checked"]}</b>已处理视频</div>
<div class="stat"><b>{stats["candidate_count"]}</b>语境候选</div>
<div class="stat"><b>{stats["confirmed_issue"]}</b>声学冲突</div>
<div class="stat"><b>{stats["problem_videos"]}</b>涉及视频</div>
<div class="stat"><b>{stats["uncertain"]}</b>不确定</div>
<div class="stat"><b>{stats["processing_failed"]}</b>处理失败</div></div>{cards}</main>
<div id="modal" class="modal"><div class="dialog"><div class="bar"><div id="title"></div><button onclick="closePlayer()">关闭</button></div><video id="player" controls preload="metadata"></video></div></div>
<script>
const modal=document.getElementById('modal'),player=document.getElementById('player'),label=document.getElementById('title');
function playAt(id,s){{label.textContent=id;player.src='/media?item='+encodeURIComponent(id);modal.classList.add('open');player.addEventListener('loadedmetadata',()=>{{player.currentTime=s;player.play().catch(()=>{{}})}},{{once:true}})}}
function closePlayer(){{player.pause();player.removeAttribute('src');player.load();modal.classList.remove('open')}}modal.addEventListener('click',e=>{{if(e.target===modal)closePlayer()}});document.addEventListener('keydown',e=>{{if(e.key==='Escape')closePlayer()}});
</script></body></html>"""


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--results", type=Path, required=True)
    parser.add_argument("--output", type=Path, required=True)
    parser.add_argument("--title", default="多音字批量排查结果")
    args = parser.parse_args()
    print(json.dumps(
        generate(args.results, args.output, title=args.title),
        ensure_ascii=False,
    ))


if __name__ == "__main__":
    main()
