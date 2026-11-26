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
- 前端在 `frontend/` 启动，Vite 默认将 API 请求代理到本机 8000。多工作树并行时，可在本工作树的 `frontend/.env.development.local` 设置 `AE_DEV_API_ORIGIN` 指向对应 API。

## 后台进程

API 不负责直接消费任务。按所使用的功能在独立终端启动对应进程，部署配置应覆盖相同角色。

SSH 隔离预检使用 `GET /api/autoeval/v1/planning/probes/{job_id}` 查询进度。Worker 在 `result.preflight_progress` 中记录冻结的数据集到资源 ID 的映射，以及带时间戳的容器准备、工具与数据校验、回收和检查结果。控制台按 SSH 地址和端口合并主机展示，每个数据集单列一个执行节点。提交及调度仍使用具体的资源配置 ID。旧预检记录按已有结果显示。

每个数据集通过预检并确认回收临时容器后，Worker 保存来源任务、完整 Docker 容器 ID、实检时间和检查结果。同一 SSH 绑定、执行模板和冻结数据集输入在实检后五分钟内可以复用该记录。多个预检同时请求相同配置时共享同一次实检。组合快照最晚在其中最早的一条证据到期时失效。正式测评仍为每个子任务创建独立执行容器。

预检按登记的执行配置、样本清单、工具版本和节点模板匹配。数据集顺序、数据集并发数和样本并发数可以在有效期内调整。提交时使用最终并发值校验配置约束，并按对应节点的容量快照核算资源需求。发布此改动时需一并更新 API 和规划 Worker，使两端采用相同的匹配条件。

| 进程 / 角色 | 命令 | 用途 |
| --- | --- | --- |
| Dispatcher | `uv run python -m autoeval.entrypoints.dispatcher` | 投递持久化 Outbox 任务 |
| Workflow | `uv run python -m autoeval.entrypoints.worker workflow` | 测评工作流编排 |
| Planning coordinator | `uv run python -m autoeval.planning.planning_worker` | 环境预检与可选规划 |
| Planning execution | `uv run python -m autoeval.entrypoints.worker planning-execution` | 统一测评执行活动 |
| Isolated execution | `uv run python -m autoeval.entrypoints.worker isolated-execution` | 混合版本环境中仅消费 R13 新任务；已启动本版 planning-execution 时无需重复启动 |
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

### R13 remote execution templates

SSH 节点是执行资源，容器由平台按子任务创建。首次预检也会创建临时独立容器，
完成检查后回收。正式任务获配容量后创建自己的容器。资源池无需手工新增每个容器。
从旧版配置升级时，只有 `container_id` 和 `image_id` 的绑定还缺少执行模板，
需要在同一节点条目中补充 `executors`。原固定容器信息供历史任务和兼容路径读取。

```json
{
  "<SSH 节点 UUID>": {
    "executors": {
      "aisbench": {
        "revision": "<与执行配置一致的完整 Git 提交>",
        "image_id": "sha256:<节点上已安装镜像的 64 位摘要>",
        "readonly_mounts": [
          {"source": "/srv/evaluation/datasets", "target": "/benchmark/ais_bench/datasets"}
        ]
      }
    }
  }
}
```

模板无需 `container_id`。镜像必须包含匹配的工具及平台适配器，数据可以包含在镜像中，
或通过只读挂载提供。平台仍校验工具版本、评分文件和数据目录。

同一节点有多个工具版本时，可在 `executors` 中以 `harbor@<完整revision>` 等键登记版本专用模板。平台优先读取精确版本键，缺少该键时再检查默认工具模板的版本。API 与规划工作进程应指向同一份 `AE_PLANNING_CONTAINER_CONFIG`。

Unified evaluation accepts SSH resources. Configure the protected
`AE_PLANNING_CONTAINER_CONFIG` mapping by SSH binding UUID. Each binding's
`executors` object maps tool names to execution templates with `revision`,
`image_id` (a full local Docker image ID on the remote host), and optional
`readonly_mounts`. Each entry is either one absolute path for both sides or
an object with separate absolute `source` and `target` paths. Set
`environment.AE_VALIDATED_DATASETS` only for validated datasets.

Harbor templates require `private_docker: true` and an image whose entrypoint
runs a private Docker daemon at `/tmp/autoeval-docker.sock`. The runner sets
`DOCKER_HOST` to that socket. Prepare and validate this image on the target
node before enabling Harbor there. Its trial resources belong to that private
daemon. Keep the existing fixed runner binding for planning and in-flight
snapshots. Apply migrations through `0038_cleanup_attempt_order` before starting the
updated worker and reconciler.

Harbor 节点也可在模板中配置 `rootless_docker_helper`，值为节点上可执行的
`deploy/r13-rootless-docker` 的绝对路径。将该程序安装在节点已配置的
Docker 静态工具目录中，与 `docker/`、`docker-rootless-extras/` 同级。
节点需为 SSH 用户配置 subordinate UID/GID，并提供 `ip`、Python 3.9+
和支持 pidfd 的 Linux 内核。每个子任务有独立套接字和状态目录。
执行器先回收外层容器，再让节点程序停止相应的私有 daemon。

PEIR and AgentX currently have tool identifiers and template matching tests.
Production submission and native output adapters require their tool contracts.

新任务的工作流与活动使用 `autoeval.dataset-containers.v1` 队列。本版 `planning-execution` 同时监听历史活动队列，升级时先启动 Worker 再切换 API。
同机隔离验收可设置 `AE_ISOLATION_RESOURCE_ID` 为已登记 AISBench 镜像的 SSH 资源 UUID，执行 `uv run pytest -q -s tests/test_dataset_container_ssh.py`。此用例启动三个固定输出容器，使用配置的对象存储保存验收记录并校验回读，模型请求数为零。

The optional lifecycle fixtures in `tests/test_isolated_execution.py` accept
`AE_ISOLATED_SSH_CONFIG`, a protected JSON file for an approved test node.
Provide `host`, `port`, `username`, `fingerprint`, `workdir`, `auth_kind`,
`credential_ref` from the secret store, and the full `image_id` of a preloaded
Python image. The SSH variants exercise remote Docker and SFTP using fixed
framework jobs with no model calls.

Use `AE_ISOLATED_NATIVE_SSH_CONFIG` to opt in to the AISBench and Harbor native
smoke tests. The protected JSON has `aisbench` and `harbor` entries. Each entry
provides `connection` fields from the SSH fixture above excluding `image_id`,
the resolved execution `template`, an adaptor `spec` without credentials,
`model_credential_ref`, `dataset`, and frozen `samples` with `tool_case_id` and `sample_id`. Use a bounded
AISBench fixture configured for a controlled model response and a Harbor
fixture configured for a no-model trial. Both tests exercise preflight,
native execution, SSH result retrieval, and removal on the configured node.

The AISBench source lock records exact file bytes. For a disposable checkout at
the locked commit, run `python deploy/prepare_r13_aisbench_source.py <checkout>`
from the repository root before packaging the image. The command reconstructs
CRLF bytes only when the result exactly matches the recorded SHA-256 and stops
on any other discrepancy.

Build the Harbor private-daemon image with `deploy/r13-harbor.Dockerfile` from
the repository root. Set `HARBOR_BASE` to the local Harbor runner containing
the locked tool and its `/opt/venvs/harbor` environment. Set `ADAPTOR_IMAGE` to
the AISBench image built with the locked adaptor. Pin the resulting image ID
in the SSH resource template. The build verifies adaptor provenance and
that the CLI actually exposes its preflight command.
Provision the node with its approved container runtime policy and preloaded
trial images before running the Harbor preflight.

## 续跑与单 Case 重试

部署 API、dispatcher 和执行 worker 到同一版本，数据库迁移到 `0041` 对应的迁移头后，使用 `AE_EVALUATION_FOLLOW_UP_ENABLED=true` 开放确认。预览接口只读，确认请求需携带预览的来源轮次、选择摘要和 `Idempotency-Key`。任务与报告使用原任务 ID，历史报告继续按各自报告 ID 读取。

`samples_unresolved` 表示无法核对历史请求是否已发出，`resource_changed` 表示执行节点当前配置与冻结模板不一致。批量续跑遇到这些情况会停止受理。手动单 Case 重试允许采用同一资源当前兼容的工具模板，确认时将它冻结到新分片。如果原样本身份一致、旧作业已失败或取消并完成清理，且本次作业没有仍在执行的样本记录，历史派发回执缺失会提示可能重复产生费用，操作者可确认重试。模板不可用、作业仍在途、预算或模型校验失败时仍会返回阻塞原因。原任务明确选择不限费用时，手动重试单个 Case 从新轮次受理时起计算 24 小时执行期限，Worker 重启后沿用同一截止时间。有金额预算的任务及批量续跑沿用原预算和期限。回滚前关闭确认入口，核对已受理轮次、未释放租约和报告版本；保留证据及数据库，使用兼容版本继续处理已受理轮次。

手动批量重试沿用 Case 重试的资源、预算与轮次规则。向任务的 `batch-case-retry-preview` POST 所选 `cases`（每项含 `dataset_key` 与 `sample_id`）取得只读预览。向 `batch-case-retry` POST 同一清单、来源轮次和选择摘要，并携带 `Idempotency-Key`。相同样本去重，清单顺序不影响确认；任何选中项无法受理时整批停止。一次确认生成一个轮次，未选样本沿用此前报告引用。
