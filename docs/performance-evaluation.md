# 控制台性能测评

打开「控制台 → 性能测评」，或直接访问当前平台的 `#console/performance`。普通推理用于测量给定请求数、长度和并发下的表现；AgentX 用 Weka 轨迹回放多轮会话。切换精度与性能页签会保留本次访问中的表单，预检和提交由用户手动触发。

## 接入模型服务

已有服务可直接从「模型服务」选择。首次使用时，打开「管理模型服务 → 新增服务」，按端点的实际提供方选择来源。同一个平台模型可以绑定不同推理服务。模型服务负责响应推理请求，SSH 节点负责运行 AISBench 客户端，两者分别选择。

| 服务来源 | 地址 | 模型名与凭据 |
| --- | --- | --- |
| 本地模型服务 | 团队部署的推理端点，例如 `https://inference.example.com/v1` | 部署时指定的模型名、本地服务访问密钥 |
| 官方 API | 模型厂商公布的 API 基础地址 | 厂商 API 使用的模型 ID、厂商签发的 API Key |

先选平台「模型标识」，再选「模型版本」。上表的模型名是请求实际发送给端点的标识。本地服务填写执行节点可访问的 HTTP 或 HTTPS 地址，可含端口。官方 API 填写平台允许列表内的 HTTPS 地址，保留厂商要求的基础路径。切换来源会清空地址、远程模型名和密钥。

点击「保存服务绑定」后，在模型服务列表中检测连接。本地模型服务选择 SSH 节点进行检测；官方 API 可直接检测模型列表。点击「用于测评」选择该服务。管理列表支持按来源筛选，历史绑定显示「待确认」时可在「编辑服务」中确认来源。

## 提交作业

1. 选择模型服务与 SSH 执行节点。新节点先按下方「节点准备」配置运行镜像和挂载。
2. 普通推理填写目标输入 token 数、最大输出 token 数、并发数和请求数。AgentX 选择 `256k` 或 `full` 语料，填写会话并发档位和每档时长。默认 `smoke`，可以限制 trace 数；正式 `benchmark` 每档至少 900 秒。
3. 点击「环境预检」。预检通过后点击「提交性能测评」，进入任务详情。修改服务、节点或负载后需重新预检，页面提示预检过期时也需重新检查。

## 查找任务与报告

- **查运行记录**　在「任务管理」（`#tasks`）按任务 ID 或模型名搜索，打开任务详情查看执行阶段、最近观测和配置快照。仍在运行的任务可以申请取消。
- **查原生指标**　归档后点击任务详情中的「查看报告」。也可进入「报告管理」（`#reports`），将「任务类型」设为「性能」，结合模型、分析状态或任务 ID 查找。普通推理和 AgentX 都归在此类型。
- **核对原始数据**　报告开头展示冻结配置。「指标明细」可按指标名或统计口径搜索，「CSV 预览」最多显示 50 行，「原生 CSV 下载」用于核对完整文件。普通推理的最大输出长度是配置上限，模型可提前结束。核对实测长度时请使用原生结果中的输入、输出 token 统计。
- **判断适用范围**　AgentX 按会话并发档位展示结果。`comparison_scope=smoke` 表示这次回放验证了链路；达到原生有效性条件的本地语料 benchmark 才标为 `internal_only`。解析失败时查看该档的解析状态，证据不可用时检查对象存储归档。

2026 年 11 月 23 日的真实 SSH 验收覆盖普通推理和一次 Weka `256k` 单档 smoke，已从对象存储回读 CSV 并核对原生指标。正式 benchmark、Weka full 和极光节点仍待实测。[任务 ID、实测值与验收范围](performance-acceptance-2026-11-23.md)

## 接口参数

预检使用 `POST /api/autoeval/v1/planning/resources/preflight`，提交使用 `POST /api/autoeval/v1/evaluation-tasks` 并携带 `Idempotency-Key`。请求体的 `performance` 字段示例如下。

| 方式 | 请求示例中的 performance | 实测证据 |
| --- | --- | --- |
| 普通推理 | `{"kind":"inference","input_tokens":512,"max_output_tokens":128,"concurrency":1,"requests":4}` | 合成 token 负载、流式单次尝试、零预热。实际输入包含服务的聊天模板开销，输出可提前结束。 |
| AgentX | `{"kind":"agentx","variant":"256k","run_mode":"smoke","duration":60,"concurrency":1,"trace_limit":1}` | Weka 会话的多轮请求、原生 manifest 和性能摘要。一次 trace 可产生多次模型调用。 |

两个请求均需同时提供 `target_id`、`resource_id` 和 `resource_kind="customer_ssh"`。AgentX 的 `concurrency` 可为单个并发数，也可为按顺序执行的档位列表（如 `[1,4]`）。启用预算代理时需为对应目标和数据集标识（`Synthetic` 或 `AgentX`）配置 evaluation grant。报告注明是否经预算网关。

报告列表接口 `GET /api/autoeval/v1/reports` 支持 `task_type=performance`，可与 `model`、`analysis_status`、`query`、`offset` 和 `limit` 组合。

## 节点准备

在目标 Linux 节点用官方 Ubuntu / Python 3.12 AgentX 镜像和独立的 AISBench 源码检出构建客户端。Dockerfile 固定基础镜像摘要，检查 Git 版本和独立 harness 环境。取得构建完成的镜像 ID。按后端 README 启动 API、规划预检进程、dispatcher、workflow、planning-execution 和 reconciler；模型、SSH 凭据通过已有资源绑定管理。

```sh
git clone --no-checkout https://github.com/AISBench/benchmark.git aisbench-performance-source
git -C aisbench-performance-source checkout --detach 842d0dd6b87a3a8620b6931aafa1b9089d91485f
cp deploy/performance.Dockerfile aisbench-performance-source/Dockerfile.autoeval
docker build -f aisbench-performance-source/Dockerfile.autoeval -t autoeval/performance:842d0dd6 aisbench-performance-source
docker image inspect --format '{{.Id}}' autoeval/performance:842d0dd6
```

在 `AE_PLANNING_CONTAINER_CONFIG` 指向的受保护文件中，给相应 SSH 资源的 `executors` 对象增加 `llm_perf` 和 `agentx` 两个条目。二者可引用同一镜像，每个条目的结构如下。将占位值替换为节点实值；目标上下文数取自已登记服务的实际能力。

```json
{
  "revision": "842d0dd6b87a3a8620b6931aafa1b9089d91485f",
  "image_id": "sha256:<实际镜像摘要>",
  "readonly_mounts": [
    {"source": "/srv/models/example-tokenizer", "target": "/models/example"},
    {"source": "/srv/bench/weka", "target": "/data/weka"}
  ],
  "targets": {
    "<target-binding-uuid>": {"tokenizer_path": "/models/example", "context_tokens": 262144}
  }
}
```

普通推理只需要对应模型的 tokenizer。AgentX 须在 `/data/weka/256k/traces.jsonl` 或 `/data/weka/full/traces.jsonl` 提供匹配的官方语料。预检核对语料 SHA-256、固定 AISBench 版本、适配器摘要、tokenizer 与 AgentX 的 dry-run。本地语料的有效 benchmark 结果仅供内部对比（`internal_only`）；冒烟作业按 `smoke` 单独记录。控制台按档位数和每档秒数显示配置的测量总时长，预热、档间冷却和归档另计。详见[上游固定版本文档](https://github.com/AISBench/benchmark/blob/842d0dd6b87a3a8620b6931aafa1b9089d91485f/docs/source_zh_cn/extended_benchmark/agentx/agentx.md)。
