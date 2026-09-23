const state={items:[],reviews:[],selected:null,reviewer:localStorage.getItem("audio-screening-reviewer")||""};
const label={correct:"正确",missing:"漏字",incorrect:"不正确",uncertain:"待定"};
const reviewer=document.querySelector("#reviewer");reviewer.value=state.reviewer;
reviewer.addEventListener("change",()=>{state.reviewer=reviewer.value.trim();localStorage.setItem("audio-screening-reviewer",state.reviewer);render()});
for(const id of ["tier","verdict","kind","search"])document.querySelector(`#${id}`).addEventListener("input",renderItems);

function myReview(target){return state.reviews.find(x=>x.target_id===target&&x.reviewer===state.reviewer)}
function node(tag,className,text){const value=document.createElement(tag);if(className)value.className=className;if(text!==undefined)value.textContent=String(text);return value}
function metrics(){const a=state.items.filter(x=>x.priority==="A").length;const done=state.items.filter(x=>myReview(`video:${x.item_id}`)).length;
  document.querySelector("#metrics").replaceChildren(...[["候选视频",state.items.length],["A 级优先",a],["我已判断视频",done],["未判断",state.items.length-done]].map(([name,count])=>{const box=node("div","metric");box.append(node("span","",`${name} `),node("b","",count));return box}))}
function visible(item){const tier=document.querySelector("#tier").value,verdict=document.querySelector("#verdict").value,kind=document.querySelector("#kind").value,q=document.querySelector("#search").value.trim().toLowerCase();
  const mine=myReview(`video:${item.item_id}`)?.verdict||"pending";
  if(tier&&item.priority!==tier||verdict&&mine!==verdict||kind&&!item[`${kind}_issues`]?.length)return false;
  return !q||JSON.stringify([item.external_key,item.batch_name,item.source_issues,item.audio_issues]).toLowerCase().includes(q)}
function renderItems(){const root=document.querySelector("#items");root.replaceChildren();let count=0;
  for(const item of state.items){if(!visible(item))continue;count++;
    const button=node("button",`item ${item.item_id===state.selected?"active":""}`);
    button.append(node("strong","",item.external_key),node("small","",`${item.batch_name} · ${Math.round(item.duration_seconds)} 秒 · `));
    button.append(node("span",`tag ${item.priority==="A"?"a":""}`,`${item.priority} 级`));
    const verdict=myReview(`video:${item.item_id}`)?.verdict;
    if(verdict)button.append(node("span",`tag ${verdict}`,` ${label[verdict]}`));
    button.addEventListener("click",()=>{state.selected=item.item_id;renderItems();renderDetail()});root.append(button)}
  if(!count)root.append(node("p","empty","当前筛选下没有视频"))}
function actionBox(item,target){const box=node("article","review-target");box.dataset.target=target;
  const mine=myReview(target);const note=node("textarea");note.placeholder="记录听到的内容或判断依据（选填）";note.value=mine?.note||"";box.append(note);
  const actions=node("div","actions");for(const [value,title] of Object.entries(label)){
    const button=node("button",mine?.verdict===value?"selected":"",title);button.type="button";
    button.addEventListener("click",()=>save(item,target,value,box));actions.append(button)}
  const saved=node("span","saved",mine?`已保存：${label[mine.verdict]} · ${mine.reviewer}`:"");actions.append(saved);box.append(actions);return box}
function issueCard(item,issue){const box=actionBox(item,issue.issue_id);const head=node("h3","",`${issue.kind==="source"?"原始旁白缺漏":"成片疑似读错"} · ${issue.category||""}`);box.prepend(head);
  box.insertBefore(node("p","issue-meta",`${issue.line?`源码第 ${issue.line} 行 · `:""}${issue.confidence||"待核"} · 自动候选，须人工听/看`),box.querySelector("textarea"));
  box.insertBefore(node("p","source-text",`原始旁白：${issue.source_quote||""}`),box.querySelector("textarea"));
  if(issue.asr_quote)box.insertBefore(node("p","asr-text",`ASR 转写：${issue.asr_quote}`),box.querySelector("textarea"));
  if(issue.suggested_reading)box.insertBefore(node("p","suggested",`建议核对读法：${issue.suggested_reading}`),box.querySelector("textarea"));
  if(issue.why)box.insertBefore(node("p","",issue.why),box.querySelector("textarea"));
  const seek=node("button","seek",issue.time_seconds==null?"从头播放":`跳到 ${Number(issue.time_seconds).toFixed(1)} 秒核听`);
  seek.type="button";seek.addEventListener("click",()=>seekTo(issue.time_seconds||0));box.insertBefore(seek,box.querySelector("textarea"));return box}
function renderDetail(){const item=state.items.find(x=>x.item_id===state.selected),root=document.querySelector("#detail");root.replaceChildren();if(!item){root.append(node("div","empty","请选择左侧一条视频开始复审。"));return}
  const playerBox=node("div","player-box"),head=node("div","detail-head"),info=node("div");info.append(node("h2","",item.external_key),node("p","",`${item.batch_name} · ${item.priority} 级 · ${Math.round(item.duration_seconds)} 秒`));head.append(info);playerBox.append(head);
  const video=node("video");video.id="player";video.controls=true;video.preload="metadata";video.src=`/media/${encodeURIComponent(item.item_id)}.mp4`;playerBox.append(video,node("p","hint","点击下方时间按钮可跳到问题前约 2 秒。红字是源码原文，橙字是 ASR 候选；请以实际听到的视频为准。"));root.append(playerBox);
  const overall=actionBox(item,`video:${item.item_id}`);overall.prepend(node("h3","","整条视频的结论"));root.append(overall);
  if(item.triage_note)root.append(node("p","hint",`交叉核对：${item.triage_note}`));
  for(const issue of [...item.source_issues,...item.audio_issues])root.append(issueCard(item,issue))}
function seekTo(seconds){const player=document.querySelector("#player");if(!player)return;const jump=()=>{player.currentTime=Math.max(0,Number(seconds)-2);player.play().catch(()=>{})};if(player.readyState>=1)jump();else player.addEventListener("loadedmetadata",jump,{once:true});player.scrollIntoView({behavior:"smooth",block:"center"})}
async function save(item,target,verdict,box){if(!state.reviewer){alert("请先填写评审人姓名");reviewer.focus();return}
  const note=box.querySelector("textarea").value.trim();const response=await fetch("/api/reviews",{method:"POST",headers:{"Content-Type":"application/json"},body:JSON.stringify({item_id:item.item_id,target_id:target,reviewer:state.reviewer,verdict,note})});
  const body=await response.json();if(!response.ok){alert(body.error||"保存失败");return}
  state.reviews=state.reviews.filter(x=>!(x.target_id===target&&x.reviewer===state.reviewer));state.reviews.push(body.review);
  box.querySelectorAll(".actions button").forEach(button=>button.classList.toggle("selected",button.textContent===label[verdict]));
  box.querySelector(".saved").textContent=`已保存：${label[verdict]} · ${state.reviewer}`;metrics();renderItems()}
function render(){metrics();renderItems();renderDetail()}
fetch("/api/state",{cache:"no-store"}).then(async response=>{if(!response.ok)throw new Error(response.status===401?"请先登录 B2B 8085 管理后台":"加载失败");return response.json()})
  .then(data=>{state.items=data.items;state.reviews=data.reviews;state.selected=data.items[0]?.item_id||null;render()})
  .catch(error=>{document.querySelector("#detail").replaceChildren(node("div","error",String(error)))})
