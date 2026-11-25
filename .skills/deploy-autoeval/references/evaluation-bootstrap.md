# 跨环境恢复真实测评入口

基础 SQL 恢复模型、数据集、标准输入和外部榜单的目录信息。发起测评还要让目标平台读到 Full/Lite 样本清单对象、版本化 Profile、与目标模型服务对应的编译结果，并让目标执行节点读到题目、工具、评分器和依赖。以下使用 2026-11 Linux AMD64 快照，路径左侧是新节点，右侧是该版本工具在**容器内**读取的位置。切换发布后以当次工具锁、Profile 和资源清单为准。

DeepSWE 若使用原生 Pier，按 [Pier x86 部署与验收](deepswe-pier-x86.md) 操作。下文的 DeepSWE 配置、SSH 模板和平台运行 ID 对应 AISBench/Harbor。

## 1. 在执行节点准备文件

### 先还原平台目录和对象

本次配套资源包为 `autoeval-evaluation-kit-20261125.zip`，按包内 `README.md` 操作。在平台主机把 ZIP 解入私有目录，令 `KIT` 指向含 `SHA256SUMS` 的绝对路径。执行 `(cd "$KIT" && sha256sum --quiet -c SHA256SUMS)`，成功退出后再导入。发行包包含普通 SQL、4 个版本化 Profile、8 个 Full/Lite 清单和 1 个原生数据对象、4 套启动配置，以及执行节点只读资源。源库使用 `0041_report_versions`，平台验收提交为 `08eb3dd53d3661828be780b16f189be38a42a60c`。

在**平台主机**读取当前项目的 PostgreSQL 容器、业务库名、角色和 API 容器名，先完成迁移并初始化持久化 S3 桶。已有业务数据先备份。把 `PG_CONTAINER`、`PG_ROLE`、`AE_DB`、`API_CONTAINER` 指向本次目标。以下命令通过正在使用的后端 Python 和服务端配置访问当前数据库和当前桶。为每次操作创建独立的临时目录，避免覆盖其他部署文件。

~~~bash
set -euo pipefail
(cd "$KIT" && sha256sum --quiet -c SHA256SUMS)
docker exec -i "$PG_CONTAINER" psql -X -v ON_ERROR_STOP=1 -U "$PG_ROLE" -d "$AE_DB" < "$KIT/catalog.sql"
work=$(docker exec "$API_CONTAINER" mktemp -d /tmp/ae-eval-seed.XXXXXXXX)
for file in evaluation_seed.py startup_inputs.py; do
  docker exec -i "$API_CONTAINER" sh -ec 'umask 077; cat > "$1"' sh "$work/$file" < "$KIT/.skills/deploy-autoeval/scripts/$file"
done
for file in evaluation-seed.zip startup-inputs.json; do
  docker exec -i "$API_CONTAINER" sh -ec 'umask 077; cat > "$1"' sh "$work/$file" < "$KIT/$file"
done
for action in check import check; do
  docker exec "$API_CONTAINER" python "$work/evaluation_seed.py" "$action" --bundle "$work/evaluation-seed.zip"
done
docker exec "$API_CONTAINER" python "$work/startup_inputs.py" import --file "$work/startup-inputs.json"
~~~

若容器无法写入临时目录，可用同一后端镜像启动临时 Compose 服务，沿用 API 的受保护环境并将四个文件只读挂载到该账号可读的路径。导入输出应显示 4 个 Profile、9 个对象，最后一次检查为 `0 objects initially absent`；启动配置导入会打印四个输入 ID。已有记录出现同名异值、UUID 冲突或对象摘要错误时，保留现场，按源记录和目标记录对照后选择兼容版本。包里的官方榜单仅含外部成绩。已有运行、Case、正式报告和历史成绩的证据迁移按[验收与恢复](acceptance-recovery.md)处理。

用将由平台通过 SSH 登录的账号执行。`ASSETS` 设为本次经过哈希核验、已解包的绝对路径；`REPO` 指向同版本的平台源码。镜像导入和标签/ID 核对见[镜像手册](obs-images.md)。目标不通外网时，在中转机下载镜像包、只读数据包及发布包，校验后带入。

解包使用**私有父目录、新的发行目录**。在 `umask 077` 下解包曾使容器中的不同 UID 无权打开文件。`PRIVATE` 是目标 SSH 用户所有的私有父目录，`DATA_ARCHIVE` 为已核验、目录结构与下表一致的 gzip 压缩包。先查看 `tar -tzf "$DATA_ARCHIVE"`；若发布为多个独立包，分别使用发布清单列出的解包位置和格式。

~~~bash
set -euo pipefail
install -d -m 0700 "$PRIVATE"
mkdir -m 0755 "$ASSETS"      # ASSETS 直接位于 PRIVATE 下；必须是新的目录
(umask 022; tar --no-same-owner -xzpf "$DATA_ARCHIVE" -C "$ASSETS")
~~~

未压缩的 tar 改用 `-xpf`。只读数据子目录通常为 0755，题目数据文件为 0644；私有父目录 0700 限制宿主上的遍历。`-p` 保留归档内权限，归档本身过严时只修正本次解包的题目目录、数据文件和应可执行的脚本。在模板对应容器的实际 UID 下打开一份真实文件验证；宿主可读与容器可读需分别检查。平台配置、密钥及运行状态文件保持私有。

| 数据集 | 本次快照的只读资源与容器路径 | 核对点 |
| --- | --- | --- |
| GPQA | `$ASSETS/gpqa` → `/benchmark/ais_bench/datasets/gpqa` | `gpqa_diamond.csv` 是完整 Diamond 数据，198 项；用发布的 `backend/tool-locks/gpqa-source.json` 验 CSV。按固定提交单独取源时还要核对 ZIP 和许可文件。 |
| MMMU-Pro | `$ASSETS/mmmu` → `/benchmark/ais_bench/datasets/mmmu_pro` | `MMMU_Pro_10c.tsv` 为 1,730 项、140,919,931 字节，图像随文件提供；核对数据包摘要。执行镜像使用 `031a793` 系列的工具和评分器。源机快照已用断网的新容器，仅挂该 TSV，实际加载全部 1,730 条并获取 content 与 answer。原挂载 `/home/yanhe/agent_deps` 可从本组合的模板省去。此次检查为只读根镜像设置了 `BFCL_PROJECT_ROOT=/tmp`；新节点若报 BFCL 缓存目录无写权限，在派生镜像中将此变量设为可写的 `/tmp`。 |
| AutomationBench | `$ASSETS/automationbench/tasks` → `/home/chenluwen/autoeval-automationbench-acceptance-20261116/tasks-public` | 右侧为快照编译所用的容器路径；保留 `_runtime` 和原生文件布局，核对 600 个任务。其他标准输入若锁了不同路径，调整挂载目标并重新预检。 |
| DeepSWE | `$ASSETS/deepswe/tasks` → `/data/deep-swe/tasks`，`$ASSETS/wheelhouse` → `/acceptance/deepswe-lite-wheelhouse-20261120` | 固定提交 `0b9fabbb63b9104d678fe965e1632f2dd9eaa2ea` 共 113 个任务，Lite 样本为 `abs-module-cache-flags`。保留 Git 原始 LF；`deploy/intranet/install-deepswe-tasks.sh` 包含验证脚本及补丁哈希。wheelhouse 对应 Python 3.12、MiniSwe 2.4.6，含 `requirements.lock`、wheels 和 `sha256sums`。 |

~~~bash
set -euo pipefail
test "$(sha256sum "$ASSETS/gpqa/gpqa_diamond.csv" | cut -d' ' -f1)" = \
  "$(jq -er .csv_sha256 "$REPO/backend/tool-locks/gpqa-source.json")"
test "$(wc -c < "$ASSETS/mmmu/MMMU_Pro_10c.tsv")" -eq 140919931
test -d "$ASSETS/automationbench/tasks/_runtime"
test "$(find "$ASSETS/deepswe/tasks" -mindepth 1 -maxdepth 1 -type d | wc -l)" -eq 113
(cd "$ASSETS/wheelhouse" && echo '5365624582ff0bd98eb8ccf3b5ef91479df349f8f90173c28b87f1b1919c209e  sha256sums' | sha256sum -c - && sha256sum --quiet -c sha256sums)
~~~

按所选数据集执行对应命令。Harbor 额外需要 `$ASSETS/rootless/bin/{autoeval-rootless-docker,autoeval-rootless-docker-seeded}` 和同级 `docker/`、`docker-rootless-extras/` 程序目录。SSH 账号需要运行宿主 Docker、SFTP、`/usr/bin/python3`，能创建自有的工作目录和 `/var/tmp/autoeval-harbor-job-<UUID>`。检查目标用户的从属 UID/GID 段、`newuidmap` 和 `newgidmap`，宿主须支持非特权用户命名空间、RootlessKit 所需网络以及私有 Docker 数据目录空间。核实 Docker 地址池可用容量，下文按实际值传入。

在目标执行账号下检查 `id -u`、`id -g`、镜像内的 `getent passwd`/`getent group` 以及挂载读权限；根用户能列目录并不能证明分片账号能打开题目、读取 `_runtime` 或写 trial。Harbor 通过 helper 为每个分片创建私有 daemon，用同一路径共享任务目录；不复制旧 socket、daemon 数据或源机用户身份。若预置镜像缺目标用户或 Agent 阶段允许的模型源不同，用 `deploy/Dockerfile.r13-harbor` 按 `docs/deepswe-task-deployment.md` 同步准备固定基镜像并传 `RUNNER_UID`、`RUNNER_GID` 和需要的 `DEEPSWE_MODEL_ORIGIN` 重新构建，记录新 ID。`AE_DEEPSWE_MODEL_ORIGIN` 须匹配模型或预算网关的实际 HTTPS origin。

在使用 Harbor 的执行节点，从已核验标签生成未压缩的 Docker tar。下面两个例子对应 AutomationBench 和固定的 DeepSWE Lite 样本，各按需执行。已有文件先与发布清单核对；原子发布或保留旧发行目录，避免改写在途分片正在使用的文件。

~~~bash
set -euo pipefail
mkdir -p "$ASSETS/cache"
save_cache() (
  tag=$1 expected=$2 dest=$3
  test "$(docker image inspect --format '{{.Id}}' "$tag")" = "$expected"
  test ! -e "$dest"
  tmp=$(mktemp "$ASSETS/cache/.image-XXXXXXXX")
  trap 'rm -f "$tmp"' EXIT
  docker save -o "$tmp" "$tag"
  chmod 0644 "$tmp"
  ln "$tmp" "$dest"
)
save_cache harbor-automationbench:e45f2f2ac0d7e2215205fa44 \
  sha256:086c2b1898ad38faa5420a29046e8430c285e2fae35bdea3977b5fc5b6afa779 \
  "$ASSETS/cache/automationbench-base.tar"
save_cache public.ecr.aws/d3j8x8q7/swe-bench-202605:kh75679ajj3b8dtd7se3h7z0a1833y6r-v1.1 \
  sha256:85f743fa1c3b772abbac100056350657e771a10196c31512f68fc4dc114c19cd \
  "$ASSETS/cache/deepswe-85f743fa1c3b.tar"
~~~

`cache/docker-cli` 是可执行文件，挂到 `/opt/autoeval-r13/bin/docker`。模板挂上对应的 `/opt/autoeval-cache/*.tar`，包装器才会在使用时把镜像导入该分片的 daemon。DeepSWE 全量需要为选中的其余样本在实际分片供应相应标签/ID；当前 Lite 包装器只处理一个 DeepSWE 标签。逐个核实后才开放相应范围。

## 2. 登记目标模型与 SSH 资源

平台管理员从目标网关进入资源配置。以下 API 均以 `/api/autoeval/v1` 为前缀。写入凭据时使用受保护表单或本地受保护请求文件，不记录请求正文。

1. 选择已导入模型的**版本**。注册目标模型密钥 `POST /credentials`，将新 `credential_ref` 和 `model_version_id`、`base_url`、`remote_model` 提交给 `POST /target-bindings`，保留返回的 `target_id`。`AE_ALLOWED_MODEL_HOSTS` 配置所选主机的 JSON 列表，平台和执行容器均能验证 TLS、DNS 及路由。`POST /targets/{target_id}/connection-tests` 只检查模型列表；无需以付费生成测试连接。
2. 在 SSH 主机控制台从受信任的 host 公钥确定指纹，例如 `ssh-keygen -lf /etc/ssh/ssh_host_ed25519_key.pub -E sha256`。按实际 SSH 握手使用的主机密钥类型核对。`POST /ssh-resources/credentials` 写入本环境 SSH 密码或私钥；`POST /ssh-resources` 登记 `binding_key,host,port,username,fingerprint,workdir,auth_kind,credential_ref`。`workdir` 为该用户能写的宿主绝对路径。保存返回的**新资源 UUID**，`POST /ssh-resources/{id}/validate` 检查指纹、登录、工作区及文件传输。任务使用 `customer_ssh`。把凭据卷和 `AE_SECRET_STORE_PATH` 供给同一发布中需要解析引用的服务；数据库里的 UUID 不能还原密钥。
3. 选中的 Full/Lite 清单在目标 S3 应可读取。数据目录和逐样本 `sample_id`/`sha256` 对应。由 `GET /dataset-manifests/{id}`、`GET /profiles` 核对本次选用的 Profile 绑定了同一 Full/Lite，`tool.family,revision,scorer_reference,scorer_sha256,parallelism_owner` 完整。仅有基础 SQL 时需恢复/导入这组业务记录及 S3 原文，详见本次数据包的导入说明。若从已核验的 Full 建立新的最小 Lite，`POST /dataset-manifests` 传新的 `manifest_key`、`scope=lite`、`parent_id` 及选中一个原始 `sample_id,sha256`，随后用 `POST /profiles` 建新版本关联它；保留原清单与历史 Profile。

## 3. 生成执行模板并部署到平台

`scripts/render_evaluation_resources.py` 在**目标 Linux 执行节点**运行，需要 Python 3 和 Docker。一个 SSH 资源的 `executors` 每个工具家族只容纳一个镜像/提交。快照中 GPQA 和 MMMU-Pro 均属 `aisbench`，但工具提交不同；在同一主机登记两个不同 `binding_key` 的资源，各自生成一份。DeepSWE 与 AutomationBench 使用相同版本 Harbor 时可在同一项挂两套资源。脚本只生成一个新资源片段，不含凭据，也不会写配置或拉取镜像。

1. 从已校验的镜像清单取目标执行镜像 ID。GPQA 使用 `autoeval/r13-aisbench:525ed17-locked`，MMMU-Pro 使用 `autoeval/r13-aisbench:031a793-locked`，Harbor 使用 `autoeval/harbor-runner:main-f4d0ea9` 或已在新节点校验的重建镜像。镜像内 `git -C /benchmark rev-parse HEAD` 必须与目标 Profile 的完整 `tool.revision` 一致；在同一镜像和执行账号下比较 `sha256sum /benchmark/<scorer_reference>` 与 `scorer_sha256`。
2. 准备此节点上常驻的规划容器，使用包含 Python、固定适配器及规划依赖的发布镜像，命名为本目标独有的 `ANCHOR_NAME`。首次安装且镜像包含这些依赖时可用下面的独立容器。重用已有容器时先检查运行状态和镜像 ID。锚定的规划容器与平台为每个测评创建的分片分别校验。

~~~bash
set -euo pipefail
# ANCHOR_IMAGE 为已在此节点检查的本地镜像 ID；首次创建，已有同名容器不覆盖。
docker run -d --pull never --restart unless-stopped --name "$ANCHOR_NAME" \
  --entrypoint python3 "$ANCHOR_IMAGE" -c 'import time; time.sleep(10**8)'
docker exec "$ANCHOR_NAME" sh -ec 'python3 --version; git --version; command -v autoeval-adaptor; test -w /tmp'
~~~

3. 在节点运行下例，每次选一个资源 UUID。`PROFILE_REVISION` 来自目标刚核验的 Profile；`EXEC_IMAGE_ID` 来自已核验清单。按需改为 `mmmu-pro`、`automationbench`、`deepswe` 或 `automationbench deepswe`。Harbor 调用再传 `--harbor-network-capacity "$NETWORK_CAPACITY"`。输出目录为本次新建的私有发行目录。

~~~bash
set -euo pipefail
umask 077
fragments=$(mktemp -d)
python3 "$REPO/.skills/deploy-autoeval/scripts/render_evaluation_resources.py" \
  gpqa --resource-id "$SSH_ID" --assets "$ASSETS" --planning-container "$ANCHOR_NAME" \
  --revision "$PROFILE_REVISION" --image-id "$EXEC_IMAGE_ID" > "$fragments/$SSH_ID.json"
~~~

脚本从当前 Docker 引擎读取规划容器完整 `Id` 和 `Image`，用禁网临时容器按分片身份打开只读数据、缓存和依赖，核对镜像里的实际 Git 提交。出现 PermissionError 时先检查数据目录能否遍历、挂载文件是否对容器用户可读。复制**成功生成且非空**的片段到平台受保护的发布目录。多节点使用不同文件名；在目标平台合并并拒绝重复 UUID。例如首次部署在新目录中执行 `jq -es 'if ([.[]|keys[]] | length == (unique|length)) then add else error("duplicate resource UUID") end' fragments/*.json > planning-containers.json`。升级时纳入应保留的既有资源，备份原配置；原地换镜像先处理对应在途任务。受保护文件提供给 API、planning worker 和 planning-execution worker。为实际消费配置的每个容器设置相同的 `AE_PLANNING_CONTAINER_CONFIG` **容器内文件路径**、只读挂载、可读权限；用 `sha256sum` 比较容器内文件摘要。随发布重建/重载消费进程。缺模板、路径不存在、Git/scorer 不符时，修正目标资源并重新预检。

## 4. 验证版本固定的远程运行时

平台侧参照 `backend/src/autoeval/planning/planning_transport.py`。发布容器须能读取 `runtime_files()` 使用的源码和相对位置的 `tool-locks/planner-package.json`；对只安装 wheel 的镜像实际执行下面的读取及哈希核验。规划包由同版后端按 `backend/uv.lock` 安装，`PlanningRemoteContainer` 通过 SSH 在容器里写入控制脚本、已核验的 Planner 包及其发行元数据，逐文件读回哈希。目标机仅安装宿主 Python 不会给分片安装 AISBench、Adaptor、Harbor 及其依赖。适配器须已在执行镜像或明确的只读依赖目录内，`python3`、`autoeval-adaptor` 和所选 `python_executable` 必须能加载它。

在实际 API 和两个规划/执行 worker 的**发布容器**内运行：

~~~bash
python - <<'PY'
from autoeval.planning.planning_transport import execution_template, runtime_files
from autoeval_runtime.planning_runtime import PLANNER_REVISION, installed_revision
files = runtime_files()
assert files["planning_runtime.py"] and files["planner-package.json"]
assert installed_revision("autoeval-task-planner") == PLANNER_REVISION
assert callable(execution_template)
print("控制脚本、锁文件和固定 Planner 可用")
PY
~~~

在执行节点对所选 `EXEC_IMAGE_ID` 运行，使用与平台一致的 `python3`。Harbor 另用 `/acceptance/runtime/bin/python`（本快照的兼容入口）或实际编译的解释器导入 `harbor.models.job.config`。发现 `/home/<旧账户>/…`、可执行文件依赖写入运行容器的临时目录、缺 `direct_url.json` 或 `git … HEAD` 不符时，使用同版离线 wheelhouse/固定 Git checkout 在发行镜像中安装依赖，保留真实来源记录，再执行模板检查。

~~~bash
docker run --rm --pull=never --network none --entrypoint sh "$EXEC_IMAGE_ID" -ec '
  command -v autoeval-adaptor
  python3 -c "import importlib.metadata as m,json,sys; import autoeval_adaptor; print(sys.executable); print(json.loads(m.distribution(\"autoeval-benchmark-adaptor\").read_text(\"direct_url.json\"))[\"vcs_info\"][\"commit_id\"])"
  git -C /benchmark rev-parse HEAD'
~~~

当前快照需 Adaptor `955089ab32ef696c231d628f5ad0d9da28f430c4` 和 Planner `0ee9abf49a57c5accc62df8900693cdcea88ea9a`。随包四份 Profile 中，GPQA、MMMU-Pro 的 AISBench 提交分别为 `525ed1779f50a8ac068b8638771f633a151e769f`、`031a79318a350732af1ac86b8c58f6ceabc08bd7`，两个 Harbor Profile 均为 `698ff2d1e027c07df37bdd158b62aace2a41ae3b`。图片协议、网关路由和额外 Python 依赖也要用实际组合验证。MMMU-Pro 历史上出现过模型端拒绝本地文件形式 `image_url`；应核对所选模型的图像能力、原生转换及实际小样本响应。

**离线工具供应与修复**

- 原版阻断外网的执行路径不会临时克隆 GitHub。准确率镜像构建时须带固定 `/benchmark/.git`、AISBench 依赖、带真实 VCS 元数据的 Adaptor 以及可执行的 `autoeval-adaptor`。若预检报 `adaptor_revision_mismatch`，在构建机取锁定提交的 Git bundle（含该提交及 refs），在发行构建上下文还原工作树和 `.git`；依照 `deploy/r13-aisbench.Dockerfile` 由目标 Python 通过 `pip install --no-index --no-deps --no-build-isolation git+file://…@<commit>` 安装进派生镜像并复核元数据。先核实基础镜像已有对应构建/运行依赖。将修复后的镜像连同 ID、校验清单带入目标并重新生成模板。不要把不同数据集工具提交一次套用到全部镜像。
- `PlanningRemoteContainer` 只在后端已安装 Planner 的版本验证通过时才把 `autoeval_planner/` 和发行元数据复制到调用方 `<runtime_root>/<内容哈希>/deps`，在该远端 Python 命令的 `PYTHONPATH` 前置此目录。后端离线 Dockerfile 已为 `tool-locks` 的包相对路径建立链接。若 `runtime_files()` 出错，修复实际发布镜像的 wheel、锁文件或链接。规划锚点用可写 `/tmp/autoeval-planning-runtime`；Harbor 分片则用属于其 SSH 用户的 `/var/tmp/autoeval-harbor-job-<UUID>`。不用源容器 `/tmp`、用户 venv 或宿主 site-packages 作为依赖源。
- 对最终 Harbor 镜像以分片身份运行下面的离线导入，检查解释器、两个 Agent、Docker CLI 和任务配置加载器。`PYTHONPATH` 与 `PATH` 要在镜像内可继承；该发布的模板只转交 `AE_HARBOR_NETWORK_CAPACITY` 和 `AE_VALIDATED_DATASETS` 两类环境字段。随意在模板里加 `PYTHONPATH`、模型密钥或安装命令不会修复镜像。

~~~bash
docker run --rm --pull=never --network none --user "$(id -u):$(id -g)" \
  --env HOME=/tmp --entrypoint sh "$HARBOR_IMAGE_ID" -ec '
    test -x /usr/local/bin/docker
    /acceptance/runtime/bin/python -c "from harbor.models.job.config import DatasetConfig"
    /opt/venvs/harbor/bin/python -c "from automationbench_adapter.agent import AutomationBenchOfficialAgent; from harbor.agents.installed.deepswe_offline_agent import OfflineMiniSweAgent"'
~~~

本次源机已在不挂载历史 Python 依赖的断网临时容器中，逐一核对三个最终镜像的 Adaptor 提交和 AISBench HEAD；Harbor 还以源机实际 SSH UID/GID 成功导入以上两个 Agent。这些结果用于选择可携带的制品，目标节点的权限与预检仍单独记录。

完整重建 `deploy/Dockerfile.r13-harbor` 需要两个历史 `FROM`；2026-11-24 清单没有收录其中 `autoeval/aisbench-harbor:d97a8e7-f59cb89-agent-container-fix`。若只有目标 UID/GID 或 DeepSWE 模型源不同，从已核验、具备上述 Agent 的最终镜像派生即可。以下在目标节点执行，`HARBOR_IMAGE_ID` 取已核对的最终镜像 ID，`MODEL_ORIGIN` 为批准的 HTTPS 源（仅协议、域名、可选端口）。用新构建上下文和未被占用的目标标签；本机 Docker builder 须使用已导入镜像所在的存储。

~~~bash
set -euo pipefail
ctx=$(mktemp -d)
base_tag="autoeval-local/harbor-base:${HARBOR_IMAGE_ID:7:12}"
docker tag "$HARBOR_IMAGE_ID" "$base_tag"
test "$(docker image inspect --format '{{.Id}}' "$base_tag")" = "$HARBOR_IMAGE_ID"
cat > "$ctx/Dockerfile" <<'DOCKERFILE'
ARG BASE
FROM ${BASE}
ARG RUNNER_UID
ARG RUNNER_GID
ARG MODEL_ORIGIN
USER 0
RUN (getent group "$RUNNER_GID" || groupadd --gid "$RUNNER_GID" "ae-g$RUNNER_GID") \
 && (getent passwd "$RUNNER_UID" || useradd --no-create-home --home-dir /tmp \
     --shell /bin/sh --uid "$RUNNER_UID" --gid "$RUNNER_GID" "ae-u$RUNNER_UID")
ENV AE_DEEPSWE_MODEL_ORIGIN=$MODEL_ORIGIN
DOCKERFILE
docker build --pull=false --network none --build-arg BASE="$base_tag" \
  --build-arg RUNNER_UID="$(id -u)" --build-arg RUNNER_GID="$(id -g)" \
  --build-arg MODEL_ORIGIN="$MODEL_ORIGIN" -t "$NEW_HARBOR_TAG" "$ctx"
docker image inspect --format '{{.Id}}' "$NEW_HARBOR_TAG"
~~~

将新 ID 用于模板；平台创建 Harbor 分片时显式设置 `--user <SSH UID>:<SSH GID>`。如果改动涉及工具代码、评分或 Agent 版本，则另行准备对应源码/中间镜像和 Profile，按新发布验证行为。

## 5. 用目标身份编译、预检、提交和回读

这份基础 SQL 的 147 条官方标准输入没有启动配置，且其目录内没有 AutomationBench。随包的 `startup-inputs.json` 在 `local-operator/deployment-startup` 名下登记四项精简验收配置。注册目标模型服务后，在具备**同版本后端 Python 环境**的客户端执行以下命令。选用导入输出的输入 ID；脚本从目标 API 校验服务归属，回查所保存配置的 SHA-256 和 ID，结果用于后面的预检。AutomationBench 使用当前模型服务对应的 Agent 地址。精简验收参数仅用于该样本范围，正式测评另行核对模型能力与参数。

~~~bash
set -euo pipefail
s="$KIT/.skills/deploy-autoeval/scripts"
platform=(--base-url "$GATEWAY" --ca-file "$CA_FILE" --user "$GW_USER" --target-id "$TARGET_ID")
python "$s/compile_evaluation_input.py" "${platform[@]}" --file "$KIT/startup-inputs.json" \
  --dataset GPQA --tool-root /benchmark --datasets-dir /benchmark/ais_bench/datasets
~~~

MMMU-Pro 使用同一 datasets-dir 并选择 `--dataset MMMU-Pro`。DeepSWE 和 AutomationBench 用 `--task-path` 替换 `--datasets-dir`，值分别为本手册列出的两个容器内任务路径。各保留自己的 `compilation_id`。

1. 在“测评配置”选择目标标准输入、模型资产和属于其版本的服务绑定。`POST /standard-inputs/{input_id}/compile` 使用目标 `model_id,target_id`、匹配 Adaptor 的 `adaptor_revision`，`tool_root=/benchmark`。准确率配置 `datasets_dir=/benchmark/ais_bench/datasets`，启用逐样本评分的 `dump_eval_details`；Harbor 配置 `task_path` 为表中容器任务路径，核对 Agent、`python_executable` 和 `n_attempts`。检查标准锁字段与工具、评分契约，选择此版本支持的 `input_policy` 和 `execution`。标准缺 `benchmark_config.json` 时，使用支持补全的策略和新 `template_version`，提供带非空 `params` 的启动模板，保留平台生成的服务与作业目录字段；切换配置后要求 `input_ready=true` 且 `blocking_reasons=[]`。通过 `GET /planning/options` 取得与编译摘要匹配的 `compilations[].id` 作为 `compilation_id`，它与 `sha256` 是不同字段。
2. 在任务页面选择新 SSH 资源及目标服务，挑刚冻结的 Lite 清单。对完全相同的 `target_id,resource_id,resource_ids,tasks` 运行 `POST /planning/resources/preflight`，其中任务含 `task_id,dataset,manifest_id,compilation_id`。以 `GET /planning/plans/{job_id}` 读作业；需作业完成、`execution_ready=true`、所选数据集均受支持、`blocking_reasons` 为空。逐项核对预期与实际版本、评分文件、路径和分片镜像。看到 `dataset_not_validated` 保留首次实跑待验状态；不在环境变量中预标已经验收。镜像/资源/模板/清单变化或预检过期后重做。
3. 最小真实验收选择 GPQA 的一个连续样本，`concurrency=1`、`dataset_concurrency=1`，确认尝试次数 1、已批准的模型、输出上限、请求重试行为和费用策略。用户明确不限额时，记录授权引用；指定额度时，在账本或供应商处落实后再提交。启用请求级预算时，目标账号、价格、凭据与截止时间必须有效，`AE_ENFORCE_TASK_BUDGET` 开启，`AE_BILLING_EXECUTION_CONFIG` 和预算代理路由须可从执行容器访问，`ignore_budget=false`。平台读取 `AE_EVALUATION_ORIGIN=real`。记录本次唯一 `Idempotency-Key`，在任务确认页面提交一次（`POST /evaluation-tasks`）。记录 `run_id`；响应丢失时先按原任务、原键及账务查证，不能用新键再发。
4. `GET /evaluation-tasks/{run_id}` 跟踪分发、真实分片及终态，`GET /evaluation-tasks/{run_id}/report` 或报告页核对同一运行、样本 ID、原生判分、证据归档与当前报告。按对象引用从持久化 S3 回读并核对摘要；记录预算/上游请求观测，不记录密钥或题目正文。一个选错答案但原生正确判为 0 的案例也能验证执行链路。逐数据集登记所测范围；仅预检、固定产物、结果未知、未给目标或预算的均保留对应状态，不能据此宣布四项真实评分通过。

在能访问目标平台的受控客户端，可直接用随包命令完成相同预检并保留状态。以下 Bash 示例针对随包的一题 GPQA Lite；变量均来自目标网关、所选服务和本次导入记录。`STATE` 为本次验收专用的新文件路径，续查始终使用同一文件。首次运行不提交模型任务。

~~~bash
set -euo pipefail
umask 077
args=(--base-url "$GATEWAY" --ca-file "$CA_FILE" --user "$GW_USER"
      --dataset GPQA --scope lite --target-id "$TARGET_ID" --resource-id "$SSH_ID"
      --compilation-id "$COMPILATION_ID" --manifest-id "$LITE_MANIFEST_ID")
python3 "$REPO/.skills/deploy-autoeval/scripts/check_evaluation_readiness.py" "${args[@]}"
python3 "$REPO/.skills/deploy-autoeval/scripts/accept_evaluation.py" "${args[@]}" --state-file "$STATE"
~~~

本次模型和资源已获真实调用授权，且费用策略已确认后，在同一终端运行。`BUDGET_REF` 是授权引用；费用上限由已配置的平台账本或供应商执行。超时保留 `STATE` 和原运行标识，先续查已提交运行。

~~~bash
python3 "$REPO/.skills/deploy-autoeval/scripts/accept_evaluation.py" "${args[@]}" \
  --state-file "$STATE" --submit --max-samples 1 --max-attempts 1 --budget-ref "$BUDGET_REF"
~~~
