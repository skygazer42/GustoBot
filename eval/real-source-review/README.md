# 真实菜谱来源验收草稿

这份草稿从项目现有 `data/recipe.json` 选取 48 份真实记录，整理为 240 个问题。它补充原有受控测试集，**尚未经过人工业务核对，也不是验收通过的证明**。所有题目的 `truth` 均为 `manual_unverified`，不会参与已批准业务指标。

可先打开[人工核对表](REVIEW.md)，按菜谱查看问题和程序草稿。`questions.jsonl` 使用现有评测工具的格式；`real_sources.json` 保存选中记录的原文、正式对象 ID、关系和引文；`review.jsonl` 按题关联来源记录行号、内容 hash、语义请求、当前程序给出的草拟答案及待填写的核对结果。`manifest.json` 固定来源文件、本体版本和各文件 hash。原始菜谱及已有受控保留集未改动。

问题涵盖食材用量、辅助用料、来源耗时、做法步骤，以及来源声明的菜系／工艺／口味，包含佛跳墙与数量未知、不可比较的记录。题目中的“这份来源”指 manifest 中选定的做法版本；问题的对象 ID 不能用相同菜名的其他版本代替。

准备过程中，每份记录都执行现有映射、正式身份绑定、实际 SHACL 与证据检查；合并的 48 份候选来源也通过正式输入校验。草拟答案来自同一个业务运行时，因此它们只能帮助核对，不能作为独立正确性证明。没有调用生成模型、embedding 或数据库。

## 核对方式

将 `review.jsonl` 复制成工作文件，逐题对照 `source_evidence` 和 `real_sources.json` 中的原始记录。确认菜名对应的具体做法、食材范围、数量及单位、时长口径和步骤是否正确；“适量”保持定性，来源未记录的内容保持未知。修改答案或指标口径时同时修正期望对象、来源、状态和定量字段。

完成后由业务核对人记录姓名／标识、日期及修正后的 `verified_expected`。以新的数据集版本发布核对通过的题目，标为 `human_verified`，重新计算 manifest，而不要把当前草稿直接改成“已批准”。若仍有未核对题目，继续保留 `manual_unverified`。

实际模型评测还需要选定 LLM、embedding 部署修订，并将对应来源导入隔离评测环境。按[评测工具说明](../knowledge/README.md)运行 off／shadow／on、人工复核和准入工件导出。当前草稿不能用于导出已批准校准策略。

只检查格式和待验收状态时，可运行以下不访问模型或数据库的命令：

```powershell
.venv\Scripts\python.exe scripts/evaluate_knowledge.py --mode qa --scope recipes --dataset eval/real-source-review/questions.jsonl --output docs/evaluation/real-source-dry-run --dry-run
```
