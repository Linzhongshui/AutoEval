# 恢复报告部署验收（2026-11-18）

## 发布

- 目标：179.214.2.3，独立 AutoEval 平台；原测评容器及数据未替换。
- API、planning-execution、planning、result：autoeval/platform:task-report-recovery-20261118-r3。
- API 镜像：sha256:8bf42767b6d0（前缀）；完整镜像身份以服务器 docker inspect 为准。
- 独立 analysis Worker：autoeval/platform:task-report-recovery-20261118-r2，保留原执行参数、受保护配置及网络方式；未提交分析作业。
- 前端：index-Bd0XYhLg.js，固定分辨率浏览器核验通过。
- Alembic：0036_result_revisions，新建追加归档修订表。
- 部署目录：/home/chenluwen/autoeval-platform/task-report-recovery-20261118/。
- 发布前数据库备份：该目录 database-before.sql，78,968,024 bytes，目录 0700、文件 0600；源码和配置以发布目录清单留存。
- 原镜像层数达到上限，使用未启动、无运行配置挂载的临时容器导出旧镜像文件系统，构建扁平基础镜像。未导出运行中容器的密钥挂载。

## 正式数据

任务 a1452c45-8416-4f6f-b9d5-2c22610b848a。

- 恢复修订：a768f262-901e-45d0-a438-ce1ac4a06570。
- 正式报告：682578fb-771e-4148-967b-6a6fb186e2e1。
- 报告 SHA-256：34596e5c70d9df007eac1bfaaa1e41e3168ee72a80054e0db27578cff2dd2e94。
- 一个任务、一份报告、两个数据集，无综合准确率。
- GPQA Diamond：198/198，85.85858585858585%，基线 90.9%，差 -5.041414141414151 个百分点。
- AutomationBench：600/600，349 正确、251 错误，58.166666666666664%，参考 60.5%，差 -2.333333333333336 个百分点。
- 实际冻结并发各 12，未重跑模型。Harbor 未知 token 保持 null。
- 原始 CaseExecutionRecord 仍为 798 条，恢复修订 1 条，正式报告 1 条。
- 原始运行事件 running、failed 保留；新增 seq=4 results_recovered，保存原 failed 状态及各数据集原摘要；当前状态 completed，两个子执行 succeeded。
- 恢复监控为带报告哈希的归档最终快照，分别 198/198、600/600，标明非新增实时采集。

三个历史 raw_result 索引引用完全相同的对象哈希 c2159d2059820591e5e4b2cacebc76f8e64d44997bb4eef4427eff627dcae963，属于归档重试，不是额外模型运行。恢复工具允许相同哈希去重，保留三个原始索引 UUID；不同哈希依然拒绝自动选择。

## 审批榜单与标准来源

- GPQA-Diamond 已审批：0317b802-0136-49dd-8fc6-1b6bb102d207。
- AutomationBench 已审批：1fc7439b-f4d3-4e06-ab32-77fe3c4404af。
- 走既有来源校验、提名与审批函数，产生审计记录，未绕过评分 / 证据校验。
- 185 条官方来源记录未修改，审批前后内容哈希均为 6b0866d3b7f3fd41c0c4e386c9f50561d93d41877594150d6021cb621595493c。
- GPQA 使用任务内冻结标准版本 2f8f167a68f86ee022afcc7f2ae2b62bc2e6d2a2 的基线附件。
- AutomationBench 原冻结版本没有对应附件；独立补录固定标准提交 a8955cad4e3656a2c9dc23a8e0bb2e8632ef07d4 的 DeepSeek-V4.1-Flash-1017/AutomationBench/baseline.json，原字节 SHA-256 为 2a55b5fc1ef35c785bb8516f1741f08d454394ddc2d544fe1c5be4caa2499e8a。补录记录 UUID 16684eca-e90a-4e51-988e-5b8e312d578f。
- 补录与原任务快照、正式报告对象分离，页面标注“执行后补录固定版本”。该参考不代表相同参数复测，verdict 保持 null，不作为发布通过判定。

## 验证

真实服务器浏览器：任务完成、分数据集最终监控、GPQA/AB 两份日志、恢复 Case 证据、正式报告双数据集成绩与基线、已发布榜单通过；无浏览器运行错误。

截图、验证 JSON、正常节奏操作 WebM：deliverables/task-report-recovery-20261118/。该录像是部署恢复复核，不是新增测评或完整智能分析验收。

服务器 API healthy，其余相关 Worker running。未新增测评 / 分析作业，未发生本轮模型调用。

## 回滚边界

保留发布前 SQL 备份、旧镜像和 analysis Worker 旧容器、UI 备份。当前已产生正式报告、审批和审计写入，禁止直接用旧 SQL 覆盖当前数据库；回滚需先停止调度并核对新增差异。旧版本不认识恢复报告协议，不应在继续开放页面时直接回退代码。

本轮未提交或推送代码。
