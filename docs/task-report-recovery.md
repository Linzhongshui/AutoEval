# 任务报告与恢复归档

## 业务约束

一次任务一份正式报告（evaluation_report.run_id 保持唯一）。task-report.v2 内的 datasets 分别保存各数据集冻结参数、成绩、标准基线来源和证据引用；顶层 accuracy 为 null。原 gpqa-report.v1、planned-report.v1 继续可读。

原始状态事件、Case 尝试、UnifiedCollection 不改写。明确执行恢复完成操作时，追加 results_recovered 事件保存旧状态和旧数据集摘要，再更新当前状态与监控投影。result_archive_revision 追加保存恢复结果，记录父归档 UUID / SHA-256、原快照哈希、恢复原因、操作者、方法版本以及每份评分源文件的 SHA-256。修订表示对同一次执行的证据恢复，不新增测评尝试。

恢复要求终态任务、样本身份 / trial 名称 / 结束时间一致，两份原生 accuracy 一致且无执行异常。拒绝缺失、额外 trial、来源哈希不一致、修改原执行事实。Harbor 未知 token 保持 null。

报告发布显式选择修订 UUID，不自动取“最近一条”。同内容重复恢复 / 发布幂等。已有不同内容的正式报告时拒绝覆盖，不能用此命令替换已发布成绩；本次 a1452c45 尚无正式报告，可以首次生成恢复报告。原有 planned-report 失败摘要继续保留。

## 本地部署与恢复入口

先备份目标数据库和对象，再应用新增迁移：

```powershell
cd backend
uv run alembic upgrade head
```

迁移仅新增 result_archive_revision。迁移环境先注册 FK 依赖，修复从旧版本升级时 ORM DDL 推导出 NullType 的问题，不改写旧迁移。

由受保护文件提供本次 trial -> {result.json: 原文, verifier/reward.json: 原文} 映射，不能填写人工成绩。运行环境使用已有数据库 / S3 配置：

```text
python -m autoeval.reporting.recover_results RUN_UUID /protected/native-score-files.json --reason "原始评分证据因内联额度丢失，从同次 Harbor 产物恢复"
```

命令不启动执行器、不调用模型、不更新任务终态；从原始 raw_result 对象核对输入，先追加 AutomationBench 修订，再为任务所有数据集生成一份报告。事务失败时回滚数据库；已上传的内容寻址对象不会引用为有效报告，后续重试可复用。

## 查询和页面

- `/reports`、`/reports/{id}`：一任务一行，dataset_results 返回各数据集成绩及独立基线比较。
- `/evaluation-tasks/{id}/report`：优先读取正式任务报告；旧任务兼容原归档。
- `/runs/{id}/monitor/log?dataset_key=...`：按数据集查询日志，多数据集不传筛选返回 409，避免任取一份日志。
- `/runs/{id}/case-executions?dataset_key=...`：原始 Case 历史不变。
- `/runs/{id}/result-revisions` 和 `/runs/{id}/result-revisions/{revision}/cases`：显式查看恢复版本，支持分页、数据集、样本及状态筛选。
- 任务与报告页面均提供 Case 数据集筛选和原始 / 恢复证据切换；恢复证据展示父归档、文件哈希和来源，不伪造 Trace。
- 候选榜单按每个数据集的冻结条件独立分组；同一报告可包含多个数据集候选，无综合分。人工提名使用 `report-{报告UUID}:{dataset_key}` 区分同报告数据集，正式审批流程保持不变。

## 验证范围（2026-11-18）

本地 PostgreSQL 16.6：迁移通过；事务内恢复 / 发布、重复导入唯一性、拒绝覆盖正式报告、保留旧状态与归档通过，测试记录最终回滚。对象存储在此项数据库测试中使用受控替身。

本地浏览器：固定产物验证多数据集报告图表、Case 数据集筛选、恢复版本选择通过，无模型调用。服务器现有真实产物只读试算：600 条评分完整，1200 个评分文件哈希，349/600 = 58.1667%；未知 token 未填零。现已部署并写入正式恢复报告及两条已审批榜单；详见 [部署与恢复验收记录](task-report-recovery-deployment-2026-11-18.md)。
