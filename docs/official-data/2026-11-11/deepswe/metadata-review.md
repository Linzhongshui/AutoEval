# DeepSWE 模型元数据核查记录

核查日期：2026-11-11。范围：已录入 DeepSWE v1.1 榜单的全部 21 个模型。

| 模型 | 发布时间 | 参数量（总量 / 激活） | 日期依据 |
| --- | --- | --- | --- |
| gemini-3.5-flash | 2026-05-19 | - | [来源](https://docs.cloud.google.com/gemini-enterprise-agent-platform/models/gemini/3-5-flash) |
| glm-5.2 | 2026-06-16 | 744B total / 40B active (publisher model table) | [来源](https://docs.z.ai/release-notes/new-released.md) |
| gemini-3.6-flash | 2026-07-21 | - | [来源](https://blog.google/innovation-and-ai/models-and-research/gemini-models/gemini-3-6-flash-3-5-flash-lite-3-5-flash-cyber/) |
| deepseek-v4-flash | 2026-04-24 | 284B total / 13B active | [来源](https://deepseek.com/en/news/v4-preview/) |
| claude-sonnet-5 | 2026-06-30 | - | [来源](https://www.anthropic.com/news/claude-sonnet-5) |
| muse-spark-1.2 | 2026-08-05 | - | [来源](https://research.meta.ai/blog/introducing-muse-code-and-muse-spark-1-2) |
| qwen3.8-max | 2026-08-03 | 2.4T total / 95B active | [来源](https://www.alibabacloud.com/en/press-room/alibaba-unveils-qwen3-8-max) |
| claude-opus-4.8 | 2026-05-28 | - | [来源](https://www.anthropic.com/news/claude-opus-4-8) |
| deepseek-v4-pro | 2026-04-24 | 1.6T total / 49B active | [来源](https://deepseek.com/en/news/v4-preview/) |
| glm-5.3-flash | 2026-08-26 | 320B total / 18B active | [来源](https://docs.z.ai/release-notes/new-released.md) |
| gemini-3.7-flash | 2026-08-13 | - | [来源](https://blog.google/innovation-and-ai/models-and-research/gemini-models/introducing-gemini-3-7-flash/) |
| gpt-5.5 | 2026-04-23 | - | [来源](https://openai.com/index/introducing-gpt-5-5/) |
| gpt-5.6-luna | 2026-07-09 | - | [来源](https://openai.com/index/gpt-5-6/) |
| grok-4.6 | 2026-08-12 | - | [来源](https://x.ai/news/grok-4-6) |
| kimi-k3 | 2026-07-16 | 2.8T total / 104B active | [来源](https://epoch.ai/models/kimi-k3) |
| glm-5.3 | 2026-08-18 | 744B total / 40B active (publisher model table) | [来源](https://docs.z.ai/release-notes/new-released.md) |
| claude-fable-5 | 2026-06-09 | - | [来源](https://www.anthropic.com/news/claude-fable-5-mythos-5) |
| gpt-5.6-sol | 2026-07-09 | - | [来源](https://openai.com/index/gpt-5-6/) |
| claude-opus-5 | 2026-07-24 | - | [来源](https://www.anthropic.com/news/claude-opus-5) |
| gemini-3.8-flash | 2026-09-02 | - | [来源](https://blog.google/innovation-and-ai/models-and-research/gemini-models/3-8-flash-and-3-8-flash-cyber/) |
| gpt-6-astra | 2026-09-03 | - | [来源](https://openai.com/index/safety-overview-gpt-6-astra/) |

## 口径与缺失项

- 已填写 21 个发布时间、7 个参数量；其余参数量在已核查来源中未找到，界面显示 `-`，不代表参数量为零。
- 21 个模型均未获得可可靠归属到对应榜单行的实际评测时间，保持缺失。官方结构化数据中的全局 `generated_at`、`latest_job.finished_at` 不写入各模型的 `evaluated_at`。
- Kimi K3 日期引用 Epoch AI；GLM 日期使用厂商 release notes，其中 GLM-5.3 的 2026-08-18 是该文档发布记录日期，不宣称为最早公告日期。GPT-5.6 使用正式可用日期，保留此前有限预览的说明。
- 总参数与激活参数分开；GLM-5.2/5.3 的 744B / 40B 按厂商模型表保留，未以第三方数字覆盖。

## 验证

已从当前 API 回读全部 21 条发布记录，与原始抓取 `official-results.json` 按模型匹配：分数与来源 SHA-256 一致；无重复模型；全部为 approved；无以抓取时间补评测时间。前端榜单分别读取 `model_release_date`、`evaluated_at` 和 `parameter_count`，缺失值显示 `-`。

逐条字段核查记录见 `metadata-audit.json`，补录源见 `model-metadata.json`，结构化榜单快照见 `leaderboard-live.json`。
