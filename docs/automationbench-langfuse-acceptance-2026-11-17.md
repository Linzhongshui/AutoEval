# AutomationBench → Langfuse 真机验收记录（2026-11-17）

**用户验收确认：2026-11-17，用户已确认本轮平台跳转、Langfuse 轨迹及 full 正文展示验收通过。** 对应实现提交为 `87061ee`，正文 Trace 为 `b48a5cdee574516489fa28c8e911b89c`；下文保留各阶段验证范围及原任务历史状态，不将本次确认追溯改写为修复后重新测评或正式报告链路已重验。

本轮真实 agent 轨迹的归档、自动导入、平台新标签页跳转、层级映射与原生评分核对已通过。**整体验收仍为分项通过**：真实任务在评分解析修复前已被平台归档为失败，未生成正式报告；修复后的报告“样本明细”入口没有本轮真实报告可验证。按用户边界，实际模型调用后不再重新提交测评，也不将旧任务状态改写为成功。

## 固定输入与部署

- 单样本 `automationbench-support-1587-0252fa3e9d`，1 次尝试、并发 1；官方 AutomationBench 提交 `4a8e1061254004d9dac807054eed33fad7d1ff14`，Harbor 提交 `641c9f06b5a22704b8633d05f7ec1e9b5894c83d`，适配器提交 `955089ab32ef696c231d628f5ad0d9da28f430c4`。
- agent 为 `automationbench_adapter.agent:AutomationBenchOfficialAgent`；模型 `deepseek-flash`，单次输出最多 65536 tokens、effort=max、thinking enabled，最多 50 次真实 HTTP 请求。实际 **38 次请求、38 个 HTTP 200**；没有自动重跑模型。请求审计不记录 key、headers 或对话。
- 任务运行镜像 `harbor-automationbench:e45f2f2ac0d7e2215205fa44`，内容摘要 `sha256:086c2b1898ad38faa5420a29046e8430c285e2fae35bdea3977b5fc5b6afa779`；任务基于离线锁定依赖构建。预检补齐 CPU PyTorch；关闭不可联网拉取 BuildKit 的构建路径，使用已缓存运行镜像。
- 原生输入、工具配置与预算通过独立 operator acceptance compilation 固定，不冒充官方标准仓配置。最终 compilation 为 `31223be4-ef1d-43f2-91b0-2af67214343a`，SSH 资源为 `c84c335e-2249-40a1-b856-613a607d2f23`。
- runner 使用所属目录在宿主机与容器之间的相同绝对路径挂载，`runtime_root=/home/chenluwen/autoeval-automationbench-acceptance-20261116/platform-runtime`。先执行 `nop + install_only` 检查，1 trial 完成、0 错误、0 模型调用，再提交真实任务。
- 平台基线提交 `d1a6b6517c087412ec6623ac80f3e0c9194e5c04` 加本轮工作区修复；不是已提交的整仓发布快照。API、planning、planning-execution、Langfuse worker 最终镜像为 `sha256:482d106c536f0cfe2f3f1b4016eaf911c92896739250e3ff6929d687a54cd9a8`，使用原有四层 Compose 加独立 validation override；保留其他服务。
- Langfuse 4.70.1，项目 `autoeval-harbor`，独立 PostgreSQL / ClickHouse / Redis / MinIO 与持久卷；demo 仍使用原有 PostgreSQL、S3 和 Temporal。`0032_langfuse` 已应用。已清除旧 `/opt/harborstack-src` 的 PYTHONPATH 遮蔽，使 worker 使用锁定的安装包。
- fork 已发布命名评分修复：[a62c1be](https://github.com/llauren48/harbor-otel-stack/commit/a62c1be62888e2cb5c89f92aa2dc00731f4f5ed1)，分支 `fix/automationbench-verifier-metrics`。依赖锁、requirements 与部署脚本统一固定此提交。服务后端只接收凭据引用；交付物不包含凭据。

## 真实执行与产物

| 项目 | 实际结果 |
| --- | --- |
| Run | `a6ec7563-4326-45e9-9348-754ebff65e89` |
| 执行 job | `8124d404-5ac9-443e-9f5e-54804fdf6a5d` |
| Case attempt | `dfc4cdf5-9169-43d1-9369-548afbe9579e`，attempt 1 |
| 原生执行 | 无 exception，agent 与 verifier 均执行完成 |
| 原生 verifier | `verifier_result.rewards.accuracy=1.0`，与 `verifier/reward.json` 一致 |
| 平台历史状态 | failed；原汇总 partial、scored_cases=0，原生 case 执行状态 succeeded |
| Trace | `cfc0e6ea48fd58abbf8bc638c4e0cb36`，自动导入 succeeded |
| 结构 | 1 root、38 generation、66 tool，共 105 observations，ID 唯一，全部父子关系一致 |
| Langfuse 评分 | `reward.accuracy=1.0`，ClickHouse FINAL 验证记录数 1；未虚构通用 reward |
| 产物包 SHA-256 | `8536be36c8cff1baacaad215d3fb83bfaa665433d49a9feb6954902835657fda` |
| ATIF SHA-256 | `2aad216726c24250562dc27f37ccd0a5bf25d0b6e89546f34d4580a9a57b78b7` |

平台入口：[本轮任务](https://179.214.2.3/#run/a6ec7563-4326-45e9-9348-754ebff65e89)。在样本执行记录点击“查看 Trace”，打开 [本轮真实轨迹](https://179.214.2.3:8443/project/autoeval-harbor/traces/cfc0e6ea48fd58abbf8bc638c4e0cb36)。需要原有 VPN、证书及 Langfuse 登录；现使用 IP + 8443，无需 hosts。

评分解析问题已修复：平台仅在两个原生评分文件一致时识别 AutomationBench accuracy；缺失值不补造，不使用适配器漏算后的总分占位值。fork 保留命名指标，导入为 `reward.accuracy`。使用本轮对象存储中已有产物做只读重解析，结果为 complete、scored_cases=1；没有覆写旧 case 证据、成绩汇总或任务失败历史。针对本轮已有 Trace 补验评分，无模型调用，observations 仍为 105。

ATIF 未提供逐步时间戳；Langfuse 展示的约 0.04 秒不是模型或工具实测耗时，根节点标记 `atif.timing_missing`，节点时间来源为 unknown。原生 result 中 agent 执行时间为 02:19:53–02:24:32 UTC。原适配器输出的 token 数为 0，不据此声称真实 tokens 或费用为零。首轮仅 structural 模式展示摘要和工具层级，不包含完整对话原文。

## 固定产物、恢复与失败边界

- 固定产物 run `e9af725c-ffe2-40ec-8047-5fd092f133a4` 通过真实归档、Outbox、Temporal worker 导入。两个有效执行尝试映射不同 Trace；缺少轨迹显示 missing，损坏轨迹显示 failed。
- 鉴权失败恢复使用独立人工夹具 run `85255f8c-cf93-4e47-8774-6cee82f3e67c`。错误 key 导入失败，公开 retry 接口只重新排队失败导入，恢复后成功，无测评重发。
- 夹具 Trace `9eb9856bc1fe53b0bf89c37f5ece4953` 重复导入保持 4 observations、reward=1 且评分记录数 1。独立 Langfuse web/worker 重启后仍可查询，并通过平台浏览器跳转。没有重启其他用户的 `harborstack-default`。
- 查询失败、401、部分 observations 的单元测试均确认不盲目重发；部分写入暂时拒绝自动重发，防止 Langfuse v4 追加重复 observations。此项是失败可见和幂等保护，不代表已支持部分 observations 自动补齐。
- 配置缺少后端地址、浏览器地址、项目或任一 key 时，新归档有轨迹的记录为 disabled；不提供成功链接。AISBench 保持 unsupported。相关分支以单元测试验证，未逐一修改生产配置制造故障。
- 本轮先前 4 次平台提交均确认零真实请求：缺 PyTorch (`1f820ba1…`)、任务目录名筛选错误 (`9ea5b288…`)、BuildKit 无法拉取镜像 (`a72acc40…`)、预算器在发送前拦截重命名的 token 参数 (`eb26b790…`)。后续均在用户零调用重试授权内修复；最后一轮实际调用后没有再提交。
- 第一轮预检失败保留 cleanup_pending 与容量租约，尚未人工解除，不将未知的 Harbor 外部容器所有权默认为可释放。最新真实任务 cleanup 为 not_required，无重测待执行。

## 检查与证据

后端全量 pytest、Ruff、前端 typecheck / build，以及 Chrome 平台 → Langfuse 新标签页真实交互已执行。最终全量结果为 312 passed / 121 skipped，Ruff 通过，前端 typecheck 与 build 通过，真实 Chrome 跳转测试 1 passed。fork 命名评分与转换相关测试 27 项通过；曾尝试整个 fork 测试集，Windows 下为 100 passed / 17 failed，失败涉及路径转义、默认 GBK 与 Unix 权限假设，未将该结果宣称全量通过，Linux 全量尚未运行。

- [真实轨迹与摘要核对](evidence/automationbench-real-trace-evidence.json)
- [已有产物只读重解析](evidence/automationbench-score-reparse-evidence.txt)
- [实际请求次数审计](evidence/automationbench-request-audit-summary.json)
- [Langfuse 真实命名评分](evidence/automationbench-langfuse-scores.jsonl)
- [固定产物失败恢复](evidence/automationbench-fixture-recovery-evidence.json)
- [平台跳转截图](../deliverables/automationbench-langfuse-platform.png)
- [真实 agent 工具树截图](https://github.com/llauren48/AutoEval-Platform/blob/1faf83a0d78d880324280f7d9e2656291ce00734/deliverables/automationbench-langfuse-trace.png)

后续若要判定修复后的“新真实任务 completed → 报告样本明细 → Trace”全链路通过，需要新的模型执行授权；本轮不自动扩样或重跑。

## 同日 UI 与登录回跳修复

样本表中的“查看证据”和“查看 Trace”已改为独立按钮，保留明确间距、键盘焦点和新标签页提示，去掉重复说明及表格中的冗长摘要。新版前端已发布，旧静态资源备份位于服务器 validation 目录的 `frontend-before-trace-ui-20261117.tgz`。

用户截图中的权限错误页复现为无 Langfuse 登录会话时的默认显示。现由 Nginx 引导到 Langfuse 原生登录页，使用当前版本的 `targetPath` 参数保留原项目与 Trace；会话有效时直接进入轨迹。项目权限仍由 Langfuse 校验。真实 Chrome 回归 **2 passed**（首次登录回跳、已有会话直达），前端类型检查及构建通过，Nginx 配置检查及热重载通过；没有新增模型调用，原任务状态未修改。更新后的截图仍使用上方证据链接。

## 用户选择的单条免登录分享

随后按用户明确选择，为本轮演示 Trace `cfc0e6ea48fd58abbf8bc638c4e0cb36` 开启 Langfuse 原生公开分享，并为这一条路径配置网关例外。平台按钮沿用该记录的链接，首次打开直接看到 structural 轨迹。其他 Trace 及新导入任务不会自动公开。

真实 Chrome 再次验证 **3 passed**：匿名平台跳转直达、已登录平台跳转直达、未公开的独立夹具 Trace 仍要求登录。匿名场景确认不存在 Langfuse session-token cookie；前端类型检查、构建、Ruff 和 Nginx 配置检查通过。此变更没有重跑测评或改变成绩。撤销分享及网关配置说明见接入文档。

匿名访问截图：[公开 Trace 页面](../deliverables/automationbench-langfuse-public-trace.png)。公开链接可被能到达服务器且持有该链接的人访问；本次仅分享这一条脱敏演示轨迹。

## 正文模式补验（同日）

按用户后续要求启用 full。新增 `0033_langfuse_content_mode`，迁移前完成业务库备份，旧记录默认保持 structural，新归档默认 full；已有任务不会因配置改变而自动重新导入。正文 Trace 使用独立稳定命名空间，保持旧公开摘要不变。

本次从相同原生产物生成私有正文 Trace `b48a5cdee574516489fa28c8e911b89c`，确认导入后更新该 attempt 的平台链接并追加模式切换审计。仍为 105 个唯一节点：38 generation、66 tool、1 root。35 条非空模型回复、66 个工具参数和 66 个工具输出与 ATIF 一致，38 条 reasoning_content 与对应节点 Attributes 一致；其余 3 条回复原本为空字符串，Langfuse 表示为 null，未补造文本。

模式固定、正文保留与跨模式身份隔离回归通过，后端全量 315 passed / 123 skipped，Ruff、前端类型检查 / 构建通过。私有正文的未登录回跳、已登录直达和匿名权限隔离浏览器检查 **3 passed**。本次没有新增模型请求，原任务 failed 历史及成绩未改动。数值与摘要验证见 [正文内容核对](evidence/automationbench-full-content-verification.json)，正文截图保留本地 `.screenshots/`，不进入公开交付截图。

新默认模式通过真实 Outbox / Temporal / Langfuse worker 补验：simulation run `66cfc03a-c7ca-4520-9af0-c128db705b41` 的两个有效尝试自动导入成功，另两个为 missing / failed，4 条记录均冻结 content_mode=full；原样重复归档未产生额外 attempt。此项为固定产物联调，模型请求为 0，见 [worker 核对记录](evidence/automationbench-full-mode-worker-verification.json)。真实正文评分 `reward.accuracy=1.0` 的 ClickHouse FINAL 记录数仍为 1。API、planning、planning-execution、Langfuse worker 的 full 相关补丁镜像为 `sha256:3adb33cad49d620f20c3725b77863bf34d30b600488371e4a7a2c18b6342a981`，不代表其他历史 worker 已统一升级为最新主分支。
