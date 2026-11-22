# DeepSWE v1.1 数据部署

官方任务源为 https://github.com/datacurve-ai/deep-swe，固定提交 `0b9fabbb63b9104d678fe965e1632f2dd9eaa2ea`。服务器已校验并解包任务至 `~/autoeval-platform/datasets/deepswe-v1.1-0b9fabbb/tasks`。

在执行服务器运行：

```sh
sh install-deepswe-tasks.sh "$HOME/autoeval-platform/datasets/deepswe-v1.1-0b9fabbb/tasks" autoeval-automationbench-runner-shared
```

脚本核对任务目录，现有容器数据与来源目录不一致时退出。容器重建后可重新运行。控制台选择 `platform.deepswe-v11.v1.harbor`。全量 113 个任务，Lite 为 `abs-module-cache-flags`。

四数据集 Lite 环境预检 `42dbe2ea-5440-4eb1-8897-f068aa62dcdd` 中 GPQA 和 AutomationBench 通过。DeepSWE 剩余 `dataset_not_validated`。MMMU-Pro 仍需对齐工具身份并完成小样本验收。

## 在私有 Rootless Docker 上重跑

在执行节点使用 SSH 执行账户的 UID 和 GID 构建 Harbor runner。仓库根目录下的构建命令如下。

```sh
docker build -f deploy/Dockerfile.r13-harbor \
  --build-arg RUNNER_UID="$(id -u)" --build-arg RUNNER_GID="$(id -g)" \
  -t autoeval/harbor-runner:shared-workdir deploy
```

在选定资源的 `executors.harbor` 中固定新镜像 ID，设置 `rootless_docker_helper` 和 `shared_trial_workdir: true`。新分片在宿主机和 runner 内使用相同的私有路径 `/var/tmp/autoeval-harbor-job-<分片 UUID>`。执行账户需要有权读取挂载的数据集和工具。使用原冻结模板的分片仍按原路径读取。

DeepSWE 使用隔离网络调用模型时，可在构建 runner 时传入 `--build-arg DEEPSWE_MODEL_ORIGIN=https://api.deepseek.com`。该值必须匹配所选模型的 HTTPS 服务地址。Harbor 仅在 MiniSwe 的 Agent 执行阶段应用该主机许可，安装和评分阶段继续使用各自的网络策略。已有的显式主机清单优先。

离线安装 MiniSwe 时，将经过校验的 wheelhouse 只读挂载到 `/acceptance/deepswe-lite-wheelhouse-20261120`。离线安装器核对清单摘要和包哈希，使用 Python 3.12 安装 MiniSwe 2.4.6。可先用样本镜像在禁网环境运行安装并检查 `mini-swe-agent --help`。随后通过平台预检并提交单 Case，分别检查原生执行记录、评分和归档结果。

回滚前先停止受理新分片，等待使用新模板的在途分片完成归档和目录回收，再恢复资源配置和上一版服务镜像。

对于 bs-module-cache-flags 的固定样本镜像，执行节点可将已核对发布方镜像 ID 的 Docker 归档只读挂载到 /opt/autoeval-cache/deepswe-85f743fa1c3b.tar。使用 deploy/harbor-offline-docker.sh 时，Harbor 检查镜像操作系统前会按需载入归档，并再次校验分片内的镜像 ID。
