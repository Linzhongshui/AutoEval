# AutoEval · Langfuse 部署与轨迹验收

适用于 AutoEval 平台提交 `4ddc14d` 的 Linux 部署。Langfuse 保存和展示 Harbor 轨迹；AutoEval 平台的导入 Worker 将已归档的轨迹写入指定项目。两者可以位于不同主机。已有 Langfuse 实例直接从第 2 节开始。

## 1. 准备 Langfuse 实例

**联网首次安装。** 在安装了 Git、Docker Compose 和 uv 的独立 Linux 主机，从上述 AutoEval 提交的仓库根目录执行。目标目录必须尚未创建。

```bash
bash deploy/langfuse/setup.sh /opt/autoeval/harborstack
```

脚本检出 harbor-otel-stack 的固定提交 `a62c1be62888e2cb5c89f92aa2dc00731f4f5ed1`，安装锁定依赖，执行 doctor 和 init。完成后从目标客户端登录 Langfuse，确认可访问接收轨迹的项目，取得该项目的 ID 和一对 API keys。已有实例升级时沿用原数据卷、项目、域名和登录配置。

**离线准备。** 平台后端镜像包含导入代码，Langfuse 服务端镜像另行获取。在有桶读取权限的中转机上执行以下 Bash 命令。

```bash
set -euo pipefail
obsutil cp obs://aisbench/images/autoeval/runtime-20261124/manifest.json manifest.json
echo '54056f812c0b7f29be468c99dcfe3440c049b9f877e73ed07d5cbb22e258b092  manifest.json' | sha256sum -c -
obsutil cp "$(jq -er '.archives.langfuse.uri' manifest.json)" langfuse-images.tar.gz
echo "$(jq -er '.archives.langfuse.sha256' manifest.json)  langfuse-images.tar.gz" | sha256sum -c -
```

将清单、镜像包、固定版本的 HarborStack 源码、离线依赖及部署配置带到目标机。复验上述两项摘要，确认 Docker context 指向承载 Langfuse 的引擎，再执行 `docker load -i langfuse-images.tar.gz`，按清单中 `archives.langfuse.refs` 核对镜像 ID。该归档对应 Linux AMD64；ARM64 平台可以连接另一台 AMD64 主机上的 Langfuse。全离线首次安装还需配套 HarborStack 安装包，请按固定版本的 `harborstack install --help` 核对离线包格式与初始化步骤。[离线发布清单与引擎核对方法](https://github.com/llauren48/AutoEval-Platform/blob/4ddc14d/.skills/deploy-autoeval/references/obs-images.md)

## 2. 在平台机配置项目和访问地址

在部署实际加载的后端环境文件中填写以下字段，标准布局为 `shared/backend.env`。已有环境保留实际值，API、dispatcher 和相关 Worker 加载同一份受保护配置。

| 字段 | 取值 |
| --- | --- |
| `AE_LANGFUSE_HOST` | 导入 Worker 能访问的 Langfuse 基础地址。容器内的 localhost 指向该容器所在的网络命名空间。 |
| `AE_LANGFUSE_BROWSER_URL` | 用户浏览器能访问的 HTTPS 入口，包含实际端口，并与登录回跳、网关证书匹配。 |
| `AE_LANGFUSE_PROJECT_ID` | 接收轨迹的项目 ID。 |
| `AE_LANGFUSE_PUBLIC_KEY` | 该项目签发的 public key。 |
| `AE_LANGFUSE_SECRET_KEY` | 同一对密钥的 secret key，通过受保护配置注入。 |
| `AE_LANGFUSE_CONTENT_MODE` | `full` 导入输入、回复、工具参数与输出；`structural` 导入结构摘要。沿用项目批准的模式。 |

## 3. 启用平台导入 Worker

在平台 Compose 中启用服务 `langfuse`，使用与 API 相同的本次后端镜像、后端环境文件、Temporal 命名空间及所需挂载。其容器启动命令为 `python -m autoeval.entrypoints.worker langfuse`。使用仓库发布渲染器时，在生成新发布配置的命令中追加 `--role langfuse`。该服务名指平台导入 Worker，Langfuse 服务端由第 1 节的独立部署管理。

在维护窗口内用现网项目名和完整 Compose 文件集重建读取新配置的 API、dispatcher、任务与结果 Worker，以及导入 Worker。仅执行容器 restart 不会载入修改后的 env_file。确认 dispatcher 正常运行，导入 Worker 已在目标 Temporal 命名空间开始轮询；启动失败先看相应容器日志并核对环境文件是否实际挂载或加载。

## 4. 验收与排障

| 检查项 | 操作与通过条件 |
| --- | --- |
| 浏览器访问 | 从已有 Harbor Case 打开 Trace，完成 Langfuse 登录后应回到同一项目的对应轨迹。若回到首页，核对浏览器入口和登录回跳。 |
| 新轨迹导入 | 对已有授权的新 Harbor 归档，通过平台接口 `GET /api/autoeval/v1/runs/{run_id}/traces` 查看状态，在 Case 页打开 Trace 并核对样本和评分。仅打开历史链接时，将新导入记录为待验。 |
| disabled 或缺少轨迹 | 核对项目配置与该次归档是否包含有效的 Harbor 轨迹文件。历史记录不会因启用配置而自动补导。 |
| 排队或导入失败 | 排队先查 dispatcher 和导入 Worker。失败则检查 Worker 到 HOST 的网络、证书、项目密钥、OTLP 和 observations 查询权限。修复后可通过 `POST /api/autoeval/v1/runs/{run_id}/traces/retry` 重新排队失败的导入项，无需重跑模型测评。 |

记录平台版本、项目 ID、验证时间、run ID、Trace ID 及两项验收结果。交付记录中省略密钥和轨迹正文。
