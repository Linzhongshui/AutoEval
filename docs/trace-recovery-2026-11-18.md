# AutomationBench 轨迹恢复（2026-11-18）

任务：a1452c45-8416-4f6f-b9d5-2c22610b848a；子执行：c2716a4e-94ac-49a8-95c2-0e24c5d2a1e7。

## 来源与边界

原导入状态为 23 succeeded、577 missing；不是 577 次 Langfuse 导入报错。原生输出目录仍保有 600 份 ATIF 轨迹，全部有效且步骤非空，总计 307,675,819 bytes。

本次只补回原始轨迹、结果和 reward 文件，不执行测评、验证器或模型，不修改正式报告成绩和原始 Case 尝试。

受保护来源包：服务器 /home/chenluwen/autoeval-platform/trace-recovery-20261118/native-traces.tar；312,750,080 bytes；SHA-256 35cfb041d71e9e6cf104acc33d963616805c8f411be1ab7e37b9f0555d4f6c3b。内置清单 SHA-256 32c82173c7ce0b8c02f1fe613c33dcae3e317bbcca40ec1a35878597cce2ba66，逐文件记录大小与哈希。

新 API 镜像 autoeval/platform:trace-recovery-20261118，基于上一版正式恢复服务构建，仅增加恢复工具和恢复版 Case 的 Trace 关联。其他测评容器及 Worker 不替换。

## 恢复实现

1. 新增 reporting.trace_recovery CLI，拒绝路径穿越、链接、重复成员、文件 / 清单哈希不符、额外 / 缺失 trial。
2. 全量核对 trial 名、原 Case UUID / attempt、结束时间、ATIF session_id 与 native result.id，并与正式评分恢复源文件逐字节核对。检查产物中不含该任务的模型凭据。
3. 已成功的 23 条核对后跳过，不重新排队。缺失的 577 条逐条上传独立 S3 对象并回读校验，避免内联总额度影响。
4. TraceImport 保留原 UUID 和原 Case UUID；旧对象仍保留，AuditEvent 追加旧对象引用、旧状态、新哈希及来源清单。retry_no 增加后创建去重 Outbox 意图。
5. 每批 8 条，调用既有 Temporal / Langfuse 导入链路。既有导入器核对确定性 Span ID 集合及评分写入后，才标记成功。失败或不确定结果时停止，不自动重发部分 Span。
6. 恢复版 Case 查询通过 dataset + sample + attempt 找回原 Case UUID，关联同一 TraceImport；不存在身份匹配则拒绝，不创建新的 Case。

## 操作与恢复

源包和发布前数据库备份 database-before-traces.sql 均保存在上述独立受保护目录；目录 0700、来源包与 SQL 文件 0600，不提交到仓库。

```text
python -m autoeval.reporting.trace_recovery RUN_UUID /protected/native-traces.tar --dry-run
python -m autoeval.reporting.trace_recovery RUN_UUID /protected/native-traces.tar --batch-size 8
```

此工具对已成功 / 已排队条目幂等。遇到 failed 状态必须先检查 Langfuse 实际接收情况，不能盲目重复发送。默认依赖已验证的评分恢复修订，适用于本次既有产物恢复；不声称已完成未来任意大规模任务的自动轨迹回收改造。

## 验证

新增归档验证、身份冲突拒绝和恢复 Case 使用原 Trace 的测试；相关测试通过。真实浏览器已确认此前缺失的 finance-4024 在原始 / 恢复两个 Case 视图打开相同 Trace，Langfuse 调用树可查看，未关闭 TLS 校验。

最终数量与验收截图见 deliverables/trace-recovery-20261118/，恢复日志位于服务器 API 容器 /tmp/trace-recovery-20261118.log。

## 最终验收结果

恢复程序正常退出（exit_code=0）：600/600 succeeded，600 个独立 Trace ID，600 个原 Case UUID；新增恢复审计 577 条。retry_no=0 的原 23 条保持不重导，retry_no=1 的恢复条目为 577 条，全部 content_mode=full。

真实浏览器分页核验原始 Case 和恢复 Case 各 600 条：两种视图均有 600 个 Trace 链接、600 个唯一 URL，全部指向相同原 Case UUID / Trace；恢复版 600 条评分完整。截图中的 support-1490 已实际打开 Langfuse 工具树，Trace ID 为 87def6d5ad825360927bb58ac5465832，无浏览器运行错误。

正式报告仍为 682578fb-771e-4148-967b-6a6fb186e2e1，SHA-256 34596e5c70d9df007eac1bfaaa1e41e3168ee72a80054e0db27578cff2dd2e94，完整性 verified；原 Case 数仍为 798，评分修订仍为 1，任务 completed，已审批报告榜单仍为 2。未调用模型、未增加测评尝试、未重复计分。

本轮代码未提交或推送。
