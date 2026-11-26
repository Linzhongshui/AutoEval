# AutoEval 平台侧升级手册

适用场景：已有数据的 Linux 内网单机部署，使用 Docker Compose 管理平台，SSH 测评机继续使用现有环境。目标为 2026-11-25 核对的 [main 提交 1a327972503b85fab866a62019a0de8bcca7bc39](https://github.com/llauren48/AutoEval-Platform/commit/1a327972503b85fab866a62019a0de8bcca7bc39)。本文是升级操作说明，现场验收由部署人员填写。

| 更新位置 | 本次动作 |
| --- | --- |
| 平台机 | 同一提交构建网页和后端镜像；替换 API、分发器、规划、执行协调、结果收集和对账等已启用的平台进程。网关沿用现有镜像，切换静态文件挂载。 |
| 业务库 | 在原库运行 Alembic。以此前的 `347b335` 为基线，0043 给执行配置关联工具参数，0044 新建独立的配置名称表。两项迁移均保留原报告、榜单和任务数据。更早环境需审核中间全部迁移。 |
| 基础设施与测评机 | 复用当前 PostgreSQL、Temporal、S3、网关认证、密钥和 SSH 资源。离线传输只含平台应用。无需在 x86/ARM 测评机加载镜像、安装 Pier/MiniSwe、重新导入数据集或基础 SQL。 |

本版可从控制台按模型服务查看执行配置列表、查看详情、命名和复制配置；还包含标准输入详情、模型映射、计费与任务恢复的更新。新增 Harbor 工具锁随平台后端交付。选择新的工具版本跑任务前，仍须核对测评机实际安装版本。此前开发分支上的“手动指定 SSH 资源进行模型连通测试”提交 `b8413cb` 未合入本次固定提交。

## 1. 确认现网并记录回退点

在平台机运行以下 Bash 命令。先定位实际 API 容器，再读取部署项目与文件顺序。命令示例适用 Compose v2 和仓库服务名；定制部署先按现场服务建立对应关系。

```bash
set -euo pipefail
docker ps --format '{{.Names}} {{.Label "com.docker.compose.project"}} {{.Label "com.docker.compose.service"}}'
: "${API_CONTAINER:?填入现网 API 容器名}"
docker inspect -f '{{index .Config.Labels "com.docker.compose.project.working_dir"}} {{index .Config.Labels "com.docker.compose.project.config_files"}}' "$API_CONTAINER"
docker inspect -f '{{.Image}} {{range .Mounts}}{{.Source}} -> {{.Destination}} {{end}}' "$API_CONTAINER"
docker info --format '{{.OSType}}/{{.Architecture}}'
df -h
```

在现网发布目录，设置下列变量并保持同一 Bash 会话。`OLD_FILES` 是有序的 Compose 文件绝对路径数组，包含正在使用的覆盖文件；同步沿用原部署的环境文件、profiles 和项目目录参数。若网关在 Compose 之外，由其现有发布机制切换静态目录。

```bash
PROJECT=$(docker inspect -f '{{index .Config.Labels "com.docker.compose.project"}}' "$API_CONTAINER")
IFS=, read -ra OLD_FILES <<< "$(docker inspect -f '{{index .Config.Labels "com.docker.compose.project.config_files"}}' "$API_CONTAINER")"
BASE=(docker compose -p "$PROJECT")
for f in "${OLD_FILES[@]}"; do test -r "$f"; BASE+=(-f "$f"); done
old() { "${BASE[@]}" "$@"; }
old ps -a
old config --services
old exec -T api alembic current
```

记录当前发布目录、镜像 ID、迁移号、业务库/Temporal/S3 卷标识、入口及一份已有报告、榜单条目和证据对象。核对 API 与 Worker 的启动命令、挂载和临时热修，特别是标准仓同步、Tag 显示和网关路由；切换前逐项确认新版实现或保留现场适配。如果容器挂载了旧应用源码，会遮盖新镜像，须先处理。保存可启动的旧 Compose、镜像和前端文件。

## 2. 从 OBS 获取本次已发布的平台包

发布提交为 `1a327972503b85fab866a62019a0de8bcca7bc39`。两个后端镜像均在 179.214.2.3 构建。构建复用了前一版同架构镜像中已锁定的依赖，已核对两个版本的 pyproject.toml 和 uv.lock 一致。AMD64 通过原生容器验证，ARM64 通过 QEMU 容器验证。两者均检查了 API 和后台模块导入、迁移头及 HTTP 存活接口。前端从同一提交单独构建并通过类型检查。上传后的三个归档和清单均已从 OBS 回读并校验 SHA-256。

| 发布对象 | OBS 路径 | SHA-256 |
| --- | --- | --- |
| 发布清单 | `obs://aisbench/images/autoeval/releases/20261125-1a32797/52120e1f89d4/manifest.json` | `52120e1f89d4992028935969365ebb12a693b9908beb546df20f44b2e7966f9e` |
| Linux AMD64 平台后端 | `obs://aisbench/images/autoeval/releases/20261125-1a32797/6ea146cba08d/platform-amd64.tar.gz` | `6ea146cba08dfdf5e5ba6f5f55e3510eb2c3cc74b6181896a11ea7102fca8bf7` |
| Linux ARM64 平台后端 | `obs://aisbench/images/autoeval/releases/20261125-1a32797/6c867067419c/platform-arm64.tar.gz` | `6c867067419cbbf4bda42510d015026c52555a6f8a4e9583e42222e614bc44e1` |
| 两种架构共用的前端 | `obs://aisbench/images/autoeval/releases/20261125-1a32797/6940550b7368/frontend-dist.tar.gz` | `6940550b7368e65a7625945344dade31597e19c9890180145bfd328e58a29cbf` |

在有桶读取权限的传输机执行以下 Bash 命令。`REL` 是本次发布的新绝对目录。根据**平台 Docker 主机**选择 `ARCH=amd64` 或 `ARCH=arm64`。配置好的 obsutil 使用所在环境的凭据。

```bash
set -euo pipefail
: "${REL:?新的绝对发布目录}" "${ARCH:?amd64 或 arm64}"
case "$ARCH" in amd64|arm64) ;; *) exit 1 ;; esac
mkdir -m 700 "$REL"
cd "$REL"
obsutil cp 'obs://aisbench/images/autoeval/releases/20261125-1a32797/52120e1f89d4/manifest.json' manifest.json
echo '52120e1f89d4992028935969365ebb12a693b9908beb546df20f44b2e7966f9e  manifest.json' | sha256sum -c -
python3 - "$ARCH" <<'PY'
import json, pathlib, subprocess, sys
m = json.loads(pathlib.Path("manifest.json").read_text())
assert m["source"] == "1a327972503b85fab866a62019a0de8bcca7bc39"
backend = m["backend"][sys.argv[1]]
for item, name in [(backend, "platform.tar.gz"), (m["frontend"], "frontend-dist.tar.gz")]:
    subprocess.run(["obsutil", "cp", item["uri"], name], check=True)
    subprocess.run(["sha256sum", "-c", "-"], input=item["sha256"]+"  "+name+"\n", text=True, check=True)
pathlib.Path("image-id").write_text(backend["image_id"]+"\n")
pathlib.Path("source-revision").write_text(m["source"]+"\n")
PY
sha256sum manifest.json platform.tar.gz frontend-dist.tar.gz image-id source-revision > SHA256SUMS
```

将整个发布目录通过批准的通道传给离线平台机，另行记录 SHA256SUMS 的摘要。目标机无须联网拉镜像。在平台机设置 REL 后执行：

```bash
cd "$REL"
sha256sum -c SHA256SUMS
docker load -i platform.tar.gz
IMAGE=$(cat image-id)
docker image inspect -f '{{.Id}} {{.Os}}/{{.Architecture}} {{index .Config.Labels "org.opencontainers.image.revision"}}' "$IMAGE"
tar -xzf frontend-dist.tar.gz
test -s dist/index.html
```

核对镜像 ID、平台机架构、完整提交后，直接继续第 3 节。目标环境的数据库迁移、Worker 轮询和历史报告抽查仍须按后文完成。

### 可选：自行重建离线包

在可联网且与**平台机** CPU 架构一致的 Linux 构建机、仓库根目录执行。准备 Node 22+、uv、Docker 和与离线 Dockerfile 基础镜像兼容的 Linux Python 3.12/pip。为两个路径选择不存在的绝对目录。若采用预构建镜像，须有相同提交、架构及镜像 ID 的发布记录，前端也必须来自该提交。

```bash
set -euo pipefail
REV=1a327972503b85fab866a62019a0de8bcca7bc39
: "${BUILD:?新源码目录}" "${OUT:?新发布目录}" "${PLATFORM:?linux/amd64 或 linux/arm64}"
mkdir -m 700 "$BUILD" "$OUT"
git archive "$REV" | tar -x -C "$BUILD"
cd "$BUILD"
printf '%s\n' "$REV" > "$OUT/source-revision"
(cd frontend && npm ci && npm run build)
cp -a frontend/dist "$OUT/dist"
cd backend
uv lock --check
mkdir wheels
uv export --frozen --no-dev --no-emit-project --no-hashes --format requirements-txt -o "$BUILD/runtime.txt"
python3.12 -m pip wheel --no-deps -r "$BUILD/runtime.txt" -w wheels
uv build --wheel --out-dir wheels .
(cd wheels && sha256sum *.whl > SHA256SUMS)
cd "$BUILD"
TAG="autoeval-platform:${REV:0:12}-${PLATFORM#linux/}"
docker build --platform "$PLATFORM" --label "org.opencontainers.image.revision=$REV" \
  -f deploy/intranet/backend.offline.Dockerfile -t "$TAG" .
docker run --rm "$TAG" alembic heads
docker run --rm "$TAG" sh -ec 'pip check && test -r /app/tool-locks/aisbench-harbor-d97a8e7.json'
docker image inspect -f '{{.Id}}' "$TAG" > "$OUT/image-id"
docker save -o "$OUT/platform.tar" "$TAG"
(cd "$OUT" && find . -type f ! -name SHA256SUMS -print0 | sort -z | xargs -0 sha256sum > SHA256SUMS)
(cd "$OUT" && sha256sum SHA256SUMS)
```

迁移头应只有 `0044_compilation_display_name`。将整个 OUT 传入平台机新的持久发布目录，经可信渠道另行传递清单摘要。在平台机设置 `REL` 为该目录绝对路径，核对根摘要后执行：

```bash
: "${REL:?本次发布绝对路径}"
(cd "$REL" && sha256sum SHA256SUMS && sha256sum -c SHA256SUMS)
docker load -i "$REL/platform.tar"
IMAGE=$(cat "$REL/image-id")
docker image inspect -f '{{.Os}}/{{.Architecture}} {{index .Config.Labels "org.opencontainers.image.revision"}}' "$IMAGE"
test "$(cat "$REL/source-revision")" = 1a327972503b85fab866a62019a0de8bcca7bc39
test -s "$REL/dist/index.html"
```

核对镜像显示的架构和完整提交。挂载 dist 的每级目录需满足现场 Docker 和网关的读取权限。

## 3. 生成仅涉及应用的覆盖文件

在平台机沿用第 1 步的会话。盘点所有启用的平台后端角色，包括独立项目或宿主服务。下面的 APPS 是标准发布示例，按现网增减；已有 Langfuse 导入 Worker 则加入其服务名。结果收集依赖 result，缺少该服务时先按固定版本的[内网手册](https://github.com/llauren48/AutoEval-Platform/blob/1a327972503b85fab866a62019a0de8bcca7bc39/.skills/deploy-autoeval/references/intranet.md)补齐角色。避免遗漏在另一项目中的旧 Worker。

```bash
APPS=(api dispatcher workflow planning planning-execution monitored result reconciler)
for s in "${APPS[@]}" gateway; do old config --services | grep -Fxq "$s" || { echo "核对服务 $s"; exit 1; }; done
python3 - "$REL" "$IMAGE" "${APPS[@]}" <<'PY'
import json, pathlib, sys
release = pathlib.Path(sys.argv[1]).resolve()
services = {s: {"image": sys.argv[2]} for s in sys.argv[3:]}
services["gateway"] = {"volumes": [f"{release}/dist:/usr/share/nginx/html:ro"]}
with (release / "platform.override.json").open("x") as f:
    json.dump({"services": services}, f, indent=2)
PY
new() { "${BASE[@]}" -f "$REL/platform.override.json" "$@"; }
new config --quiet
new run --rm --no-deps gateway nginx -t
new run --rm --no-deps api alembic heads
```

在受保护终端检查合并配置：应用镜像均为新 ID，网关仅替换静态目录，认证、证书、反向代理、网络锚点及业务卷均指向原位置。保留 `platform.override.json`，后续服务管理也需加载它。若另有 CDN 或外层网关提供首页，须核对实际首页由哪一层提供。

## 4. 停写、备份和迁移

1. 在入口进入维护窗口，关闭新提交、定时作业及其他写入，等待在途任务和外部请求结束。对结果未知的模型请求先核对账本。记录迁移前报告与证据标识。
2. 执行 `old stop "${APPS[@]}"`，停用其他写入方。按[有数据的升级与备份、隔离恢复](https://github.com/llauren48/AutoEval-Platform/blob/1a327972503b85fab866a62019a0de8bcca7bc39/.skills/deploy-autoeval/references/acceptance-recovery.md#有数据的升级与备份)冻结 Temporal 服务，备份业务库、两个 Temporal 库、S3 对象、配置、凭据和旧发布。数据库、对象存储和网络锚点保持运行。在独立空目标验证可恢复、报告对象可回读后继续。
3. 在原平台项目执行以下命令。若旧 revision 不在新镜像历史中，或数据库已有同名表/列但 revision 不符，保留日志并暂停；直接标记迁移完成会掩盖实际结构差异。

```bash
new run --rm --no-deps api alembic current
new run --rm --no-deps api alembic history
new run --rm --no-deps api alembic upgrade head
new run --rm --no-deps api alembic current
```

确认 current 为 `0044_compilation_display_name (head)`。恢复已暂停的原 Temporal 服务（标准项目执行 `old start temporal`），验证原 namespace 可查询。随后只重建应用和提供静态文件的网关：

```bash
new up -d --no-deps --pull never --force-recreate "${APPS[@]}"
new up -d --no-deps --pull never --force-recreate gateway
new ps
for s in "${APPS[@]}"; do
  ids=$(new ps -q "$s"); test -n "$ids"
  for id in $ids; do test "$(docker inspect -f '{{.Image}}' "$id")" = "$IMAGE"; done
done
```

## 5. 开放入口前的验收与回退

| 从哪里检查 | 通过条件与失败定位 |
| --- | --- |
| 平台机 | 在 API 容器执行下列探测，两项返回 200。失败先看 `new logs --tail 100 api` 和迁移结果，核对原库、S3 和 Temporal 连接。 |
| 平台调度 | API 和所有启用角色运行；在原 Temporal namespace 核对工作流、执行和结果队列有对应轮询者，分发器、规划及对账进程无循环报错。队列检查方法见上述验收手册。 |
| 用户浏览器 | 通过真实 HTTPS 入口登录，从控制台选择原有模型服务，打开“执行配置列表”和已有配置详情，核对名称、配置与样本范围；从测评配置页核对已登记标准输入和已知 Tag。若仍看到旧界面，比对网关挂载与浏览器加载的 JS 文件名。 |
| 原有数据 | 用升级前记录的标识打开同一历史任务、报告和榜单记录，回读一个证据对象并核对摘要。页面为空时先核对数据库和桶的身份。 |

```bash
new exec -T api python -c 'import httpx; c=httpx.Client(trust_env=False, timeout=15); urls=["http://127.0.0.1:8000/health/"+p for p in ("live","ready")]; rs=[c.get(u) for u in urls]; print([r.status_code for r in rs]); [r.raise_for_status() for r in rs]'
```

在验收记录填写实际提交、平台架构、镜像 ID、迁移前后版本、备份位置、入口、队列及历史报告抽查结果。通过后，把日常启动及重启命令切换为含新覆盖文件的 Compose 配置，再开放写入。本次验收不触发真实模型请求。

**回退决策。** 迁移前失败，使用原发布配置和静态目录恢复已停止的服务。迁移后失败，保持维护窗口、停新应用并保存日志，记录切换后写入。0044 降级会删除配置名称表，0043 在存在配置级工具参数时会拒绝降级。兼容性未经验证时，按第 4 步的恢复手册将同一备份点的业务库、Temporal、对象和受保护配置恢复到独立卷，与旧镜像、旧网页配套验证，再切回入口；保留故障卷并核对增量数据。全程避免清卷、重灌基础数据或强制重发任务。
