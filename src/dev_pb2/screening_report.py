"""Build a staff review desk from immutable source and ASR evidence."""

from __future__ import annotations

import argparse
import csv
import json
import re
from collections import Counter
from pathlib import Path
from zipfile import ZIP_STORED, ZipFile

from .semantic_review import _match, actionable_source_issue
from .subtitle_cues import read_srt_cues

OBVIOUS_GAP = re.compile(
    r"(?:已知向量与|当等于|若(?:小于|大于|等于)|求的值|解得等于|"
    r"由此得等于|将的值|以为原点|过点作|与的延长线|已知分之一|"
    r"减的[二三四]次方|加的[二三四]次方|所以的|等于方)"
)


def _read_items(folder: Path) -> dict[str, dict]:
    return {row["item_id"]: row for path in (folder / "items").glob("*.json")
            if (row := json.loads(path.read_text(encoding="utf-8")))}


def _source_time(issue: dict, cues: list[dict]) -> float | None:
    quote = issue.get("source_quote", "")
    for cue in cues:
        if _match(quote, cue["text"]):
            return cue["start_seconds"]
    full = issue.get("source_text", "")
    for cue in cues:
        if _match(cue["text"], full) or _match(full, cue["text"]):
            return cue["start_seconds"]
    return None


def _source_priority(issues: list[dict]) -> str:
    high = [row for row in issues if row.get("confidence") == "high"
            and row.get("category") == "source_missing_object"]
    if len(high) >= 4 or any(OBVIOUS_GAP.search(row.get("source_quote", "")) for row in high):
        return "A"
    return "B"


def _math_expression(value: str) -> list[str]:
    return [re.sub(r"\s+", "", match).replace("减", "-").replace("加", "+")
            for match in re.findall(r"[A-Za-z0-9]+\s*(?:减|加|[-+])\s*[A-Za-z0-9]+", value)]


def _strong_audio_difference(issue: dict) -> bool:
    source = str(issue.get("source_quote") or "")
    actual = str(issue.get("asr_quote") or "")
    category = issue.get("category")
    if category == "audio_wrong_operator":
        expected = _math_expression(source)
        heard = _math_expression(actual)
        if expected and heard and expected == heard:
            return False
        return (("减" in source or "-" in source) and ("加" in actual or "+" in actual)
                or ("加" in source or "+" in source) and ("减" in actual or "-" in actual))
    if category == "audio_wrong_number":
        expected = re.findall(r"\d+(?:\.\d+)?", source)
        heard = re.findall(r"\d+(?:\.\d+)?", actual)
        return bool(expected and heard and expected != heard
                    and any(len(number) >= 2 for number in expected + heard)
                    and not any(mark in source + actual for mark in ("/", "%")))
    if category == "audio_wrong_letter":
        expected = set(re.findall(r"(?<![A-Za-z])[A-Z]{2,4}(?![A-Za-z])", source))
        heard = set(re.findall(r"(?<![A-Za-z])[A-Z]{2,4}(?![A-Za-z])", actual))
        return bool(expected and heard and expected != heard)
    if category in {"audio_wrong_unit", "audio_missing_object"}:
        if any(expected in source and heard in actual
               for expected, heard in (("立方厘米", "平方厘米"),
                                       ("平方厘米", "立方厘米"),
                                       ("立方米", "平方米"),
                                       ("平方米", "立方米"))):
            return True
        return any(unit in source and unit not in actual and plain in actual
                   for unit, plain in (("平方米", "米"), ("平方厘米", "厘米")))
    return False


def _reportable(issue: dict, kind: str) -> bool:
    reason = str(issue.get("why") or "")
    if re.search(r"不构成(?:缺陷|问题|错误)|无直接错误|故不报告|表述可通|数学上等价", reason):
        return False
    if kind == "source":
        return actionable_source_issue(issue)
    if issue.get("category") == "audio_wrong_operator":
        expected, heard = _math_expression(str(issue.get("source_quote") or "")), \
                          _math_expression(str(issue.get("asr_quote") or ""))
        if expected and heard and expected == heard:
            return False
    if re.search(r"同音|近音", reason):
        return False
    if issue.get("confidence") not in {"high", "medium"}:
        return _strong_audio_difference(issue)
    if issue.get("category") == "audio_other":
        return False
    return not (issue.get("category") == "audio_wrong_letter"
                and ("大小写" in reason or "大写" in reason and "小写" in reason))


def compile_candidates(dataset: Path) -> list[dict]:
    with (dataset / "metadata/samples.csv").open(encoding="utf-8-sig", newline="") as stream:
        samples = list(csv.DictReader(stream))
    source = _read_items(dataset / "semantic-source")
    audio = _read_items(dataset / "semantic-audio")
    literal = _read_items(dataset / "literal-reading") if (dataset / "literal-reading").is_dir() else {}
    triage_path = dataset / "metadata/audio-triage.json"
    audio_triage = json.loads(triage_path.read_text()) if triage_path.is_file() else {}
    result = []
    for sample in samples:
        item_id = sample["item_id"]
        source_issues = [issue for issue in source.get(item_id, {}).get("issues") or []
                         if _reportable(issue, "source")]
        audio_issues = [issue for issue in audio.get(item_id, {}).get("issues") or []
                        if _reportable(issue, "audio")]
        audio_issues.extend(issue for issue in literal.get(item_id, {}).get("issues") or []
                            if _reportable(issue, "audio"))
        if not source_issues and not audio_issues:
            continue
        cues = read_srt_cues(Path(sample["subtitle_path"])) if sample["subtitle_path"] else []
        for issue in source_issues:
            issue["kind"] = "source"
            issue["time_seconds"] = _source_time(issue, cues)
        for issue in audio_issues:
            issue["kind"] = "audio"
            issue["time_seconds"] = round(int(issue.get("start_ms") or 0) / 1000, 2)
        priority = _source_priority(source_issues) if source_issues else "B"
        triage = audio_triage.get(item_id) or {}
        if triage.get("priority") == "A" and audio_issues:
            priority = "A"
        if any(issue.get("category") == "audio_literal_formula"
               and issue.get("confidence") == "high" for issue in audio_issues):
            priority = "A"
        result.append({"item_id": item_id, "external_key": sample["external_key"],
                       "batch_name": sample["batch_name"], "tts_status": sample["tts_status"],
                       "duration_seconds": float(sample["duration_seconds"]),
                       "priority": priority, "triage_note": triage.get("note", ""),
                       "source_issues": source_issues,
                       "audio_issues": audio_issues})
    return sorted(result, key=lambda row: (row["priority"],
                                          -len(row["source_issues"]),
                                          -len(row["audio_issues"]), row["item_id"]))


def _csv(dataset: Path, candidates: list[dict]) -> None:
    for filename, rows in (("shortlist.csv", [x for x in candidates if x["priority"] == "A"]),
                           ("all_candidates.csv", candidates)):
        path = dataset / "screening-review" / filename
        with path.open("w", newline="", encoding="utf-8-sig") as stream:
            writer = csv.writer(stream)
            writer.writerow(["优先级", "题目ID", "题号", "批次", "证据类型", "类别", "时间秒",
                             "源码旁白原文", "ASR转写", "建议读法", "原因", "交叉核对说明",
                             "人工结论", "复核备注"])
            for item in rows:
                for issue in item["source_issues"] + item["audio_issues"]:
                    writer.writerow([item["priority"], item["item_id"], item["external_key"],
                                     item["batch_name"], issue["kind"], issue.get("category", ""),
                                     issue.get("time_seconds") or "", issue.get("source_quote", ""),
                                     issue.get("asr_quote", ""), issue.get("suggested_reading", ""),
                                     issue.get("why", ""), item.get("triage_note", ""), "", ""])
        path.chmod(0o600)
    path = dataset / "screening-review/shortlist-videos.csv"
    with path.open("w", newline="", encoding="utf-8-sig") as stream:
        writer = csv.writer(stream)
        writer.writerow(["题目ID", "题号", "批次", "源码候选处数", "音频候选处数",
                         "首条候选原文", "是否确有明显问题", "实际问题类别", "复核备注"])
        for item in candidates:
            if item["priority"] != "A":
                continue
            first = (item["source_issues"] + item["audio_issues"])[0]
            writer.writerow([item["item_id"], item["external_key"], item["batch_name"],
                             len(item["source_issues"]), len(item["audio_issues"]),
                             first.get("source_quote", ""), "", "", ""])
    path.chmod(0o600)


def _package(dataset: Path, candidates: list[dict]) -> None:
    priority = [item for item in candidates if item["priority"] == "A"]
    archive = dataset / "screening-review/priority-a-review-package.zip"
    readme = (
        f"A 级优先复审：{len(priority)} 条最终配音视频。\n"
        "机器结论只是核听线索，不代表已确认错误。\n"
        "先按 shortlist.csv 的时间点核听，再填写复核列。\n"
        "shortlist-videos.csv 每条视频一行，可统计视频级准确率。\n"
        "题目 ID 对应 videos/ 下的同名 MP4；subtitles/ 是原始字幕。\n"
    )
    with ZipFile(archive, "w", compression=ZIP_STORED, allowZip64=True) as bundle:
        bundle.writestr("README.txt", readme)
        for name in ("shortlist.csv", "shortlist-videos.csv"):
            bundle.write(dataset / "screening-review" / name, name)
        for item in priority:
            item_id = item["item_id"]
            bundle.write(dataset / "videos" / f"{item_id}.mp4", f"videos/{item_id}.mp4")
            subtitle = dataset / "subtitles" / f"{item_id}.srt"
            if subtitle.is_file():
                bundle.write(subtitle, f"subtitles/{item_id}.srt")
    archive.chmod(0o600)


def _page(candidates: list[dict], total: int) -> str:
    payload = json.dumps(candidates, ensure_ascii=False).replace("<", "\\u003c")
    return """<!doctype html><html lang="zh-CN"><head><meta charset="utf-8">
<meta name="viewport" content="width=device-width,initial-scale=1"><title>152 条 TTS 样本复审</title>
<style>body{font:15px/1.55 system-ui;margin:0;background:#f4f6fb;color:#142033}header{background:#172b4d;color:white;padding:22px 5vw}main{max-width:1300px;margin:20px auto;padding:0 20px}.toolbar{display:flex;gap:10px;flex-wrap:wrap;margin:18px 0}.toolbar input,.toolbar select{padding:8px;border:1px solid #ccd3df;border-radius:8px}.card{background:white;border:1px solid #dce2ec;border-radius:12px;margin:12px 0;padding:16px}.head{display:flex;justify-content:space-between;gap:14px}.tag{border-radius:6px;padding:2px 7px;background:#e6ebf4}.tierA{background:#ffe3df;color:#9f2d1d}.issue{border-top:1px solid #e4e8ef;margin-top:12px;padding-top:12px}.source{color:#a12727}.asr{color:#9c5b00}.suggested{color:#086d46}.muted{color:#66758b}.seek{cursor:pointer;border:0;background:#dfebff;border-radius:6px;padding:5px 8px}dialog{width:min(1000px,92vw);border:0;border-radius:12px;box-shadow:0 20px 60px #0005}video{width:100%}pre{white-space:pre-wrap}</style></head>
<body><header><h1>终版 TTS 样本复审</h1><p>""" + f"{total} 条成片 · 候选 {len(candidates)} 条 · A 级 {sum(x['priority']=='A' for x in candidates)} 条。" + """机器结果仅供核听，人工结论请填入 CSV。</p></header>
<main><p>红色是最终源码旁白的原文；橙色是 Qwen ASR 听写结果；绿色是 AI 提出的读法建议。源码缺漏与成片疑似读错分别记录，ASR 候选并非确认错误。</p>
<div class="toolbar"><select id="tier"><option value="">全部优先级</option><option value="A">A 优先</option><option value="B">B 扩展</option></select><select id="kind"><option value="">全部类型</option><option value="source">源码缺漏</option><option value="audio">疑似读错</option></select><input id="search" placeholder="搜索题号、批次、引文"></div>
<div id="cards"></div></main><dialog id="player-dialog"><button id="close">关闭</button><h3 id="video-title"></h3><video id="player" controls></video></dialog>
<script id="data" type="application/json">""" + payload + """</script><script>
const items=JSON.parse(document.getElementById('data').textContent), cards=document.getElementById('cards');
const esc=s=>{const n=document.createElement('span');n.textContent=String(s??'');return n.innerHTML};
function render(){const tier=document.getElementById('tier').value,kind=document.getElementById('kind').value,q=document.getElementById('search').value.toLowerCase();cards.innerHTML='';for(const item of items){if(tier&&item.priority!==tier)continue;const issues=[...item.source_issues,...item.audio_issues].filter(x=>!kind||x.kind===kind);if(!issues.length)continue;if(q&&!JSON.stringify([item.external_key,item.batch_name,issues]).toLowerCase().includes(q))continue;const section=document.createElement('section');section.className='card';section.innerHTML=`<div class="head"><div><b>${esc(item.external_key)}</b> <span class="tag ${item.priority==='A'?'tierA':''}">${esc(item.priority)}级</span><p class="muted">${esc(item.batch_name)} · ${Math.round(item.duration_seconds)}秒 · 源码${item.source_issues.length}处 / 音频${item.audio_issues.length}处</p></div><button class="seek" data-id="${esc(item.item_id)}" data-time="0">播放视频</button></div>`+issues.map(x=>`<div class="issue"><b>${x.kind==='source'?'源码旁白缺漏':'成片疑似读错'}</b> · ${esc(x.category||'')} · ${esc(x.confidence||'待核')}${x.line?' · 源码第'+x.line+'行':''}<p class="source">原始旁白：${esc(x.source_quote)}</p>${x.asr_quote?'<p class="asr">ASR 转写：'+esc(x.asr_quote)+'</p>':''}${x.suggested_reading?'<p class="suggested">建议核对：'+esc(x.suggested_reading)+'</p>':''}<p>${esc(x.why)}</p><button class="seek" data-id="${esc(item.item_id)}" data-time="${Number(x.time_seconds||0)}">${x.time_seconds==null?'从头核听':'从 '+Number(x.time_seconds).toFixed(1)+' 秒核听'}</button></div>`).join('');cards.append(section)}}
document.querySelectorAll('.toolbar input,.toolbar select').forEach(x=>x.addEventListener('input',render));cards.addEventListener('click',e=>{const b=e.target.closest('button[data-id]');if(!b)return;const player=document.getElementById('player');document.getElementById('video-title').textContent=b.dataset.id;player.src='/media?item='+encodeURIComponent(b.dataset.id);player.onloadedmetadata=()=>{player.currentTime=Math.max(0,Number(b.dataset.time)-2);player.play().catch(()=>{})};document.getElementById('player-dialog').showModal()});document.getElementById('close').onclick=()=>{document.getElementById('player').pause();document.getElementById('player-dialog').close()};render();
</script></body></html>"""


def build(dataset: Path) -> dict:
    candidates = compile_candidates(dataset)
    output = dataset / "screening-review"
    output.mkdir(exist_ok=True)
    _csv(dataset, candidates)
    _package(dataset, candidates)
    total = len(json.loads((dataset / "manifest.json").read_text())["items"])
    (output / "report.html").write_text(_page(candidates, total), encoding="utf-8")
    (output / "candidates.json").write_text(
        json.dumps(candidates, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    counts = Counter(item["priority"] for item in candidates)
    summary = {"total": total, "candidate_videos": len(candidates),
               "priority_a": counts["A"], "priority_b": counts["B"],
               "source_videos": sum(bool(item["source_issues"]) for item in candidates),
               "audio_videos": sum(bool(item["audio_issues"]) for item in candidates),
               "audio_priority_a": sum(item["priority"] == "A" and bool(item["audio_issues"])
                                       for item in candidates)}
    (output / "summary.json").write_text(json.dumps(summary, ensure_ascii=False, indent=2) + "\n")
    return summary


def main() -> None:
    parser = argparse.ArgumentParser(description="Build TTS screening review report")
    parser.add_argument("--dataset", type=Path, required=True)
    args = parser.parse_args()
    print(json.dumps(build(args.dataset), ensure_ascii=False))


if __name__ == "__main__":
    main()
