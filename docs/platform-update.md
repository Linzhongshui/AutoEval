# AutoEval 平台镜像与数据库升级

适用于已有数据的 Linux AMD64 / ARM64 内网单机 Compose 部署。脚本为 [update-platform.sh](../deploy/intranet/update-platform.sh)，默认提交为 `8912940d0bfcef9b0913af73a0175ab2bfdc7981`，前端版本 **0.6.4**，业务库目标 **0044_compilation_display_name**。从之前发布的 `4ddc14d` 升级没有新增迁移；更早的环境由 Alembic 根据当前版本执行缺少的步骤。本次核对到的 OBS 发布记录对应旧提交，本指南从新提交构建离线包。

## 一、构建平台包

在与目标架构一致的 Linux 构建机上，从 AutoEval 仓库根目录执行。需要 Git、Node.js 22+、Docker、uv 和 Python 3.12/pip；构建环境应与后端基础镜像的 Linux ABI 兼容，能够访问锁定的依赖与镜像。REL 为尚不存在的绝对目录。

```bash
git fetch origin main
export REL="/srv/releases/platform-8912940-$(uname -m)"
bash deploy/intranet/update-platform.sh build
```

记录最后输出的 SHA256SUMS 摘要并通过可信通道传递。将整个 REL 和升级脚本传到平台机，保留当前发布目录。两种平台架构分别构建。复用缓存或从 OBS 中转时使用同一份完整校验清单。

## 二、现场预检

平台机需要 Bash、Python 3、flock 及支持 `up --wait` 的 Docker Compose v2。按实际路径设置以下变量，在同一个 Shell 执行。API_CONTAINER 必须是当前线上 API 实例；脚本从其标签读取项目名、工作目录和有序 Compose 文件，要求部署账户可写该工作目录。沿用启动时的环境变量、profiles 及环境文件。服务名和网关静态挂载按仓库标准布局；外置数据库、外部网关或自定义服务名需要先适配脚本。

```bash
docker ps --format '{{.Names}} {{.Label "com.docker.compose.project"}} {{.Label "com.docker.compose.service"}}'
export REL=/srv/releases/platform-8912940-x86_64
export API_CONTAINER=autoeval-platform-api-1
export SUMS_SHA256='替换为构建机记录的64位摘要'
SCRIPT=/opt/autoeval/update-platform.sh
bash "$SCRIPT" check
```

check 校验包、架构和提交，导入本地镜像，在新目录解包网页并验证网关配置；临时 API 容器读取当前迁移版本和目标 head。此阶段不切换服务。检查输出中的服务清单；运行中与 API 使用同一镜像的可选 Worker 会被纳入。其他需要同步升级的同项目角色在 check 前设置，例如 `export EXTRA_SERVICES=langfuse`。独立 Compose 项目中的进程需单独协调。

## 三、维护窗口内升级

1. 关闭新任务入口、暂停定时提交，等待在途任务和远程执行结束。保存旧镜像、网页、有效 Compose、受保护配置及历史报告标识。按恢复手册备份并验证可还原的业务库、Temporal 和 S3 对象。检查可用磁盘空间；确认新镜像中的 API 所连接的数据库就是 Compose 的 postgres 服务与下方 DB_NAME 对应的数据库。[备份与隔离恢复](https://github.com/llauren48/AutoEval-Platform/blob/8912940/.skills/deploy-autoeval/references/acceptance-recovery.md)
2. 在同一维护窗口仅运行一次 apply，保持外层入口处于维护状态。脚本停止网关和列出的业务进程，再新增一份业务库转储并检查归档目录，运行迁移，核对 current 与 head，重建 API、Worker 和网关。基础设施复用现有容器与卷。
   
```bash
export DB_USER=autoeval DB_NAME=autoeval
export BACKUP_DIR="/srv/backups/platform-8912940-$(date +%Y%m%d-%H%M%S)"
bash "$SCRIPT" apply
```

3. 将输出的 `platform.override.json` 作为最后一个 Compose 文件加入日常启动配置。保留 REL 内本次生成的 web 目录，网关持续挂载其中的 dist。用真实客户端登录并核对侧栏 **0.6.4**、API readiness、原 Temporal 命名空间中的 Worker 轮询、历史报告与证据对象。已有 Langfuse 的环境另验导入 Worker 和历史 Trace。记录结果后开放提交。

## 四、失败处理

check 失败时，按报错核对发布摘要、平台架构、现网项目文件、受保护配置和数据库身份。apply 在停服务后出错会中止并保留现场；先确认备份是否完整、迁移执行到了哪一步，以及新应用是否已开始写入。若迁移尚未开始，可用旧 Compose 和旧网页恢复原服务。迁移已开始且兼容性未知时，将同一备份点恢复到独立空卷，核对旧版本业务库、Temporal、S3 和报告后再切回。不要直接降级数据库或覆盖故障卷。脚本的 pg_restore 目录检查不替代隔离恢复演练。
