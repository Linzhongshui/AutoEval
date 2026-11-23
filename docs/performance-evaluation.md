# 控制台性能测评

控制台默认显示精度测评。打开 `#console/performance` 选择普通推理或 AgentX，指定模型服务及登记的 SSH 节点，点击「环境预检」，通过后提交。可在任务管理中查看阶段、最后观测时间、远程任务标识和取消结果。预检及提交分别复用 `POST /api/autoeval/v1/planning/resources/preflight` 和 `POST /api/autoeval/v1/evaluation-tasks`，提交携带 `Idempotency-Key`。性能请求用 `performance` 代替精度请求的 `tasks`。

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

普通推理只需要对应模型的 tokenizer。AgentX 须在 `/data/weka/256k/traces.jsonl` 或 `/data/weka/full/traces.jsonl` 提供匹配的官方语料。预检核对语料 SHA-256、固定 AISBench 版本、适配器摘要、tokenizer 与 AgentX 的 dry-run。使用本地语料时上游决定可比范围。详见[上游固定版本文档](https://github.com/AISBench/benchmark/blob/842d0dd6b87a3a8620b6931aafa1b9089d91485f/docs/source_zh_cn/extended_benchmark/agentx/agentx.md)。

## 参数与报告

| 方式 | 请求示例中的 performance | 实测证据 |
| --- | --- | --- |
| 普通推理 | `{"kind":"inference","input_tokens":512,"max_output_tokens":128,"concurrency":1,"requests":4}` | 合成 token 负载、流式单次尝试、零预热。实际输入包含服务的聊天模板开销，输出可提前结束。 |
| AgentX | `{"kind":"agentx","variant":"256k","run_mode":"smoke","duration":60,"concurrency":1,"trace_limit":1}` | Weka 会话的多轮请求、原生 manifest 和性能摘要。一次 trace 可产生多次模型调用。 |

两个请求均需同时提供 `target_id`、`resource_id` 和 `resource_kind="customer_ssh"`。AgentX 的 `concurrency` 可为单个并发数，也可为按顺序执行的档位列表（如 `[1,4]`）。一份报告按档位展示指标、可比范围与 CSV。正式 AgentX 每档至少 900 秒，仅 smoke 接受 trace 数上限。启用预算代理时需为对应目标和数据集标识（`Synthetic` 或 `AgentX`）配置 evaluation grant。报告注明是否经预算网关。

报告管理支持精度、性能及其他类型筛选。性能报告按原生文件归档配置、指标、单位、分位数及 CSV 预览；原始 CSV 下载会校验内容摘要。缺失文件、解析失败与 smoke 范围分别显示。平台的规划用吞吐曲线保持独立。首次真实验收记录了节点、镜像、参数、任务和报告 ID、原生 CSV 摘要及逐项指标核对结果。[普通推理与 AgentX smoke 验收](performance-acceptance-2026-11-23.md)
