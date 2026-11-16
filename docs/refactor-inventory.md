# 重构盘点：模块职责、契约与回归基线

> 阶段一产物。后续阶段完成对应批次后更新此文档。日期：2026-11-16。

## 一、回归基线（阶段一起点）

| 检查 | 结果 |
|---|---|
| `uv run ruff check .` | 通过（修复 migrations/env.py 一处 import 排序后） |
| `uv run pytest -q`（默认模式） | 302 passed, 121 skipped |
| `npm run typecheck` | 通过 |
| `npm run build` | 通过（CSS 96.6 kB / JS 453.7 kB） |

说明：121 项跳过为 AE_INFRA_TEST、AE_SSH_SIM_TEST、AE_BROWSER_LIVE_TEST 等条件门控的专项，不计为通过也不计为失败。补齐 response_model 后全量测试与基线一致（302 passed, 121 skipped）。

## 二、后端路由 → 目标模块映射（96 路由 / 23 router）

| 目标模块 | 现有文件（router 前缀 / 路由数） |
|---|---|
| evaluation | evaluation_tasks.py（`/evaluation-tasks`，6）、evaluations.py（`/runs`，6）、runs.py（`/diagnostics/runs`，4）、task_monitor.py（`/runs/{id}/monitor*`，4）、monitored_execution.py（`/aisbench-monitored`，3，dev 门控）、fixture_pipeline.py（`/diagnostics/unified-fixture`，1，dev 门控）、evaluation_activity.py、orchestration.py、run_activities.py（无路由） |
| planning | planning.py（`/planning`，17）、planning_engine.py、planning_worker.py、planning_observations.py、planning_runtime.py、planning_transport.py、probe_dispatch.py（无路由） |
| catalog | standard_inputs.py（`/standard-inputs`，10）、datasets.py（`/dataset-manifests`，3）、registry.py（`/models`，6）、profiles.py（`/profiles`，2）、configuration.py（`/test-configs`，3）、benchmarks.py、dataset_identity.py、adaptor_bridge.py、adaptor_versions.py、import_* 脚本、register_automationbench.py |
| resources | targets.py（`/credentials|/target-bindings|/targets`，6）、resources.py（`/resources`，3）、ssh_resources.py（`/ssh-resources`，4）、execution_transport.py、monitor_transport.py |
| reporting | reports.py（`/reports`，3）、case_history.py（`/runs/{id}/case-executions` + `/case-executions`，2）、unified_outputs.py（`/runs/{id}/unified-output`，1）、leaderboards.py（`/leaderboard`，1）、data_workbench.py（`/data-workbench`，5）、report_integrity.py、unified_activity.py、unified_artifacts.py、native_case_evidence.py、export_trial.py |
| analysis | analysis.py（`/reports/{id}/analysis*`，3）、analysis_activity.py、analysis_runtime.py、scan_result_analyze.py、trial_analysis_schema.py |
| infrastructure / 共享 | api.py（应用工厂 + health/capabilities，3）、db.py、secrets.py、config.py、dispatcher.py、worker.py、reconciler.py、bootstrap.py、backup.py、cleanup.py、audit.py（`/audit-events`，1）、langfuse_integration.py（`/runs/{id}/traces`，2）、job_runtime.py、native_request_runtime.py、migrate_storage.py、models.py（Base/Record + 4 核心表）、domain.py、contracts.py、aisbench_native.py、ssh_executor.py、ssh_native.py、docker_executor.py、dsh_agent.py、repair_gpqa_evidence.py、native_smoke.py、import_gpqa.py、native_predictions.py、native_case_evidence.py |

阶段二实施时归属存疑的文件（monitored_*、docker_executor、langfuse_integration 等）按"路由归属 + ORM 表归属 + 依赖方向"就近判定，并回填本表。

### 已知耦合点

- `evaluation_tasks.py` 6 处路由互调（submit→planning.submit_run、detail→evaluations.detail + planning.run_detail、report→planning.run_report / evaluations.report_evidence、cleanup→evaluations.retry_cleanup）。
- `planning.py`（863 行）混合 ORM 2 表 + 17 路由 + 共享辅助（resolve_inputs / current_preflight / selection_identity / envelope），被 api.py、evaluation_tasks.py、orchestration.py、planning_worker.py、migrations/env.py 及 6 个测试依赖。
- 33 张 ORM 表散布 19 个模块；migrations/env.py import 22 个模块注册元数据。
- 事务统一走 `async with sessions() as session, session.begin()`（87 处），显式 commit 仅 targets.py:156。

## 三、前端手写类型盘点（63 处 / 27 文件）

无 OpenAPI 生成前的重复定义（阶段一后由 `src/types/api.ts` 生成类型覆盖接口响应）：

| 类型名 | 重复处 | 形状是否一致 |
|---|---|---|
| `Config` | services/evaluation.ts、components/ExecutionBindings.tsx、components/ModelRegistry.tsx | 不一致（各自子集） |
| `Target` | services/evaluation.ts、ExecutionBindings.tsx、ModelRegistry.tsx | 不一致 |
| `Resource` | services/evaluation.ts、ExecutionBindings.tsx、ModelRegistry.tsx | 不一致 |
| `Snapshot` | components/EvaluationRuns.tsx、components/RunMonitor.tsx | 语义不同（运行快照 vs 监控快照），不合并 |
| `Report` | components/TaskPlanning.tsx、app/ReportView.tsx | 语义不同（估算报告 vs 证据报告），不合并 |
| `Run`/`Detail` | components/EvaluationRuns.tsx、components/DiagnosticTasks.tsx | 语义不同（测评任务 vs 诊断任务） |

处理原则：与生成类型（`components["schemas"]`）重合的响应结构删除手写定义并引用生成类型；语义不同的同名类型保留但重命名区分（阶段三执行）。

## 四、契约与生成流程

- 后端导出：`backend/` 下 `uv run python scripts/export_openapi.py` → `backend/openapi.json`（纳入版本管理，作为契约快照）。
- 前端生成：`frontend/` 下 `npm run generate:api` → `src/types/api.ts`（纳入版本管理）。
- 契约差异检查：`git diff backend/openapi.json`。
- 工具版本：`openapi-typescript` 7.13.0（package-lock 锁定）。

## 五、历史与外部入口标注（重构不得破坏）

- 旧链接跳转：`#planned-run/{id}` → 重定向 `#run/{id}`（App.tsx）；`#evaluate?…` → 重定向控制台。
- 旧接口：`/api/autoeval/v1/planning/runs*` 仍被前端 EvaluationRuns/历史书签使用；`evaluations.py`（`/runs`）与 `runs.py`（`/diagnostics/runs`）分别为正式与诊断入口。
- `backend/scripts/`：import_latest_official.py、import_mainstream_official.py、import_official_modelscope.py、import_deepswe.py、import_expanded_families.py、enrich_deepswe_metadata.py、start_probe_worker.py、export_openapi.py（本次新增）。
- Dev/Test 门控路由：monitored_execution、fixture_pipeline、data_workbench（仅 development/test 环境）。
- 后台进程入口（均有 `__main__`）：dispatcher.py、worker.py（9 角色）、reconciler.py、planning_worker.py、monitored_runtime.py、analysis_runtime.py。
