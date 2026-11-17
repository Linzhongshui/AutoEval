# 默认测评监控与失败状态恢复（2026-11-17）

新统一测评任务在提交事务内为每个数据集建立监控绑定，初始投影为 waiting_tool，明确显示监控已启用、等待远程启动。执行期间按所属资源收集；终态快照写对象存储并校验回读。任务详情同时显示各数据集，历史没有绑定的任务不补造监控。

来源分开表达：

- aisbench_native_predictions：GPQA 原生预测记录计数，已有运行时记录工具 PID。
- harbor_result_files：只统计本次独立输出目录中含 agent_execution、verifier_result 且 finished_at 非空的原生终态 trial 文件，不用日志行数或耗时推算。
- executor_lifecycle：远程作业已查证状态，工具尚未返回原生数据时使用；不填造工具 PID、正确数或已完成样本数。

默认监控不是所有工具均启用同一种 HTTP 监控服务。Harbor 当前使用原生产物观测，不宣称已经连接 Harbor 实时 HTTP 端点。真实新测评尚未在本轮执行。

## b7e8588c 排障

任务 b7e8588c-05ab-4172-a819-ec11b16df8e6 的两个远程作业均在启动工具前失败：配置中的平台资源分配字段 resource_ids / manifest_ids 被严格远程运行时拒绝。工具日志尚未生成，平台 collect_log 读取缺失文件又抛异常，Temporal 活动持续恢复重试，页面一直显示 running。

修复执行桥接：仅在独立执行配置副本中移除平台分配元数据，原冻结快照保持不变；工具日志缺失时读取已有作业 stdout，未生成内容保持为空，不编造工具日志。先收集可得的最终原生进度，再归档终态，避免较旧计数抢先冻结。

该任务通过原工作流查证更新为 failed，两个数据集均归档当前观测到的失败终态，未重发模型请求；不是恢复为成功。AutomationBench 的 cleanup_pending 仍保留，未擅自释放外部容器所有权和容量。

## 验证与部署

- 默认监控、字段映射、资源契约及预算兼容回归13项通过，1项基础设施测试跳过；Ruff、TypeScript、前端构建通过。
- 服务器浏览器查看该任务：两项 monitor 均 executor_lifecycle / failed / final，无页面异常。不代表历史实时采集已存在。
- API 与 planning-execution 发布镜像 sha256:de766aedb2b9，受保护部署目录 /home/chenluwen/autoeval-platform/monitor-default-20261117；前端另有发布前备份。
- 本轮没有创建新真实测评，没有新增模型调用。原生 GPQA / Harbor 新任务动态进度仍需在之后获准的真实运行中验收。
