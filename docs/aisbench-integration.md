# AISBench 原生适配核验记录

源仓库：https://github.com/AISBench/benchmark 。固定提交以 backend/tool-locks/aisbench.json 的 revision 为准；该文件覆盖 ais_bench 上游树全部已跟踪文件的 SHA-256。开发依赖版本在同目录 aisbench-linux-requirements.txt；尚非生产镜像验收。

## GPQA首条路径

- 选择 gpqa_gen_0_shot_str，配置默认 GPQA_diamond。GPQADataset.load 使用原始CSV第7—11列，依全量行序循环置换选项。Lite必须在完整原生加载后按清单选择；先截取CSV会改变选项位置和正确答案。
- 原生后处理 first_option_postprocess(options=ABCD)，评分 GPQAEvaluator.score；accuracy为百分制，details包含逐样本pred/answer/correct。
- 空输出诊断单独保留，仍按原生后处理/评分进入分母；不擅自改为不计分。执行失败与合法空响应后续需由case执行状态区分。
- bridge按锁核验源码，直接import原生类，不提取函数或mock原生依赖。目前仅数据准备/评分，不包含推理HTTP、正式运行提交或已验证工具注册。
- Windows环境原生导入在fcntl失败；不修改上游，改用Docker Linux的Python3.12与CPU torch依赖。依赖下载经主机网络完成，避免Docker守护进程代理问题。

## 待验收

- 在Linux执行完整原生加载与评分差分测试；自建fixture只检验适配规则，不得作为GPQA测评成绩。
- 批准数据来源、许可证及数据版本输入后导入真实样本；当前无批准的正式数据快照。
- 原生PromptTemplate与服务模型调用、DeepSeek请求语义、逐尝试证据、错误/截断诊断、重试与报告接入。
- MMMU-Pro需另外固定options10/vision及cot变体；锁中源码存在不等于多模态已验证。AutomationBench工具/数据承诺仍需单独核验。

## 本轮Linux验证结果

现有Docker executor内的固定原生路径两项测试已通过（约31秒）：评分与直接原生调用一致，空输出保持原规则；两行自建CSV加载后答案依序D/C且样本标识稳定。没有调用模型服务。另有源码篡改/额外Python文件拒绝测试。

开发容器目录：/work/tools/aisbench/source（上游ais_bench树）、site-packages（Linux CPython3.12 CPU依赖）、bridge.py、lock.json。运行时设置PYTHONPATH=/work/tools/aisbench/site-packages:/work/tools/aisbench/source。以AE_AISBENCH_NATIVE_TEST=1启用tests/test_aisbench_native_live.py；默认测试跳过此专项，不能将跳过当成原生验证。

生产前需将依赖制成锁定镜像，并核验所有wheel/hash及第三方许可证；当前仅记录解析版本，未承诺生产可复现镜像。原生评分首批通过，不代表数据、推理、正式报告和评分完整性验收已完成。
