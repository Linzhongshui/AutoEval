# Windows 本地开发部署

在仓库根目录打开 PowerShell。主机运行 API、后台和 Vite，Docker Desktop 的 Linux 容器提供 PostgreSQL、Temporal 和持久化 MinIO。已有环境先检查容器、卷和监听者，优先复用。命令按段运行，每个外部命令检查退出码，再执行下一条。

~~~powershell
$repo = (git rev-parse --show-toplevel).Trim()
Set-Location -LiteralPath $repo
git status --short
git rev-parse HEAD
node --version
uv --version
uv python find 3.12
docker compose version
docker info --format '{{.OSType}}'
docker ps -a --format '{{.Names}} {{.Ports}}'
docker volume ls
Get-NetTCPConnection -State Listen | Where-Object LocalPort -in 5432,7233,9000,9002,8000,5173
~~~

需要 Node 22+、Python 3.12、uv、可用的 Docker Linux 引擎和 Compose 插件。按所在组织的安装渠道补齐工具；缺少 Python 可用 uv python install 3.12。若端口被占用，先识别实例与数据，勿另起一个不同卷的同名工作空间。

## 配置和持久化基础设施

~~~powershell
if (!(Test-Path deploy/.env)) { Copy-Item deploy/.env.example deploy/.env }
if (!(Test-Path backend/.env)) { Copy-Item backend/.env.example backend/.env }
~~~

在本机受保护编辑器中填写两个文件。deploy/.env 的 AE_DB_PASSWORD 与 backend/.env 的 AE_DATABASE_URL 口令一致，URL 中的特殊字符需编码；两边 S3 键一致。backend/.env 设 AE_ENVIRONMENT=development、AE_AUTH_MODE=local、AE_TEMPORAL_ADDRESS=127.0.0.1:7233、目标命名空间（默认 default）、AE_S3_ENDPOINT=http://127.0.0.1:9002 和约定的桶名。清查当前 shell 同名环境变量是否覆盖文件，只列键名。首次使用的外部 evidence 卷可创建；升级找不到原卷时，应核实或恢复原数据，不能用空卷续跑。

~~~powershell
# 在确认卷和项目身份后，首次安装设 $deploymentMode='fresh'，升级设为 'upgrade'
if ($deploymentMode -notin @('fresh','upgrade')) { throw '请先确定部署模式' }
$volumes = docker volume ls --format '{{.Name}}'
if ($LASTEXITCODE -ne 0) { throw '无法读取 Docker 卷' }
if ($volumes -notcontains 'autoeval-evidence-persistent') {
  if ($deploymentMode -ne 'fresh') { throw '升级所需证据卷缺失，请核对目标或恢复备份' }
  docker volume create autoeval-evidence-persistent
  if ($LASTEXITCODE -ne 0) { throw '创建持久化证据卷失败' }
}
if ($deploymentMode -eq 'upgrade') {
  # 默认 Compose 项目名的示例；现网覆盖了项目名或卷名时须按实测修正，包括下方 Compose 调用
  foreach ($requiredVolume in @('autoeval-demo_database','autoeval-demo_temporal')) {
    if ($volumes -notcontains $requiredVolume) { throw "业务卷缺失 $requiredVolume" }
  }
}
docker compose --env-file deploy/.env -f deploy/compose.yaml up -d postgres temporal
if ($LASTEXITCODE -ne 0) { throw '数据库或 Temporal 启动失败' }
docker compose --env-file backend/.env -f deploy/compose.storage-durable.yaml up -d storage
docker compose --env-file deploy/.env -f deploy/compose.yaml exec -T postgres pg_isready -U autoeval
docker compose --env-file backend/.env -f deploy/compose.storage-durable.yaml ps
~~~

两个 Compose 文件分别启动；基础文件的 storage 在 9000 提供 Moto，仅在隔离协议测试需要时单独运行 docker compose --env-file deploy/.env -f deploy/compose.yaml up -d storage。业务端使用 9002。历史环境若指向 Moto，先按 docs/development-recovery.md 停写、预览对象迁移和逐对象比对，再切换后端。不要只改 endpoint。Temporal 起不来时核对 temporal-data-init 的退出状态、持久卷和 7233 监听。

## 应用及后台

在 backend 目录执行。可用 uv lock --check 确认项目声明与锁一致。首次同步需要能访问锁定的 Git 提交与包源，失败时修复网络或提供已校验的离线依赖。

~~~powershell
Set-Location (Join-Path $repo backend)
uv sync --frozen --python 3.12
uv run --frozen alembic current
uv run --frozen alembic heads
# 核对目标数据库；已有数据先执行验收与恢复手册中的备份
uv run --frozen alembic upgrade head
uv run --frozen alembic current
uv run --frozen python -m autoeval.infrastructure.bootstrap storage
uv run --frozen uvicorn autoeval.entrypoints.api:app --host 127.0.0.1 --port 8000
~~~

current 与本次 head 一致，初始化返回桶可用。API 常驻后，在 backend 的独立终端分别运行以下各行。统一结果收集使用 result；规划协调默认处理 preflight,plan。需要兼容执行、轨迹导入等能力时按对应版本 backend/README.md 添加角色。

~~~powershell
uv run --frozen python -m autoeval.entrypoints.dispatcher
uv run --frozen python -m autoeval.entrypoints.worker workflow
uv run --frozen python -m autoeval.planning.planning_worker
uv run --frozen python -m autoeval.entrypoints.worker planning-execution
uv run --frozen python -m autoeval.entrypoints.worker result
uv run --frozen python -m autoeval.entrypoints.reconciler
~~~

在 frontend 目录的独立终端启动前端。使用 strictPort，遇冲突时明确处理原监听者。

~~~powershell
npm ci
npm run build
npm run dev -- --host 127.0.0.1 --port 5173 --strictPort
~~~

从任意终端检查本机地址：

~~~powershell
Invoke-RestMethod http://127.0.0.1:8000/health/live
(Invoke-RestMethod http://127.0.0.1:8000/health/ready).checks
Invoke-RestMethod http://127.0.0.1:5173/api/autoeval/v1/system/capabilities
~~~

浏览器打开 http://127.0.0.1:5173，从 Network 核实 API 返回 JSON。本地回环开发路径使用 HTTP，内网 TLS/网关认证另行验收。503 按响应中的 database、temporal 或 storage 排查；Vite 返回 502 时先查 API；提交停在 accepted 时检查分发与队列。继续执行[固定产物验收](acceptance-recovery.md)。停机时结束对应独立终端，再用原 Compose 文件和项目执行 stop，保留卷。
