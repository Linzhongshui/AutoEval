# AutomationBench 统一入口接入（2026-11-16）

GitHub 实时 API 确认 AISBench/benchmark PR #639 已合入，merge commit 为 aff1554354fbf19dccbdf2199cc3c22119f815a2。
来源：https://github.com/AISBench/benchmark/pull/639

控制台增加 AutomationBench；统一任务允许四个数据集。后端将 AutomationBench 按 Harbor 家族校验配置、保留任务样本 ID、应用 Lite task_names 与 n_attempts，并交给现有 Harbor 执行及归档链路。估算沿用 Harbor 非模型耗时缺失提示。

这次没有升级远程工具、修改已有数据登记记录或发起模型调用。实际执行仍需可用的标准配置、完整清单、AutomationBench adapter 及匹配的 AISBench/Harbor 环境；旧 registration.v1 的禁用记录不会被自动改成已验证。通用 Harbor 结果解析与官方 publisher 的评分一致性及远程闭环仍需专项验收，不能将入口开放视为真实测评验收。

验证：相关后端测试 23 passed、2 skipped；新增选择回归单独运行。Ruff 检查通过；前端执行包含类型检查的构建。
