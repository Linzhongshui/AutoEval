# AutoEval 后端基础架构

当前为详设的第一批基础设施实现，**不是已完成的测评后台**。单团队、单工作空间，无项目/租户层。不读取极光内部服务，也不改动前端现有展示数据。

## 已实现

- FastAPI应用工厂、lifespan资源回收、请求ID、统一异常和OpenAPI。
- `/health/live`存活检查、`/health/ready`真实检查PostgreSQL/Temporal/S3 bucket；依赖不可用返回503。
- `/api/autoeval/v1/system/capabilities`明确返回执行/分析/SSH/极光尚未启用。
- SQLAlchemy执行基础模型与独立Alembic初始迁移：run、snapshot、event、outbox四表。
- Temporal Workflow/IO/Result Worker入口；尚未实现的Activity明确抛出不可重试错误，不生成模拟成功。
- START_RUN outbox投递器：稳定Workflow ID、拒绝ID复用、重复派发去重和延迟重试。
- 只读reconciler发现滞留任务并记录告警，不推断远程状态、不自动释放资源。
- Python 3.12隔离环境、uv.lock和带hash的容器依赖清单；Compose开发拓扑与Vite API代理。

## 本地运行（PowerShell）

```powershell
cd backend
uv sync --frozen --python 3.12
Copy-Item .env.example .env
# 编辑.env：真实值只保存在本地，不提交Git
uv run uvicorn autoeval.api:app --host 127.0.0.1 --port 8000 --reload
```

访问 http://127.0.0.1:8000/docs 。API启动不强依赖外部服务，未启动依赖时ready=503是预期结果。前端在仓库的`frontend/`目录运行`npm run dev`，Vite将`/api/autoeval`转发到8000。

## Compose开发环境

```powershell
Copy-Item deploy/.env.example deploy/.env
# 修改本地密码；以下均在demo根目录执行
docker compose --env-file deploy/.env -f deploy/compose.yaml up -d --build postgres temporal storage api
docker compose --env-file deploy/.env -f deploy/compose.yaml --profile tools run --rm migrate
# 在backend中运行 uv run python -m autoeval.bootstrap storage，再检查/health/ready
docker compose --env-file deploy/.env -f deploy/compose.yaml --profile workers up -d
```

PostgreSQL 5432；Temporal 7233、开发UI 8233；开发S3 9000；API 8000，仅绑定127.0.0.1。Temporal当前采用独立持久卷上的开发SQLite，**不是生产服务**；不共用业务数据库。正式环境需独立Temporal数据库/账号及真实身份，当前代码主动拒绝production环境使用local身份。

容器镜像tag固定，但未在本环境拉取验证，生产前需验证并锁digest。当前机器已找到用户目录中的Docker Desktop。已验证容器PostgreSQL、Temporal和开发S3协议；完整后端镜像构建及真实测评仍待验证。

## 开发检查

```powershell
cd backend
uv run pytest -q
uv run ruff check .
uv run alembic upgrade head --sql
# 依赖变更后同步容器hash清单
uv export --frozen --no-dev --no-emit-project --format requirements-txt --output-file requirements.lock.txt
```

离线SQL生成和SQLAlchemy编译测试不等于真实数据库约束已验证。请勿用SQLite替代PostgreSQL验证JSONB、SKIP LOCKED、唯一约束与并发行为。

## 下一批实现边界

1. 模型、数据、Profile、整套配置及默认指针API和迁移，替换页面预置状态。
2. 正式测评run提交、工具适配及完整状态对账；诊断提交链路已实现，见下文。
3. SSH指纹和凭据、远程作业查证、资源锁及所有权清理。
4. case执行历史、原生产物、报告、基准、独立分析和榜单。

Outbox本批只投递START_RUN；CANCEL_RUN仅有schema占位，不消费。后续启用取消必须先实现工作流信号与状态查证。报告/分析outbox外键和去重需后续迁移，不能将report ID写入run外键。本批采用单行有界事务持锁派发，避免提前实现未经验证的租约claim；多副本上线前验证锁竞争并按详设演进claim机制。

尚无真实SSH执行或模型生成调用。已实现本地开发凭据引用与模型列表连通检测；本地文件凭据存储不能替代生产密钥服务。不含完整生产权限和审计。真实测评前必须补齐适配能力、预算和证据留存。

## Docker诊断联调

完成迁移与资源登记后，同时启动API、`uv run python -m autoeval.worker workflow`、`uv run python -m autoeval.worker io`和`uv run python -m autoeval.dispatcher`，然后打开前端任务管理页的“本机Docker诊断任务”。该区域使用真实数据库和执行容器，支持15秒诊断、取消及刷新后找回历史。

诊断API前缀为`/api/autoeval/v1/diagnostics/runs`，提交必须提供Idempotency-Key。相同键/正文返回同一运行，正文冲突返回409。取消意图持久化在运行行，由活动轮询消费，不依赖尚未启用的CANCEL_RUN Outbox。执行状态不明保留占用并记录execution_unresolved。

另行启动`uv run python -m autoeval.reconciler`，每60秒检查创建超过5分钟的非终态运行。仅对已关闭Workflow的诊断任务恢复投影；使用原作业键查证，不调用submit。作业已终止才收集结果、补齐事件并在同一事务释放占用；运行中取消继续按进程身份查验，找不到作业或外部不可达时保留占用。正式测评恢复及长期运行心跳策略仍待实现。

该链路仅验证框架，不调用模型、不计分、不判定Release通过。浏览器测试`tests/test_browser_diagnostics.py`需要运行中的Vite/API、两个Worker、投递器及Docker基础服务；以AE_BROWSER_URL和AE_CHROME_PATH启用。

## 开发存储更新

原MinIO官方镜像当前不可访问，Compose开发环境改为官方Moto server 5.1.22提供S3协议模拟。它不提供生产身份与持久化承诺；重建/重启可能丢失模拟产物，不用于正式历史case证据。生产仍使用受支持的S3兼容存储。Temporal的/data卷先由一次性初始化容器设为UID 1000所有，避免非root启动失败。

Docker守护进程代理异常而Windows HTTPS可达时，可用deploy/pull_image_via_host.py下载官方DockerHub镜像、校验blob与层哈希后docker load；不修改全局代理。

## 数据集清单

配置页可登记JSON清单，或调用POST `/api/autoeval/v1/dataset-manifests`：

```json
{
  "dataset_key": "example-fixture",
  "name": "自建联调样本（非正式基准）",
  "version": "v1",
  "manifest_key": "full",
  "scope": "full",
  "samples": [{"sample_id": "case-001", "sha256": "实际样本内容的64位小写SHA-256"}]
}
```

样本内容hash由数据导入方生成；清单登记不验证原题是否存在或评分是否正确。Lite需scope=lite、不同manifest_key及parent_id=同版本Full清单UUID，samples为原清单中ID/hash完全相同的成员。已登记版本不覆盖；Full样本集改变须新建数据版本。清单顺序进入hash，影响执行身份。

GET支持`?offset=0&limit=50`，next_offset=null为末页。页面目前最多显示200条，仍待统一完整分页交互；不能据当前显示范围推断数据缺失。对象存储缺失或完整性失败返回503，禁止静默使用空清单。

## Profile与配置绑定

POST `/api/autoeval/v1/profiles`登记profile_key/version/dataset_name、full_manifest_id、可选lite_manifest_id及tool契约。tool明确family（aisbench/harbor）、source_url、revision（固定Git提交hash）、scorer_reference、scorer_sha256和parallelism_owner（tool/platform）。所有登记当前仍tool_verified=false，注册不代表工具或评分已验收。

创建配置时可提供`profile_bindings: {"GPQA": "Profile UUID"}`，必须覆盖items全部条目；按每条scope解析Full/Lite，缺失Lite拒绝。已有绑定的配置后续版本必须显式保留或替换绑定。配置页独立执行绑定面板支持此操作，普通参数编辑区缺少绑定时会提示后端冲突。

GET `/api/autoeval/v1/test-configs/{id}/execution-spec`查看不可变配置、Profile与清单摘要，bindings_complete仅表示引用齐备；execution_enabled仍为false，工具验证尚未完成。运行提交未来需进一步冻结端点、资源和软件环境，不能直接将该规格当成已创建运行。

## Case回溯

内部begin_attempt在外部调用前持久化started，finish_attempt归档确认结果。重试使用新attempt_no与operation_key；同一operation_key不得对应不同样本或次数。结束后不可覆盖，原生计分与执行成功状态分开。

任务管理页的case历史回溯面板按运行UUID查询每次尝试和校验后的证据。API：GET `/api/autoeval/v1/runs/{id}/case-executions?dataset_key=...&sample_id=...&offset=0&limit=50`；GET `/api/autoeval/v1/case-executions/{id}/evidence`。暂无面向外部的结果上传/改写接口，工具Worker集成仍在进行。

PostgreSQL触发器保护归档行及执行身份；对象存储耐久性仍需生产S3验证，Moto只用于协议模拟。数据库触发器不能防止超级用户绕过，不代替正式最小权限和备份。当前没有自动删除case历史或证据的操作。

## 显式原生模型联调

`uv run python -m autoeval.native_smoke --target-id <登记的官方DeepSeek目标UUID> --resource-id <Docker资源UUID>` 会发出一次真实模型生成请求，最多32输出tokens，无自动重试。必须先布置docs/aisbench-integration.md中的固定Linux工具目录。该命令只用自建算术fixture，不能作为GPQA成绩或正式门禁验收。凭据从受保护配置按引用读取并通过stdin传给容器，不接收命令行明文密钥。

结果给出run_id/attempt_id，可在任务页case回溯面板查证。若state=unresolved，不要直接重跑；先查attempt/作业与占用，当前native-smoke恢复仍为人工调查路径，不适用DockerDiagnosticWorkflow的自动对账。正式测评还需要Temporal活动、批准数据/配置、运行快照、完整报告及原生工具差分验收。

## GPQA公开数据导入

作者仓库固定来源见tool-locks/gpqa-source.json。将CSV和source.json放入受控本地目录后，运行：

`uv run python -m autoeval.import_gpqa --csv <gpqa_diamond.csv绝对路径> --source <source.json绝对路径> --resource-id <Docker资源UUID> --lite-count 5`

该命令不调用模型；固定全量原生加载后再生成Lite，数据正文只在本地缓存、Docker导入目录和S3数据包内，Git保留摘要。版本由CSV摘要与工具提交构成，改变任何一方会生成不同版本。来源状态not_approved，不能自动用于正式Release验收。配置页可查看清单来源及摘要。

AE_GPQA_CSV指向该实际CSV时，tests/test_gpqa_import_live.py会启用真实工具/数据库/S3专项，不发出付费请求。数据导入和S3协议验证不能替代生产存储耐久性或正式测评正确性验收。

## GPQA Lite探索任务

开发启动API、workflow Worker、`uv run python -m autoeval.worker gpqa`及Outbox投递器。gpqa Worker需要主机Docker CLI、已登记执行容器和固定/work/tools/aisbench目录；现有通用Compose后端容器没有自动配置Docker CLI/daemon权限，不能直接声称容器化GPQA Worker已就绪。Docker本地联调由主机Worker控制执行容器，SSH路径待实现。

任务页新增真实GPQA Lite入口。POST `/api/autoeval/v1/runs`请求：config_version_id、target_id、resource_id、run_mode=exploration、max_model_requests（1—5），必须Idempotency-Key。首批固定Lite<=5、单GPQA、并发1、max output<=64、temperature=0/top_p=1。配置需要绑定与原生锁一致的Profile及实际导入的数据包。其他组合明确拒绝，不回退示例成绩。

GET `/runs`支持offset/limit，GET `/runs/{id}`返回进度和报告摘要，GET `/runs/{id}/report`校验并返回完整报告证据。POST `/runs/{id}/cancel`仅保存取消意图，当前请求返回后停止后续样本。未知状态不重发请求，当前正式探索任务仍需人工查证，不套用诊断任务恢复器。

报告complete指完整覆盖所选Lite清单，不能解读为全量198题。partial只显示成功样本范围指标；failed_summary无有效执行，invalid表示评分失败、accuracy=null。正式发布门禁始终not_applicable。后续继续完成分析、基准、正式Release规则及其他工具。

AE_GPQA_PIPELINE_TEST=1启用真实SQL/S3/Temporal、模拟模型边界专项；专用随机测试队列避免与真实模型Worker混用，该测试不发出付费请求。真实模型联调须明确提交任务，禁止由普通测试自动重复触发。

## 报告目录与产物来源

报告管理页已读取真实后端，GET `/api/autoeval/v1/reports?offset=0&limit=20`返回目录及next_offset，GET `/reports/{id}`读取详情，GET `/reports/{id}/evidence`校验S3正文。`#report/<UUID>`可刷新直达。原型示例报告明确折叠标记。

execution_origin由服务端运行环境冻结，默认real；模拟测试应用显式设为simulation。历史来源不明的报告默认unverified。普通报告目录只展示real，不把模拟成绩当真实结果。历史来源核验只补充元数据/审计，不重写原始成绩或快照。自动分析尚未启用，不展示伪造分析。

AE_REPORTS_TEST=1启用已存在真实报告的只读目录/证据验证；搭配AE_BROWSER_URL及AE_CHROME_PATH可运行浏览器详情测试。它们不发出模型生成请求。
