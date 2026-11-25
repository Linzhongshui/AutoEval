# Linux 内网单机发布

以下为 Bash。构建机可联网，目标机只需 Docker、兼容 Compose、Python 3、tar、sha256sum 和已批准的传输通道。构建机使用与目标架构、Python 3.12 ABI、Linux libc 兼容的环境，安装 Node 22+、uv、Git、Python 3.12/pip。下面的变量取自当次任务；路径取绝对路径。每段遇错即停。

## 1. 查清目标与卷

在目标机运行，记录架构、可用空间、监听、已有容器的项目与挂载；分别为镜像包、导入后的镜像、证据增长和备份留足空间。

~~~bash
uname -m
docker info --format '{{.OSType}}/{{.Architecture}}'
docker compose version || docker-compose version
df -h
ss -lnt
docker ps -a --format '{{.Names}} {{.Label "com.docker.compose.project"}} {{.Ports}}'
docker volume ls
~~~

首次安装选择独立项目名和空 release。升级读取现有容器的 Compose 标签、卷名、镜像 ID、配置和入口；沿用原项目名，核对业务库、Temporal 库及 S3 卷身份。在验收手册完成停写和备份后才进入会改变既有实例的步骤。若用户仅要求预制发布包，到传输前即可交付。

## 2. 在构建机打包

新工作空间要发起真实任务时，把[跨环境测评资源](evaluation-bootstrap.md)所列的基础目录、执行配置输入、样本对象和节点数据一并带入，并为数据库、S3 桶和执行节点分别指定恢复位置。

复用已有镜像时，按 [OBS 运行镜像手册](obs-images.md) 获取所需归档。该路径提供 Docker 镜像；继续准备与目标发布匹配的前端 dist、Compose、运行配置及迁移。若 OBS 中的应用版本不匹配，本节构建目标版本，数据集执行镜像仍可按锁定 ID 单独复用。

在仓库根目录设置 REV（已选提交）、BUILD（新临时目录）、OUT（新发布目录）、SKILL（本 Skill 的绝对路径）、PLATFORM（如 linux/amd64）。示例按提交构建。若明确发布工作区快照，先在隔离目录按清单复制选定源文件和新增迁移，记录逐文件哈希，排除已有 .env、私钥、缓存和构建产物。下文统一从同一快照取材。

~~~bash
set -euo pipefail
repo=$(git rev-parse --show-toplevel)
commit=$(git rev-parse --verify "$REV^{commit}")
mkdir -m 700 "$BUILD" "$OUT"
git archive "$commit" | tar -x -C "$BUILD"
cd "$BUILD"
printf '%s\n' "$commit" > "$OUT/source-revision"
(cd frontend && npm ci && npm run build)
mkdir -p "$OUT/frontend"
cp -a frontend/dist "$OUT/frontend/"
cp deploy/intranet/{compose.json,compose.workers.json,image-lock.json,nginx.conf,backup_objects.py,restore_objects.py} "$OUT/"
cp "$SKILL/scripts/render_release.py" "$OUT/"
~~~

在同架构的 Linux Python 3.12 构建环境制作 wheel。先导出 uv 锁定的运行依赖；Git 依赖须保留锁定提交。pip 只构建清单项，应用 wheel 单独构建。核查所用 Python 为 3.12；编译扩展若依赖较新 libc，换成与目标基础镜像匹配的构建环境。

~~~bash
cd "$BUILD/backend"
python3.12 -V
uv lock --check
mkdir wheels
uv export --frozen --no-dev --no-emit-project --no-hashes --format requirements-txt -o "$BUILD/runtime.txt"
python3.12 -m pip wheel --no-deps -r "$BUILD/runtime.txt" -w wheels
uv build --wheel --out-dir wheels .
(cd wheels && sha256sum *.whl > SHA256SUMS)
cd "$BUILD"
~~~

按 image-lock 拉取基础镜像，核对离线 Dockerfile 的 FROM 与 python 锁一致。构建并在出包前用实际新镜像验证导入、迁移入口和工具锁。应用标签仅用于传输，部署采用导入后能核对的镜像 ID。

~~~bash
backend_tag=autoeval-backend:build-$(git -C "$repo" rev-parse --short "$commit")
python3 - "$OUT" <<'PY'
import json, pathlib, sys
out = pathlib.Path(sys.argv[1])
lock = json.loads((out / "image-lock.json").read_text())
names = ["python", "postgres", "storage", "temporal", "nginx"]
(out / "base-images").write_text("".join(f"{k} {lock[k]}\n" for k in names))
PY
tags=()
while read -r name ref; do
  docker pull --platform "$PLATFORM" "$ref"
  tag="autoeval-offline/$name:${commit:0:12}"
  docker tag "$ref" "$tag"
  tags+=("$tag")
done < "$OUT/base-images"
docker build --platform "$PLATFORM" -f deploy/intranet/backend.offline.Dockerfile -t "$backend_tag" .
docker run --rm "$backend_tag" python -c 'import autoeval.entrypoints.api, autoeval.entrypoints.worker, autoeval.planning.planning_worker'
docker run --rm "$backend_tag" alembic heads
docker run --rm "$backend_tag" sh -ec 'pip check && test -r /app/tool-locks/planner-package.json'
docker save -o "$OUT/images.tar" "${tags[@]}" "$backend_tag"
python3 - "$OUT" "${tags[@]}" "$backend_tag" <<'PY'
import json, pathlib, subprocess, sys
out = pathlib.Path(sys.argv[1])
names = [line.split()[0] for line in (out / "base-images").read_text().splitlines()] + ["backend"]
ids = {k: subprocess.check_output(["docker","image","inspect","-f","{{.Id}}",tag], text=True).strip()
       for k, tag in zip(names, sys.argv[2:])}
(out / "images.json").write_text(json.dumps(ids, indent=2))
PY
cp -a backend/wheels "$OUT/"
(cd "$OUT" && find . -type f ! -path './SHA256SUMS' -print0 | sort -z | xargs -0 sha256sum > SHA256SUMS)
~~~

检查 dist/index.html、wheels/SHA256SUMS、images.json 和发布清单。若任一基础镜像不可拉取，通过获批镜像缓存取得相同摘要，避免以浮动标签代替。将 OUT 的内容传入目标新 release（SSH_HOST、REMOTE_RELEASE 由本次确定；远端先创建空的私有目录）。通过受信通道另行记录根清单摘要。

~~~bash
(cd "$OUT" && sha256sum SHA256SUMS)
# 两端已安装 rsync 时使用；若只有 OpenSSH，可用 scp -pr "$OUT/." "$SSH_HOST:$REMOTE_RELEASE/"
rsync -a -- "$OUT/" "$SSH_HOST:$REMOTE_RELEASE/"
~~~

## 3. 在目标 release 适配配置

进入目标新 release。核对根清单摘要与构建端一致，再导入。读取当前部署账户 UID/GID，用于业务进程与宿主挂载目录；平台凭据存储、备份目录的实际属主需与运行身份匹配。共享数据卷沿用原数据库、存储镜像要求的权限。

~~~bash
set -euo pipefail
umask 077
sha256sum SHA256SUMS
sha256sum -c SHA256SUMS
docker load -i images.tar
while read -r image; do
  docker image inspect --format '{{.Id}} {{.Os}}/{{.Architecture}}' "$image"
done < <(python3 -c 'import json; print(*json.load(open("images.json")).values(), sep="\n")')
python3 render_release.py . --uid "$(id -u)" --gid "$(id -g)" --role result
~~~

上述渲染保留模板网络、卷和基础服务，为统一结果收集补 result；启用 Langfuse 时在同一条渲染命令追加 --role langfuse。生成的 release.json / workers.json 属于本次发布；重新渲染用新空目录。镜像 ID 和服务定义以二者为准。若当前发布使用了额外挂载、外部卷、网关或自定义角色，合并已批准的差异，逐项检查；不要让新模板覆盖现网配置。历史 trialctl.sh 绑定旧 Compose 路径、项目、UID、容器名和文件名，此处直接按服务名操作。

首次部署通过受保护的凭据管理或编辑器在 shared 中配置以下文件。升级使用既有受保护配置引用，仅增补本版本必需字段。shared 目录 0700，环境文件 0600；容器内实际读取证书、htpasswd 和 secret store 的账户需具备相应访问权限。以下为同一 network-anchor 命名空间的地址。

| 文件 | 字段与一致性检查 |
| --- | --- |
| shared/postgres.env | POSTGRES_USER=autoeval、POSTGRES_DB=autoeval、POSTGRES_PASSWORD，由 backend.env 引用同一口令。 |
| shared/temporal-db.env | POSTGRES_USER=temporal、POSTGRES_PASSWORD，数据库服务监听 5433。 |
| shared/temporal.env | 对照所锁 auto-setup 镜像入口配置 DB=postgres12、DB_PORT=5433、POSTGRES_SEEDS=127.0.0.1、POSTGRES_USER=temporal、POSTGRES_PWD；核对 BIND_ON_IP、TEMPORAL_ADDRESS 与实际回环监听，DEFAULT_NAMESPACE 与后端一致。检查 temporal 和 temporal_visibility 两个库初始化。 |
| shared/storage.env | Bitnami MinIO 的 MINIO_ROOT_USER、MINIO_ROOT_PASSWORD，实际数据目录 /data 对应 evidence 卷。 |
| shared/backend.env | 从选定源码 backend/.env.example 取字段；受控试用使用 AE_ENVIRONMENT=development、AE_AUTH_MODE=local。AE_DATABASE_URL 指向 127.0.0.1:5432/autoeval，口令按 URL 编码。AE_TEMPORAL_ADDRESS=127.0.0.1:7233，配置命名空间。AE_S3_ENDPOINT=http://127.0.0.1:9000 指向本套 MinIO，指定桶、访问键及密钥，AE_SECRET_STORE_PATH=/app/.secrets。后端设置在 production 会拒绝启动。 |
| shared/secrets、shared/tls、shared/htpasswd | 准备 secret store 所引用的文件。网关要求 server.crt、server.key 和 Basic Auth 密码文件；证书 SAN 覆盖客户端实际使用的名称。首次使用组织签发的证书，或在受控 CA 流程签发并把公开 CA 安装到客户端。新 htpasswd 可用交互式 htpasswd -Bc 创建；已有文件加用户用 -B。检查 Nginx worker 能读 htpasswd。 |

模板把 shared/secrets 只读挂载。已有凭据供执行使用时保留只读；若部署范围含通过 API 登记新凭据，核对 FileSecretStore 写入路径，只给负责登记的服务所需挂载写权限。网关默认仅向宿主回环发布 18443；沿用经授权的 SSH 转发或既有统一 HTTPS 入口。需要新域名时同步 DNS/转发、证书 SAN 和网关配置。确认连通前勿扩大端口绑定。

首次配置网关时，在目标 release 创建 shared/secrets、shared/tls 私有目录。使用已有证书时校验证书链和主机名；需要新签发时可在目标机生成私钥和 CSR，把 CSR 送交受信 CA。下面的签发申请示例用于 DNS 名；若客户端通过 IP 访问，SAN 应填写 IP 类型。安装 CA 返回的完整服务证书链至 server.crt，CA 的签名私钥始终保留在 CA 上。

~~~bash
# 仅首次：下面的文件保护检查必须通过才可创建
: "${ACCESS_NAME:?set gateway DNS name}" "${WEB_USER:?set login name}"
install -d -m 700 shared/secrets shared/tls
test ! -e shared/tls/server.key && test ! -e shared/tls/server.csr || exit 1
openssl req -new -newkey rsa:3072 -nodes -keyout shared/tls/server.key \
  -out shared/tls/server.csr -subj "/CN=$ACCESS_NAME" -addext "subjectAltName=DNS:$ACCESS_NAME"
test ! -e shared/htpasswd || exit 1
htpasswd -Bc shared/htpasswd "$WEB_USER"
# 已安装 server.crt 后
openssl x509 -in shared/tls/server.crt -noout -dates -checkhost "$ACCESS_NAME"
~~~

htpasswd 使用只读文件挂载；可给实际 nginx worker GID 只读权限，私钥仅授予加载 TLS 的进程。不得为修复 403/500 一并放宽 shared/secrets。实例设置完成后把客户端需要的公开 CA 和入口另行交付。

## 4. 按依赖启动并核对

在目标 release 中设置 PROJECT 为第 1 步确认的项目名，以下 dc 函数供本手册及验收/恢复手册共用。Compose v1 回退需 docker-compose 在 PATH 中，或将数组首项设为实测绝对路径。升级沿用既有卷并逐一比对 docker inspect 的 Mounts。network-anchor 有实例依附时，重建它需在停写维护窗口内先停整套业务、清理已停的依附容器再按序重建，保留数据卷。

~~~bash
: "${PROJECT:?set the verified Compose project name}"
if docker compose version >/dev/null 2>&1; then compose=(docker compose); else compose=(docker-compose); fi
dc() { "${compose[@]}" -p "$PROJECT" -f release.json -f workers.json "$@"; }
dc config --quiet
dc config --services
dc up -d network-anchor postgres temporal-db storage
wait_for() {
  local deadline=$((SECONDS+180))
  until "$@"; do
    if (( SECONDS >= deadline )); then return 1; fi
    sleep 3
  done
}
wait_for dc exec -T postgres pg_isready -U autoeval -d autoeval
wait_for dc exec -T temporal-db pg_isready -p 5433 -U temporal
dc up -d temporal
namespace_ready() {
  dc run -T --rm --no-deps api python - <<'PY'
import asyncio
from temporalio.client import Client
from temporalio.api.workflowservice.v1 import DescribeNamespaceRequest
from autoeval.infrastructure.config import get_settings
async def probe():
    s = get_settings()
    client = await Client.connect(s.temporal_address, namespace=s.temporal_namespace)
    await client.workflow_service.describe_namespace(DescribeNamespaceRequest(namespace=s.temporal_namespace))
asyncio.run(asyncio.wait_for(probe(), timeout=10))
PY
}
wait_for namespace_ready
~~~

等两个 PostgreSQL 就绪，使用 Temporal CLI 或 SDK 确认目标 namespace 可查询（见验收手册）。MinIO 启动日志应显示 API 已就绪。失败先检查该服务的日志、卷权限、5433/9000 监听和密钥匹配。确认数据库身份、既有版本、备份可恢复之后依次执行：

~~~bash
dc run --rm --no-deps api alembic current
dc run --rm --no-deps api alembic heads
dc run --rm --no-deps api alembic upgrade head
dc run --rm --no-deps api alembic current
dc run --rm --no-deps api python -m autoeval.infrastructure.bootstrap storage
dc up -d api dispatcher workflow planning planning-execution result reconciler monitored
dc run --rm --no-deps gateway nginx -t
dc up -d gateway
dc ps
~~~

current 应等于本镜像唯一 head；多 head、未知 revision、迁移失败立即停止切换。development 的 storage bootstrap 应确认桶可访问；已有桶保留原数据，在 test 环境使用管理员准备好的桶。检查每个 API/后台容器的实际 .Image 与 images.json 中 backend 相同。planning 是预检/规划协调进程，planning-execution 才是 Temporal 执行角色；不要为就绪检查启用吞吐探测或独立付费分析。

可选 Langfuse 使用 docs/langfuse-integration.md。在具备网络和依赖的独立 Linux 环境从源码根目录执行 `bash deploy/langfuse/setup.sh "$NEW_LANGFUSE_DIR"`。该脚本固定 fork 版本，运行 doctor 和 init，后者会启动独立服务并等待健康检查。已有实例沿用。全离线环境需先准备该 fork 与依赖和离线镜像包，用对应版本的 harborstack install --help 核对 --from-bundle 后再 init。验证网页登录；把 API 地址、浏览器地址、项目及 server-side keys 配入后端，重建读取配置的进程并执行 `dc up -d langfuse`。有已授权轨迹时验证跳转并记录展示范围。

继续执行[验收与恢复](acceptance-recovery.md)。
