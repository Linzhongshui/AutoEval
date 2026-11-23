# AutoEval Platform

<p align="center">
  <img src="./frontend/public/brand/autoeval-logo.svg" alt="AutoEval 智能测评平台" width="300" />
</p>

AutoEval 面向单团队、单工作空间。你可以在控制台为一个模型选择多个数据集，提交测评，再从任务详情追踪到具体样本、执行日志、评分证据和报告。平台使用 React、TypeScript、Vite、FastAPI、Temporal、PostgreSQL 和 S3 兼容对象存储，当前用于受控开发与演示。

已有演示环境的用户可连接 VPN 后打开 [AutoEval](https://179.214.2.3/) 或 [Langfuse](https://179.214.2.3:8443/)。首次访问所需的证书和代理设置见 [Langfuse 接入说明](docs/langfuse-integration.md)。

[当前能力与验证范围](#当前能力与验证范围) · [快速启动](#快速启动) · [跑通一次测评](#跑通一次测评) · [问题排查](#问题排查)

## 当前能力与验证范围

| 能力 | 已有记录覆盖的范围 |
| --- | --- |
| 多数据集串行与并行 | GPQA、MMMU-Pro、DeepSWE 和 AutomationBench 的四路并行已验证控制台提交参数（浏览器模拟）及 Worker 调度（独立 PostgreSQL 配合模拟容器接口）。同一 SSH 节点上的并发实测覆盖两个 AISBench 作业，四个正式容器同时运行仍需独立证据。[R13 验收记录](docs/r13-acceptance.md) |
| GPQA Diamond | 真实模型在 20 题 Lite 清单上完成 20 题、答对 18 题，可回看 Case、报告、分析与入榜记录。90% 仅适用于该清单。[真机验收与录屏](docs/live-e2e-gpqa20-2026-11-16.md) |
| AutomationBench 与 Langfuse | 已验证单样本原生执行、自动导入和从平台打开 Agent 轨迹。评分修复用已有产物复核，原任务保留失败历史。[真机验收与限制](docs/automationbench-langfuse-acceptance-2026-11-17.md) |
| 续跑与单 Case 重试 | 原任务可预览、确认新轮次并查看分片日志及各轮报告。实际受理取决于部署开关、冻结资源和历史请求核对结果。[受理条件](backend/README.md#续跑与单-case-重试) |
| 多数据集报告与榜单 | 报告按数据集展示清单范围、准确率和可比基线，历史报告可按版本回看。入榜还需核对证据并评审。[报告修订](docs/task-report-recovery.md) · [榜单规则](docs/leaderboard-best-selection.md) |

吞吐与延迟需专门采集，报告总耗时包含排队、准备与归档。极光资源、正式身份与生产发布门禁仍待专项验收。[吞吐探测验收范围](docs/probe-live-acceptance-2026-11-16.md)

## 快速启动

### 打开本地页面并检查依赖

准备 Node.js 22+、Python 3.12、uv、Docker / Docker Compose，以及可访问的 PostgreSQL、Temporal 和持久化 S3。首次从 `backend/.env.example` 建立 `backend/.env`，填写本地连接参数。已有配置请保留。开发 Compose 中的 Moto 用于协议测试，真实测评证据使用持久化存储。[后端配置](backend/README.md) · [存储启动与恢复](docs/development-recovery.md)

在仓库根目录打开 PowerShell，确认目标数据库，已有数据先备份，再启动 API：

```powershell
cd backend
uv sync --frozen --python 3.12
uv run alembic upgrade head
uv run python -m autoeval.infrastructure.bootstrap storage
uv run uvicorn autoeval.entrypoints.api:app --host 127.0.0.1 --port 8000
```

从仓库根目录打开第二个终端启动前端：

```powershell
cd frontend
npm ci
npm run dev
```

打开 [本地控制台](http://127.0.0.1:5173/) 和 [API 就绪检查](http://127.0.0.1:8000/health/ready)。页面可访问且就绪检查返回 HTTP 200，说明前端和 API 依赖已就绪。若返回 503，先检查数据库、Temporal 和对象存储。API 也提供[交互文档](http://127.0.0.1:8000/docs)。

### 启动任务执行进程

在 `backend/` 下为每个常驻命令分别打开终端，使用与 API 相同的配置。

| 进程 | 命令 | 何时用到 |
| --- | --- | --- |
| 规划协调 | `uv run python -m autoeval.planning.planning_worker` | 控制台环境预检和参数规划，默认消费 `preflight,plan` |
| 分发器 | `uv run python -m autoeval.entrypoints.dispatcher` | 将已受理任务的 Outbox 记录投递到 Temporal |
| 测评执行 | `uv run python -m autoeval.entrypoints.worker planning-execution` | 消费统一测评活动，同时监听新版隔离工作流与活动队列 |
| 工作流 | `uv run python -m autoeval.entrypoints.worker workflow` | 消费分配到通用工作流队列的任务，包括历史路径 |
| 状态对账 | `uv run python -m autoeval.entrypoints.reconciler` | 核对在途状态并恢复已有任务 |

需要收集统一输出、导入 Harbor 轨迹或运行独立分析时，按实际路径配置对应角色。真实模型调用、吞吐探测和分析按已授权的目标、样本、尝试次数和预算启用。[后台进程与角色](backend/README.md#后台进程)

## 跑通一次测评

1. **选定清单。** 在控制台选择已登记的模型服务、执行资源、配置和数据集。全量与 Lite 分别对应完整清单与精简清单。串行与并行控制数据集如何调度，样本并发数单独设置。[统一测评任务](docs/unified-evaluation-tasks.md) · [任务规划](docs/task-planning.md)
2. **预检并提交。** 点击“检查服务、资源与配置”。查看各数据集的资源绑定和检查结果，核对样本范围、并发及预算后提交。任务从“已接收”进入准备或执行时，打开详情的“监控”查看工具进度。
3. **读报告。** 打开“查看报告”。精度图的横轴是数据集，纵轴是准确率；存在可比基线时，同组并列展示本次测评与基线，并在详情给出百分点差值。合法零分显示为 0%。任务整体执行失败时，如果样本没有可核验结果，可以同时看到“执行失败”和缺测样本。[标准输入与基线规则](docs/standard-inputs.md)
4. **处理需要补跑的样本。** 在任务列表选“续跑测评”，或在详情的目标样本行选“重试此 Case”。需要一次重试多个样本时，可跨页或跨数据集勾选，也可选择本页，点击“批量重试”并核对所选清单。先查看预览里的样本和阻塞原因，确认受理后在同一任务的“执行轮次”查看分片日志和本轮报告。历史报告仍按原报告 ID 读取。[续跑与单 Case 重试](backend/README.md#续跑与单-case-重试)

## 问题排查

| 看到的现象 | 从哪里查起 |
| --- | --- |
| 页面能打开，任务一直“已接收” | 检查分发器是否投递、目标 Temporal 队列是否有对应 Worker，再看执行资源容量及对账记录。[后端进程](backend/README.md#后台进程) |
| 单 Case 重试无法确认 | 按任务、数据集和样本 ID 核对预览。若旧作业已结束并清理，确认弹窗会提示兼容的资源配置变更和历史请求可能产生的重复费用。仍提示 `resource_changed` 或 `samples_unresolved` 时，核对资源模板、作业状态和样本身份。[续跑受理条件](backend/README.md#续跑与单-case-重试) |
| 报告缺成绩或没有基线差值 | 查看数据集清单范围、评分、当前证据和基线匹配状态，再查对象存储与归档记录。[报告恢复](docs/task-report-recovery.md) · [标准输入](docs/standard-inputs.md) |
| 找不到 Harbor 轨迹或首次访问要求登录 | 核对 Langfuse 导入状态、worker 和私有记录访问权限。公开演示与私有正文记录的区别见[接入说明](docs/langfuse-integration.md)和[演示验收记录](docs/automationbench-langfuse-acceptance-2026-11-17.md)。 |

## 文档导航

- 开发与验证：[贡献指南](AGENTS.md) · [后端说明](backend/README.md) · [浏览器回归](backend/tests/browser_checks/README.md)
- 工具与证据：[AISBench](docs/aisbench-integration.md) · [AutomationBench](docs/automationbench-integration.md) · [统一输出](docs/unified-output-integration.md) · [数据工作台](docs/data-workbench.md)
- 环境与历史：[内网发布](deploy/intranet/README.md) · [持久化与恢复](docs/development-recovery.md) · [早期 README 快照](docs/readme-history-2026-11-17.md)
