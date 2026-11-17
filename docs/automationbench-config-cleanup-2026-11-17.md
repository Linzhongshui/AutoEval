# AutomationBench 配置排障与清理（2026-11-17）

本次仅做配置、环境检查和网页回归，没有提交测评，没有模型调用。

阻塞来自执行资源不匹配：`real-179-214-2-3-chenluwen` 绑定 GPQA 容器，该容器未登记 AutomationBench 能力，也没有其数据路径及 Harbor 网络环境。截图中的四项阻塞是容器检查结果，不能通过将校验标记改为通过来解决。另有旧配置使用 `/acceptance/tasks` 等失效路径、旧评分契约或已停用模型服务。

## 新配置与验证

- 配置：`a5812c29-b393-41df-a681-a0752d1d5231`，版本 `AutomationBench.server-20261117.v1`。
- 配置 SHA-256：`e46eb572518c00bc051880eb15f02a718fbbf2a47ce9c91c0e2be09b18a20844`。
- 使用资源：`automationbench-acceptance-shared-20261117`（`c84c335e-2249-40a1-b856-613a607d2f23`）。
- 数据路径：`/home/chenluwen/autoeval-automationbench-acceptance-20261116/tasks-public`。
- AISBench：`698ff2d1e027c07df37bdd158b62aace2a41ae3b`；适配器：`955089ab32ef696c231d628f5ad0d9da28f430c4`。
- 清单：全量 600 题 `bbdcc129-4d73-4381-8314-2144f9ac8161`；Lite 1 题 `99fb416b-b694-486e-badb-42884b244bd6`，使用原生目录名。
- 新配置基于已有成功执行过原生 agent 的 operator 配置生成，保留参数锁定，不冒充新的官方标准版本；新增固定资源与清单引用，不改写旧配置。

Lite 和全量清单均通过真实 SSH 容器预检：Planner、适配器、AISBench 提交及评分源码校验、数据目录、Docker 网络容量、适配器依赖与 Harbor 原生任务枚举。结果 execution_ready=true，blocking_reasons=[]。这不代表已重新完成 600 题模型测评。

后端拒绝在错误资源上使用绑定配置（422），拒绝用已归档配置预检或创建新任务（409）。网页隐藏与所选资源不匹配的配置，显示应选择的资源，切换资源时清除不兼容的选择。原有未绑定配置保持兼容。

目前该专用资源只验证 AutomationBench；GPQA 仍使用原 GPQA 资源。不能据此声称同一资源已支持两个数据集混跑。

## 清理与恢复

从新任务选项中归档移除 65 条配置：编译阻塞、引用停用模型服务、被新版替代的 AutomationBench 配置。保留当前 GPQA 和新版 AutomationBench 两条配置。移除 6 份旧 AutomationBench 清单选项，仅保留上述原生身份的全量/Lite 清单。

旧记录物理保留，共 67 条编译记录；不删除标准来源、历史任务、快照、报告、榜单及证据，不变更在途任务输入。清理前完整配置备份写入对象存储并回读校验：

- 对象：`planning/config_cleanup/c28385fbfb05ad7367226214080fef1a40b1cf495bab9bddf36c5c0d340df6ae.json`。
- SHA-256：`c28385fbfb05ad7367226214080fef1a40b1cf495bab9bddf36c5c0d340df6ae`。
- 服务端通过 `AE_ARCHIVED_COMPILATION_IDS`、`AE_ARCHIVED_MANIFEST_IDS` 冻结归档集合；选项查询先过滤后分页。恢复个别选项前应核实其环境，不能整体重新开放旧配置。

服务器增量发布目录：`/home/chenluwen/autoeval-platform/automation-config-20261117`，保留 Compose override、清理清单及发布前前端备份。本次只重建 API，保留其他执行容器和工作进程。

## 检查结果

- 配置生命周期、配置页契约、预算兼容回归：6 passed；Ruff 通过。
- TypeScript 与 Vite 构建通过。
- 真实服务器接口：仅返回 2 条可选配置；备份回读通过；错误资源 422、旧配置 409。
- 真实 Chrome：错资源隐藏配置并提示；正确资源可选新版及两份清单；自动环境检查通过；无页面异常，未提交模型任务。
- 截图：[AutomationBench 配置就绪](../deliverables/automationbench-config-ready-20261117.png)。
