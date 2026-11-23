---
name: deploy-autoeval
description: 部署、升级、验收或恢复单团队 AutoEval 测评平台。适用于 Linux 内网单机离线发布和 Windows 本地开发，包含固定产物从任务提交到报告的无模型验收。
---

# 部署 AutoEval

在能访问目标的会话中执行以下流程。按用户给定目标选择发布版本、主机和验收环境。单纯编写方案或检查部署时仅执行相应的只读步骤。

1. 在源码目录运行 `git rev-parse --show-toplevel`、`git status --short`、`git rev-parse HEAD`。读取本次版本的 AGENTS.md、README.md、backend/README.md，确认 frontend、backend、deploy/intranet 都来自同一源码。工作区有未提交修改时，区分“指定提交”和“包含本地改动的快照”；缺少版本选择且差异影响发布时先确认。保留原工作区。
2. 从任务或受保护部署清单确定目标、既有 Compose 项目/卷、访问路径、允许写入范围、发布源及恢复位置。发现现有服务先取证，再选择首次安装、同工作空间升级或隔离演练。缺目标时仍可完成离线包准备；禁止从历史验收报告选取实际服务器。当前代码只支持受控开发/试用身份。正式生产要求需先核对当前版本的身份实现。
3. Linux 服务器按[内网单机发布](references/intranet.md)执行。Windows 开发工作站按[本地部署](references/windows.md)执行。升级或迁移先读[验收与恢复](references/acceptance-recovery.md)的停写与备份步骤。所有命令从手册注明的目录运行，匹配目标发布版本。配置、对象和密钥留在受保护位置。
4. 使用[验收与恢复](references/acceptance-recovery.md)从用户入口一直检查到样本和报告，分别记录目标环境与隔离环境证据。只在明确指定模型、资源、样本、尝试次数及预算时执行真实测评或探测。待查证的模型调用保留原运行。
5. 交付版本、入口、各层验收结果及恢复位置。说明当前可使用哪些能力，列出失败或未验项的直接原因。
