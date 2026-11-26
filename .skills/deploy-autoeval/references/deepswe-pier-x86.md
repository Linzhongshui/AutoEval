# 在 Linux x86_64 上用原生 Pier 跑 DeepSWE v1.1

当交付条件指定 `pier run`、Pier 轨迹或独立 verifier 时，使用本页。当前 AutoEval 的统一测评入口为 DeepSWE 编译 `harbor_agent`，按 Harbor 工具身份调度、归档。原生 Pier 在独立执行节点发起，保留 Pier job/trial 标识。若要求控制台发起或显示正式报告，先核对目标发布是否已有 Pier 的编译、执行与结果导入适配。当前代码中的 `peir` 标识只有模板分发测试，不能用它为原生结果创建平台成绩。

本流程锁定任务提交 `0b9fabbb63b9104d678fe965e1632f2dd9eaa2ea`、Pier 0.3.1（提交 `df89f994623a0a6a57229103b6fe910766693c30`）、Harbor Python 依赖 0.5.0。DeepSWE v1.1 要求 Pier 高于 0.3.0。Agent 提交改动后，任务的 collect hook 导出补丁，独立 verifier 在干净环境应用补丁并评分。上游榜单使用的运行环境为 Modal，应在结果中标清本次使用本地 Docker。[DeepSWE 任务与评分](https://github.com/datacurve-ai/deep-swe/blob/0b9fabbb63b9104d678fe965e1632f2dd9eaa2ea/README.md) · [Pier 版本声明](https://github.com/datacurve-ai/pier/blob/df89f994623a0a6a57229103b6fe910766693c30/pyproject.toml)

## 1. 导入指定的 x86 执行镜像

本次指定的执行镜像是 AISBench Agent Runtime `v3.1-20261119-master`，独立于 11 月 24 日的 AutoEval 快照发布。[OBS 镜像归档](https://aisbench.obs.cn-north-4.myhuaweicloud.com/images/agent_time/ais_bench_agent_runtime_image_v3.1-20261119-master-ubuntu24.04-py312-x86_64.tar.gz)

实物检查确认 `/benchmark` 的提交为 `e968d1bd7f48404bd913b95560f33938072336fa`，系统 Python 为 3.12.3，AISBench 命令位于 `/usr/local/bin/ais_bench`，`/opt/venvs/harbor` 内的 Harbor 为 0.21.0。系统 Python 与 Harbor 环境均未安装 `datacurve-pier`。要跑原生 Pier，按第 2 节在独立环境安装其锁定依赖，保留 AISBench 自带的 Harbor。每题的工作区与独立评分容器使用第 3 节的任务镜像。[发布 Dockerfile](https://github.com/AISBench/benchmark/blob/e968d1bd7f48404bd913b95560f33938072336fa/docker/agent_runtime/Dockerfile.agent-runtime) · [运行说明](https://github.com/AISBench/benchmark/blob/e968d1bd7f48404bd913b95560f33938072336fa/docker/agent_runtime/USAGE.md)

在可访问 OBS 的中转机进入发布缓存目录，下载执行镜像。核对文件为 1,034,678,851 字节，使用完整归档的 SHA-256 校验传输。

~~~bash
set -euo pipefail
archive=ais_bench_agent_runtime_image_v3.1-20261119-master-ubuntu24.04-py312-x86_64.tar.gz
obsutil cp "obs://aisbench/images/agent_time/$archive" "./$archive"
test "$(wc -c < "$archive")" -eq 1034678851
printf '%s  %s\n' d3e0bf430687db8e9e4d16d59c3f9f18092cf86da9f1775b50244e4c89da7976 "$archive" | sha256sum -c -
~~~

将归档送至执行节点，在接收目录执行下列命令。先核对目标 Docker 引擎，再按归档中的标签导入。已有同名标签绑定其他 ID 时保留现场，核查依赖该标签的模板与在途任务。

~~~bash
set -euo pipefail
archive=ais_bench_agent_runtime_image_v3.1-20261119-master-ubuntu24.04-py312-x86_64.tar.gz
tag=ghcr.io/aisbench/agent-runtime:v3.1-20261119-master-ubuntu24.04-py312-x86_64
id=sha256:96621d743152db4115d5d1c169379e9e7952349ddbb4d4261a83ec9637d4d917
printf '%s  %s\n' d3e0bf430687db8e9e4d16d59c3f9f18092cf86da9f1775b50244e4c89da7976 "$archive" | sha256sum -c -
docker info --format '{{.Name}} {{.OSType}}/{{.Architecture}}'
if docker image inspect "$tag" >/dev/null 2>&1; then
  test "$(docker image inspect -f '{{.Id}}' "$tag")" = "$id"
fi
docker image load -i "$archive"
test "$(docker image inspect -f '{{.Id}} {{.Os}}/{{.Architecture}}' "$tag")" = "$id linux/amd64"
docker run --rm --pull never --network none --entrypoint /bin/bash "$id" -c \
  'set -eu; uname -m; /opt/venvs/harbor/bin/harbor --help >/dev/null'
~~~

在平台执行模板中选用此版本时，用新模板版本冻结该标签、镜像 ID 和工具身份，并用实际 Worker 预检模板入口、任务清单及卷挂载。已有发布和历史任务保留原模板引用。

## 2. 准备原生 Pier 的离线控制端

在已配置 OBS 只读访问的中转机下载 Pier 控制端。补充包包含 140 个 wheel、两份依赖锁和校验清单，已在 Debian 13 x86_64 / Python 3.12.16 验证。随执行镜像转入目标机，目标需具备兼容的 Linux AMD64、CPython 3.12 与 libc。任务目录来自 OBS 测评资源包，任务镜像来自快照的 `deepswe-lite` 或 `deepswe-full` 分组。[OBS 下载说明](obs-images.md)

~~~bash
set -euo pipefail
ctrl_name=autoeval-evaluation-kit-pier-x86-controller-0.3.1.zip
obsutil cp "obs://aisbench/autoeval/deployment-resources/deepswe/pier-x86/v0.3.1/1d50b6234a75/$ctrl_name" "./$ctrl_name"
printf '%s  %s\n' 1d50b6234a755b1e325c274cbcc7be9247954e575d4104ca4d0f78aa81ebbb93 "$ctrl_name" | sha256sum -c -
~~~

### 在 Linux x86_64 执行节点启动控制容器

使用有权访问本地 Docker 引擎的执行账号。在宿主 Bash 设置 `ASSETS`（已解包的测评资源）、`SKILL`（部署 Skill 目录）、`RUNTIME_MANIFEST`（已校验的快照清单）、`CTRL_ZIP` 和 `RUN_PARENT`（有足够空间且该账号可写的工作目录）。指定镜像内置 Docker CLI 27.3.1 和 Compose v2.29.7，已验证可连接本机引擎并列出 Compose 项目。本文记录的单题实测使用另行提供的 Compose v5.7.0。部署时记录实际客户端、插件和引擎版本。

~~~bash
set -euo pipefail
umask 077
ASSETS=$(realpath -e "$ASSETS")
SKILL=$(realpath -e "$SKILL")
RUNTIME_MANIFEST=$(realpath -e "$RUNTIME_MANIFEST")
CTRL_ZIP=$(realpath -e "$CTRL_ZIP")
RUN_PARENT=$(realpath -e "$RUN_PARENT")
TASKS="$ASSETS/deepswe/tasks"
test -r "$TASKS/abs-module-cache-flags/task.toml"
test -r "$RUNTIME_MANIFEST" && test -r "$CTRL_ZIP" && test -r "$SKILL/scripts/check_deepswe_pier_images.py"
# 本地 Docker unix socket，可按当前执行账号的 rootless 引擎调整
socket=${PIER_DOCKER_SOCKET:-/var/run/docker.sock}
test -S "$socket"
id=sha256:96621d743152db4115d5d1c169379e9e7952349ddbb4d4261a83ec9637d4d917
docker --host "unix://$socket" image inspect "$id" >/dev/null
run=$(mktemp -d "$RUN_PARENT/pier-x86.XXXXXXXX")
CTRL="$run/controller"
JOBS="$run/jobs"
mkdir -m 700 "$CTRL" "$JOBS" "$run/home"
printf '本次工作目录 %s\n' "$run"

controller() {
  docker --host "unix://$socket" run --rm --pull never -it --network "$1" \
    --user "$(id -u):$(id -g)" --group-add "$(stat -c %g "$socket")" \
    --mount "type=bind,src=$socket,dst=/var/run/docker.sock" \
    --mount "type=bind,src=$ASSETS,dst=$ASSETS,readonly" \
    --mount "type=bind,src=$SKILL,dst=$SKILL,readonly" \
    --mount "type=bind,src=$RUNTIME_MANIFEST,dst=$RUNTIME_MANIFEST,readonly" \
    --mount "type=bind,src=$CTRL_ZIP,dst=$CTRL_ZIP,readonly" \
    --mount "type=bind,src=$CTRL,dst=$CTRL" --mount "type=bind,src=$JOBS,dst=$JOBS" \
    --mount "type=bind,src=$run/home,dst=$run/home" --env "HOME=$run/home" \
    --env "ASSETS=$ASSETS" --env "TASKS=$TASKS" --env "CTRL=$CTRL" --env "JOBS=$JOBS" \
    --env "SKILL=$SKILL" --env "CTRL_ZIP=$CTRL_ZIP" --env "RUNTIME_MANIFEST=$RUNTIME_MANIFEST" \
    --env LITELLM_LOCAL_MODEL_COST_MAP=True --workdir "$CTRL" --entrypoint /bin/bash "$id" --noprofile --norc
}
controller none
~~~

上述命令进入断网的 Oracle 控制容器。任务目录随 `ASSETS` 在完全相同的绝对路径只读可见，便于宿主引擎查找构建上下文。只有受信任的控制容器挂 Docker socket。在容器内先运行 `docker info`、`docker compose version` 和 `docker compose ls`。以当前身份验证 `test -w "$CTRL" && test -w "$JOBS"`。绑定目录不可读写或 socket 权限不匹配时，核对宿主账号、引擎用户映射及目录权限。上例的 UID/GID 适用于普通 Linux Docker 引擎，启用用户命名空间或 rootless 时要按其映射选择控制容器身份。

### 在断网控制容器中安装 Pier

首次安装时 `CTRL` 是上一步已创建的空目录。解压前验证 ZIP 的完整摘要。在同一路径重新打开控制容器时，沿用已有 venv，重新运行版本和依赖检查即可。

~~~bash
set -euo pipefail
umask 077
printf '%s  %s\n' 1d50b6234a755b1e325c274cbcc7be9247954e575d4104ca4d0f78aa81ebbb93 "$CTRL_ZIP" | sha256sum -c -
cd "$CTRL"
test ! -e venv && test ! -e SHA256SUMS
python3.12 -m zipfile -e "$CTRL_ZIP" "$CTRL"
sha256sum --quiet -c SHA256SUMS
python3.12 -m venv venv
venv/bin/python -m pip install --no-index --require-hashes --find-links=wheels -r dependencies.lock -r pier.lock
venv/bin/python -m pip check
export LITELLM_LOCAL_MODEL_COST_MAP=True
venv/bin/python -c 'from importlib.metadata import version; assert version("datacurve-pier") == "0.3.1" and version("harbor") == "0.5.0"'
venv/bin/pier run --help
~~~

若需重新制备，构建端安装 Git、uv 和 Python 3.12，在匹配目标 ABI 的 Linux 节点执行下列命令，再把两个 lock、wheels 目录和校验清单一起带入。源码标签的 uv.lock 将本项目列为 editable，因此这里从上游锁导出依赖，另锁定 Pier 正式发布 wheel。

~~~bash
set -euo pipefail
git clone --branch v0.3.1 --depth 1 https://github.com/datacurve-ai/pier.git pier-src
test "$(git -C pier-src rev-parse HEAD)" = df89f994623a0a6a57229103b6fe910766693c30
mkdir pier-controller
out=$(cd pier-controller && pwd)
(cd pier-src && uv export --frozen --no-dev --no-emit-project --format requirements-txt -o "$out/dependencies.lock" >/dev/null)
cd "$out"
echo 'datacurve-pier==0.3.1 --hash=sha256:6986b3cb5f66aada5ed6edcc9f045cdf62d19f66b95ff99c706ec8e835981ae1' > pier.lock
python3.12 -m pip download --only-binary=:all: --require-hashes -d wheels -r dependencies.lock -r pier.lock
sha256sum dependencies.lock pier.lock wheels/*.whl > SHA256SUMS
~~~

## 3. 在 Pier 实际使用的 Docker 引擎核对任务

从[跨环境测评资源](evaluation-bootstrap.md)恢复 `execution-assets.tar.gz`，在解包根目录验证 `files.sha256`。按 [OBS 镜像手册](obs-images.md)向目标引擎导入所选镜像。Lite 选 `abs-module-cache-flags`，全量选 113 项。任务镜像的准确标签来自每题 `task.toml` 的 `environment.docker_image`。Lite 的 Dockerfile 基镜像是另一个标签，不能用来代替任务镜像。

在执行节点设置 `TASKS="$ASSETS/deepswe/tasks"`、`RUNTIME_MANIFEST`（已按 OBS 手册核验的 2026-11-24 镜像清单）、`SKILL`（本部署 Skill 的绝对路径）。检查工具只读取本地 Docker 与 task.toml，输出引擎架构、Compose 版本和镜像 ID。出现镜像缺失、架构或 ID 不符时，核对 Docker context、离线包和实际加载标签。全量时把 `--task abs-module-cache-flags` 换成 `--all`。

~~~bash
"$CTRL/venv/bin/python" "$SKILL/scripts/check_deepswe_pier_images.py" \
  --manifest "$RUNTIME_MANIFEST" --tasks "$TASKS" --task abs-module-cache-flags
~~~

Lite 任务声明 2 CPU、8192 MB 内存、20480 MB 存储，Agent 和 verifier 均指定 no-network。按并发、镜像解压及日志额外预留空间。控制端在容器中运行时，确保 Docker 引擎可以按相同绝对路径读写本次的 jobs 挂载。Docker 控制权限只交给控制进程，任务与 verifier 各用其隔离环境。[Lite 资源与 collect 定义](https://github.com/datacurve-ai/deep-swe/blob/0b9fabbb63b9104d678fe965e1632f2dd9eaa2ea/tasks/abs-module-cache-flags/task.toml)

此版 113 道任务的 `tests/Dockerfile` 均从该任务锁定的镜像构建独立评分镜像，并复制测试文件。转移整个任务目录，保留 `tests/`、`solution/` 和文件的 LF 换行。检查工具遇到其他 verifier 基镜像或多阶段构建会提示复核。

## 4. 单题无模型验收

在执行节点准备可写的 `JOBS` 绝对目录，每次新验收使用唯一的 job 名。Oracle 使用该题的参考解。检查结果时同时打开 trial 和 verifier 文件；上游 CLI 退出状态本身不足以确认评分成功。

~~~bash
set -euo pipefail
umask 077
mkdir -p "$JOBS"
job="oracle-$(python3.12 -c 'import uuid; print(uuid.uuid4().hex)')"
"$CTRL/venv/bin/pier" run -p "$TASKS/abs-module-cache-flags" --env docker \
  --agent oracle --jobs-dir "$JOBS" --job-name "$job" --n-attempts 1 --n-concurrent 1 --max-retries 0 --no-force-build
python3.12 - "$JOBS/$job" <<'PY'
import json
import sys
from pathlib import Path

trial_file, = Path(sys.argv[1]).glob("*/result.json")
trial = trial_file.parent
result = json.loads(trial_file.read_text())
assert result["exception_info"] is None, result["exception_info"]
assert result["verifier_result"]["rewards"]["reward"] == 1
assert json.loads((trial / "verifier/reward.json").read_text())["reward"] == 1
assert (trial / "artifacts/model.patch").stat().st_size > 0
summary = json.loads((trial / "verifier/ctrf.json").read_text())["results"]["summary"]
assert summary["passed"] == summary["tests"] == 23, summary
print(trial.name, summary)
PY
~~~

若缺少 trial、参考补丁或奖励，保留该 job 下的异常、verifier 日志和实际 Docker 镜像 ID，先排查挂载映射、资源限制与独立 verifier。Oracle 通过后，在验收单记为“参考解评分通过，模型调用 0”。

2026-11-25 在本机 Linux AMD64 Docker 引擎导入上表指定的 AISBench 镜像，在该镜像内用独立 venv 从离线包安装 Pier。参考解完成一题，耗时 46 秒，生成 23,719 字节补丁。独立 verifier 记录 20/20 项修复测试和 3/3 项既有测试通过，原生 reward 为 1。Pier job ID 为 `6b3747bf-5d54-4d77-b9ac-18b1f0cf08b7`，trial ID 为 `ee691ac1-ba3e-44b5-a2cd-0e35301a1745`。模型调用数为 0。

## 5. 离线 MiniSwe 与真实模型

### 固定 Lite 样本，在控制端运行 MiniSwe 2.4.6

本节对应已在指定 AISBench x86 镜像上运行的 `abs-module-cache-flags`。控制端拥有 Docker CLI、Compose 和目标引擎 socket，运行 Pier 与 MiniSwe，并通过受信连接访问选定的模型服务。模型给出的命令只在 Pier 创建的断网任务容器中执行。适配器在运行命令前核对容器 ID、任务镜像 ID、网络、特权标记及挂载。任务与独立 verifier 均不挂 Docker socket，模型凭据仅供控制端进程使用。适配器固定到这道 Lite 题的镜像 ID。

完成 Oracle 后，在控制容器内执行 `exit` 回到第 2 节的同一宿主 Bash，保留已有工作目录。将 `MODEL_NETWORK` 设为此次已配置出站策略、可访问选定模型服务的 Docker 网络。宿主执行 `controller "${MODEL_NETWORK:?设置已核验的模型网络}"`，重新进入同一镜像。控制容器复用已有 Pier venv、绝对路径和隔离挂载。任务和 verifier 继续由 Pier 按 Lite 定义创建断网环境。在新控制容器创建独立的 MiniSwe venv。

~~~bash
set -euo pipefail
umask 077
wheelhouse="$ASSETS/wheelhouse"
(cd "$wheelhouse" && \
  echo '5365624582ff0bd98eb8ccf3b5ef91479df349f8f90173c28b87f1b1919c209e  sha256sums' | sha256sum -c - && \
  sha256sum --quiet -c sha256sums)
export MINI_VENV="$CTRL/miniswe-2.4.6"
export PYTHONPATH="$SKILL/scripts/pier_x86_lite"
export LITELLM_LOCAL_MODEL_COST_MAP=True
test ! -e "$MINI_VENV"
python3.12 -m venv "$MINI_VENV"
"$MINI_VENV/bin/python" -m pip install --no-index --require-hashes \
  --find-links="$wheelhouse" -r "$wheelhouse/requirements.lock"
"$MINI_VENV/bin/python" -m pip check
"$MINI_VENV/bin/python" "$PYTHONPATH/worker.py" --self-check
"$CTRL/venv/bin/python" -c 'from local_pier_agent import ControllerMiniSwe'
~~~

`pip check` 和两种模型消息配置的自检均应通过。依赖缺失时先复核 wheelhouse 清单、解释器及解包目录。上述自检不调用模型。[Pier 适配器](../scripts/pier_x86_lite/local_pier_agent.py) · [MiniSwe 执行与自检](../scripts/pier_x86_lite/worker.py)

按目标平台的模型服务模板将实际模型 ID 赋给 `MODEL_ID`，并将无内嵌凭据的 HTTPS API 基址赋给 `OPENAI_API_BASE`。由受保护的凭据来源把 `OPENAI_API_KEY` 注入已启动的控制进程。交互式验收可在控制容器内执行 `set +x`，再以 `IFS= read -rs -p '模型 API 密钥：' OPENAI_API_KEY` 关闭回显读取。这样命令历史、Docker 创建参数和共享目录中均无密钥。选择一种执行方式且仅提交一次。以下在同一控制环境中执行，选定的服务须支持 OpenAI 兼容的聊天与工具调用。本次 DeepSeek 验收使用 `MINISWE_THINKING_DISABLED=1` 以匹配该服务的工具调用模式，其他服务按其已验证的接口约定设置。

适配脚本在未设置 `MINISWE_COST_LIMIT` 和 `MINISWE_STEP_LIMIT` 时沿用 MiniSwe 的原生费用与步骤配置。本次已获不限额授权，实测对应 `MINISWE_COST_LIMIT=0`、`MINISWE_STEP_LIMIT=0`。有硬性费用上限的任务须选用能够执行该额度的模型网关。模型价格未知时，本地估算无法保证费用上限。

~~~bash
set +x
set -euo pipefail
umask 077
: "${OPENAI_API_BASE:?设置已登记的模型 API 基址}" "${OPENAI_API_KEY:?需要受保护的模型凭据}" "${MODEL_ID:?设置模板中的实际模型 ID}"
export OPENAI_API_BASE OPENAI_API_KEY
export MINISWE_MODE=tools
# 仅用于本次 DeepSeek 服务配置
export MINISWE_THINKING_DISABLED=1
mkdir -p "$JOBS"
job="model-$(python3.12 -c 'import uuid; print(uuid.uuid4().hex)')"
printf 'Pier job: %s\n' "$JOBS/$job"
"$CTRL/venv/bin/pier" run -p "$TASKS/abs-module-cache-flags" --env docker \
  --agent-import-path local_pier_agent:ControllerMiniSwe --model "openai/$MODEL_ID" \
  --jobs-dir "$JOBS" --job-name "$job" --n-attempts 1 --n-concurrent 1 --max-retries 0 --no-force-build
~~~

沿同一 job 回读 trial 下的 `agent/agent-status.json`、`agent/trajectory.json`、`result.json` 和 verifier 原生结果。分别核对模型响应数、Agent 结束原因、补丁以及测试执行情况。网络或网关结果未知时保留原 trial，按网关记录核对是否已调用。原始轨迹存放在本次受保护的 jobs 目录中。

### 本地单样本实测记录

2026-11-25 在指定 AISBench x86_64 镜像的控制端运行 Pier 0.3.1 与 MiniSwe 2.4.6。模型服务返回的标识为 `deepseek-flash`，本次关闭 thinking。样本为 `abs-module-cache-flags`，任务容器与独立 verifier 的 Docker 网络均为 `none`。实际执行使用单题控制端适配，保留上游 Agent 循环、补丁收集和评分。

| 记录 | 实测结果 |
| --- | --- |
| 运行 | job `28fb1864-4fa6-4b10-a547-a348cd902dda`，trial `6caa9343-ee85-4a88-999e-b9cf24031850`，耗时 362.5 秒 |
| 模型和提交 | 1 次 trial，104 个模型响应，0 次自动重试，Agent 原生退出原因为 `Submitted`。29,596 字节补丁的 SHA-256 为 `a1d5497ccba1c7e3f5bd6eac460c1650a4ba37ad81fc17c00978a1fab9c4dd97` |
| 独立评分 | 修复测试 9/20，回归测试 3/3，CTRF 共 12/23 通过。原生 `partial=12/23`，整题 `reward=0`，trial 无异常 |
| 用量 | 104 个响应均含用量。累计输入 3,613,930 token（含缓存 3,568,256），输出 26,484 token |
| 平台范围 | 本次由本机原生 Pier 发起，证据保存在 Pier job 目录。AutoEval 平台报告与目标服务器部署另行验收 |

### 上游 Agent 安装方式

控制端的 Python 环境、Agent 试验容器、verifier 是三处独立依赖。Pier 0.3.1 会为 MiniSwe 建立 Agent 派生层，默认安装脚本需要系统包、uv 0.7.13 安装器以及指定版本的 mini-swe-agent。模型白名单生效时，Docker 后端还可能构建带 Squid 的出站代理。`--no-force-build` 用于选择已有任务镜像，仍须满足上述派生层和代理的构建需求。[安装逻辑](https://github.com/datacurve-ai/pier/blob/df89f994623a0a6a57229103b6fe910766693c30/src/pier/agents/installed/mini_swe_agent.py) · [Docker 环境实现](https://github.com/datacurve-ai/pier/blob/df89f994623a0a6a57229103b6fe910766693c30/src/pier/environments/docker/docker.py) · [代理构建](https://github.com/datacurve-ai/pier/blob/df89f994623a0a6a57229103b6fe910766693c30/src/pier/environments/agent_setup.py)

- 在匹配的构建机固定 Agent 版本、基础镜像 ID、uv 安装器及平台二进制、系统包和对应依赖 wheelhouse。按该 Pier 版本的 Agent install spec 和代理构建上下文准备内部源、缓存或已验证的离线适配。在目标引擎限制公网访问后，实测派生层和代理可创建、Agent 可启动，独立 verifier 仍隔离。缺少其中一项，登记具体缺件和镜像列表；已有 Harbor 离线 Agent 的 wheelhouse 需要重新核对解释器、依赖和安装入口。
- 在受保护的执行环境注入模型凭据和受信 CA，只为已选模型服务配置必要的出站访问。按模型网关实际支持的 API 核对 MiniSwe 的模型类型。单次 trial 可能多次调用模型，预算和请求上限由所选实现及网关执行。不要将带凭据的配置、原始轨迹或请求正文上传到普通共享目录。
- 已明确模型、Agent 版本、目标节点和费用授权后，将 `MODEL` 设为 Pier 支持的带 provider 前缀的模型名。`MINISWE_VERSION` 使用本次离线供应并已验证的版本；以下只提交一个 Lite 任务。

~~~bash
set -euo pipefail
umask 077
job="model-$(python3.12 -c 'import uuid; print(uuid.uuid4().hex)')"
printf 'Pier job: %s\n' "$JOBS/$job"
"$CTRL/venv/bin/pier" run -p "$TASKS/abs-module-cache-flags" --env docker \
  --agent mini-swe-agent --agent-kwarg "version=$MINISWE_VERSION" --model "$MODEL" \
  --jobs-dir "$JOBS" --job-name "$job" --n-attempts 1 --n-concurrent 1 --max-retries 0 --no-force-build
~~~

保存 job/trial ID、任务源和镜像 ID、Pier/Agent 版本、模型标识与原生奖励。回读 trial 的 `result.json`、`agent/trajectory.json`、`artifacts/model.patch` 及 verifier 的奖励、测试输出、可用的 CTRF；按原生规则区分合法零分、执行异常、评分异常和缺失证据。发生超时或模型请求结果未知时沿原 job 核查日志与网关账本。交付分别记录“镜像核对”“Oracle”“MiniSwe 模型调用及评分”“AutoEval 平台报告”的实际状态。
