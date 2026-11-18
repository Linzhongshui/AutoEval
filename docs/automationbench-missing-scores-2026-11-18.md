# AutomationBench 577 条评分缺失排查（2026-11-18）

任务：a1452c45-8416-4f6f-b9d5-2c22610b848a；子执行：c2716a4e-94ac-49a8-95c2-0e24c5d2a1e7。
本次只读检查，没有调用模型、重跑验证器、修改历史结果或入榜。

## 已确认事实

- 归档的原始适配器输出包含 600 条记录，顶层 case.score 全部为 null。
- 其中 23 条携带 result.json、verifier/reward.json 等原生证据；14 条 accuracy=1，9 条 accuracy=0。另 577 条 harbor_artifact.files 为空。
- 平台 result_identity.apply_automationbench_accuracy 仅在两份原生评分文件一致时恢复 accuracy，因此归档可评分数为 23。
- 远端本次子执行 output 下仍有 600 份 Harbor trial result.json。每份均无 exception_info，且 result.json 的 verifier_result.rewards.accuracy 与 verifier/reward.json 一致：349 条为 1，251 条为 0。
- 文件总大小：result.json 3,118,302 bytes；reward.json 13,200 bytes；trajectory.json 307,675,819 bytes。

## 原因

planning_runtime.py 为所有 case 共用约 12MiB 的内联证据额度，将轨迹与评分证据放在同一包；超过额度时整个 case 的 files 置空。约 293MiB 的轨迹挤占额度，导致 577 条评分凭证未回收。与此同时适配器没有把命名 accuracy 指标写入 case.score，平台只能依赖已携带的文件恢复评分。

这不是 577 条验证器没有产出评分；也不能把记录执行成功等同于答题正确。
远端原生结果的诊断性汇总为 349/600=58.1667%；尚未完成全部身份、对象哈希及正式报告重建，不能当作已入榜成绩。

## 建议修复与恢复

1. 评分小文件与大轨迹分开回收；优先确保所有 case 的 result.json 和 reward.json，轨迹独立对象归档并记录哈希/缺失原因。
2. 在适配器中按明确的 AutomationBench accuracy 规则输出命名评分，不对其他奖励指标泛化取值；保留原始证据与转换版本。
3. 保全本次原生文件，核对 600 个样本身份、尝试与哈希后，从现有产物创建可追溯恢复记录，不重跑付费模型，不覆盖历史 partial 记录。
4. 补充超过 12MiB 的多 case 回收回归测试，验证不会因轨迹截断丢失评分。
