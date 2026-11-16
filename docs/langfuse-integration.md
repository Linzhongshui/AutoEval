# Harbor Langfuse 接入

来源固定为 https://github.com/llauren48/harbor-otel-stack ，提交 `6ca5ef9b8fedc78e8106d202a5c6a84e6f24f940`，依赖由 backend/uv.lock 锁定。

## 部署

在具备 Docker Compose 和 uv 的独立 Linux 环境运行 `bash demo/deploy/langfuse/setup.sh /absolute/new/harborstack`。该脚本不会复用 demo 的数据库或对象存储。已有部署直接使用其配置，不重复初始化。部署账户及 API keys 从该部署受保护的配置获取，不提交 Git。不要改变评测执行进程的 DOCKER_HOST。

后端 `.env` 配置：

```dotenv
AE_LANGFUSE_HOST=http://langfuse-host:18930
AE_LANGFUSE_BROWSER_URL=http://browser-accessible-host:18930
AE_LANGFUSE_PROJECT_ID=your-project-id
AE_LANGFUSE_PUBLIC_KEY=your-public-key
AE_LANGFUSE_SECRET_KEY=your-secret-key
```

HOST 为 worker 可达地址，BROWSER_URL 为用户浏览器可达地址；跨主机部署需配置受控网络入口。生产或远程入口使用 HTTPS。项目 ID 必须与 API keys 所属项目一致。

在 backend 执行 `uv sync --frozen` 和 `uv run alembic upgrade head`，重启 API、任务执行 worker 与 dispatcher，新增启动 `uv run python -m autoeval.worker langfuse`。现有 dispatcher 负责持久化任务投递。

## 行为与排障

仅新归档的 Harbor 结果创建导入任务。原生 trial 的 trajectory、result 和 verifier reward 文件按白名单收集并校验摘要。每个文件上限 8 MiB、每个 trial 10 MiB；超限或缺失轨迹显示缺少轨迹，不补造 trace。现有统一结果传输仍受原有整体大小限制。

导入使用 fork 的 scan、plan、export 和 scores Python 接口，无需解析日志或修改 fork。平台 attempt 为 trace 身份增加命名空间，重试保持不变。默认使用 structural 脱敏模式。

`GET /api/autoeval/v1/runs/{run_id}/traces` 查看状态；`POST /api/autoeval/v1/runs/{run_id}/traces/retry` 只重新排队失败项。Case 历史页面显示状态、失败重试和新标签页 Trace 跳转。未配置项目的新记录显示 disabled；历史记录不自动补导入。AISBench 显示暂不支持。

导入失败只写脱敏错误码 TRACE_IMPORT_FAILED，不改变测评成绩。先检查 worker、dispatcher、服务连通性、项目 keys、OTLP 接口和 observations 查询权限。服务确认 trace 可查询及评分请求成功后才显示成功。浏览器访问使用 Langfuse 自身登录。

固定产物离线测试不代表真实 Harbor 执行或真实 Langfuse 部署验收；真实基础设施与模型调用需单独记录。

## 服务器部署记录

2026-11-16 已部署独立 Langfuse 和统一 Nginx，入口、证书、hosts 与实测边界见 [服务器验证记录](langfuse-server-validation-2026-11-16.md)。
