# AutoEval 在用镜像与 OBS 路径（2026-11-24）

清单依据为服务器实际运行容器、API 和执行 worker 的资源配置、业务库中有执行记录的数据集及其任务定义。按镜像 ID 核对；全部路径使用 aisbench 桶。

| 分组 | 用途 | 大小（字节） | OBS 路径 |
| --- | --- | ---: | --- |
| platform | API、后台进程、网关、PostgreSQL、Temporal、MinIO 和 DinD 服务 | 999486214 | `obs://aisbench/images/autoeval/runtime-20261124/platform-6c3c16f50bbd.tar.gz` |
| analysis-budget | 分析与预算辅助服务 | 132339256 | `obs://aisbench/images/autoeval/runtime-20261124/analysis-budget-70cd777dc7e3.tar.gz` |
| dataset-executors | 资源配置引用的 AISBench、Harbor 基础环境和精度执行镜像 | 1458496835 | `obs://aisbench/images/autoeval/runtime-20261124/dataset-executors-f80971b0cc3e.tar.gz` |
| langfuse | 独立 Docker 引擎中的 Langfuse 服务及数据库 | 1291136909 | `obs://aisbench/images/autoeval/runtime-20261124/langfuse-fca3bcb64ee9.tar.gz` |
| harbor-support | AutomationBench 600 个任务 Dockerfile 共用的基础镜像 | 1474314386 | `obs://aisbench/images/autoeval/runtime-20261124/harbor-support-cd834d2bcba3.tar.gz` |
| standalone-dataset-runners | 同机直接运行的 GPQA、Harbor、DeepSWE 独立执行环境 | 2354916151 | `obs://aisbench/images/autoeval/runtime-20261124/standalone-dataset-runners-052ed6d2c69f.tar.gz` |
| deepswe-lite | 现役 Harbor runner、固定 Lite 样本、内核探测与网络辅助镜像 | 2430514926 | `obs://aisbench/deepswe/deepswe-lite-linux-amd64-20261124.tar.gz` |
| deepswe-full | DeepSWE v1.1 全部 113 个任务标签，与服务器镜像 ID 逐项比对 | 24013532317 | `obs://aisbench/deepswe/deep-swe-v1.1-task-images.tar.gz` |
| archived-task-runners | 历史 AutomationBench、DeepSWE 任务冻结的 Harbor 执行模板 | 1474421545 | `obs://aisbench/images/autoeval/runtime-20261124/archived-task-runners-2f026715c4ca.tar.gz` |

## 导入和使用

下载所需对象，以 manifest.json 的 SHA-256 核验压缩包。宿主镜像使用 docker load -i 文件名；Langfuse 包导入对应独立 Docker 引擎。保持各服务绑定的镜像 ID，特别注意宿主和子引擎同名标签。

GPQA、MMMU-Pro 需要精度执行组和各自只读数据目录。AutomationBench 与 DeepSWE 共用 Lite 包中的 Harbor runner、探测镜像和 sidecar。AutomationBench 另加载 harbor-support 包，DeepSWE 全量执行另加载 deepswe-full 包。使用私有 rootless Docker 的任务按部署配置向内层引擎提供已固定的基础镜像或离线归档。

平台数据、数据库和对象卷、前端静态文件、证书与凭据、任务源、wheelhouse、rootless helper、配置与宿主路径需要单独准备。镜像覆盖已经核对；本次未执行新服务器恢复或模型测评。验证/回滚专用实例、构建缓存与其他项目任务不计入现役范围。

详细镜像标签、完整 ID、归档哈希、服务和执行器用途见同目录 manifest.json。
