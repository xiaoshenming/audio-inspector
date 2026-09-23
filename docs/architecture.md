# DEV-PB2 模块结构

核心包 `src/dev_pb2/` 只保留本轮 600 条样本实测需要的能力：

- `manifest.py`：一次筛查的资源输入校验；
- `qwen_asr.py`：最终视频音轨的分段 ASR 与时间点；
- `semantic_review.py`：最终源码旁白缺漏、源码与实际读法差异；
- `literal_asr.py` / `literal_reading.py`：函数记号被机械念出括号的定向补查；
- `screening_report.py`：证据归并和候选清单；
- `pipeline.py`：独立运行与 `clean/candidate/failed_open` 合同；
- `decisions.py`：管理员通过或确认修复后的确定性命令；
- `synthetic_*`：600 条合成样本构造、TTS 生成与量化；
- `review_server.py`：可选的原有人工核听页，不承担 BatchOps 正式交付动作。

数据目录按输入指纹创建，每个阶段逐条保存 JSON，可续跑；视频、源码、模型结果和人工命令用 revision 与 SHA 关联。证据不完整时输出 `failed_open`，不把未检测解释成正常。筛查器不修改视频、源码或 BatchOps 的工作流状态。

正式视频重做建议使用确定性 BatchOps 编排，参见[接入合同](batchops-integration.md)。历史多音字声学检测、通用 MFA 分析和旧 CLI 已从 DEV-PB2 当前代码移除，但仍可在本仓库 Git 历史的 `main` 分支追溯。
