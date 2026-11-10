# 后端开发与前后端联调计划

日期：2026-11-10。范围依据详设V1.7及Demo后端框架方案：单团队、单工作空间、FastAPI/Temporal/PostgreSQL/S3，客户服务器真实执行；极光仅适配契约。全程不得用模拟结果替代真实验收。

## 阶段及验收

| 阶段 | 模块与交付 | 必须验证的证据 | 当前状态 |
| --- | --- | --- | --- |
| M0 | 基础骨架、开发计划、前端API客户端及连接状态 | 单测、构建、经Vite到真实API请求 | 已完成基础链路及多项浏览器交互验证 |
| M1 | PostgreSQL/Temporal/S3启动和迁移 | 实际数据库约束、Worker派发、存储写读 | Docker开发服务已验证；生产部署/耐久性未验收 |
| M2 | 模型及配置持久化：模型默认、多配置版本、逐数据集参数、Lite | SQL集成、API和配置页面保存/刷新/历史隔离 | 模型/配置/清单/Profile及绑定、批准配置导入和选择器分页已实现；正式批准输入与统一业务表单整合待完成 |
| M3 | 客户主机、凭据引用、SSH指纹/运行时预检 | 真实授权服务器预检，秘密不入日志 | Docker及本机OpenSSH控制/SFTP/页面预检已验证；客户SSH测评编排及真实服务器验收待完成 |
| M4 | 运行提交、幂等、快照、取消及状态投影 | 并发提交、重启、重复派发和前端轮询 | Docker诊断与GPQA Lite探索提交已验证，已归档attempt可恢复且不重发；未确认外部结果保留占用，正式Release待实现 |
| M5 | GPQA→MMMU-Pro→AutomationBench逐工具适配 | 固定原生路径差分、真实case及产物 | GPQA真实探索闭环及MMMU-Pro原生加载/评分适配已加入；MMMU-Pro真实多模态推理与AutomationBench待完成 |
| M6 | case历史、证据、完整/部分报告、JSON基准及门禁 | 重试保留失败、分母不暗改、不可比不补0 | 历史证据/报告/批准JSON基准条件比较已接入；正式门禁批准输入与Release执行未完成 |
| M7 | 独立自动分析、重试和内部榜单 | 不重复分析、不重测、来源和证据正确 | 分析编排、证据引用校验、独立重试及内部榜单已实现；真实分析需独立配置目标/资源，不能以单测替代模型联调 |
| M8 | 联合验收、恢复、审计及部署 | SSH断网/unknown、取消/清理、备份恢复、全流程页面 | 本机恢复/幂等清理/审计/独立scratch备份恢复测试已加入；SSH与生产环境验收未完成 |

每模块同时交付迁移、应用用例、API契约、页面接入和测试；先通过单元/契约，再真实PostgreSQL与服务集成，最后页面联调。不能仅凭mock或编译通过关闭阶段。

## 执行规则

- M0完成后推进M1/M2，无法访问真实资源时仍推进不依赖资源的实现与契约测试，真实验收保持待办。
- 数据库、API客户端、参数schema和错误处理集中实现，不以组件内存冒充持久化。
- 探索、自定义/Lite不得产生Release通过；正式验收必测和基准须获批准。
- 无计划外付费调用。SSH地址、凭据/指纹、工具版本、数据快照和分析模型预算由用户或部署方提供。
- 按用户新目标，以可验证模块分批提交，每次记录测试数量和未完成边界；推送按明确指令执行。

## 完成定义

配置保存→实际执行→case历史→报告→自动分析→榜单的真实闭环和前端证据齐备，故障恢复测试通过，且以上阶段无未验证项，才认为整体目标完成。

## 2026-11-10 M0进展证据

- FastAPI真实进程 `/health/live` 返回200。
- Vite 5173代理 `/api/autoeval/v1/system/capabilities` 到8000返回200和request_id，明确evaluation_enabled=false。
- 前端新增连接状态、重试与超时处理；页面原有业务示例未伪装为真实任务。
- TypeScript与Vite构建通过。尚未执行浏览器级交互测试、SQL约束或真实测评，整体目标保持进行中。

## M2 第一批实现（进行中）

- 新增test_config_version和test_config_item迁移0002，单工作空间，配置键/版本及版本名唯一。
- GET/POST test-configs API：参数schema、逐数据集保存、自定义追加版本、expected_version并发检测、标准只读检查。数据库不可用返回503，无内存回退。
- Ruff和9项测试通过，Alembic离线SQL可生成。尚未执行真实PostgreSQL读写/并发，不代表持久化验收完成。
- 后续补齐模型/数据/Profile外键、标准配置导入、分页契约和幂等键后再接入页面；当前接口是增量实现，未宣称完整详设API。

## M1/M2 真实PostgreSQL与配置链路进展

- 便携PostgreSQL 16.6仅绑定127.0.0.1:55432，数据位于用户缓存，不注册系统服务；开发实例为本机trust认证，不适用于正式部署。
- 已执行Alembic至0002；真实数据库测试验证追加版本、冲突409、旧版本参数保留及新应用实例重新读取；包含该测试共10项通过。
- Vite 5173→FastAPI 8000→PostgreSQL真实POST返回201，GET读到已提交记录。
- 配置页保存动作已调用API，加载自定义配置来自数据库；标准配置仍为只读示例。前端类型检查与构建通过；完整浏览器点击/刷新验收尚待补齐。
- Temporal/S3真实运行、标准配置导入、模型/Profile/子集关系、默认指针、参数分页和幂等完整契约仍待推进，不能将M1或M2整体标记完成。

## M2 浏览器联调进展

- 使用本机Chrome无头模式，经真实Vite/API/PostgreSQL完成新建配置→保存201→刷新→自定义列表搜索并找到该配置；页面未捕获JS异常。
- 新增可重复执行的test_browser_configuration.py（显式AE_BROWSER_URL启用）；与真实PostgreSQL测试共11项通过。
- 修正控制台另一个“保存为新配置”入口，使其调用后端，保存失败不关闭抽屉；此入口尚待独立浏览器验收。
- 模型默认绑定、数据/Profile关系、标准导入和完整API契约仍未完成，M2继续进行。

## 模型登记与默认配置指针

- 新增asset/asset_version/model_config_binding迁移0003，真实PostgreSQL已执行。
- POST/GET models与PUT default-test-config：稳定modelId、模型版本、配置外键和If-Match并发控制；未知配置404、旧revision412。
- 真实数据库测试覆盖登记、默认绑定、冲突拒绝及重新读取；本轮11项通过，浏览器测试因未提供AE_BROWSER_URL显式跳过（此前独立已通过）。
- 模型仅登记为not_configured，尚无服务端点/凭据/真实连接；不将登记成功视为模型可调用。前端模型选择接入及默认自动加载待下一批。

## 模型登记前端闭环

- 控制台新增真实模型登记/默认配置管理区；登记仅代表模型资产，不代表端点可调用。
- 新增GET模型默认配置API，按UUID读取精确版本及逐数据集参数，不通过截断列表猜测默认值。
- Chrome实测登记模型→保存默认绑定→刷新→选择模型→加载默认配置通过；连同配置保存刷新与真实数据库测试共13项通过，前端构建通过。
- 当前真实端点、凭据引用、连接检测、数据/Profile约束和标准配置导入仍未完成；已询问实际SSH/模型环境输入，不阻塞其他模块开发。

## Docker调试与DeepSeek接入方向更新

- 用户确认改用本机Docker模拟执行环境，模型使用DeepSeek官方API；密钥不得写入计划、代码、测试或日志。
- 已通过实际docker version/compose version确认Docker Desktop可用，CLI在用户安装目录；历史“无Docker”结论已过期。
- Compose基础镜像拉取失败：registry-1.docker.io HTTPS收到HTTP响应；尚未修改全局代理，也未宣称容器已运行。便携PostgreSQL继续支持代码验收，不能代替Docker模拟验收。
- 新增开发FileSecretStore与路径/头注入检查；18项测试通过、2项浏览器测试本轮未启用。Windows部署须确认凭据目录仅当前用户访问，生产须改用正式密钥服务。
- 接下来实现目标绑定与显式/models检测，再对DeepSeek做最小冒烟；真实执行仍需Docker镜像网络恢复。

## 端点与DeepSeek真实连接检测

- 新增target_binding_version/connection_probe及迁移0004，真实PostgreSQL已执行。
- 凭据API仅返回不透明引用，端点仅允许管理员白名单HTTPS主机，无重定向；模型列表检测有10秒超时和1MiB响应上限，错误不透传上游敏感正文。
- 本机凭据目录已设置仅当前Windows用户访问；密钥不进入源码、计划或数据库。
- DeepSeek /models真实检测outcome=matched，列表包含deepseek-flash/deepseek-v4-pro；generation_tested=false，未进行生成或测评。
- Ruff及24项测试通过，2项浏览器测试本轮未启用；端点API已经实际写入及检测。前端服务绑定、探测展示、Docker网络问题继续推进。

## 前端服务绑定与Docker镜像进展

- 控制台真实服务绑定区已接入模型版本、凭据引用、保存端点、已保存服务选择和显式检测。Chrome实测选择持久化DeepSeek端点→GET模型列表→matched提示，无生成请求。
- Windows主机HTTPS可访问官方Docker Hub，新增开发辅助脚本经主机下载、验证manifest/blob及解压层hash后docker load，不改变Docker全局代理。
- postgres:16.6镜像加载且容器启动；Temporal旧tag不存在，改用经实际读取registry并加载成功的1.4.1，容器启动待进一步健康验证。
- MinIO原官方镜像访问未授权，存储服务仍未运行，待选择可验证开发S3服务；不宣称完整Compose就绪。
- 24项后端测试、前端类型检查及真实服务检测浏览器路径通过；正式自动化全套及服务创建表单仍需持续扩展。

## M1真实基础服务验证

- PostgreSQL开发数据在确认Docker目标库为空后从便携实例复制，源库保留；当前backend/.env连接Docker 5432，不输出密码。
- Temporal卷权限修正后实际健康检查通过，真实Worker执行工作流并按预期拒绝未实现执行器，不伪成功。
- 官方Moto开发S3容器完成bucket初始化及put/get/delete；非生产持久化存储，历史证据保留不在本次验证范围。
- 基于Docker PostgreSQL/Temporal/S3共26项测试通过，浏览器2项本轮未启用。API重启后/health/ready实测全部ready。
- 下一步补齐真实资源/任务/工具适配，不能据基础服务通过宣称完整测评闭环。

## M3 本机Docker执行资源

- 用户授权Docker模拟路径，新增docker_local资源提供方与不可变容器/镜像绑定，迁移0005已执行。
- Compose executor使用官方python:3.12-slim及独立工作卷，仅带autoeval.role=executor标签才可登记。无任意命令/启动/删除容器API。
- 真实容器登记201与预检200已通过，环境running及image identity验证，tools_validated=false/evaluation_ready=false。
- 单测验证不泄露Config.Env、拒绝无标记容器与CLI选项注入；本轮27项通过，4项浏览器/基础服务专项未启用。
- 下一步作业submit/lookup/status/cancel与工具版本核验；本轮未运行AISBench，不宣称真实测评。

## Docker作业执行适配第一批

- 新增DockerExecutor与上传容器的版本化固定Python运行包装器，实现submit/lookup/status/cancel/collect。
- 仅允许固定framework_smoke和0—30秒持续时间，不开放用户任意shell/命令；冒烟结果明确model_called=false、measurement=null，不进入模型成绩。
- Linux flock保护稳定UUID提交目录，正文hash冲突拒绝；job记录PID、starttime、boot_id，取消前查验进程身份，未知任务不推定成功。
- 真实容器测试验证重复提交不重复启动、结果查询收集、未知key、取消确认。两项专项通过；未实现AISBench或真实模型任务，不能据此关闭工具适配里程碑。
- 下一步接入业务运行/状态投影/Temporal后，再注册真实工具能力与数据manifest。

## M4 Docker诊断任务持久化链路

- 新增迁移0006：execution_lease（物理容器独占）与diagnostic_result（诊断摘要），不作为正式模型评分表。
- /api/autoeval/v1/diagnostics/runs支持提交、查询、取消；提交事务原子保存运行、快照、占用、初始事件及Outbox。
- DockerDiagnosticWorkflow经独立I/O队列执行；状态遵循领域转换，终态、结果及释放占用同一事务提交。
- 相同幂等键返回同一任务，不同正文返回409；运行中取消检查实际容器作业终态；超时或外部通信异常保留占用，追加execution_unresolved事件，不伪造终止。
- 新增真实HTTP/SQL/Outbox/Temporal/Docker集成测试，验证成功、重复提交、正文冲突、运行中取消及连续事件序号。
- 该接口仅framework_smoke，gate_status=not_applicable，无模型推理或付费调用；不能替代GPQA/MMMU-Pro/AutomationBench正确性验证。
- 待深化：未知状态自动对账恢复、Worker中断后接续、前端诊断面板、真实工具与数据清单；当前Reconciler仍仅告警，不能宣称自动恢复已完成。

## M4 前端诊断任务联通

- 任务管理页新增独立真实Docker诊断区；资源选择、15秒任务提交、每2秒状态刷新、事件展示、取消和刷新后历史找回已接入API。
- 诊断组件与示例测评列表分开，明确不调用模型、不产生正式成绩。提交进行中防重复点击；网络失败重试沿用同一提交键。
- 浏览器通过Vite代理→API→PostgreSQL/Outbox→Temporal Worker→Docker实际验证完成与运行中取消，以及两次页面刷新后的历史查询，测试通过。
- TypeScript无错误，Vite生产构建通过。开发需同时启动workflow/io Worker和Outbox投递器，启动方法已更新backend/README。
- 待完成正式测评工具、证据存储、报告与分析及恢复对账，不能将诊断链路当成完整测评验收。

## M4 诊断异常对账第一批

- Reconciler由只读告警扩展为诊断恢复；仅处理Temporal已关闭的Workflow，活跃Workflow不参与状态竞争，不重新提交作业。
- 原稳定作业键查证与取消后确认；已终止任务补齐合法状态转换、结果和占用释放，同一事务提交，重复对账返回terminal。
- 找不到作业或通信异常保持占用；前端新增待查证提示，查询返回execution_unresolved和ownership_held。
- 真实PostgreSQL/Temporal/Docker故障注入通过：无Worker队列启动Workflow→活跃跳过→终止Workflow→未知作业保留占用→容器已有结果恢复→重复对账无副作用。
- 本轮后端33项通过、3项浏览器测试未启用，TypeScript检查通过；本批专注诊断恢复，不代表正式工具任务或SSH恢复已实现。
- Reconciler开发进程已启动；默认60秒轮询、创建5分钟后进入对账，数据库/外部服务错误仅记录运行ID并继续下轮。

## M2 数据集确定性清单

- 新增dataset_manifest及迁移0007/0008，引用dataset类型资产版本；每个版本只有一个Full清单，Lite必须引用同版本Full，ID与SHA-256逐项匹配。
- POST /dataset-manifests保存不可变内容；相同版本/清单键与相同正文重试返回同一ID，改变正文409。GET支持offset/limit分页。
- 有序样本ID/校验值规范化JSON写入S3，数据库只存摘要、数量与对象引用，不写入题目/答案；读取验证字节校验值。当前单次最多20000样本；大清单分段导入后续深化。
- S3写入在数据库提交前，失败可能留下未引用对象，不在回滚中按hash删除，以免误删并发引用；孤立对象回收待实现。Moto仅协议模拟，生产证据耐久性尚未验收。
- 配置页新增独立真实样本清单登记区，Chrome实测JSON提交201→刷新→找到已保存清单；TypeScript与Vite构建通过。
- SQL/S3专项验证重复登记、覆盖拒绝、第二Full拒绝、合法Lite、缺失/改变样本、跨版本父清单拒绝和分页通过。
- 当前仅清单登记，尚未绑定Profile/正式运行快照；未导入批准的GPQA/MMMU-Pro/AutomationBench数据或运行正式工具，不能据登记成功宣称可测评。

## M2 Profile与配置执行绑定

- 新增迁移0009：evaluation_profile固定Full/Lite清单、工具提交版本、评分规则引用与摘要、并行拥有者；config_dataset_binding将配置条目固定到Profile与选定清单。
- POST/GET /profiles支持不可变版本登记与分页；Lite必须属于选定Full，数据集与工具家族按首期边界校验。全部契约tool_verified=false，未实现的工具不得伪装已验证。
- test-configs新增profile_bindings，提供时必须覆盖全部数据集；Lite未配置拒绝保存。已有绑定的配置不能通过遗漏字段悄悄降级为无绑定版本。
- GET /test-configs/{id}/execution-spec返回配置、Profile、清单及工具摘要和缺失绑定/工具未验证阻塞原因。新版本不会修改旧版规格；该规格尚非运行快照，后续提交还需冻结目标与资源。
- 前端配置页新增Profile契约登记和逐数据集绑定面板，以新配置版本保存；Chrome实测登记→选择绑定→保存→刷新后绑定仍在。
- 真实SQL/S3集成验证不可变Profile、重复登记、未配置Lite拒绝、绑定完整性、工具保持未验证和旧规格隔离。测试采用明确标识的fixture契约，无正式模型调用或虚构正式成绩。
- 后续补齐原生工具注册/核验、提交快照、批准配置与正式数据输入；原参数编辑面板尚未统一Profile选择，有绑定的版本会明确拒绝缺失绑定保存，需使用绑定面板。

## M5 AISBench原生路径第一批

- 官方仓库固定提交525ed1779f50a8ac068b8638771f633a151e769f，tool-locks/aisbench.json记录ais_bench完整已跟踪文件树1367项hash；执行前核验源码，不接受改写评分文件或额外Python源码。
- 新增aisbench_native桥接命令，直接调用上游GPQADataset、first_option_postprocess和GPQAEvaluator，不重写评分逻辑；固定gpqa_gen_0_shot_str对应路径。
- Windows原生导入确认fcntl不支持，改用Docker Linux Python3.12，CPU torch和上游runtime依赖经主机下载后复制到独立/work/tools/aisbench目录；未改上游源码，未改变既有模型服务。
- GPQA加载依全量行序置换选项，Lite必须先完整原生加载再选择；准备结果保存稳定行标识、原生样本与摘要，避免截取CSV造成答案位置漂移。
- 两项Docker真实原生测试通过：评分桥接与直接原生调用差分一致，空输出诊断不改变计分；两行自建CSV的加载/置换/样本标识验证通过。不是正式GPQA数据或成绩，无DeepSeek生成调用。
- 开发依赖版本已留存；该工具环境为开发卷中的手动布置，生产镜像、依赖wheel hash和正式软件环境快照尚待补齐。详见docs/aisbench-integration.md。
- 下一步原生prompt/推理调用与逐attempt证据接入；MMMU-Pro/AutomationBench尚未原生验证，不能宣称整个M5完成。

## M6 case执行历史与证据首批

- 迁移0010新增case_execution_record：按运行/数据集/样本/attempt索引与唯一约束，operation_key去重。执行前写started，后续succeeded/failed只代表执行结果，与原生评分正确性分离。
- 证据schema只允许prompt/response/finish_reason/归类error_code，排除请求头和凭据。长正文放S3，数据库保存摘要、对象引用和状态；未知执行保持started，不捏造已失败或重新发起。
- 归档后应用拒绝不同正文覆盖，相同摘要幂等；迁移0011增加真实PostgreSQL触发器禁止修改已归档行、改变attempt身份或删除历史。受控保留期清理和权限模型后续设计，当前不执行删除。
- GET /runs/{id}/case-executions支持样本/数据集过滤及分页；GET /case-executions/{id}/evidence校验hash，缺失/损坏返回503，未归档409。
- SQL/S3专项验证失败→重试成功后两份证据保留、重复结果幂等、应用和直接SQL覆盖/删除拒绝、证据篡改拒绝、空输出/截断原因原样保存。
- 任务管理页新增回溯面板，浏览器真实查询第二次成功与第一次失败证据通过；TypeScript及生产构建通过。
- 存储应用用例仍待接入真实推理Worker。当前fixture运行仅验证历史机制，无正式模型测评成绩；轮次/分片外键、最终case结果索引、分区保留、摘要汇总与正式报告继续深化。

## M5 原生推理与历史归档首条真实链路

- aisbench_native新增原生GPQA PromptTemplate及VLLMCustomAPIChat调用；显式model避免自动探测，retry=1对应仅一次请求，非流式、thinking disabled，注入30秒session并禁止重定向。
- native_smoke为显式开发命令：限官方deepseek-flash、自建算术fixture、输出32 tokens、无自动重试。执行前登记运行/快照/占用及attempt，完成后归档证据、记录独立诊断摘要并释放占用。
- 真实调用一次成功：运行4698abc8-31ba-4606-acae-7ecf787aa369，attempt aaaf9040-b4b7-4725-87a5-dd507a70a49e，官方返回input_tokens=56/output_tokens=7。不是GPQA基准数据或正式成绩，不进入Release/榜单。
- 核验S3证据、数据库快照无api_key、占用释放；Chrome任务页case回溯可读取该次真实响应。密钥仅经docker exec stdin传入，不在argv/env/文件/快照中传递。
- 增补SQL/S3集成测试对模型边界使用明确模拟，验证一次调用及accepted→queued→preparing→running→aggregating→completed连续事件；该模拟测试不替代上述真实调用。
- 本批仍是操作员CLI联调，尚未注册成Temporal测评活动、页面正式提交或任意批准Profile执行。通信/归档结果未知时保留attempt/占用并记录unresolved；native-smoke尚无自动恢复，不应重复运行来代替查证。
- 首次真实调用保留当时事件记录，后续代码完善为合法连续状态路径，不重写既有审计。

## M5 真实GPQA数据原生导入

- 从GPQA作者仓库固定提交56686c06f5e19865c153de0fdb11be3890014df7下载其公开dataset.zip，使用作者README公开的解压口令，仅取Diamond；无登录凭据、无模型调用。
- tool-locks/gpqa-source.json记录来源、提交、压缩包/CSV/许可证hash，题目与答案不进入Git或日志。
- 新增import_gpqa操作员命令，先校验来源CSV摘要，再在固定Docker工具中全量原生加载，生成稳定ID/原生样本hash；数据包存S3，资产版本metadata固定其摘要、来源、工具提交和not_approved状态。
- 实际Full=198、Lite=固定前5，登记结果：Full 2eacdae0-6d95-47ae-b1f3-3caf6b00d89d，Lite c43e1352-b3dd-46ad-9876-b714d9d86489，数据版本cc781905-a013-4e28-8652-d5788a2cbcd7。
- 原生导入专项通过：CSV与Docker输入摘要一致、数据包校验、198唯一ID、Lite条目与全量前5完全相同，重复导入复用不可变记录，无模型请求。
- 新增清单详情API及来源查看按钮，Chrome验证真实GPQA数据名/数量/作者提交/not_approved，TypeScript与Vite构建通过。
- 本批不批准正式配置、不评测198题、不触发额外DeepSeek生成；数据包依然在Moto开发模拟存储中，生产耐久性待验收。

## M4/M5/M6 GPQA Lite探索运行与报告

- 新增POST/GET /runs、运行查询与取消、报告证据读取；仅exploration，提交事务保存运行/最终快照/占用/Outbox，幂等键冲突409，预算不覆盖清单时拒绝。
- 首批适配边界：GPQA单数据集、已导入的原生数据包、固定上游Profile契约、Lite<=5样本、并发1、每样本输出<=64、temperature=0/top_p=1/thinking disabled。正式Release、其他工具及任意参数尚未启用。
- GpqaExplorationWorkflow和专用gpqa Worker串行生成原生prompt、登记attempt、调用真实模型、归档及原生整体评分；已有attempt/已被领取运行不重发请求。重复活动终态直接返回。
- 报告表迁移0012只存摘要/hash/引用，产物保存在S3；报告明确complete/partial/failed_summary/invalid，列出预期/执行/失败/缺测及所选Lite范围。评分器失败返回invalid、accuracy=null，不补零、不改case证据。
- 取消意图在样本边界检查；当前请求返回后才停止后续样本，已产生用量不可撤销，终态后才释放占用；未知执行保留占用，尚无正式运行自动恢复。
- 模拟模型边界的真实SQL/S3/Temporal验证：幂等提交、预算不足拒绝、部分失败报告、取消零请求、评分失败不误判通过、重复活动不重复调用。测试使用唯一工作流/活动队列，与真实模型Worker隔离。
- 浏览器真实调用一次GPQA Lite1：运行e7035c8d-bb48-4b0e-acb5-9e05cf7aa172，报告653472dd-cdbf-49c2-a6ae-dcbf8f4a2ae4；input_tokens=117/output_tokens=11。提交→Temporal→Docker原生路径→attempt证据→完整所选Lite报告→刷新找回通过。
- 这只代表198题数据集中的1题探索；formal_score_eligible=false，gate_status=not_applicable，不作为Full成绩、榜单或正式发布结论。
- 下一步报告页主流程替换、未知运行恢复、分析Outbox/工作流、基准可比性/门禁及MMMU-Pro/AutomationBench；单团队身份仍仅受控开发模式。

## M6 报告管理真实数据接入与来源隔离

- 新增GET /reports分页目录、/reports/{id}详情及/evidence校验读取；前端真实目录支持分页、直达链接、刷新后详情恢复、成绩范围/缺测/完整性及校验值展示。旧原型报告移入明确标记的折叠区。
- 迁移0013新增execution_origin（real/simulation/unverified）；提交快照冻结服务端来源，Worker把来源写入报告元数据与新产物。模拟模型测试显式标记simulation，真实目录仅查询real，运行列表也按来源隔离。
- 历史报告默认unverified，不推断为真实。对上一轮已通过真实浏览器与S3验证的报告653472dd-cdbf-49c2-a6ae-dcbf8f4a2ae4，再次核验报告hash/运行ID/原生工具提交后补充real来源及审计事件；未修改既有快照、成绩或证据正文。
- 只读集成验证目录排除simulation/unverified，隐藏产物详情返回404，真实报告证据与快照摘要匹配、分页参数校验通过。
- Chrome真实报告目录→详情→校验证据→刷新直达链接通过，未发出任何新模型请求；TypeScript与Vite构建通过。
- 自动分析状态仍not_enabled，无虚构的等待/成功结果；后续接入独立分析工作流，不改原始报告。

## 2026-11-10 当前代码基线复核与量化提交

- 复核基线：886b9c5（及之前按模块提交的配置、恢复、基准、分析、分页、审计、备份和清理变更）。本次不重复实现已有模块。
- 全量回归：154 passed / 4 skipped，耗时129.26秒；覆盖真实PostgreSQL、Temporal、Docker、S3协议模拟、浏览器及隔离scratch备份恢复。
- 补充开启MMMU-Pro原生与批准标准配置专项：28 passed（41.54秒），实际覆盖上次跳过的3项，另含25项重复验证。当时合计覆盖157个唯一测试项，仍有1项基准数据库专项未开启；此前“覆盖158项”的记录已据开关复核更正，该项在SSH批次补跑通过。
- TypeScript检查和Vite生产构建通过；本轮无新增模型生成请求。原生fixture测试、模拟模型边界测试和真实模型历史证据分别陈述，不互相替代。
- README、后端运行说明和M0—M8进度表已对齐现有实现。历史分批日志保留，用于追踪先后变化，不作为当前完成声明。
- 继续顺序：客户SSH/SFTP适配及本机Docker模拟SSH联调 → 原型主流程整合 → MMMU-Pro多模态与AutomationBench明确输入及适配 → 正式Release/生产身份与部署验收。未知外部状态不以重发模型请求代替恢复。
- 用户新目标授权按模块提交；每批记录变更范围、测试数量、真实/模拟边界，未授权自动推送。

## M3 客户SSH/SFTP控制层首批

- 新增迁移0018及独立ssh_resource_binding，登记主机/端口/用户名、批准SHA-256主机指纹、执行目录、密码或私钥引用，不依赖极光账号。
- 使用Paramiko固定主机指纹校验，禁止AutoAdd/TOFU、ssh-agent及隐式本地密钥。未加密RSA/Ed25519/ECDSA私钥在内存解析，密钥材料仅在受保护服务端存储；加密私钥/口令组合尚未支持。
- 仅在workdir/.autoeval/<binding UUID>内创建带所有者标记的运行目录，拒绝根目录/路径穿越/符号链接；固定运行包装器按hash通过SFTP上传，不提供任意shell输入。
- SSHExecutor实现固定framework_smoke的submit/lookup/status/cancel/collect/cleanup；稳定UUID目录及提交hash去重，远程PID/starttime/boot ID查证，SFTP收集产物，未知作业不启动替代任务。
- Docker OpenSSH模拟器绑定127.0.0.1:2222，公钥认证；setup_ssh_sim.py只接受带ssh-simulator标签的本机容器，通过Docker控制面读取实验主机指纹，不对客户主机自动批准指纹。
- 三项真实协议测试通过：重复提交/正文冲突、结果SFTP收集/未知key不建作业、取消确认/幂等清理/既有文件保留、错误指纹拒绝。单元测试及SQL登记测试也通过。
- 控制台新增SSH资源登记与显式预检；Chrome验证私钥登记→输入清空→真实预检→刷新保留通过。TypeScript与Vite构建通过。
- 边界：本批是SSH控制层与资源预检，尚未接入Temporal任务提交/GPQA执行/远程断网恢复。customer_ssh_enabled仍false；不能以预检成功替代客户测评验收。

### 本批提交验证数量

- 新增14个测试项：SSH校验单元9、真实OpenSSH协议3、SQL登记1、浏览器登记预检1。
- 全量回归171 passed / 1 skipped，157.09秒；唯一跳过项为未开启AE_BASELINE_TEST的批准基准数据库专项。
- 补开AE_BASELINE_TEST后基准测试文件28 passed，其中1项补齐该跳过、27项重复验证；当前172个唯一测试项均已有通过证据。未将重复执行累加为不同测试。
- Ruff检查通过，TypeScript与Vite构建通过，git diff --check通过；本批无模型生成调用。
- OpenSSH安装因容器下载链路问题使用受限于Debian源的临时本机HTTPS转发，APT签名验证保持启用；安装完成后已停止代理并恢复模拟容器软件源。未更改客户服务器或Docker全局代理。
