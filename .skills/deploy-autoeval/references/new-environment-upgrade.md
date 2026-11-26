# 新环境部署 AutoEval 并运行 DeepSWE Lite

适用发布为 `347b3352ecfeaeb18f925a30518d9af7298a871d`，业务库目标 revision 为 `0042_target_service_kind`。以下命令使用 Bash。交接时记录平台主机、执行节点、Docker context、入口、模型 ID 和凭据引用。

## 1. 确定两台机器各自需要什么

| 位置 | 取用资源 | 验收 |
| --- | --- | --- |
| AMD64 平台节点 | 主清单中的 platform-backend、frontend-dist，以及目标需要的基础服务 | API、全部 Worker、网关及数据库迁移 |
| ARM64 平台节点 | ARM 清单中的 platform_backend、主清单中的同版 frontend-dist；逐一准备 ARM64 PostgreSQL、Temporal、对象存储、网关及 network-anchor 镜像 | 在目标原生节点复验。既有服务器的验证为 x86_64 上 QEMU 运行 ARM64 API，未覆盖数据库升级和 Worker 轮询 |
| Linux x86_64 执行节点 | 主清单中的 deepswe-pier-x86、Lite 任务镜像、固定任务目录 | 先 Oracle，再按授权运行真实模型。同为 AMD64 时可以和平台共机 |

在**每个节点**运行 `uname -m` 和 `docker info --format '{{.OSType}}/{{.Architecture}}'`。11 月 24 日的基础设施快照只提供 AMD64 镜像。纯 ARM64 环境可以先部署平台；本版 Pier 单题流程还需要 x86_64 执行节点。原生 Pier 在执行节点发起。若验收要求从平台页面提交并查看报告，走第 5 节的 AISBench/Harbor 路径。

## 2. 在中转机取包，在目标机校验

中转机准备 obsutil、jq、sha256sum，在新的发布缓存目录运行。按两节点实际架构选择包，可将以下文件分开传至对应节点。

~~~bash
set -euo pipefail
base=obs://aisbench/images/autoeval/releases/20261125-347b335
obsutil cp "$base/manifest-927d8667ac59.json" main.json
obsutil cp "$base/arm64/manifest-ee847971f85f.json" arm.json
echo '927d8667ac5962ca824937db96e8c316d4971c2a6813c032235b1003e9a6065f  main.json' | sha256sum -c -
echo 'ee847971f85f2122dcf49c6cf2a5479cdbfcc52d339c19cfe50cc2de42cb6355  arm.json' | sha256sum -c -
get_asset() {
  local uri sha
  uri=$(jq -er "$2.uri" "$1")
  sha=$(jq -er "$2.sha256" "$1")
  obsutil cp "$uri" "$3"
  printf '%s  %s\n' "$sha" "$3" | sha256sum -c -
}
case "${PLATFORM_ARCH:?设置为 amd64 或 arm64}" in
  amd64) get_asset main.json '.archives["platform-backend"]' backend.tar.gz ;;
  arm64) get_asset arm.json '.platform_backend' backend.tar.gz ;;
  *) exit 1 ;;
esac
get_asset main.json '.archives["frontend-dist"]' frontend.tar.gz
get_asset main.json '.archives["deepswe-pier-x86"]' pier.tar.gz
~~~

按 [OBS 镜像手册](obs-images.md) 取 `deepswe-lite` 镜像归档和快照清单，再按[跨环境测评资源](evaluation-bootstrap.md)获取加密数据资源包和单独保管的解密口令。执行侧需解包 `execution-assets.tar.gz` 并校验 `files.sha256`，确认 `deepswe/tasks/abs-module-cache-flags/task.toml`、`solution/`、`tests/` 齐全。仅导入榜单 SQL 或模型列表无法发起测评。

目标机收到文件后，使用上面的独立摘要复核对应清单。下面函数在目标机使用，输入为已校验清单中的镜像条目。平台节点按自身架构加载 backend，执行节点只需加载 pier 及 Lite 任务归档。

~~~bash
set -euo pipefail
load_image() {
  local sha tag id platform
  sha=$(jq -er "$2.sha256" "$1")
  tag=$(jq -er "$2.tag" "$1")
  id=$(jq -er "$2.image_id" "$1")
  platform=$(jq -er "$2.platform" "$1")
  printf '%s  %s\n' "$sha" "$3" | sha256sum -c -
  if docker image inspect "$tag" >/dev/null 2>&1; then
    test "$(docker image inspect -f '{{.Id}}' "$tag")" = "$id"
  fi
  docker load -i "$3"
  test "$(docker image inspect -f '{{.Id}} {{.Os}}/{{.Architecture}}' "$tag")" = "$id $platform"
}
# 按节点选一行
# load_image main.json '.archives["platform-backend"]' backend.tar.gz
# load_image arm.json '.platform_backend' backend.tar.gz
# load_image main.json '.archives["deepswe-pier-x86"]' pier.tar.gz
~~~

## 3. 首次安装、迁入数据或原地升级

1. **空白环境。** 按[内网部署手册](intranet.md)建立新发布目录，准备同提交的 Compose、迁移、网关配置、TLS、认证、受保护配置及持久化卷。复用上述成品时跳过镜像和前端的重新构建。在新发布目录创建 `frontend/`，按主清单 SHA-256 校验 `frontend.tar.gz`，执行 `tar -xzf "$FRONTEND_ARCHIVE" -C frontend`，确认 `frontend/dist/index.html` 存在。将所选 backend 的 **image_id** 填入 `images.json` 的 `backend`，其余五个基础镜像键填写目标引擎已验证的同架构 ID。按手册渲染并检查 `release.json`、`workers.json`。
2. **迁入旧环境的历史报告。** 在源环境停止接单，核对在途任务及不确定模型请求；按[备份和隔离恢复操作](acceptance-recovery.md)一致备份业务库、Temporal、S3 对象及受保护配置，在隔离目录/新卷恢复并核对旧版可读。迁移前记录代表性榜单、报告 ID、Case 数量和关联对象摘要。目录种子适用于空库初始化；历史运行、报告与证据需要配套数据库和对象备份。
3. **已有数据原地升级。** 沿用现有 Compose 项目、卷、凭据和网关入口，确认停写和隔离恢复演练成功。保留旧镜像与旧发布目录。从相同源码生成新的 Compose，带入已有挂载、资源配置和启用的 Worker。核对所有服务实际渲染的镜像，尤其是分发、结果收集和执行角色；出现架构不符或历史后端标签时先修正。
4. **执行切换。** 在新 release 目录按[内网部署手册](intranet.md)定义 `dc`，检查 `dc config --quiet`，启动并等待 PostgreSQL、Temporal 及对象存储就绪。运行下面的迁移，再按手册初始化存储、启动后台角色并验证网关。发现未知 revision、多 head 或迁移失败时停止业务启动，保留日志和现场。

~~~bash
set -euo pipefail
dc run --rm --no-deps api alembic current
dc run --rm --no-deps api alembic heads  # 预期仅 0042_target_service_kind
dc run --rm --no-deps api alembic upgrade head
dc run --rm --no-deps api alembic current  # 核对 0042_target_service_kind
~~~

从目标客户端核对 TLS、认证、首页、经网关的 API、`/health/live` 和 `/health/ready`。按[验收与恢复](acceptance-recovery.md)检查业务命名空间的 Worker 轮询、分发器和对账进程，回读之前记录的榜单、报告、Case 及对象摘要。迁移不兼容时停写，按演练过的流程恢复配套数据库、Temporal、对象和旧发布，再开放流量。

## 4. 在 x86 节点用预装 Pier 镜像跑一个样本

成品镜像内已有 `/opt/pier`、`/opt/miniswe` 和 `/opt/pier-lite`。下面从宿主启动控制容器，保留 Pier 需要的宿主绝对路径。设置 `ASSETS` 为已验证的执行资源解包目录，`JOBS` 为新建的私有可写目录，`SKILL` 为部署 Skill 的目录，`RUNTIME_MANIFEST` 为已校验的 11 月 24 日镜像清单，均使用绝对路径。使用本地 Docker Unix socket 的受信任执行账号。下例针对常规 Linux Docker；rootless 节点按 [Pier 执行手册](deepswe-pier-x86.md)核对 socket 和用户映射。

~~~bash
set -euo pipefail
umask 077
mkdir -p "$JOBS"
image=autoeval/deepswe-pier-x86:20261125-347b335
test "$(docker image inspect -f '{{.Id}}' "$image")" = "$(jq -er '.archives["deepswe-pier-x86"].image_id' main.json)"
controller() {
  docker run --rm -it --pull never --network "$1" \
    -v /var/run/docker.sock:/var/run/docker.sock \
    -v "$ASSETS:$ASSETS:ro" -v "$JOBS:$JOBS" -v "$SKILL:$SKILL:ro" \
    -v "$RUNTIME_MANIFEST:$RUNTIME_MANIFEST:ro" \
    -e "TASKS=$ASSETS/deepswe/tasks" -e "JOBS=$JOBS" -e "SKILL=$SKILL" \
    -e "RUNTIME_MANIFEST=$RUNTIME_MANIFEST" --entrypoint /bin/bash "$image"
}
controller none
~~~

在断网控制容器内运行。若缺少镜像，检查 Lite 归档是否导入**该 socket 对应的引擎**。Oracle 应生成非空补丁，修复测试 20/20、回归测试 3/3、reward 为 1。按 [Pier 手册](deepswe-pier-x86.md)核对 trial 异常、补丁和 CTRF 后退出容器。

~~~bash
set -euo pipefail
python3.12 "$SKILL/scripts/check_deepswe_pier_images.py" --manifest "$RUNTIME_MANIFEST" --tasks "$TASKS" --task abs-module-cache-flags
job=oracle-$(cat /proc/sys/kernel/random/uuid)
pier run -p "$TASKS/abs-module-cache-flags" --env docker --agent oracle \
  --jobs-dir "$JOBS" --job-name "$job" --n-attempts 1 --n-concurrent 1 --max-retries 0 --no-force-build
cat "$JOBS/$job"/*/verifier/reward.json
~~~

真实模型需要目标环境自己的模型 ID、网关、凭据和预算。由宿主调用 `controller "$MODEL_NETWORK"`，其中网络允许控制端访问已批准的网关。任务和 verifier 仍按题目配置禁网。在新控制容器内设置 `MODEL_ID` 和 `OPENAI_API_BASE`，运行：

~~~bash
set +x
set -euo pipefail
: "${MODEL_ID:?设置实际模型 ID}" "${OPENAI_API_BASE:?设置受信网关基址}"
IFS= read -rs -p '模型凭据：' OPENAI_API_KEY
echo
export OPENAI_API_BASE OPENAI_API_KEY MINISWE_MODE=tools
# 按本次授权设置 MINISWE_COST_LIMIT、MINISWE_STEP_LIMIT。硬费用上限由网关执行。
# 复现既有 deepseek-flash 工具调用配置时，另设 export MINISWE_THINKING_DISABLED=1
job=model-$(cat /proc/sys/kernel/random/uuid)
echo "$JOBS/$job"
pier run -p "$TASKS/abs-module-cache-flags" --env docker \
  --agent-import-path local_pier_agent:ControllerMiniSwe --model "openai/$MODEL_ID" \
  --jobs-dir "$JOBS" --job-name "$job" --n-attempts 1 --n-concurrent 1 --max-retries 0 --no-force-build
~~~

回读同一 trial 下的 `result.json`、`agent/agent-status.json`、`artifacts/model.patch`、`verifier/reward.json` 和 `verifier/ctrf.json`。分别记录模型响应次数、退出原因、测试通过数与原生 reward。历史单题真实测评是 12/23、reward 0；新环境应如实记录自己的结果。遇到模型请求结果未知，先沿原 job 和网关账本核查。

## 5. 需要从 AutoEval 页面提交时

在[跨环境测评资源手册](evaluation-bootstrap.md)执行基础数据导入与对象回读，重新绑定本环境的模型服务、SSH x86 执行资源、DeepSWE Lite 任务目录与 AISBench/Harbor 工具模板，然后重新编译输入。确认相应 Worker 预检通过，再从任务页面选择一个 Lite 样本并提交一次。按同一 run ID 核对分发、Temporal、S3、Case 与报告页。原生 Pier 的 job/trial 与控制台的 run/report 分别登记；这版平台没有将独立 Pier 成绩自动导入正式报告的适配。交付记录应注明采用哪条路径、实际架构、镜像 ID、迁移 revision、模型、样本及未验项。

