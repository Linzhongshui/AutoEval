# 验收、升级与恢复

Linux 示例在当前目标 release 使用[内网单机发布](intranet.md)的 dc 函数。Windows 示例从 backend 运行。对每个检查记录环境、时间、期望、实际结果和证据标识。无法执行时记录缺少的条件。

## 入口与服务

1. 内网从用户实际使用的客户端访问；回环网关如需 SSH 转发，在客户端运行 ssh -N -L 127.0.0.1:18443:127.0.0.1:18443 "$SSH_HOST" 并保留会话。用证书 SAN 中的名称访问；必要时配置该客户端到回环的名称解析。统一入口按实际地址测试，不重复建隧道。用受信 CA，首次不带认证应返回 401，交互输入密码后首页及 API 应返回 200。浏览器重新加载后能看到页面及成功的真实 API 请求，API 响应体应为 JSON。nginx.conf 的 /health/ 路径可能落在 SPA 回退，健康探针直接访问 API。
2. 在网关客户端 Linux shell 中执行：

~~~bash
curl --cacert "$CA_FILE" -sS -o /dev/null -w '%{http_code}\n' "$BASE_URL/"
curl --cacert "$CA_FILE" -fu "$WEB_USER" "$BASE_URL/api/autoeval/v1/system/capabilities"
~~~

证书错误先查 SAN、有效期、信任链与隧道解析。401 查 htpasswd 及 Nginx worker 读取权限。502 查网关与 API 是否共用预期网络命名空间。Windows 本地入口用[本地部署](windows.md)的 5173 代理检查。

3. 目标 release 内核对存活、三个依赖的就绪状态及运行镜像。同步检查 dispatcher、planning、reconciler 进程和最近错误（只在受保护终端查看日志，交付时脱敏）。

~~~bash
dc exec -T api python -c 'import httpx; c=httpx.Client(trust_env=False); rs=[c.get("http://127.0.0.1:8000/health/"+v) for v in ("live","ready")]; [r.raise_for_status() for r in rs]; print([r.json() for r in rs])'
for svc in api dispatcher workflow planning planning-execution result reconciler; do
  docker inspect --format '{{.Name}} {{.Image}} {{.State.Status}} {{.RestartCount}}' "$(dc ps -q "$svc")"
done
~~~

4. 在能访问 Temporal frontend 的网络中，使用匹配版本的 Temporal CLI。未发布 7233 时可用预置 CLI 容器加入 network-anchor 命名空间。TEMPORAL_ADDRESS、NS 取 backend.env。按 autoeval.entrypoints.worker.role_options 的实际设置列出每个启用角色的队列和类型，分别检查；混合队列需要两类 poller。规划协调和分发器在数据库中轮询，另查其工作记录。以下示例对应默认值：

~~~bash
temporal operator namespace describe --address "$TEMPORAL_ADDRESS" --namespace "$NS"
temporal task-queue describe --help
temporal task-queue describe --address "$TEMPORAL_ADDRESS" --namespace "$NS" --task-queue demo.workflow.v1 --task-queue-type workflow
temporal task-queue describe --address "$TEMPORAL_ADDRESS" --namespace "$NS" --task-queue demo.planning-execution.v1 --task-queue-type activity
temporal task-queue describe --address "$TEMPORAL_ADDRESS" --namespace "$NS" --task-queue demo.result.v1 --task-queue-type activity
~~~

CLI 版本若按所有类型输出，使用其 help 中对应的选项。没有 CLI 可在 backend 的锁定 Python 环境（服务器用 dc exec -T api python -）执行下列 SDK 检查。按启用的角色调整最后一行；启动后等待首次轮询并检查 poller 的最近活动，避免把旧实例身份算入本轮。

~~~python
import asyncio
from temporalio.api.enums.v1 import TaskQueueType
from temporalio.api.taskqueue.v1 import TaskQueue
from temporalio.api.workflowservice.v1 import DescribeNamespaceRequest, DescribeTaskQueueRequest
from temporalio.client import Client
from autoeval.entrypoints.worker import role_options
from autoeval.infrastructure.config import get_settings

async def check(roles):
    s = get_settings()
    c = await Client.connect(s.temporal_address, namespace=s.temporal_namespace)
    svc = c.workflow_service
    await svc.describe_namespace(DescribeNamespaceRequest(namespace=s.temporal_namespace))
    for role in roles:
        spec = role_options(s)[role]
        for key, kind in (("workflows", TaskQueueType.TASK_QUEUE_TYPE_WORKFLOW),
                          ("activities", TaskQueueType.TASK_QUEUE_TYPE_ACTIVITY)):
            if spec.get(key):
                result = await svc.describe_task_queue(DescribeTaskQueueRequest(
                    namespace=s.temporal_namespace, task_queue=TaskQueue(name=spec["task_queue"]),
                    task_queue_type=kind))
                print(role, key, [(p.identity, p.last_access_time.ToJsonString()) for p in result.pollers])
                if not result.pollers:
                    raise RuntimeError(f"缺少轮询者 {role}/{key}")

asyncio.run(check(["workflow", "planning-execution", "result"]))
~~~

## 无模型归档与报告

执行位置限允许维护诊断的 development/test 工作空间。目标策略限制诊断时，在隔离数据库、桶、队列和执行资源上使用同版本运行；报告分别列出目标入口验收与隔离归档结果。

1. 从目标版本的 backend/src/autoeval/evaluation/fixture_pipeline.py 核对固定输入。使用已有 kind=standard 的配置版本；空库可用 python -m autoeval.catalog.import_standard_config --input /path/to/approved.json 导入获批配置（位于已配置后端环境，容器需只读挂载输入）。记录输出的配置版本 ID。核实具备固定产物的已登记 SSH/Docker 环境、主机指纹、凭据引用和预期摘要。
2. 将 AE_UNIFIED_FIXTURE_CONFIG 指向 API 可读的受保护 JSON。其 origin 为 simulation，expected_cases 为 {"validation-dataset":["0","1"]}。填写 aisbench_revision、container、source_file、source_sha256、credential_ref，以及 ssh 的 host、port、username、fingerprint、workdir、owner_id、auth_kind。工作目录应由登记执行账户持有。文件只写凭据引用；真实密钥由 fixture worker 的 FileSecretStore 解引用。缺固定产物、资源或标准配置时，记录待验收。
3. 重新加载本环境 API 配置；在后台另开终端启动临时 worker：服务器用 dc run --rm --no-deps api python -m autoeval.entrypoints.worker fixture；Windows 用 uv run --frozen python -m autoeval.entrypoints.worker fixture。核对 demo.fixture.workflow.v1 的 workflow 和 activity poller。
4. 从数据工作台 → 环境诊断 → 平台归档流程验证选择标准配置，提交一次。记录浏览器网络请求的 Idempotency-Key、HTTP 202 和 data.run_id。接口为 POST /api/autoeval/v1/diagnostics/unified-fixture，请求体只含 config_version_id。超时先按原 run_id 或同一幂等键查证；不另造一次提交。无法使用网页时可通过该接口排查，仍需在浏览器核对最终报告。
5. 查看 GET /api/autoeval/v1/runs/{run_id}；按同一 run_id 查出 Outbox、Temporal workflow demo/run/{run_id} 和最终报告 ID。任务事件应包含 fixture_remote_collected 和 fixture_completed；报告页面打开「查看结果 → 样本明细」，核对样本 0、1 的 Case、实际缺项及 simulation 标识。检查网络中真实 API 响应、已清理远端 staging、保留原固定产物。接受提交、页面截图或空报告均不足以通过。
6. 从数据库 UnifiedArtifact 与当前 EvaluationReport 取该运行的 object_key、sha256；用实际后端配置读回原始产物和报告字节。下面在已配置的后端环境运行，把两个对象的键和摘要分别传入 sys.argv[1:3]。读回与 DB、固定文件预期摘要逐一匹配。

目标 release 中运行下面的只读查询；RUN_ID 用本次提交返回值。记录分发状态、当前报告以及两组对象键与摘要，再执行回读。

~~~bash
dc exec -T postgres psql -X -v ON_ERROR_STOP=1 -v run_id="$RUN_ID" -U autoeval -d autoeval <<'SQL'
SELECT state, attempt_count FROM outbox WHERE run_id = :'run_id' AND kind = 'START_RUN';
SELECT seq, type FROM run_event WHERE run_id = :'run_id' ORDER BY seq;
SELECT object_key, sha256 FROM unified_output_artifact WHERE run_id = :'run_id';
SELECT id, object_key, sha256, validity FROM evaluation_report WHERE run_id = :'run_id' AND is_current;
SQL
~~~

~~~python
import hashlib, sys
from autoeval.catalog.datasets import storage
from autoeval.infrastructure.config import get_settings

s = get_settings()
key, expected = sys.argv[1:3]
client = storage(s)
try:
    raw = client.get_object(Bucket=s.s3_bucket, Key=key)["Body"].read()
    if hashlib.sha256(raw).hexdigest() != expected:
        raise ValueError("对象回读摘要与索引不符")
    print(key, len(raw), expected)
finally:
    client.close()
~~~

例如把上段存为受保护临时文件 verify-object.py，在目标 release 分别执行 `dc exec -T api python - "$OBJECT_KEY" "$EXPECTED_SHA" < verify-object.py`。Windows 可在 backend 目录执行 `uv run --frozen python 验证脚本路径 对象键 摘要`。

7. 若用自动化替代第 4 步，在具备 Chromium 和本机回环前端的 Windows 后端目录运行以下命令。该测试会提交一次，要求预先确认其选择的首个标准配置；同一轮从手工或自动化中选一种。浏览器用例没有内网 Basic Auth 凭据支持，目标网关仍需从实际客户端登录核对。

~~~powershell
$env:AE_BROWSER_TEST='1'
$env:AE_BROWSER_URL='http://127.0.0.1:5173'
$env:AE_FIXTURE_PIPELINE_TEST='1'
uv run --frozen pytest -q tests/browser_checks/test_fixture_pipeline_live.py
Remove-Item Env:AE_FIXTURE_PIPELINE_TEST
~~~

结束临时 worker，撤除仅为本次提供的配置/挂载并恢复 API。403/503 先查环境与配置可读性，422 查标准版本，accepted 后不动查 Outbox、dispatcher 和 namespace；采集失败查固定文件摘要、SSH 指纹及挂载凭据，报告缺对象查桶与 key。保留失败运行及日志。

真实样本只在指定模型、允许主机、资源、样本清单、最大尝试和预算均明确后，通过统一测评入口执行预检、冻结输入、提交和追踪。记录已发请求数、run_id、报告和证据状态。报错或响应未知先查调用账本；模拟结果独立标注。

## 有数据的升级与备份

1. 在旧 release 确认 PROJECT、真实卷、当前代码和镜像、Alembic revision、非终态任务及执行租约。关闭新提交入口，等在途任务和外部工作结束；未知外部执行先核查并保留。停所有写入方（含临时 worker、外部连接、API、dispatcher、reconciler 等）。停 Temporal 服务以冻结历史写入，两个 PostgreSQL 和 MinIO 保持运行。备份失败时暂停升级，保留可恢复的旧实例。
2. 在旧 release 用实际旧服务定义创建下列备份。旧端若不是渲染版，把 dc 指向旧项目的原始 Compose 文件。B 为位于受保护介质的新绝对目录。先验证目标备份路径非现存目录。对象脚本必须与执行它的镜像版本匹配：仓库旧脚本导入 autoeval.config 和 autoeval.datasets，当前实现已迁到 autoeval.infrastructure.config 和 autoeval.catalog.datasets。先对实际镜像验证；只在备份工作目录复制件调整导入。以下针对当前命名空间，旧镜像使用其通过导入检查的脚本。

~~~bash
umask 077
mkdir -m 700 "$B"
dc exec -T postgres pg_dump -U autoeval --no-owner --no-privileges -d autoeval > "$B/database.sql"
for db in temporal temporal_visibility; do
  dc exec -T temporal-db pg_dump -U temporal -p 5433 --no-owner --no-privileges -d "$db" > "$B/$db.sql"
done
if dc run --rm --no-deps api python -c 'from autoeval.infrastructure.config import get_settings; from autoeval.catalog.datasets import storage'; then
  for task in backup restore; do
    sed -e 's/from autoeval.config import/from autoeval.infrastructure.config import/' \
        -e 's/from autoeval.datasets import/from autoeval.catalog.datasets import/' \
        "${task}_objects.py" > "$B/${task}_objects.py"
  done
elif dc run --rm --no-deps api python -c 'from autoeval.config import get_settings; from autoeval.datasets import storage'; then
  cp backup_objects.py restore_objects.py "$B/"
else
  echo '备份工具与旧发布镜像不匹配，停止升级' >&2
  exit 1
fi
dc run --rm --no-deps -v "$B:/backups" api python /backups/backup_objects.py
~~~

确保容器用户实际可访问 B（尤其旧镜像 UID）。备份 protected env、凭据文件、TLS、htpasswd、实际生效的 Compose、镜像清单/离线包与源码标识。配置若用符号链接，解析具体路径并仅备份已核实的目标文件；旧 release 与引用目标都要能重建。可用以下命令备份常规模板布局；另加实际启用的配置。备份与服务密钥同级保护。

~~~bash
tar -chzf "$B/credentials.tar.gz" -C shared secrets tls backend.env postgres.env temporal-db.env temporal.env storage.env htpasswd
(cd "$B" && find . -type f ! -path './SHA256SUMS' -print0 | sort -z | xargs -0 sha256sum > SHA256SUMS && sha256sum -c SHA256SUMS)
~~~

核对数据库转储非空且命令成功，objects.json 与 objects.tar.gz 项数和摘要可恢复，将受保护备份复制到独立介质并复验清单。Windows 本地可在 backend 用 uv run --frozen python -m autoeval.infrastructure.backup create --postgres-container 实际数据库容器名 --output 新备份目录 备份业务库与证据；另保存配置及凭据，停本地 Temporal 后备份其 SQLite 持久卷。该工具的清单范围不包括 Temporal。

## 隔离恢复、切换与回滚

1. 使用单独 Compose 项目、新卷、未占用端口、空业务库和新桶，检查 docker inspect 的 Mounts 与源端无重叠。复制配置后**先替换所有目标连接**并核对；隔离外部执行和模型出口，保持调度/Worker 关闭。仅在受保护目录还原凭据。运行对象脚本前检查桶为空；已部署 Temporal auto-setup 会创建表，SQL 导入前仅启动两个空 PostgreSQL 和 MinIO，手工建立空的 temporal 与 temporal_visibility 数据库。确认目标角色、数据库和桶名，复核 SHA256SUMS。
2. 在隔离 release 中，让 dc 指向**隔离项目**。用与备份匹配的 PostgreSQL 主版本、角色和工具导入；若已初始化过表，改用另一个空恢复目标。下面两条 createdb 仅在该数据库尚未创建时执行。SQL 出错即停，转至新的空目标排查。

~~~bash
dc exec -T temporal-db createdb -U temporal -p 5433 temporal
dc exec -T temporal-db createdb -U temporal -p 5433 temporal_visibility
dc exec -T postgres psql -X -v ON_ERROR_STOP=1 -U autoeval -d autoeval < "$B/database.sql"
for db in temporal temporal_visibility; do
  dc exec -T temporal-db psql -X -v ON_ERROR_STOP=1 -U temporal -p 5433 -d "$db" < "$B/$db.sql"
done
dc run --rm --no-deps -v "$B:/import:ro" api python /import/restore_objects.py
dc run --rm --no-deps api alembic current
~~~

核对 verified_objects 与清单长度、恢复后的 revision 与备份值，在隔离网内开启 Temporal/API 后抽查 namespace、原报告、Case、对象回读。演练已恢复的 outbox/执行租约不得投向真实执行资源。Windows 业务库与 S3 恢复可查 uv run --frozen python -m autoeval.infrastructure.backup restore --help，仅使用独立空目标。
3. 同工作空间升级按内网手册在维护窗口内启动新版本，核对迁移和后台角色。限制常规用户写入，同时允许授权验收。完成验收后将服务管理入口 current 切到已验收 release（同一目录下建立临时符号链接，再用 mv -T 原子替换既有符号链接），再开放新提交。失败时记录切换后写入；先停止新进程。数据库兼容性已核实才可切回旧镜像；不兼容时恢复配套库、Temporal、对象和配置至已校验环境，核对增量处置后再切流。保留故障卷及原备份，不执行 down -v 或覆盖在用库。
4. 最终交付一张结果表，列出目标/环境、源码提交或快照哈希、后端镜像 ID、迁移前后 revision、入口、TLS/认证、readiness、角色/队列、固定产物 run_id/report_id/对象摘要、备份与恢复验证位置、可选真测结果。每项填通过、失败或未验及原因；验证历史成绩时分别记录 validity 与 evidence_status，不补写缺失对象或成绩。
