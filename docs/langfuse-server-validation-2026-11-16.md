# Langfuse 服务器部署与验证（2026-11-16）


2026-11-17 入口更新：Langfuse 已改为 `https://179.214.2.3:8443/`，无需 hosts。以下域名入口记录为原部署历史；当前配置见 [接入说明](langfuse-integration.md)。
## 实际部署

服务器：179.214.2.3；独立目录 `/home/chenluwen/autoeval-langfuse`。来源为 `llauren48/harbor-otel-stack` 提交 `6ca5ef9b8fedc78e8106d202a5c6a84e6f24f940`。服务器无 Git/现代 Compose，故传输固定提交源代码，使用 fork 的 Langfuse Compose 模板生成独立 compose.json，通过已有 dind 内的 Compose v2.33.0 部署。镜像复用该 Docker 引擎中现有的内容寻址镜像，全部固定为 SHA256 image ID，不更新现有镜像。

项目 `harborstack-autoeval` 含 web、worker、PostgreSQL、ClickHouse、MinIO、Redis，使用独立网络和命名数据卷。既有 `harborstack-default` 属于其他用户，未修改。Langfuse 版本 4.70.1。运行依赖既有共享 harborstack-dind，引擎原有 restart policy 为 no；本次未改变共享引擎启动策略，不代表整机重启自动恢复已验收。

统一网关位于 `/home/chenluwen/autoeval-unified-gateway`，容器 `autoeval-unified-gateway`，使用 Nginx，restart unless-stopped。配置源见 `deploy/langfuse/nginx-unified.conf`。独立旧 19030 网关已停止。服务器 firewalld public 区域仅新增 http/https 服务，并持久化；数据库等内部服务未放行。

## 访问

在访问电脑 hosts 添加：

```text
179.214.2.3 langfuse.autoeval.local
```

- Demo：https://179.214.2.3 ，保留既有 Basic Auth；转发到原 127.0.0.1:18443 网关，并使用原 CA 验证上游证书。
- Langfuse：https://langfuse.autoeval.local ，使用 Langfuse 自身登录。
- 新入口使用包含 IP 与域名 SAN 的自签证书。公开证书保存在本地 `backend/.secrets/langfuse-server.crt`，需在访问电脑受信任证书配置中导入；不要全局禁用证书验证。
- Langfuse 登录信息保存在本地被 Git 忽略的 `backend/.secrets/langfuse-server.json`；服务器完整随机凭据为 `/home/chenluwen/autoeval-langfuse/credentials.json`（0600）。不在正文记录密码或 API keys。

## 已验证

- 从当前电脑通过统一 HTTPS 入口访问：Demo 返回预期 401，Langfuse health 返回 200。
- 在服务器独立验证容器调用本次平台 import_one，使用固定 Harbor ATIF 样本；不调用真实模型。
- Trace：`fbf4e49cda895dd58456c2c22fddf268`，两次导入得到相同 ID；observations 查询均为 2 条，没有重复增长。
- ClickHouse scores FINAL 查询确认 reward=1，记录数为1。此版本 /api/public/v2/scores 返回404，故使用实际存储验证评分，不将该接口404当作评分成功证据。
- 重启新实例 web/worker 后重复导入，trace 与 observation 数量不变。
- HTTPS 下实际账号登录、session 返回 user、对应 Trace 页面 HTTP 200；Demo 原认证保护401保持有效。

- 当前电脑 Chrome + Playwright 真机浏览器测试通过（1 passed）：通过统一 HTTPS 网关登录，打开指定 trace，确认 llm 节点与 reward=1.00 展示。测试只对新入口证书的 SPKI 做精确固定，不全局跳过 TLS 检查；浏览器 DNS 使用显式映射。
- 浏览器截图：`deliverables/langfuse-trace-2026-11-16.png`。
- 复验命令：在 backend 设置 `AE_LANGFUSE_LIVE_TEST=1` 后运行 `uv run pytest -q tests/browser_checks/test_langfuse_live.py`。需要本机 Chrome 与上述受保护的访问配置和证书。

## 验证边界

本次部署 Langfuse 与统一 Nginx，未升级既有 demo 业务镜像、迁移业务库或启用其中的 Langfuse worker。测试通过上传到独立验证容器的平台导入代码完成，不代表既有 demo 已自动触发归档导入。平台测评到页面 Trace 按钮的整体闭环仍需发布本次业务代码并单独验证；未重跑历史任务或触发真实模型测评。
