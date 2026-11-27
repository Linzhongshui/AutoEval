---
name: deploy-autoeval
description: 部署、升级、验收或恢复单团队 AutoEval 测评平台。覆盖 Linux 内网离线发布、Windows 本地开发、跨环境补齐数据清单和执行资源、固定产物归档以及真实测评验收。
---

# 部署 AutoEval

在能访问目标的会话中执行以下流程。按用户给定目标选择发布版本、主机和验收环境。单纯编写方案或检查部署时仅执行相应的只读步骤。

新环境安装、迁移历史报告或升级到 347b335 并运行 DeepSWE 时，先按[新环境部署与升级指南](references/new-environment-upgrade.md)选择 AMD64/ARM64 平台归档、同版前端和 x86 执行节点，再按任务入口完成验收。

目标需要复用已归档的 Linux AMD64 镜像时，先按 [OBS 运行镜像手册](references/obs-images.md) 选择平台、数据集与目标 Docker 引擎，再按下列流程部署和验收。新版本的应用镜像仍按选定源码构建。

DeepSWE 部署先确认执行器。控制台的 AISBench/Harbor 任务走跨环境测评资源流程；实际使用原生 Pier 和 Linux x86_64 节点时，按 [Pier x86 部署与验收](references/deepswe-pier-x86.md) 准备控制端、任务镜像和独立评分环境。

1. 在源码目录运行 `git rev-parse --show-toplevel`、`git status --short`、`git rev-parse HEAD`。读取本次版本的 AGENTS.md、README.md、backend/README.md，确认 frontend、backend、deploy/intranet 都来自同一源码。工作区有未提交修改时，区分“指定提交”和“包含本地改动的快照”；缺少版本选择且差异影响发布时先确认。保留原工作区。
2. 从任务或受保护部署清单确定目标、既有 Compose 项目/卷、访问路径、允许写入范围、发布源及恢复位置。发现现有服务先取证，再选择首次安装、同工作空间升级或隔离演练。缺目标时仍可完成离线包准备；禁止从历史验收报告选取实际服务器。当前代码只支持受控开发/试用身份。正式生产要求需先核对当前版本的身份实现。
3. Linux 服务器按[内网单机发布](references/intranet.md)执行。Windows 开发工作站按[本地部署](references/windows.md)执行。升级或迁移先读[验收与恢复](references/acceptance-recovery.md)的停写与备份步骤。所有命令从手册注明的目录运行，匹配目标发布版本。配置、对象和密钥留在受保护位置。
4. 跨环境安装、任务页面选项为空或要求真实测评时，先按[跨环境测评资源](references/evaluation-bootstrap.md)导入版本化 Profile、Full/Lite 清单及 S3 实物，在目标机注册模型和 SSH 资源、准备执行节点挂载并重新编译。用随包目录检查定位缺项，再让真实 Worker 执行所选任务的预检。每个数据集的精简验收都需要独立记录。
5. 使用[验收与恢复](references/acceptance-recovery.md)从用户入口一直检查到样本和报告，分别记录目标环境与隔离环境证据。用用户指定的模型、资源、样本和费用策略执行真实测评或探测。预算可按用户授权记录为不限额。遇请求结果未知时保留原运行。
6. 交付版本、入口、各层验收结果及恢复位置。说明当前可使用哪些能力，列出失败或未验项的直接原因。
