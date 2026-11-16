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

阶段二各批次完成后均为 304 passed / 121 skipped（新增 2 个后端边界测试），`openapi.json` 零差异，37 张 ORM 表注册完整。

阶段三验证（2026-11-16）：`npm run typecheck`、`npm run build`（CSS 96.64 kB / JS 454.06 kB）、`npm run check:boundaries`（60 文件）通过；浏览器检查 `AE_BROWSER_TEST=1` 结果 11 passed / 5 failed / 9 skipped，失败集合与阶段一基线完全相同（standard_inputs、mocked_flows×3、unified_output），非本次改动引入。

## 二、后端路由 → 目标模块映射（96 路由 / 23 router）

| 目标模块 | 现有文件（router 前缀 / 路由数） |
|---|---|
| evaluation | **批次 A 已部分子包化**：`evaluation/`（models.py：EvaluationReport/DatasetExecution/CapacityLease；service.py：提交/预检/查询服务；orchestration.py：执行循环），evaluation_tasks.py 与 evaluations.py 路由保留顶层并改为调用 evaluation.service（6 处路由互调已消除）。其余（runs.py（`/diagnostics/runs`，4）、task_monitor.py（`/runs/{id}/monitor*`，4）、monitored_execution.py（dev 门控）、fixture_pipeline.py（dev 门控）、evaluation_activity.py、run_activities.py）待阶段四就近归位 |
| planning | **批次 A 已子包化**：`planning/`（routes.py：17 路由；models.py：PlanningArtifact/PlanningJob），共享辅助（resolve_inputs / current_preflight / selection_identity / artifact 等）归 evaluation.service 并由 planning 兼容再导出。planning_engine.py、planning_worker.py、planning_observations.py、planning_runtime.py、planning_transport.py、probe_dispatch.py 待阶段四就近归位 |
| catalog | **批次 B 已子包化**：`catalog/`（models.py 含 9 张 ORM 表 + datasets/registry/profiles/configuration/benchmarks/dataset_identity/adaptor_bridge/adaptor_versions 路由与纯逻辑 + import_* 与 register_automationbench CLI，旧顶层文件保留兼容 shim；`python -m autoeval.import_*`、`-m autoeval.register_automationbench` 入口不变）。standard_inputs.py（`/standard-inputs`，10）因外部并行修改暂留顶层，待其落地后再迁入 |
| resources | **批次 B 已子包化**：`resources/`（models.py 含 5 张 ORM 表 + targets/docker_bindings/ssh_resources 路由 + execution_transport/monitor_transport，旧顶层文件保留兼容 shim（批次 D 删除了与包同名的 resources.py 死文件）。ssh_resources 原 `Path(__file__).with_name("aisbench_native.py")` 改为按包根解析，哈希对象文件不变 |
| reporting | **批次 C 已子包化**：`reporting/`（models.py 含 4 张 ORM 表：CaseExecutionRecord/UnifiedCollection/UnifiedArtifact/LeaderboardRecord + reports/case_history/unified_outputs/leaderboards/data_workbench 路由 + report_integrity/native_case_evidence 纯逻辑 + unified_activity 活动 + export_trial CLI，旧顶层文件保留兼容 shim；`python -m autoeval.export_trial` 入口不变） |
| analysis | **批次 D 已子包化**：`analysis/`（models.py：ReportAnalysis；routes.py：3 路由与输入/输出校验；activity.py：分析活动；scan_result_analyze.py、trial_analysis_schema.py，旧顶层同名文件改为别名 shim；`python -m autoeval.scan_result_analyze` 入口不变）。analysis_runtime.py 为进程入口暂留顶层 |
| infrastructure / 共享 | **批次 D 已部分子包化**：`infrastructure/`（config/db/secrets/domain/contracts/audit/cleanup 库模块 + bootstrap/backup/job_runtime/native_request_runtime/migrate_storage 脚本，旧顶层同名文件改为别名 shim，`python -m autoeval.bootstrap/migrate_storage/backup/job_runtime/native_request_runtime` 入口不变）。暂留顶层：api.py（应用工厂 + health/capabilities）、models.py（Base/Record + 4 核心表）、responses.py；进程入口 dispatcher.py、worker.py（9 角色）、reconciler.py（阶段四集中角色配置）；langfuse_integration.py 与 standard_inputs.py（外部并行修改）；aisbench_native.py（内容哈希被 SSH 原生桥固定，移动会改变已登记摘要）；ssh_executor/ssh_native/docker_executor/dsh_agent、repair_gpqa_evidence/native_smoke/import_gpqa、native_predictions、evaluation_activity/run_activities/workflows、runs/task_monitor/monitored_*、fixture_pipeline、planning_engine/planning_worker/planning_observations/planning_runtime/planning_transport/probe_dispatch 待后续批次或阶段四就近归位 |

阶段二实施时归属存疑的文件（monitored_*、docker_executor、langfuse_integration 等）按"路由归属 + ORM 表归属 + 依赖方向"就近判定，并回填本表。

### 已知耦合点

- `evaluation_tasks.py` 6 处路由互调（submit→planning.submit_run、detail→evaluations.detail + planning.run_detail、report→planning.run_report / evaluations.report_evidence、cleanup→evaluations.retry_cleanup）。
- `planning.py`（863 行）混合 ORM 2 表 + 17 路由 + 共享辅助（resolve_inputs / current_preflight / selection_identity / envelope），被 api.py、evaluation_tasks.py、orchestration.py、planning_worker.py、migrations/env.py 及 6 个测试依赖。
- 33 张 ORM 表散布 19 个模块；migrations/env.py import 22 个模块注册元数据。
- 事务统一走 `async with sessions() as session, session.begin()`（87 处），显式 commit 仅 targets.py:156。

## 三、前端结构与类型盘点

阶段三已完成 `app / features / shared` 重组（2026-11-16）：

| 目录 | 内容 |
|---|---|
| `app/` | App.tsx（hash 路由、导航、布局、toast/Overview） |
| `features/evaluation/` | types.ts / logic.ts / hooks.ts / submitIntent.ts、EvaluationRuns、EvaluationConsole、RunMonitor、DiagnosticTasks、FixturePipeline、SubmissionReview、ProbeProgress |
| `features/catalog/` | Configurations、DatasetTree、ParameterCards、StandardInputs、DatasetManifests、ModelRegistry、Workbench*、AdapterFields、CustomAdapterEditor、数据集元数据与 identity 转换 |
| `features/resources/` | ServiceBindings、SSHResources、ModelServices |
| `features/reporting/` | ReportView、RealReports、RealLeaderboard、CaseHistory、DataWorkbench、AnalysisPanel、ReportCharts、UnifiedOutputSummary |
| `features/planning/` | TaskPlanning（估算/探测/建议/提交区块仍在同一文件的 6 个区块内） |
| `shared/` | api.ts（请求层）、types/api.ts（OpenAPI 生成）、types/domain.ts、hooks/useRequest.ts、hooks/usePolling.ts、status.ts（任务/数据集/证据/有效性/清理状态映射）、constants.ts、ui/*（分页、抽屉、提示等基础控件） |

- 提交意图与幂等键：`features/evaluation/submitIntent.ts`，sessionStorage key 仍为 `autoeval.pending-exploration.v1`。
- 轮询统一走 `usePolling`：上次请求完成后才调度下一次、页面隐藏暂停并在恢复可见时立即刷新；任务详情进入终态停止；列表请求变化用世代号丢弃过期响应。
- 边界检查：`npm run check:boundaries`（shared 不得依赖 features/app；features 不得依赖 app；手写类型不得重定义生成的 schema 名）。
- 原 `components/`、`services/`、`types/`、`layouts/AppLayout.tsx`（死代码）已移除。

阶段一前的重复定义（现由生成类型与域类型统一）：

| 类型名 | 原重复处 | 处理 |
|---|---|---|
| `Config` | services/evaluation.ts、ExecutionBindings.tsx、ModelRegistry.tsx | 统一 `features/evaluation/types.ts` 中生成类型别名 |
| `Target`/`Resource` | services/evaluation.ts、ExecutionBindings.tsx、ModelRegistry.tsx | 统一 `features/evaluation/types.ts`（后端暂无响应模型） |
| `Snapshot` | EvaluationRuns.tsx、RunMonitor.tsx | 语义不同，分别命名为 `RunSnapshot` 与监控 `Snapshot` |
| `Report` | TaskPlanning.tsx、app/ReportView.tsx | 语义不同（估算报告 vs 证据报告），未合并 |
| `Run`/`Detail` | EvaluationRuns.tsx、DiagnosticTasks.tsx | 语义不同，分别命名 `Run`/`RunDetail` 与诊断 `Run`/`Detail` |
| `Bundle` | catalog/StandardInputs.tsx | 与生成 schema 同名但形状不同 → 重命名 `StandardBundleView` |

## 四、契约与生成流程

- 后端导出：`backend/` 下 `uv run python scripts/export_openapi.py` → `backend/openapi.json`（纳入版本管理，作为契约快照）。
- 前端生成：`frontend/` 下 `npm run generate:api` → `src/shared/types/api.ts`（纳入版本管理）。
- 契约差异检查：`git diff backend/openapi.json`。
- 工具版本：`openapi-typescript` 7.13.0（package-lock 锁定）。

## 五、历史与外部入口标注（重构不得破坏）

- 旧链接跳转：`#planned-run/{id}` → 重定向 `#run/{id}`（App.tsx）；`#evaluate?…` → 重定向控制台。
- 旧接口：`/api/autoeval/v1/planning/runs*` 仍被前端 EvaluationRuns/历史书签使用；`evaluations.py`（`/runs`）与 `runs.py`（`/diagnostics/runs`）分别为正式与诊断入口。
- `backend/scripts/`：import_latest_official.py、import_mainstream_official.py、import_official_modelscope.py、import_deepswe.py、import_expanded_families.py、enrich_deepswe_metadata.py、start_probe_worker.py、export_openapi.py（本次新增）。
- Dev/Test 门控路由：monitored_execution、fixture_pipeline、data_workbench（仅 development/test 环境）。
- 后台进程入口（均有 `__main__`）：dispatcher.py、worker.py（9 角色）、reconciler.py、planning_worker.py、monitored_runtime.py、analysis_runtime.py。

## 六、阶段四：样式与执行基础设施

**样式**：`src/app/app.css`（4112 行）拆为 `src/styles/` 下五个文件，`index.css` 按原顺序 `@import`，选择器与顺序不变（构建产物体积一致：CSS 96.64 kB）。残留在业务组件内的全局类名未改为 CSS Modules，以保持当前视觉一致；分页组件保留两套协议（offset 与页码），外观类名维持现状。

**状态词汇**：`infrastructure/domain.py` 集中 RunState 迁移表、`RUN_TERMINAL`、`DatasetState` 与 `DATASET_ACTIVE`/`DATASET_TERMINAL`、`ScoringStatus`、`EvidenceStatus`；对外字符串值不变，`evaluation/orchestration.py` 与 `evaluation/service.py` 已改用常量。前端对应 `shared/status.ts`。

**执行角色**：`worker.py` 的 9 个 Temporal 角色集中到 `role_options(settings)` 单表，`--role` 选项由该表派生；文档说明每个角色的队列、工作流/活动边界与依赖（Temporal、数据库、对象存储、执行资源）。

**日志**：API 中间件每条请求记录 `request_id`、方法、路径与状态码；既有进程日志保留 `run=` 等标识。凭据、提示词与模型原文不进入日志。
