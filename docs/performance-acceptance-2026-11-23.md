# R04–R06 控制台与性能测评验收

日期为 2026-11-23，时间使用北京时间。两项任务均由本次开发工作树的性能页签发起，经过预检、任务 API、事务发件箱、Temporal Worker、真实 SSH 独立容器及持久化 MinIO。测评目标为已登记的 `deepseek-flash`。本次在现有 PostgreSQL 服务中新建独立验收库，沿用授权的资源绑定和凭据引用。原开发库的迁移版本保持为 `0039_compilation_tool_profile`，验收库使用 `0041_report_versions`。

## 页签与回归

浏览器覆盖默认精度页、性能直达与刷新、历史导航、各自草稿、SSH 资源池返回、普通推理和 AgentX 的显式提交，以及性能报告筛选和 CSV 下载链接。组合筛选和分页覆盖跨服务端页面返回的数据。在模拟接口的页签切换和资源池返回过程中，预检和任务 POST 均为零。前端类型检查、构建及 Ruff 通过。后端默认套件 458 项通过，148 项条件跳过。单独开启 PostgreSQL 的提交、幂等、报告和 R13 隔离归档回归 7 项通过。浏览器专项 6 项通过。

## 执行条件

| 项目 | 冻结值 |
| --- | --- |
| SSH 绑定 | `51278e81-b71b-4425-b89f-fd90ce287402` |
| 模型绑定 | `9e3e54a2-b7d8-46d4-94f4-4171d4758167` |
| AISBench | `842d0dd6b87a3a8620b6931aafa1b9089d91485f` |
| 执行镜像 ID | `sha256:3e16fc4efa63d9983b74d719000c0d220ee24712ab5003e4daa655a85f12e7ad` |
| 性能适配器 SHA-256 | `c3d6696069853c2900d49f60159ff7a2c8e1eda0f121fa2fe14ffc08f8d056f2` |
| AgentX 运行环境 | 独立 Python 环境，`agentx-harness==1.0.13` |
| Tokenizer | `deepseek-ai/DeepSeek-V4.1-Flash@314113f8a7dadb388215396ba5fbee2c610a04d6`；`tokenizer.json` SHA-256 为 `c90dfa01249db1be4245780a052ede752e1361c612ac6d08e2bdada7d599476b` |
| Weka 256k | 官方语料 `8fecd2fc56694469f758f0afbbb6335ad3043740`，节点回读 568864747 字节，SHA-256 为 `e39cd2ff3eba21d4a3664be51da743ac3d2149a1933898cafc7bfeac8147eeef` |

## 普通推理

| 项目 | 本次结果 |
| --- | --- |
| 预检 ID | `0d4598d7-0868-4114-bf8b-070879c6451b` |
| 平台任务 ID | `4bad1d5a-3b1a-4cc4-a125-4af78e7ed362` |
| SSH 作业 ID | `7e11b72f-dc1b-4ea0-8461-198ac936f6c3` |
| 运行中观测 | 11:22:46，原生工具进程 24，`tool_running` |
| 报告 ID | `9e3eec15-fb21-49e8-b2bc-80f91dcfcc44` |
| 终态 | 平台 `completed`，SSH 作业 `succeeded`，工具退出码 0，证据 `verified` |

冻结负载为目标输入 32 token、最大输出 4096 token、并发 2、请求 2。原生 JSON 记录成功请求 2，最大并发 2。CSV 实测平均输入 62.5 token、平均输出 260.5 token、最大输出 279 token，两次响应均在输出上限内提前结束。TTFT P90 为 171.7 ms。

从持久化对象存储回读 `synthetic.csv`（781 字节）和 `synthetic.json`（732 字节），分别与报告引用的 SHA-256 `5b3fa76035f36ade19a06b045cad41eb3012dcac4837b9e90e50bf86046b1db0`、`e6c142a7b87e43cf4f5422bb145df9255bd54ac1ce18924badc845a4b449ce67` 一致。CSV 下载内容逐字节一致，逐项核对了指标表中的 68 个数值及原生单位。

## AgentX 轨迹回放

| 项目 | 本次结果 |
| --- | --- |
| 预检 ID | `f4632a84-b5d3-4850-a70a-d3f7459354a0`，含原生 dry-run |
| 平台任务 ID | `96352fd5-b3c6-468e-b295-37ca9b2a89ba` |
| SSH 作业 ID | `45359c09-e1c8-4b23-b18e-bc3bd28863ef` |
| 运行中观测 | 11:23:22 原生进程 24 已启动，11:23:42 观测到脱敏回放计划 |
| 报告 ID | `1c4d170d-0fed-4a3a-9a5d-94f803e4776c` |
| 终态 | 平台 `completed`，SSH 作业 `succeeded`，工具退出码 0，证据 `verified` |
| 原生判定 | `parse_status=success`，`comparison_scope=smoke`，`benchmark_valid=false` |

使用 Weka `256k`，会话并发 1，`smoke` 时长 60 秒，trace 上限 1。原生摘要记录 16 个请求，吞吐 0.2522835776 requests/sec。TTFT P90 在原生 JSON 中为 877.8683645 ms，在原生 CSV 中按两位小数显示为 877.87 ms。

逐个回读对象存储中的 11 个文件，核对大小和 SHA-256，覆盖 manifest、脱敏回放计划、summary CSV/JSON 和 `agentx_raw`。下载的 `agentx_summary.csv` 与对象存储原件逐字节相同，大小 7771 字节，SHA-256 为 `43e45e15901559c9b51ad3d415264af1d7c97504cc50294463809bd7cf462876`。报告指标表中 386 个统计值及单位与原生 JSON 一致。

归档完成后，通过 SSH 按上述两个作业 ID 查证，两个专属执行容器均已回收。

## 验证范围

真实 SSH 验收覆盖以上两次模型作业。AgentX 多档、提前失败及后续档位缺结果使用固定产物回归；断线查证和取消使用 R13 专项回归。本次没有运行 900 秒正式 benchmark、Weka full 或极光资源作业。该次 smoke 的性能数值仅适用于记录的链路与配置。
