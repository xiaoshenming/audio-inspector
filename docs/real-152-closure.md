# 152 条真实样本中的一条：DEV-PB2 隔离闭环

2026-09-23 从此前 152 条最终配音视频中选取 `2b03c87a-f33e-4b06-b57a-d39ec241bc0a`，在 B2B 服务器的 `/opt/mathpi/dev-pb2-closure` 与 `/var/lib/mathpi/dev-pb2-closure` 隔离目录运行。没有修改原 BatchOps 客户任务、原视频或线上复审站。

## 模块实际执行

1. `dev-pb2 inspect` 对原 19.900 秒 MP4、配音时的最终源码和字幕运行 Qwen ASR、DeepSeek 源码审查、DeepSeek 音频审查、定向字面读法补查。5 个阶段全部完成；返回 `candidate`，A 级源码缺对象 1 处。
2. 题干是“平面向量 a、b 不共线”；原源码旁白和 ASR 均为“已知向量与 b 不共线”。管理员确认新文为“已知向量 a 与 b 不共线”。`dev-pb2 decide` 输出带旧 revision、视频/源码 SHA、管理员和幂等键的修复命令。
3. `dev-pb2-close-loop` 从原源码包仅替换这句已批准旁白，保存新源码包；用 B2B 同款 Qwen Audio TTS 重配第 1 条字幕所对应的完整句子，按 5.564 秒原时间窗以约 1.048 倍速度轻微对齐；保持原画面，更新 SRT 并重新烧字幕，生成完整 MP4。
4. 重新对修复后的 MP4 与源码运行全部筛查：源码候选 0、音频候选 0，结果 `clean`。Qwen ASR 首句已包含“已知向量 a 与 b 不共线”。

## 成片核验

| 项目 | 原版 | 修复后 |
|---|---:|---:|
| 时长 | 19.900 秒 | 19.900 秒 |
| 视频轨 | H.264 | H.264 |
| 音频轨 | AAC | AAC |
| 旁白 / 字幕首句 | 缺 `a` | 包含 `a` |

修复后 MP4 与新源码的 SHA 均与模块回执一致。第一次成片校验发现原音轨比画面短约 2 秒，FFmpeg 的 `-shortest` 截断了尾画面；模块修复了按原画面时长补齐音轨的编排问题，复跑时复用了已生成的 TTS 音频，没有再次请求。

本例使用已有的未烧字幕原片，属于**局部重配音并重合成完整视频**，无需启动 Manim 子节点。它证明此类时间窗清楚、文字改动很小的问题可以在独立模块里闭环；对于画面需改变、没有未烧字幕原片、音频时长差异过大的样本，仍需接 BatchOps 最新渲染子节点做完整场景重渲染。该通道尚未接线，不得把本次结果外推为所有 152 条都能自动修复。

本地可播放文件与详细回执位于 Git 忽略的 `input/real-152-closure-20260923/`。B2B 服务器隔离回执位于 `/var/lib/mathpi/dev-pb2-closure/closure-2b03/closure.json`；没有向客户发布。

## 2026-09-24：按独立会话接口重走管理员循环

用新 `dev-pb2-cycle` 接口在 B2B 隔离目录对同一原始样本执行 `start → decide approve_repair → status → decide accept_as_is`，没有人工改写源码文件或手工合成视频。第一次状态为 `awaiting_admin/candidate`，问题仍是漏读向量 a；管理员动作指定“已知向量 a 与 b 不共线”。模块自动生成新的 19.900 秒完整 MP4，源码、字幕都包含批准的文字，TTS 回执记录了 1 段重配音，复筛为 `clean`。**复筛 clean 后的会话仍处于 `awaiting_admin`，未自动放行**；第二次管理员动作才使其成为 `release_ready`。最终文件存在，视频 SHA 与放行建议一致；正式客户交付没有执行。

会话与全部证据位于 `/var/lib/mathpi/dev-pb2-closure/review-cycle-2b03/cycle.json`、`round-1/repaired/`，可以用 `dev-pb2-cycle status --session /var/lib/mathpi/dev-pb2-closure/review-cycle-2b03` 读取简明状态。该实例只证明“发现 → 人工改文 → 重配完整视频 → 复筛 → 再人工确认”的接口闭环；其他样本仍需按其资源选择局部重配音或子节点重渲染。
