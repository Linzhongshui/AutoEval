# 从 OBS 准备 AutoEval 运行镜像

2026-11-24 的 Linux AMD64 快照覆盖 GPQA、MMMU-Pro、AutomationBench、DeepSWE 使用的镜像，以及平台和 Langfuse 服务。9 个归档、136 个不同镜像 ID 均列在 `obs://aisbench/images/autoeval/runtime-20261124/manifest.json`。同目录 `README.md` 提供路径总表。后续快照需按新的清单和独立确认的摘要核对。

DeepSWE 新 x86 部署选用指定的 Ubuntu 24.04 / Python 3.12 执行镜像 `obs://aisbench/images/agent_time/ais_bench_agent_runtime_image_v3.1-20261119-master-ubuntu24.04-py312-x86_64.tar.gz`。先从该独立路径取得执行镜像，再从快照选取对应任务镜像。归档 SHA-256、Docker 标签、镜像 ID 及离线启动命令见 [DeepSWE x86 部署与验收](deepswe-pier-x86.md)。复现旧任务时使用其冻结的模板和镜像。

## 按目标选包

跨环境首次发起任务还需导入数据资源包，并在目标平台重新绑定模型、SSH 节点和执行模板。快照的数据库、持久化对象、题目文件和各执行器挂载位置见[跨环境测评资源](evaluation-bootstrap.md)。

2026-11-25 的配套资源清单路径为 `obs://aisbench/autoeval/deployment-resources/20261125/portable-eval-08eb3dd-v1/manifest.json`。中转机按清单的 `object` 下载加密 ZIP，分别校验密文与明文的 SHA-256。解密口令通过单独的受保护通道移交，目标无需 OBS 密钥。

~~~bash
set -euo pipefail
umask 077
prefix=obs://aisbench/autoeval/deployment-resources/20261125/portable-eval-08eb3dd-v1
obsutil cp "$prefix/manifest.json" ./resources-manifest.json
expected=6d0ff97aac20981ee37fc4474d9c3b5815130d1957281f974f390493644e5814
[[ "$(jq -er .cipher_sha256 resources-manifest.json)" == "$expected" ]]
[[ "$(jq -er .object resources-manifest.json)" == "$prefix/autoeval-evaluation-kit-20261125.zip.enc" ]]
obsutil cp "$prefix/autoeval-evaluation-kit-20261125.zip.enc" ./resources.zip.enc
printf '%s  %s\n' "$(jq -er .cipher_sha256 resources-manifest.json)" resources.zip.enc | sha256sum -c -
openssl enc -d -aes-256-cbc -pbkdf2 -iter 600000 -md sha256 \
  -pass "file:$PASSFILE" -in resources.zip.enc -out resources.zip
printf '%s  %s\n' "$(jq -er .zip_sha256 resources-manifest.json)" resources.zip | sha256sum -c -
~~~

仅准备 GPQA、MMMU-Pro 或 AutomationBench 的执行节点时，可从 `obs://aisbench/images/autoeval/datasets/20261125/manifest-67a419b3c257.json` 选用 2026-11-25 的独立镜像包。清单以 `gpqa`、`mmmu-pro`、`automationbench` 为顶层键；对应条目的 `uri` 给出下载路径，`sha256` 与 `size` 用于校验文件，`images` 用于导入后核对标签和镜像 ID。AutomationBench 独立包已合并该执行节点需要的 runner、任务基础镜像与辅助镜像。三包均需配套下表列出的数据或任务挂载。下文 Bash 示例使用的是 11 月 24 日整个平台清单的字段。

| 目标 | 取用的清单分组 | 另行准备 |
| --- | --- | --- |
| 平台服务 | `platform` | 对应发布的前端、Compose、网关配置、TLS、凭据、数据库及对象存储 |
| GPQA、MMMU-Pro | `dataset-executors` | 资源绑定、各自的数据目录、工具锁和只读挂载 |
| AutomationBench | `dataset-executors`、`deepswe-lite`、`harbor-support` | 任务源和 Rootless Docker helper。Lite 包提供共用 Harbor runner、探测镜像和 sidecar；600 个任务共用的基础镜像在 harbor-support 包中 |
| DeepSWE 原生 Pier，Linux x86_64 | 单题使用 `deepswe-lite` 中的任务镜像，全量使用 `deepswe-full` | 指定的 11 月 19 日执行镜像、Pier 控制端 ZIP、任务目录和所选 Agent 的依赖，见 [Pier x86 手册](deepswe-pier-x86.md) |
| DeepSWE Lite（平台 Harbor） | `dataset-executors`、`deepswe-lite` | 固定任务源、wheelhouse、helper 与样本离线归档挂载 |
| DeepSWE 全量 | DeepSWE Lite 两包，再加 `deepswe-full` | 全量包覆盖 113 个任务标签，需将选中任务的镜像供给实际执行分片 |
| 可选服务或兼容环境 | Langfuse 用 `langfuse`，分析及预算用 `analysis-budget`。独立执行容器或历史任务恢复按原配置选择 `standalone-dataset-runners` 或 `archived-task-runners` | 核对服务绑定的镜像 ID 和 Docker 引擎。只有需要恢复对应能力时才取包 |

## 在可访问 OBS 的中转机下载

以下为 Bash，使用已配置只读访问的 obsutil、jq 和 sha256sum。在有足够空间的发布缓存目录执行。密钥通过受保护的客户端配置提供。示例选择平台和 GPQA；按上表调整 groups。

~~~bash
set -euo pipefail
prefix=obs://aisbench/images/autoeval/runtime-20261124
obsutil cp "$prefix/manifest.json" ./manifest.json
echo '54056f812c0b7f29be468c99dcfe3440c049b9f877e73ed07d5cbb22e258b092  manifest.json' | sha256sum -c -
groups=(platform dataset-executors)
for group in "${groups[@]}"; do
  uri=$(jq -er --arg g "$group" '.archives[$g].uri' manifest.json)
  sha=$(jq -er --arg g "$group" '.archives[$g].sha256' manifest.json)
  file=${uri##*/}
  if ! test -f "$file"; then obsutil cp "$uri" "./$file"; fi
  printf '%s  %s\n' "$sha" "$file" | sha256sum -c -
done
~~~

将选定压缩包与 manifest.json 一起传入目标机，重新核验清单和压缩包摘要。机器完全离线时，以上下载步骤全部留在中转机；执行节点无需 OBS 凭据。

## 在实际使用镜像的引擎上导入和核对

目标机进入收到的文件目录。示例向当前 Docker 引擎导入一个分组；先用 docker info 核对引擎身份、架构和磁盘，再按需对每组执行。用 jq 从同一份已校验的清单读取标签与 ID。如果已有同名标签指向其他 ID，先核实原服务绑定及切换窗口，再导入。

~~~bash
set -euo pipefail
echo '54056f812c0b7f29be468c99dcfe3440c049b9f877e73ed07d5cbb22e258b092  manifest.json' | sha256sum -c -
group=platform
engine=(docker)
uri=$(jq -er --arg g "$group" '.archives[$g].uri' manifest.json)
sha=$(jq -er --arg g "$group" '.archives[$g].sha256' manifest.json)
printf '%s  %s\n' "$sha" "${uri##*/}" | sha256sum -c -
"${engine[@]}" load < "${uri##*/}"
rows=$(jq -er --arg g "$group" '.archives[$g].refs | to_entries[] | [.key,.value] | @tsv' manifest.json)
while IFS=$'\t' read -r tag expected; do
  actual=$("${engine[@]}" image inspect --format '{{.Id}}' "$tag")
  [[ "$actual" == "$expected" ]] || { echo "镜像 ID 不符 $tag" >&2; exit 1; }
done <<< "$rows"
~~~

- 对独立 Langfuse 引擎，将上例设为 `group=langfuse`，并用目标 Docker context 或 `engine=(docker exec -i "$DIND_CONTAINER" docker)`。先确认该容器属于本次部署。宿主与子引擎可能有同名标签，各自在使用方核验。
- Harbor 的每个执行分片可有独立 Rootless Docker 镜像库。按资源配置安装 helper、映射离线归档并在分片内检查实际样本标签及 ID。DeepSWE Lite 若要求 `/opt/autoeval-cache/deepswe-85f743fa1c3b.tar`，先从已导入的 Lite 包中按锁定标签用 docker save 单独导出样本镜像，再按部署配置只读挂载。AutomationBench 同理准备其基础镜像归档。
- OBS 清单的 `archives` 描述分组，`usage_by_image_id` 描述盘点时的用途。该快照的 API 和部分后台角色运行不同镜像；恢复原实例时按角色核对。发布新版本时按选定源码和迁移生成 [内网发布配置](intranet.md)，其中 images.json 的字段与 OBS 清单不同，直接替换会导致配置生成失败。
- 镜像层不包含宿主挂载的数据和业务卷。导入后按 [验收与恢复](acceptance-recovery.md) 检查入口、队列、只读挂载和固定样本归档，分别记录镜像核验与实际执行结果。
