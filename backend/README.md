# AutoEval 后端基础架构

当前为详设的第一批基础设施实现，**不是已完成的测评后台**。单团队、单工作空间，无项目/租户层。不读取极光内部服务，也不改动前端现有展示数据。

## 已实现

- FastAPI应用工厂、lifespan资源回收、请求ID、统一异常和OpenAPI。
- `/health/live`存活检查、`/health/ready`真实检查PostgreSQL/Temporal/S3 bucket；依赖不可用返回503。
- `/api/autoeval/v1/system/capabilities`明确返回执行/分析/SSH/极光尚未启用。
- SQLAlchemy执行基础模型与独立Alembic初始迁移：run、snapshot、event、outbox四表。
- Temporal Workflow/IO/Result Worker入口；尚未实现的Activity明确抛出不可重试错误，不生成模拟成功。
- START_RUN outbox投递器：稳定Workflow ID、拒绝ID复用、重复派发去重和延迟重试。
- 只读reconciler发现滞留任务并记录告警，不推断远程状态、不自动释放资源。
- Python 3.12隔离环境、uv.lock和带hash的容器依赖清单；Compose开发拓扑与Vite API代理。

## 本地运行（PowerShell）

```powershell
cd backend
uv sync --frozen --python 3.12
Copy-Item .env.example .env
# 编辑.env：真实值只保存在本地，不提交Git
uv run uvicorn autoeval.api:app --host 127.0.0.1 --port 8000 --reload
```

访问 http://127.0.0.1:8000/docs 。API启动不强依赖外部服务，未启动依赖时ready=503是预期结果。前端在仓库的`frontend/`目录运行`npm run dev`，Vite将`/api/autoeval`转发到8000。

## Compose开发环境

```powershell
Copy-Item deploy/.env.example deploy/.env
# 修改本地密码；以下均在demo根目录执行
docker compose --env-file deploy/.env -f deploy/compose.yaml up -d --build postgres temporal storage api
docker compose --env-file deploy/.env -f deploy/compose.yaml --profile tools run --rm migrate
# 在MinIO本地控制台创建autoeval-evidence bucket，再检查/health/ready
docker compose --env-file deploy/.env -f deploy/compose.yaml --profile workers up -d
```

PostgreSQL 5432；Temporal 7233、开发UI 8233；S3 9000、控制台9001；API 8000，仅绑定127.0.0.1。Temporal当前采用独立持久卷上的开发SQLite，**不是生产服务**；不共用业务数据库。正式环境需独立Temporal数据库/账号及真实身份，当前代码主动拒绝production环境使用local身份。

容器镜像tag固定，但未在本环境拉取验证，生产前需验证并锁digest。当前机器没有Docker，Compose启动、真实PostgreSQL迁移、Temporal派发、S3 bucket检查均需在有Docker环境验证。

## 开发检查

```powershell
cd backend
uv run pytest -q
uv run ruff check .
uv run alembic upgrade head --sql
# 依赖变更后同步容器hash清单
uv export --frozen --no-dev --no-emit-project --format requirements-txt --output-file requirements.lock.txt
```

离线SQL生成和SQLAlchemy编译测试不等于真实数据库约束已验证。请勿用SQLite替代PostgreSQL验证JSONB、SKIP LOCKED、唯一约束与并发行为。

## 下一批实现边界

1. 模型、数据、Profile、整套配置及默认指针API和迁移，替换页面预置状态。
2. run提交事务、幂等/取消意图及状态投影；当前没有提交API，不能手工写表假装业务完成。
3. SSH指纹和凭据、远程作业查证、资源锁及所有权清理。
4. case执行历史、原生产物、报告、基准、独立分析和榜单。

Outbox本批只投递START_RUN；CANCEL_RUN仅有schema占位，不消费。后续启用取消必须先实现工作流信号与状态查证。报告/分析outbox外键和去重需后续迁移，不能将report ID写入run外键。本批采用单行有界事务持锁派发，避免提前实现未经验证的租约claim；多副本上线前验证锁竞争并按详设演进claim机制。

无真实SSH执行、模型调用或API Key接入；现有SecretStr仅用于基础设施配置脱敏，不是已实现的密钥服务。不含完整生产权限和审计。真实测评前必须补齐适配能力、预算和证据留存。
