# DeepSWE v1.1 数据部署

官方任务源为 https://github.com/datacurve-ai/deep-swe，固定提交 `0b9fabbb63b9104d678fe965e1632f2dd9eaa2ea`。服务器已校验并解包任务至 `~/autoeval-platform/datasets/deepswe-v1.1-0b9fabbb/tasks`。

从固定提交导出任务时使用 Git 对象中的原始文件。下面的命令在 DeepSWE 仓库目录中执行，生成可直接传到 Linux 节点的归档。

```sh
git -c core.autocrlf=false archive --format=tar --output=deepswe-tasks.tar 0b9fabbb63b9104d678fe965e1632f2dd9eaa2ea tasks
```

安装脚本在复制前校验 Lite 样本的验证脚本和测试补丁。Windows 工作区的 CRLF 转换会导致 Bash 解析失败，继而缺少原生评分文件。服务器使用该固定提交的独立目录作为只读挂载来源。

在执行服务器运行：

```sh
sh install-deepswe-tasks.sh "$HOME/autoeval-platform/datasets/deepswe-v1.1-0b9fabbb/tasks" autoeval-automationbench-runner-shared
```

脚本核对任务目录，现有容器数据与来源目录不一致时退出。容器重建后可重新运行。控制台选择 `platform.deepswe-v11.v1.harbor`。全量 113 个任务，Lite 为 `abs-module-cache-flags`。

四数据集 Lite 环境预检 `42dbe2ea-5440-4eb1-8897-f068aa62dcdd` 中 GPQA 和 AutomationBench 通过。DeepSWE 剩余 `dataset_not_validated`。MMMU-Pro 仍需对齐工具身份并完成小样本验收。

## 2026-11-20 工具升级与预检

使用固定的 AISBench `d97a8e7` 和 Harbor `f59cb89` 运行新版工具验收。MMMU-Pro 和 AutomationBench 各完成一条样本，原生评分均为 1.0。DeepSWE 启动后，Harbor 将 `openai/` 模型前缀与 `reasoning_effort=max` 组合映射到 `/v1/responses`。预算网关提供 `/v1/chat/completions`，请求返回 404，DeepSWE 无评分、无模型费用。三项已结算 2.522684 元。

同日通过控制台后端接口对当前已登记的配置及各自绑定的 SSH 节点发起 Lite 预检。该组配置仍使用此前固定的工具版本。

| 数据集 | 预检作业 | 结果 |
| --- | --- | --- |
| MMMU-Pro | `f7fc9c4f-0c5d-42e4-9aa1-12e468f51421` | 工具身份与数据路径通过，执行准入缺少 `dataset_not_validated` 对应的验收声明。 |
| DeepSWE | `25749812-7a7e-46f8-b224-5b20d31a9ed0` | 工具身份、数据路径与任务选择通过，执行准入缺少验收声明。 |
| AutomationBench | `8294cb82-e3b7-4aa1-b5ab-c37a88187d39` | 当前绑定配置的预检通过。 |

新版工具需绑定对应的镜像、工具版本和配置后再独立预检。新版原生工具的评分与旧版平台预检分别记录。

离线检查固定版 Harbor 的 MiniSwe 启动参数时，`deepseek/deepseek-flash` 保留了 `reasoning_effort=max` 与指定的接口地址，并走 Chat Completions 的参数分支。该检查截获了启动命令，没有调用模型。配置仍需验证 MiniSwe 到预算网关的完整请求链路。

新版 Agent 基础镜像的默认 `python3` 指向验收目录，而且基础镜像中优先加载的适配器缺少受支持的 Git 版本身份。`deploy/Dockerfile.aisbench-harbor-agent` 将默认解释器指向镜像内的 Python 3.12，并复用精度镜像中的固定版适配器。已在执行节点关闭网络构建派生镜像，完整镜像 ID 见 `backend/tool-locks/aisbench-harbor-d97a8e7.json`。

使用派生镜像的默认 `python3`，以只读方式挂载任务源，DeepSWE 与 AutomationBench Lite 均通过工具和评分器身份、规划器和适配器版本、依赖及任务选择检查。MMMU-Pro 也在新版精度镜像中通过工具身份、依赖与数据文件检查。三项检查均关闭容器网络，未发起模型请求。控制台的资源绑定、网络容量和执行准入仍需按新版镜像验证。

SSH 预检传输保留镜像的 `PYTHONPATH`，并将平台下发的依赖目录放在最前面。MMMU-Pro 使用已完成真实 Lite 验收的同一精度镜像，在 SSH 节点新建临时容器，经平台 `PlanningRemoteContainer.preflight` 检查后返回 `execution_ready=true`，阻塞项为空。测试按已完成的样本验收仅声明 MMMU-Pro 准入。测试容器已回收，运行中的控制台绑定待切换。

同一 SSH 预检路径也验证了新版 Harbor 容器的适配器、规划器、评分器版本及数据路径。无 Docker 守护进程连接的临时容器报告 `harbor_network_unavailable`，DeepSWE 同时报告 `dataset_not_validated`。预检现在会在报告网络容量阻塞的同时继续运行可独立执行的依赖和任务选择检查。

授权后的 DeepSWE 单样本复验改用 `deepseek/deepseek-flash`，Harbor 配置为一条样本、并发 1、重试 0。MiniSwe 进入了 DeepSeek Chat Completions 分支，但私有接口地址没有传入 trial 内的 LiteLLM，日志出现 DNS 解析错误。MiniSwe 自身另有重试层，检测到重试后停止了该 trial，容器和临时路由均已回收。预算账本没有 DeepSWE 请求记录，已结算总额仍为 2.522684 元。后续需在离线 trial 中验证显式 `model.model_kwargs.api_base` 和 `MSWEA_MODEL_RETRY_STOP_AFTER_ATTEMPT=1` 确实到达实际模型进程。

离线适配器现将 Harbor 解析出的显式地址和凭据传入 LiteLLM 的 `DEEPSEEK_API_BASE`、`DEEPSEEK_API_KEY`，并设置 `MSWEA_MODEL_RETRY_STOP_AFTER_ATTEMPT=1`。使用固定版本 Harbor 截获 agent 启动命令，已核对上述环境变量、Chat Completions 参数以及缺少显式网关时拒绝启动的行为。此验证未启动实际模型进程，也未发起网络请求。

随后使用锁定的 MiniSwe 2.4.6 和 LiteLLM 在无外网容器内调用本机模拟网关。模拟网关收到一次带测试凭据的 `POST /v1/chat/completions`，模型字段为 `deepseek-flash`。返回 HTTP 500 后，客户端将错误交还调用方，模拟网关记录的请求总数仍为 1。本轮未使用真实模型，也未产生费用。

随后经授权的单样本复验实际到达预算网关，无重试事件。网关因请求缺少显式 `max_tokens` 返回 `explicit_single_completion_bound_required`。任务终态为 `NonZeroAgentExitCodeError`，没有评分和 DeepSWE 模型费用。验收容器和临时放行规则已回收，总账仍为 2.522684 元。离线适配器现要求明确的输出上限，已另用锁定 MiniSwe 和模拟网关确认一次请求携带 `max_tokens=4096`，返回 HTTP 500 后没有重试。真实执行时仍需将上限与预算授权匹配。

网关回归测试使用与 MiniSwe 请求一致的模型和输出上限。缺少上限或超过测试授权时，请求在读取任务前被拒绝。`max_tokens=4096` 通过请求字段校验并进入任务准入检查。当前 DeepSWE 验收授权的单次输出上限高于 4096，累计费用仍为 2.522684 元。回归测试未调用上游模型。

本地开发 PostgreSQL 已备份并升级至 `0039_compilation_tool_profile`。以当前代码访问该数据库时，执行配置选项和工具档案接口均返回 HTTP 200。迁移为新版编译配置单独绑定工具档案提供存储结构，历史工具档案可继续读取。

使用备份恢复的独立验证数据库，通过标准编译和工具档案接口登记了 MMMU-Pro、DeepSWE、AutomationBench 的 `d97a8e7` 配置。规划选项接口已读到三条记录。以其中的 MMMU-Pro 配置 `87d50213-5b58-4898-8538-4329ec9d5860` 提交预检，规划进程经 SSH 访问锁定镜像，再从状态接口读回作业 `6cc390cf-431f-4c60-8967-0411277add98`，状态 `completed`、`execution_ready=true`。临时容器已回收，验证未调用模型。上述登记属于验证数据库，运行中控制台的数据源未切换。

新版 Harbor 配置通过平台提交并完成预检作业 `f98feee1-db78-4a1e-bda8-3156eb9c5213`。为 DeepSWE 提供镜像内 Harbor 解释器，为 AutomationBench 按标准锁定路径只读挂载 `/acceptance` 后，工具依赖和任务选择检查均通过。AutomationBench 剩余 `harbor_network_unavailable`。DeepSWE 除网络容量外，还缺 `dataset_not_validated` 对应的真实样本验收。该作业 `execution_ready=false`，临时容器已回收。

使用官方 Docker 27.5.1 静态包在验收节点启动临时 Rootless Docker，验证内部网络可创建、检查和回收。新版 Harbor 容器仅连接该独立实例的套接字。平台预检 `842aaf5d-1870-454c-8568-30e4cadad347` 中 AutomationBench 无阻塞项，DeepSWE 仅剩 `dataset_not_validated`。两项均通过网络容量检查。临时容器和守护进程已停止，本轮无模型请求。运行中控制台配置待切换。

AutomationBench 使用配置 `4bbf8a6a-8e32-4498-acc1-0e1ef7303f7b` 单独提交预检 `5995f9ce-b0ea-400f-93bc-b839ff7980a4`，状态接口返回 `completed` 和 `execution_ready=true`，数据集阻塞项为空。测试结束后回收验收容器和独立守护进程。

本机验证控制台 `http://127.0.0.1:5199/#console` 现允许实测环境预检。它使用独立验证数据库、专用工作进程及锁定到两只无外网验收容器的资源绑定，其中 Harbor 容器连接专用 Rootless Docker。浏览器选择 `deepseek-flash` 及 MMMU-Pro、AutomationBench 的 Lite 清单后，控制台实际显示「检查通过」。三数据集预检 `549a1893-751a-4620-8f34-2df5289f67d0` 中 DeepSWE 仅剩真实样本验收。验证入口的代理拒绝提交任务和其他写操作。

## 2026-11-21 控制台预检与 DeepSWE 单样本结果

本机控制台 `http://127.0.0.1:5198/#console` 已切换到使用独立验证数据库的后端。三个数据集均有新版执行配置，并各有全量和 Lite 清单。通过该入口读取联合预检 `64de67dd-2d2b-4463-ab92-4739a4fb952d`，三个数据集实际工具版本均匹配 `d97a8e7`。MMMU-Pro 与 AutomationBench 的阻塞项为空，DeepSWE 的唯一阻塞项是 `dataset_not_validated`。联合预检作业已结束，组级 `execution_ready=false`。该入口仅开放预检写操作。

DeepSWE 的 Harbor 作业 `d97a8e7-deepswe-paid-bounded-live` 执行了单个 trial `abs-module-cache-flags__uiretji`。预算网关结算了 10 次 DeepSWE 模型请求，随后拒绝了下一次请求，原因为 `dataset_request_limit_reached`。Agent 日志中重试次数为 0。trial 终态为 `NonZeroAgentExitCodeError`，没有原生评分。DeepSWE 本轮结算 0.241834 元；三个数据集累计结算 2.764518 元，预留金额为 0，总预算为 10 元。

使用控制台默认选中的执行配置与全量清单提交联合预检 `c0a688b2-a833-4e88-8f24-585e11405cf1`，覆盖 MMMU-Pro 1730 条、DeepSWE 113 条、AutomationBench 600 条的清单配置。作业返回 `completed`，MMMU-Pro 和 AutomationBench 通过，DeepSWE 仅返回 `dataset_not_validated`，整组 `execution_ready=false`。本次仅执行环境检查，模型请求数为 0。

随后按确认的准入规则，将历史验收声明改为数据集提示。相同三项默认全量配置的联合预检 `8c038ca4-24d6-44e6-8227-238aca23fd94` 返回 `execution_ready=true`，三个阻塞列表均为空。DeepSWE 返回提示 `dataset_not_validated`。浏览器显示检查通过、DeepSWE 试跑可选，提交按钮可用。另在验证数据库事务内用三项配置调用后端提交逻辑，返回 `accepted` 后回滚，并确认未留下测评任务。本轮模型请求为 0，DeepSWE 的评分与归档仍待真实任务验证。

### R13 Harbor 私有 Docker 镜像预置

任务 b06c2bbf 使用的 R13 镜像从 Harbor wheel 加载运行时，且未将镜像中的 AutomationBench 适配器加入 Python 导入路径。修复镜像由 `deploy/Dockerfile.r13-harbor` 构建，保留原入口，加载固定 Harbor 源码，并修正 AISBench runner 的异常日志调用。

每个任务的 Rootless Docker 都使用独立镜像仓库。服务器访问 Docker Hub 超时时，Harbor 的 Alpine 内核探测会失败，随后拒绝 DeepSWE 的 `no-network` 策略。`deploy/r13-harbor-rootless-docker.sh` 将已核对镜像 ID 的 Alpine 探测镜像和与源码构建上下文匹配的 egress sidecar 预置到私有仓库。执行配置须同时引用修复镜像与预置 helper。

服务器验证通过了适配器导入、私有 Docker 镜像预置、Harbor 内核探测，以及 sidecar 在 `no-network` 模式启动并安装 nftables 规则。本次验证使用临时容器，未调用模型或运行真实样本。

服务器另用独立 Rootless Docker 网络验证实际 TCP 行为。同一探针共享 sidecar 网络命名空间，切换前可访问同网络的临时 HTTP 服务，执行 `network-policy deny-all` 后请求失败。首次清理等待超时，复查后确认测试 daemon 已退出并移除 supervisor 记录。该检查覆盖容器网络策略，不涉及模型请求或真实 DeepSWE 样本。

#### R13 发布与回滚

在执行服务器上保留 R13 基础镜像和固定版本的 Harbor 构建镜像，从仓库根目录按顺序构建：

```sh
docker build -f deploy/Dockerfile.aisbench-harbor-agent -t autoeval/aisbench-harbor:d97a8e7-f59cb89-agent-container-fix deploy
docker build -f deploy/Dockerfile.r13-harbor -t autoeval/r13-harbor:container-fix-offline deploy
docker tag alpine@sha256:5b10f432ef3da1b8d4c7eb6c487f2f5a8f096bc91145e68878dd4a5019afde11 autoeval/harbor-kernel-probe:alpine-3.23.4
```

服务器镜像库还需保留 sidecar `harbor-prebuilt:harbor-docker-egress-control-sidecar--b67f71411fe7d8f5`。预置 helper 会核验两个镜像的完整 ID，缺失或不匹配时中止，并保留 Harbor 的断网要求。以 0700 安装 helper 到原 `autoeval-rootless-docker` 所在目录，文件名为 `autoeval-rootless-docker-seeded`。

备份执行资源配置文件后，以一次原子替换同时更新 Harbor executor 的 `image_id` 和 `rootless_docker_helper`。镜像 ID 通过 `docker image inspect` 获取。回滚时恢复备份文件，并从 API 和执行 worker 分别核对两项配置。已提交任务引用自己的冻结快照，回滚或切换资源配置时应先核对该资源上仍在等待或执行的任务。

### R13 GPQA 与 MMMU-Pro 数据挂载

任务 b06c2bbf 冻结的 GPQA 执行模板没有数据挂载，MMMU-Pro 只挂载了 `/home/yanhe/agent_deps`。原镜像不包含配置指定的本地数据，原生加载器因缺少路径无法读取数据。服务器已为两个 AISBench executor 增加只读绑定，并保留原有依赖挂载。

| 数据集 | 服务器来源 | 容器目标 | 原生离线加载 |
| --- | --- | --- | --- |
| GPQA | `/home/chenluwen/autoeval-data/gpqa` | `/benchmark/ais_bench/datasets/gpqa` | 198 条 |
| MMMU-Pro | `/home/chenluwen/autoeval-data/mmmu` | `/benchmark/ais_bench/datasets/mmmu_pro` | 1730 条 |

离线检查使用原任务指定的 AISBench 镜像和加载器。API 和执行 worker 已确认读取新挂载。该修复属于执行资源配置，不需要修改 AISBench 数据集源码。未重跑模型或改写原任务历史。

## e968d1b 执行镜像的离线 Agent

使用 `offline-e968d1b-20261126` 的节点按[执行镜像更新与验证](../deploy/deepswe-e968d1b/README.md)更换执行模板，并同步核对外部挂载的 AISBench runner。
