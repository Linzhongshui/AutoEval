# 统一测评任务与 Planner 辅助能力

## 业务与职责

平台只有测评任务，一次任务包含一个或多个数据集。控制台保留一个发起表单，GPQA Lite 通过数据集样本范围选择；不再设快速验证或编排任务入口。平台负责资源预检、顺序、并发、持久化工作流、结果归档及清理。

Task Planner 仅用于估算耗时和建议执行顺序、数据集并发及 case 并发。估算缺少依据时不补造实测值；建议展示可信度、来源、版本、调整前后差异，需显式采纳。采纳只修改待提交表单，旧估算失效，随后重新预检；不保存执行任务、不调用模型。未估算、Planner 不可用均不妨碍通过执行预检的任务提交。

启用 `AE_EVALUATION_FOLLOW_UP_ENABLED=true` 后，可以从任务管理列表续跑取消后剩余的样本，也可以在任务详情从数据集进入 Case 列表并只重试所选样本。执行失败和零分的 Case 优先显示。两种操作都要求显式确认，并保留原尝试和报告版本。接口、上线顺序与验收记录见 [R12 取消后续跑测评与单 Case 重试](evaluation-task-resume.md)。

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
