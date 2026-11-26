# AutoEval Platform 开发指南

本指南适用于整个仓库。默认用中文沟通、编写说明和交付结果，代码标识符及命令沿用项目约定。平台采用单团队、单工作空间语义。

## 从哪里开始

修改前运行 `git status --short`，阅读相关实现，保留已有未提交修改。用 `rg` 搜索相关目录，避开依赖、构建产物和归档文件。能力以当前实现为准，验收范围以对应记录为准。

| 任务 | 阅读入口 |
| --- | --- |
| 启动平台 | 从 [README 快速启动](README.md#快速启动) 进入。后端从 `backend/` 使用 `autoeval.entrypoints.api:app`，工作流与执行角色按[后端进程表](backend/README.md#后台进程)选择。 |
| 修改前端 | [app](frontend/src/app/) 负责页面入口，[features](frontend/src/features/) 按业务组织页面和组件，[shared](frontend/src/shared/) 放共享 API、类型与组件。 |
| 修改测评、报告或执行器 | 从[后端领域模块](backend/src/autoeval/)进入。测评提交与重跑在 `evaluation/`，资源预检与规划在 `planning/`，报告与证据在 `reporting/`，资源执行适配在 `resources/`。 |
| 修改部署或工具集成 | [部署配置](deploy/)与[工具版本锁](backend/tool-locks/)共同决定实际运行条件。检查已登记资源的固定镜像、挂载和工具版本。[标准输入](docs/standard-inputs.md) · [统一输出](docs/unified-output-integration.md) |

## 编码与集成

- Python 使用四空格、蛇形命名及 Ruff（Python 3.12，行宽 100）。需要格式化时在 `backend/` 仅对所改文件运行 `uv run ruff format <文件路径>`。TypeScript 使用两空格，组件采用大驼峰、变量采用小驼峰，沿用现有 React、CSS 与 lucide-react。
- 修改接口时同步服务端校验、OpenAPI、前端类型和调用方。维护与诊断接口限开发或测试环境。规划器通过 `backend/pyproject.toml` 和 `backend/uv.lock` 固定 Git 提交，集成相邻规划器的改动时同步核对锁定版本。
- 平台负责状态、执行编排和归档，适配器负责工具配置与结果转换，规划器提供估算建议。变更配置字段、样本标识或 Token 口径时，同时检查生产方、消费方及历史数据。
- 数据库结构变化追加 Alembic 迁移，保留已应用的版本。迁移前确认目标库及恢复条件。业务证据使用持久化 S3，Moto 仅用于协议测试。保留既有 `.env`、数据库和证据卷。[持久化与恢复](docs/development-recovery.md)

## 改动执行链与报告时

- **确认与派发。** 冻结任务输入、清单、工具身份、资源和配置版本。单 Case 以 `(dataset_key, sample_id)` 定位；同一次确认重投应返回已受理的轮次。用实际派发集合检查其他样本新增请求为零。[续跑与单 Case 重试](backend/README.md#续跑与单-case-重试)
- **中断与恢复。** Temporal 工作流保持确定性，外部 I/O 放在活动或适配器中。Outbox 重投、回执丢失或取消时，先按原作业身份核对远端状态；结果未知时保留待核对状态。清理待确认时保留容量租约。真实重跑、模型调用、探测与分析按当前授权范围执行。[执行与恢复验收](docs/r13-acceptance.md)
- **报告与计分。** 保留每次尝试、失败历史和旧报告 ID。续跑版本承接未选样本，按原清单计分。分别判断执行状态、评分、历史完整性 `validity` 和当前证据 `evidence_status`。保留工具原生评分与合法零分；缺测或证据不可用时不补零，基线差值和入榜资格各按相应规则判断。[报告恢复](docs/task-report-recovery.md) · [榜单规则](docs/leaderboard-best-selection.md)
- **指标与凭据。** 外部成绩保留来源和测评条件，缺失测评时间留空。预测时长与实测性能分别记录。密钥、受保护配置、备份、生成的分享包不提交；前端存储、快照与普通日志不写入凭据，保留 HTTPS 证书校验。

## 按变更验证

前端命令从 `frontend/` 执行，后端命令从 `backend/` 执行。PR 的后端检查在临时 PostgreSQL 上迁移后运行默认 pytest，前端检查模块边界并构建。[CI 工作流](.github/workflows/pr-checks.yml)

| 改动类型 | 先运行 | 何时扩大验证 |
| --- | --- | --- |
| 前端模块、页面或类型 | `npm run check:boundaries`、`npm run build`（含类型检查，可用 `npm run typecheck` 单独定位） | 有可见交互时按[浏览器回归说明](backend/tests/browser_checks/README.md)启用 `AE_BROWSER_TEST=1`，指定本地前端地址并运行对应 pytest。分别记录模拟接口和真实只读页面的结果。 |
| 后端服务或接口 | `uv run ruff check .`、`uv run pytest -q <相关测试路径>` | 修改共享契约时覆盖上下游调用方，扩大到 `uv run pytest -q`。行为变化按需补 `test_*.py` 回归。 |
| 持久化与迁移 | 在隔离 PostgreSQL 执行 `uv run alembic upgrade head` 与对应数据库专项 | 涉及历史数据、并发锁、对象归档时验证升级兼容、竞争写入和证据回读，按专项前置条件启用 `AE_INFRA_TEST` 或相应存储测试。 |
| 工作流、取消、重跑或资源隔离 | 运行受影响的编排与重跑用例，核对执行集合、次数和终态 | 涉及跨进程或远端状态时增加 Temporal、SSH 或容器专项，验证回执丢失、重启恢复、归档和清理失败。SSH 模拟器专项按用例启用 `AE_SSH_SIM_TEST`。[R13 验收范围](docs/r13-acceptance.md) |
| 纯文档 | 核对相对链接、标题锚点、命令工作目录和实际入口，运行 `git diff --check` | 若声称真实执行或上线结果，链接到能证明该范围的记录。纯文档修改无需业务全量测试。 |

交付新版前端时，同步更新 `frontend/package.json` 的版本号和 `frontend/package-lock.json` 中的项目版本。页面从包版本读取显示值。切换开发环境后，打开实际测试入口，核对侧栏版本号与本次交付一致。

交付时列出实际通过、失败、跳过及其前置条件。把固定产物解析、模拟接口、真实基础设施和真实模型测评分开记录。启动方式、接口或能力边界变化时同步对应指南。提交沿用 `feat(frontend): 中文说明`、`fix(m8): 中文说明` 等仓库格式。PR 写明问题、结果、验证和限制；提交、推送与发布按用户要求执行。
