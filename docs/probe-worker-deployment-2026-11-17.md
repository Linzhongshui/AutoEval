# 吞吐探测 Worker 部署修复（2026-11-17）

页面提示“探测执行器未启用”来自 `/planning/probes` 的消费者在线检查。服务器原 planning Worker 仅处理 preflight、plan；取消预算拦截并不会自动启动 probe 消费者。

已启动独立 Compose 服务 `autoeval-platform-probe-1`，复用原 planning 服务的受保护配置、网络和持久挂载，运行 `python -m autoeval.planning_worker`，仅消费 `AE_PLANNING_JOB_KINDS=probe`。镜像固定为 `sha256:77626a6b9d0db73bb94710fa038c5adcc26bec7ba1cf004949d9e88f57576540`。

设置 `AE_PLANNING_PROBE_ACCEPT_AFTER=2026-11-17T12:55:49+00:00`（北京时间20:55:49），避免启动时消费过去积压任务。服务器部署记录位于 `/home/chenluwen/autoeval-platform/probe-worker-20261117/compose.json`，目录700、文件600；该文件含运行环境配置，不提交仓库。后续维护应沿用该 override，不重置时间边界。

验证：

- PostgreSQL 消费者租约检查由 false 变为 true。
- 当前 pending/running/unresolved 探测数量为0。
- 使用不存在的目标测试真实接口：通过消费者检查后返回 Target not found（404），没有创建探测作业，未调用模型。
- 未点击真实目标的“启动探测”，未验证真实模型吞吐曲线；实际探测由用户后续主动发起。

本次是部署配置修复，未更改在线检查逻辑，未伪造 Worker 就绪状态。
