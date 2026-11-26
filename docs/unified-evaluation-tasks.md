# 统一测评任务与 Planner 辅助能力

## 业务与职责

平台只有测评任务，一次任务包含一个或多个数据集。控制台保留一个发起表单，GPQA Lite 通过数据集样本范围选择；不再设快速验证或编排任务入口。平台负责资源预检、顺序、并发、持久化工作流、结果归档及清理。

Task Planner 仅用于估算耗时和建议执行顺序、数据集并发及 case 并发。估算缺少依据时不补造实测值；建议展示可信度、来源、版本、调整前后差异，需显式采纳。采纳只修改待提交表单，旧估算失效，随后重新预检；不保存执行任务、不调用模型。未估算、Planner 不可用均不妨碍通过执行预检的任务提交。

默认可以从任务管理列表续跑取消后剩余的样本，也可以在任务详情从数据集进入 Case 列表并只重试所选样本。执行失败和零分的 Case 优先显示。两种操作都要求显式确认，并保留原尝试和报告版本。接口、上线顺序与验收记录见 [R12 取消后续跑测评与单 Case 重试](evaluation-task-resume.md)。

## 新接口

统一前缀 `/api/autoeval/v1/evaluation-tasks`：

| 操作 | 接口 | 约定 |
| --- | --- | --- |
| 提交 | `POST /evaluation-tasks` | `Idempotency-Key` 必填；同键同内容返回已有运行，内容变化返回409 |
| 列表 | `GET /evaluation-tasks` | `offset/limit`，`state`（含 `active`）、`resource_kind`、`query` 全量筛选；`statistics` 与筛选一致，分页不改变统计 |
| 详情 | `GET /evaluation-tasks/{id}` | 公共任务状态、冻结快照、各数据集状态/结果，旧任务投影成单数据集 |
| 取消 | `POST /evaluation-tasks/{id}/cancel` | 保存取消意图；不把请求接受当作进程已终止 |
| 报告证据 | `GET /evaluation-tasks/{id}/report` | 复用对象完整性校验；各数据集成绩独立，不生成综合分 |
| 清理重试 | `POST /evaluation-tasks/{id}/cleanup` | 保留原清理检查，不重新测评 |

提交体仅携带最终设置，不接受 Planner 作业或执行方案 ID：

```json
{
  "target_id": "<uuid>",
  "resource_id": "<uuid>",
  "resource_kind": "customer_ssh",
  "dataset_concurrency": 1,
  "tasks": [
    {
      "task_id": "GPQA",
      "dataset": "GPQA",
      "compilation_id": "<uuid>",
      "manifest_id": "<uuid>",
      "concurrency": 1
    }
  ]
}
```

`tasks` 按执行顺序列出 1–4 个数据集。GPQA、MMMU-Pro、DeepSWE、AutomationBench 在同一任务中各至多出现一次。`dataset_concurrency` 默认 1。控制台切换到并行执行时，按已选数据集数填写并发数，用户可再调低。每个数据集取得主机容量租约后启动独立容器，容量不足时等待。`concurrency` 控制数据集内部并发，省略时使用配置原值，显式调整仍须通过标准锁定参数校验。

提交依赖有效的环境预检。控制台按数据集展示源容器 ID 和复用状态，成功预检的五分钟有效期从原始检查时间开始计算。详见[查看预检进度与复用记录](./task-planning.md#查看预检进度与复用记录)。

## 数据及兼容

复用 `evaluation_run`、冻结快照、数据集子执行、Outbox 及原工作流，无新增表或历史数据回写。按运行 UUID 一条记录展示，不拼接两份列表。默认排除非真实来源及明确测试模型前缀，`include_test=true` 用于诊断读取，历史链接仍可访问。

旧 `/runs`、`/planning/runs` 等接口保留，旧工作流名称和快照版本保持兼容。新前端不调用旧提交入口；`#planned-run/{id}` 重定向到统一 `#run/{id}`。历史单数据集任务保持原报告及 case 证据路径，多数据集详情展示数据集结果和受控归档证据。

## 验证与发布边界

新增 `test_evaluation_tasks.py`：契约拒绝 Planner 字段、重复数据集，执行通道无 Planner 包依赖，独立真实 PostgreSQL 验证并发幂等、分页统计、取消、测试记录隐藏及历史投影。浏览器回归2项通过，用人工 API 夹具验证入口统一、参数采纳、失效、最终提交字段和旧链接；夹具不能替代真实测评。

独立临时数据库应用全部迁移后，任务/规划相关回归37通过、1跳过；该跳过项不计验收通过。现有本地业务库缺少开发中的 Langfuse 表时，相关回归会失败，不为本项功能擅自升级该业务库。本轮无付费调用、无远程发布、无提交推送。

## 在任务详情查看执行器原始文件

在本机开发库运行固定产物验收时，可从「数据工作台 → 环境诊断」提交，再在「任务管理」勾选「包含验证任务」按任务 ID 查找。报告保留模拟来源。通过服务端 `AE_UNIFIED_FIXTURE_CONFIG` 指定本机来源时，`local_output` 记录已登记的 `resource_id`、产物作业 `job_id` 和预检生成的 `storage`（`container`、`mount`、`store`）。采集器读取该作业的 `output/unified_result.json`，按 `source_sha256` 校验后归档。

新统一测评任务按数据集子作业 UUID 保存原始输出。首次执行、续跑和单 Case 重试各有独立目录。任务成功、失败或取消后，终态清理释放执行资源，已落盘的工具日志、预测、评分和 Harbor trial 持续保留，直到运维人工清理。正式报告继续引用对象存储中的归档证据。

本地 Docker 和 SSH 控制的 Docker 执行容器都需要在 `/var/lib/autoeval/artifacts` **直接挂载**可写命名卷或宿主机持久目录。例如，创建执行容器时传入 `--mount type=volume,src=autoeval-executor-artifacts,dst=/var/lib/autoeval/artifacts`。仓库的开发 Compose 已为 executor 声明命名卷。已有执行器需在维护窗口配置挂载并重新做资源预检。平台预检会试写该卷，记录存储标识，并在派发前复核。无需迁移数据库。

开发或测试环境中打开 **任务详情 → 执行器原始文件**，选择轮次与数据集子作业后，默认递归列出其 `output/` 和 `outputs/` 中的文件，显示相对路径、大小和修改时间，每页 100 条。选择文件后，桌面左侧保留当前列表和页码，右侧展示文件预览；窄屏从右侧打开预览抽屉。任务详情默认打开「运行概览」，可展开「工具运行详情」查看进程和采集信息。「执行日志」「监控快照」「配置快照」均可从同一行导航打开。隐藏文件、受保护配置和链接显示元信息，链接目标不会被遍历。切换到“作业目录”可分层浏览并查看工具日志。运行中可刷新查看新文件和增长的日志。文本预览最多 64 KiB，日志从末尾读取，页面标出原始文件字节范围。文件读取和凭据脱敏在后端完成。原始卷包含测评正文，应沿用执行器工作目录的访问权限。

重建执行容器时重新挂载原卷，保留卷内隐藏的存储标识。沿用原容器名即可从原任务查看文件。容器更名时，本地 Docker 需登记新容器，SSH 资源需更新其规划容器绑定。新任务按新容器身份重新预检。历史任务缺少可核验的挂载或现场已清理时，“全部原始输出文件”显示所选作业已归档的原生文件，按归档路径和归档时间列出，可预览 Harbor 结果、轨迹、评分文件或原生预测。“作业目录”优先浏览可核验的现场，现场不可用时显示归档目录，可逐级进入子目录并预览已保存的文件。

开发诊断接口为 `GET /api/autoeval/v1/evaluation-tasks/{run_id}/executor-files`（作业列表）和 `GET /api/autoeval/v1/evaluation-tasks/{run_id}/executor-files/{job_id}`（目录或文件）。后者接受作业相对路径 `path` 和目录分页 `offset`。生产环境禁用这两个接口。
