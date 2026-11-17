# 官方模型价格与独立额度（2026-11-17）

平台价格快照见 `backend/tool-locks/official-model-prices-20261117.json`。直接抓取官方 HTTPS 页面，保留抓取时间及原文 SHA-256；原文归档为对象存储 `model-prices/{sha256}.html`，上传后回读校验。价格可能变化，当前快照不自动改写历史价格。

| 模型 | 未缓存输入 | 缓存输入 | 输出 | 单位 |
|---|---:|---:|---:|---|
| deepseek-flash 高峰 | 2 | 0.04 | 8 | 元/百万 tokens |
| deepseek-flash 空闲 | 1 | 0.02 | 4 | 元/百万 tokens |
| glm-5.3 | 8 | 2 | 28 | 元/百万 tokens |

官方来源：[DeepSeek](https://api-docs.deepseek.com/zh-cn/quick_start/pricing/)、[智谱](https://docs.bigmodel.cn/cn/guide/start/pricing)。DeepSeek 价格页将 deepseek-flash 映射到 DeepSeek-V4.1-Flash-1017。预留费用使用高峰价，不依赖未经验证的节假日判断。

新增迁移 `0034_model_billing`：

- `model_price_version`：提供商、请求模型名、CNY、官方 URL、原文哈希、抓取时间、价格分档及说明。
- `model_budget_account`：独立预算标识、总额、测评额度、分析额度、预留额、已用额、状态及策略；金额用 Numeric(18,6)，不使用浮点数。数据库限制分项合计不超过总额、预留与已用合计不超过总额。
- `target_billing_binding`：模型服务关联价格和预算，区分官方直连与官方参考价。GLM 自定义网关绑定为 `official_reference`，不能据此声称官方价格就是网关实际账单。

服务器已备份后迁移，导入 2 份价格，建立预算 `full-acceptance-20261117`：总额 250 元、测评 240 元、分析 10 元，关联两个模型服务。策略记录每数据集 API 并发 24、合计 48、任务最长 86400 秒、不自动重试。

**初始登记阶段状态为 configured、enforcement_ready=false；后续已补齐请求级控制并部署启用，见[预算执行与验收记录](budget-enforcement-2026-11-17.md)。** 独立平台额度不等同于服务商充值或修改账号限额。spent=0 是新独立预算初始值，不是历史消费总计。新执行路径已接入预留、结算和限流；必须保持代理、受保护路由及网络预检通过，不能仅凭字段存在绕过执行控制。

验证：真实服务器 PostgreSQL 核对 2 份价格和 2 条服务绑定；保存点内验证分项超额、预留加已用超额均被约束拒绝，未留下测试行；对象原文哈希回读通过；Ruff 通过。未调用模型。
