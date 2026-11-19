# 吞吐探测与历史异常真机验收（2026-11-16）

## 结论

真实浏览器、当前API、真实PostgreSQL、对象存储和客户SSH/容器验收通过，无API mock。分两阶段录制：历史结案及已有曲线估时；单次获批真实吞吐探测及自动估时。未提交正式测评。

## 发现与修复

- 默认 preflight/plan Worker 会处理不属于其职责的历史 probe 取消恢复，覆盖 remote_check，导致结案入口消失。增加按 Worker kinds 的最终过滤，并使结果更新合并保留查证信息；本地相关进程已重载。
- PowerShell JSON 日期自动转型后以本地日期格式注入截止时间，导致专用探测 Worker 启动即退出。新增 backend/scripts/start_probe_worker.py，Python读取并保存带时区ISO时间，保持原历史排除边界并检查执行器是否已在线。

## 历史异常

在网页上依次查询、等待超过一次后台轮询以确认查证结果不被覆盖，再填写原因、确认未知用量、结束两条历史记录：

- f406c876-38a4-4fe9-8eaf-9c6eae366be6
- 2088fc55-61b2-4ff1-b1c0-c0d549c0cb56

均保留原始异常、远程查证、未知执行结果和审计记录；结案为失败，不是成功或无费用声明。随后新探测按钮可用。已有曲线自动估时58秒（不同曲线与条件，不与新结果直接等同）。

## 真实吞吐探测

用户明确批准 DeepSeek、档位1/2/4/8、输入目标512tokens、每次最大输出512tokens，含回退最多32次请求/16384输出tokens，不自动重跑。

- 任务：6ee8114a-7d71-45ee-856f-d8a9da8e1f4f
- created_at：2026-11-16T08:16:50.234177Z
- completed_at：2026-11-16T08:17:34.828481Z
- 4/4档完成，4档error_rate均为0，曲线usage_estimated=false。
- 曲线：bb638d3e-2d2b-4800-a720-4e75906ea715
- 对象：planning/throughput/a1f42108c417980293bc37e3ee6588ba5cd6f4e502e98c86a7c9ac4beefe58ba.json
- SHA256：a1f42108c417980293bc37e3ee6588ba5cd6f4e502e98c86a7c9ac4beefe58ba，已从对象存储回读验证。
- 曲线自动选中，并自动发起当前参数估时，页面显示1分29秒。未点击采纳建议，未提交测评。

第一次启动尝试因无就绪执行器返回503，未创建任务；修复日期格式后只成功创建上述一条真实探测，无重复运行。请求预算是允许上限，曲线摘要未提供完整计费请求清单，不能把32当作实测调用数。

## 证据与边界

原始录屏、截图、请求路径及JSON：.screenshots/probe-real-acceptance-20261116/ 和 .screenshots/probe-paid-acceptance-20261116/。合并录屏：[历史录屏](https://github.com/llauren48/AutoEval-Platform/blob/1faf83a0d78d880324280f7d9e2656291ce00734/deliverables/probe-acceptance-20261116.mp4)，两阶段拼接，中间有间隔。无密钥进入画面。

真实探测与自动估时链路通过不等于估时误差精度验收；自动估时仍受样本历史覆盖及输出假设影响。API和Worker运行于本地，调用客户服务器；本轮未发布服务器版本、未提交推送。
