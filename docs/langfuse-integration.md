# Harbor Langfuse 接入

来源固定为 https://github.com/llauren48/harbor-otel-stack ，提交 `a62c1be62888e2cb5c89f92aa2dc00731f4f5ed1`，依赖由 backend/uv.lock 锁定。

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

## AutomationBench 执行环境

AutomationBench 使用 Harbor 的目录名筛选样本；原生结果中的 `automationbench/` 命名空间只映射到冻结清单内的样本，不接受任意前缀。Harbor 省略 trial 的 dataset 时，平台使用该子任务冻结的数据集身份；显式返回其他数据集仍拒绝归档。

环境检查会运行适配器 `--preflight-only` 和 Harbor 原生任务枚举，不启动 agent、不发送模型请求。AutomationBench 预留与 DeepSWE 相同的 Harbor 资源，并检查 Docker 网络容量。

当 SSH runner 使用宿主机 Docker socket 时，Harbor 的日志目录必须在宿主机和 runner 中具有相同绝对路径。在后端受保护的 `planning-container.json` 对应资源项设置可选 `runtime_root`（例如 `/home/operator/acceptance/platform-runtime`），将所属宿主机目录按同一路径挂载到 runner；任务路径也应使用共享的绝对路径。默认未设置时仍使用 `/tmp/autoeval-planning-runtime`。不要把这个字段或 Docker socket 暴露为前端自由配置。

验收专用脚本 `deploy/langfuse/prepare-automationbench-acceptance.py` 仅登记配置，`submit-automationbench-acceptance.py` 默认仅检查页面和环境，显式 `--submit` 才提交真实测评。已有提交会拒绝重复发送；`--retry-approved` 仅用于已获授权且确认零模型调用的基础设施失败。模型调用后失败不得使用它自动重跑。`collect-automationbench-acceptance.py <run_id>` 在 API 容器内只读收集摘要、轨迹身份、评分和层级核对结果，不输出凭据或对话。

验收专用 DeepSeek 配置需在 `sampling_args.extra_body` 中保留 `max_tokens`：固定的 Verifiers 版本会将外层 `max_tokens` 改名为 `max_completion_tokens`。预算保护器在最终 HTTP 请求上检查模型、64K 上限、effort=max 和 thinking 参数，不符合时在发送前拦截。该保护器只在显式配置验收环境变量时启用，不替代平台的通用计费预算管理。

## 服务器部署记录

当前服务器访问入口（2026-11-17 更新）：demo 为 `https://179.214.2.3/`，Langfuse 为 `https://179.214.2.3:8443/`，均经统一 Nginx 提供 HTTPS。Langfuse 登录回调和平台 `AE_LANGFUSE_BROWSER_URL` 已同步为 IP + 端口；后端内部导入地址保持原配置。8443/tcp 已在服务器防火墙持久放通，证书包含服务器 IP，无需 hosts。

Windows 首次访问可用普通用户 PowerShell 执行 `powershell -NoProfile -ExecutionPolicy Bypass -File .\deploy\langfuse\setup-client.ps1`。脚本备份用户代理配置，为服务器 IP 添加直连例外，校验证书指纹并安装到当前用户信任库，检查 demo 和 Langfuse 连通性；不再修改系统 hosts，也不要求管理员权限。仍需先连接能到达服务器的 VPN，Langfuse 使用自身账号登录。

Trace 页面首次访问：统一 Nginx 在未携带 Langfuse 会话 cookie 时，将合法的项目 / Trace 路径转到 `/auth/sign-in?targetPath=<编码后的相对路径>`；登录成功后回到该 Trace。已有会话则直接转发，项目访问权限仍由 Langfuse 校验，不公开轨迹或代用户登录。Langfuse 4.70.1 的登录页读取 `targetPath`，只传 `callbackUrl` 会回到首页，参见该版本的 [SignInPage 实现](https://github.com/langfuse/langfuse/blob/v4.70.1/web/src/features/auth/SignInPage.tsx)。会话 cookie 仅作为是否显示登录入口的提示，不能替代 Langfuse 身份或项目权限验证。

2026-11-17 已重新部署样本记录 UI：证据与 Trace 使用独立按钮，补充轨迹已导入 / 缺少轨迹等状态，执行说明与筛选提示合并。Chrome 实测“未登录点击 → 登录 → 原 Trace”及“已登录点击 → 原 Trace”两条路径均通过，并检查两项操作无重叠。该变更未重新执行任何测评或模型请求。

同日按用户选择，仅将演示 Trace `cfc0e6ea48fd58abbf8bc638c4e0cb36` 通过 Langfuse 原生 “Make Public” 开启分享，链接仍为 `https://179.214.2.3:8443/project/autoeval-harbor/traces/cfc0e6ea48fd58abbf8bc638c4e0cb36`。Nginx 为这一个完整路径设置精确转发，免除首次登录跳转；Langfuse 自身仍检查该记录的 public 标志。其他记录和后续新导入记录继续保持私有，不自动公开。能访问服务器且持有链接的人可查看该条 structural 轨迹。

撤销时在该 Trace 的 “More actions” 中选择 “Unshare”，同时删除 Nginx 中对应的精确路径配置，执行配置检查和热重载。取消 Langfuse 分享会立即恢复其访问权限校验；同步移除网关例外后可恢复正常的登录回跳流程。前端没有保存登录凭据或 API keys。

2026-11-16 已部署独立 Langfuse 和统一 Nginx，入口、证书、hosts 与实测边界见 [服务器验证记录](langfuse-server-validation-2026-11-16.md)。

2026-11-17 的真实 AutomationBench 单样本轨迹、命名评分、浏览器跳转、修复和剩余验收边界见 [AutomationBench 真机验收记录](automationbench-langfuse-acceptance-2026-11-17.md)。
