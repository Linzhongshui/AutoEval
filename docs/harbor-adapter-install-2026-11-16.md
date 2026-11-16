# Harbor 与 AutomationBench adapter 服务器安装（2026-11-16）

服务器两个 Harbor 容器 32fea62a5112、54e215edafef 已安装独立调度环境 `/opt/venvs/harbor-automationbench`：Python 3.13.18、Harbor 0.21.0（源码提交 641c9f06b5a22704b8633d05f7ec1e9b5894c83d）、harbor-automationbench 0.1.0。源码保存在 `/opt/harbor-automationbench-641c9f0`。AISBench 保持 PR #1 对应 031a793。

两个容器均通过 JobConfig、AutomationBenchOfficialAgent 导入及 Harbor CLI --help；主环境 uv pip check 对92个包检查通过。将 websockets 固定为15.0.1，满足 realtime 的 <16 与 Harbor 的 >=15 约束。完整安装清单在各环境 installed-requirements.txt。未安装 runtime extra，遵循上游调度端/任务运行时分离要求。包下载使用 HTTPS 华为云 PyPI 镜像，保留证书校验。

使用新调度环境：

```sh
/opt/venvs/harbor-automationbench/bin/python -c 'from automationbench_adapter.agent import AutomationBenchOfficialAgent'
/opt/venvs/harbor-automationbench/bin/harbor --help
```

原 `/opt/venvs/harbor` Python3.12 未替换。新环境中联合安装 AISBench 全依赖时发生旧依赖构建错误（KeyError __version__）；因此没有切换 AISBench 的旧 wrapper，也不宣称 AISBench→Harbor→任务运行时闭环已就绪。后续应单独处理 AISBench Python3.13 依赖兼容性、配置执行解释器，并准备任务集及运行镜像。没有付费模型调用。

镜像保存为 `autoeval/aisbench-harbor:automationbench-py313-031a793-custom` 与 `autoeval/aisbench-harbor:automationbench-py313-031a793-base`。现有容器 Image ID 不因 docker commit 改变，重建须使用这些新标签。原环境及前次镜像保留用于回退。
