# 最新模型官方成绩补录（2026-11-11）

已发布 11 个模型的 44 条成绩；原有 141 条发布记录保持不变。仅抽取厂商模卡中的本模型列，未将同行对比列伪装成本模型原始来源。

| 模型（ModelScope） | 新增成绩数 |
| --- | ---: |
| ZhipuAI/GLM-5.2 | 4 |
| ZhipuAI/GLM-5.3 | 4 |
| moonshotai/Kimi-K3 | 6 |
| moonshotai/Kimi-K3.1-Pro | 6 |
| MiniMax/MiniMax-M3.1-Flash | 3 |
| deepseek-ai/DeepSeek-V4.1-Flash | 6 |
| deepseek-ai/DeepSeek-V4.1-Flash-1017 | 3 |
| Qwen/Qwen3.8-2.4T-A95B | 4 |
| Qwen/Qwen3.8-27B | 3 |
| Qwen/Qwen3.8-Flash-Next | 2 |
| ZhipuAI/GLM-5.3-Flash | 3 |

## GPQA Diamond 新增记录

| 模型 | 分数（原始量表） |
| --- | ---: |
| moonshotai/Kimi-K3.1-Pro | 94.2 |
| moonshotai/Kimi-K3 | 93.5 |
| Qwen/Qwen3.8-2.4T-A95B | 92.6 |
| Qwen/Qwen3.8-Flash-Next | 91.7 |
| ZhipuAI/GLM-5.2 | 91.2 |
| deepseek-ai/DeepSeek-V4.1-Flash | 90.9 |
| Qwen/Qwen3.8-27B | 89.2 |

## 来源与口径

- `entries.json` 是补录内容；`evidence.json` 记录模卡行、列索引或图片区域及 SHA-256；原始模卡和 ModelScope 身份响应保存在同目录。
- 原始量表保持为厂商公布值，统一标记 publisher_reported_score / points，不假称为同条件复现。
- Terminal-Bench 2.1、3.0、4.0 分开；AutomationBench-AA 独立；MMMU-Pro 的无工具和 Python 工具成绩分别留存，不能平均。
- 未公开的评测时间保持缺失；Kimi K3.1 Pro 日期使用官方 Kimi Code 完整上线日期，保留日期口径。其他未知字段显示 -。
- GLM-5.3-Flash 的 84.3、63.4、48.8 从官方图片中本模型蓝色柱的标注人工核对；图片一并留档。
- MiniMax M3.1 Flash、GLM-5.3 及 GLM-5.3-Flash 所核查模卡未提供本模型 GPQA Diamond 数值，本轮不从其他厂商对比列代填。

## 验证

- API 回读 44 条新记录，与补录源逐字段一致；原有全部记录未改动。
- 数值范围、来源键唯一性及缺失评测日期检查通过。
- 重复执行导入时使用固定抓取快照和来源键，不重复发布。
- Ruff、TypeScript 检查通过。通过本机 Edge 无头浏览器读取榜单，Kimi K3.1 Pro 与 Qwen3.8 Flash Next 已显示；截图 `.screenshots/latest-models-leaderboard.png`。
