# AutoEval 后端

FastAPI 提供接口，Temporal 执行工作流与活动，PostgreSQL 保存业务状态，S3 兼容对象存储保存测评证据。平台采用单团队、单工作空间语义。

当前功能与验收范围见[项目 README](../README.md)。本文件说明后端开发与启动，不将历史测试数量或旧探索入口限制作为当前能力结论。

## 环境与配置

要求 Python 3.12、uv，以及可访问的 PostgreSQL、Temporal 和持久化 S3。真实工具执行还需登记相应 Docker / SSH 资源，不能仅凭 API 健康判断环境就绪。

首次从 `.env.example` 建立 `.env`，已有文件不要覆盖。主要配置如下，真实凭据仅保存在本地或受保护配置文件中：

| 配置 | 用途 |
| --- | --- |
| `AE_DATABASE_URL` | 业务 PostgreSQL 连接 |
| `AE_TEMPORAL_ADDRESS` / `AE_TEMPORAL_NAMESPACE` | 工作流服务与命名空间 |
| `AE_S3_ENDPOINT` / `AE_S3_BUCKET` | 持久化证据端点与桶 |
| `AE_S3_ACCESS_KEY` / `AE_S3_SECRET_KEY` | 对象存储凭据 |
| `AE_PLANNING_CONTAINER_CONFIG` | 客户 SSH 执行资源到固定容器、镜像及可选共享 runtime_root 的保护映射 |
| `AE_LANGFUSE_*` | 内部导入地址、浏览器地址、项目与后端项目密钥 |

配置示例中的 S3 9000 端口不代表持久化保证。真实证据使用[恢复指南](../docs/development-recovery.md)中的持久化配置；Moto 仅用于协议测试，不保存正式历史产物。

## 安装、迁移与 API

以下命令在 `backend/` 执行：

```powershell
uv sync --frozen --python 3.12
uv run alembic upgrade head
uv run python -m autoeval.infrastructure.bootstrap storage
uv run uvicorn autoeval.entrypoints.api:app --host 127.0.0.1 --port 8000 --reload
```

迁移前确认目标库并按部署流程备份。新增迁移，不改写已应用版本；不要删除证据卷或清空数据库处理联调问题。

- API 前缀：`/api/autoeval/v1`，交互文档：`http://127.0.0.1:8000/docs`。
- `/health/live` 检查进程，`/health/ready` 实际检查数据库、Temporal 和对象存储；依赖不可用时 ready 返回 503。
- 前端在 `frontend/` 启动，Vite 默认将 API 请求代理到本机 8000。

## 后台进程

API 不负责直接消费任务。按所使用的功能在独立终端启动对应进程，部署配置应覆盖相同角色。

| 进程 / 角色 | 命令 | 用途 |
| --- | --- | --- |
| Dispatcher | `uv run python -m autoeval.entrypoints.dispatcher` | 投递持久化 Outbox 任务 |
| Workflow | `uv run python -m autoeval.entrypoints.worker workflow` | 测评工作流编排 |
| Planning coordinator | `uv run python -m autoeval.planning.planning_worker` | 环境预检与可选规划 |
| Planning execution | `uv run python -m autoeval.entrypoints.worker planning-execution` | 统一测评执行活动 |
| Reconciler | `uv run python -m autoeval.entrypoints.reconciler` | 对账及恢复已有状态 |
| Result | `uv run python -m autoeval.entrypoints.worker result` | 结果收集与已配置的分析活动 |
| Langfuse | `uv run python -m autoeval.entrypoints.worker langfuse` | Harbor 产物归档后的独立导入 |
| Monitored | `uv run python -m autoeval.entrypoints.worker monitored` | 已登记的 AISBench 监控执行路径 |
| I/O / GPQA | `uv run python -m autoeval.entrypoints.worker io` / `uv run python -m autoeval.entrypoints.worker gpqa` | 诊断与旧 GPQA 探索兼容入口 |
| Analysis workflow | `uv run python -m autoeval.entrypoints.worker analysis-workflow` | 独立分析工作流，需配置目标、资源与预算 |

角色定义以 [worker.py](src/autoeval/entrypoints/worker.py) 为准。`fixture` 仅供显式人工夹具验收，不作为常规业务进程启动。

规划协调默认只处理 `preflight,plan`，不消费真实吞吐探测。启用 `AE_PLANNING_JOB_KINDS=preflight,plan,probe` 前必须核对历史待办和调用预算。独立分析与真实探测都可能发送模型请求；不能为了填充页面或状态恢复而自动开启。

## 远程执行与结果

统一测评使用冻结的配置、工具版本、清单及资源身份。SSH 校验固定主机指纹；受控 runtime 独立下发到执行环境，不回退到任意宿主命令。工具依赖与工具镜像需要单独安装，修改本机源代码不等于远端已发布。

Harbor 通过宿主 Docker socket 执行时，日志与任务目录需要宿主机和 runner 的同绝对路径共享挂载。`planning-container.json` 的可选 `runtime_root` 只存在于后端受保护配置中。详情见 [Langfuse / AutomationBench 环境说明](../docs/langfuse-integration.md)。

结果归档保留原生输出和每次尝试。执行状态、评分完整性与当前证据状态分别判断；缺测不补零，结果未知不重复发送模型请求，清理无法确认时保留资源占用与失败历史。

Harbor 轨迹导入失败不修改测评成绩。只有确认导入成功才提供 Trace 链接；等待、失败、轨迹缺失、配置缺失及不支持分别展示。只有用户明确选择的演示记录可免登录分享，新记录默认不公开。

## 代码结构

| 路径 | 责任 |
| --- | --- |
| `src/autoeval/entrypoints/api.py` | 应用装配与路由注册 |
| `src/autoeval/evaluation/` / `planning/` | 测评与规划领域服务、接口及模型 |
| `src/autoeval/reporting/` / `analysis/` | 报告、证据、榜单与独立分析 |
| `src/autoeval/catalog/` | 模型、配置及目录管理 |
| `src/autoeval/infrastructure/` | 数据库、存储、执行与恢复基础能力 |
| `src/autoeval/reporting/langfuse_integration.py` | Trace 归档关联、导入活动与查询 / 重试接口 |
| `migrations/` / `tool-locks/` | 数据库迁移与固定工具依赖 |
| `tests/` | 单元、基础设施与浏览器检查 |

API、Worker、Dispatcher 和 Reconciler 命令位于 `autoeval.entrypoints`，规划协调位于 `autoeval.planning.planning_worker`。

接口输入输出、ORM 注册与实体外键见[数据契约与实体关系](../docs/backend-data-model.md)。

测评接口、执行活动和监控实现在 `evaluation/`，规划观测和探测投递在
`planning/`，Docker 与 SSH 执行器在 `resources/`。计费模型、额度、账本和
网关实现在 `billing/`，Langfuse 导入与结果标识在 `reporting/`。

计费网关通过 `python -m autoeval.billing.gateway` 启动。独立远端运行时源码
位于 `src/autoeval_runtime/`，下发文件名和内容沿用现有打包契约。

## 检查与依赖更新

```powershell
uv run pytest -q
uv run ruff check .

# 更新依赖后同步部署清单
uv export --frozen --no-dev --no-emit-project --format requirements-txt --output-file requirements.lock.txt
```

默认测试不触发真实模型调用。`AE_INFRA_TEST`、`AE_SSH_SIM_TEST`、`AE_BROWSER_TEST` 等专项需要相应真实依赖；跳过不代表通过。PostgreSQL 的 JSONB、并发锁及约束不使用 SQLite 替代验收。浏览器操作、环境变量和证据目录见[浏览器检查说明](tests/browser_checks/README.md)。

## 接入、部署与验收入口

- [统一测评任务](../docs/unified-evaluation-tasks.md)、[任务规划](../docs/task-planning.md)、[标准输入](../docs/standard-inputs.md)、[统一输出](../docs/unified-output-integration.md)。
- [AISBench](../docs/aisbench-integration.md)、[AutomationBench](../docs/automationbench-integration.md)、[Harbor 安装](../docs/harbor-adapter-install-2026-11-16.md)、[Langfuse](../docs/langfuse-integration.md)。
- [GPQA 20 题真实验收](../docs/live-e2e-gpqa20-2026-11-16.md)、[AutomationBench 真实轨迹验收](../docs/automationbench-langfuse-acceptance-2026-11-17.md)。
- [存储与恢复](../docs/development-recovery.md)、[内网发布操作](../deploy/intranet/README.md)。

原按时间追加的模块说明与早期探索命令保留在[后端 README 历史快照](../docs/backend-readme-history-2026-11-17.md)，仅作追溯，不作为当前启动步骤。
