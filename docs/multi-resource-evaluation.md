# 多资源测评执行

一次测评仍只创建一个任务。控制台执行资源支持多选，提交 `resource_ids`，兼容原有单资源 `resource_id/resource_kind`。本轮资源池限定为同一种执行环境，最多16个不同资源，主资源必须包含在池中。

平台按每份配置 `runtime_config.resource_ids` 与用户所选资源池的交集进行确定性分配。多个匹配资源时采用用户选择顺序；没有交集时拒绝提交。多资源池不猜测未登记配置的能力：必须先为配置登记兼容资源。旧单资源配置保持兼容。

预检对每个数据集分别调用所属资源的容器检查，保存 `task_resources`；全部就绪后才允许提交。分配写入每个数据集的冻结输入 `assigned_resource_id/assigned_resource_kind`，不由 Planner 决定。预检复用比较完整资源池，改变资源池使旧检查失效。

执行、恢复、取消、结果收集、日志收集与清理均使用对应数据集的适配器，容量租约采用该数据集的预检资源。一个资源容量不足不会阻止扫描其他可运行数据集；未知状态保留原有不重发规则。没有新分配字段的历史任务继续使用原适配器和资源快照。

2026-11-17 已发布服务器 API、planning、planning-execution，新镜像 `sha256:77626a6b9d0d`。发布前确认18条测评均为终态，无执行中的规划作业。补齐 GPQA 配置 `e96f41ca-15bb-4273-b3cf-732ff5420f3f` 的资源绑定，归档替代其旧版本，保持两条可选配置；原有历史记录不改写。发布目录 `/home/chenluwen/autoeval-platform/multi-resource-20261117` 留存 Compose override、配置清单及前端回滚备份。

验证：资源分配、旧接口兼容、配置生命周期和预算/配置页回归9项通过；Ruff、TypeScript及Vite构建通过。真实 Chrome 经服务器 API、PostgreSQL 与 planning worker 完成组合预检：GPQA 与 AutomationBench 自动分配到不同容器，工具提交分别为525ed1779f50与698ff2d1e027，两项就绪且无阻塞。预检作业 `e113094d-3df1-4e1b-b93a-4e18a3a60503`。改变资源池后清除不兼容配置，未出现网页异常。

另外通过真实 SSH 在两个容器分别运行 framework_smoke：相同提交键返回相同作业，重建适配器后可恢复查询，结果明确 model_called=false；成功作业与取消作业均确认清理。本次为容器协议测试，不是通过 Temporal 执行完整多数据集测评，也没有创建新模型任务。真实多数据集模型调用、故障注入、报告生成及入榜仍未在本轮验收。

证据：[浏览器预检记录](../deliverables/multi-resource-validation-20261117.json)、[预检截图](../deliverables/multi-resource-preflight-20261117.png)、[容器生命周期测试](../deliverables/multi-resource-lifecycle-20261117.json)。
