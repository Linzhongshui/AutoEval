# 本机持久化存储与恢复

适用范围：单团队开发环境，主机运行API/Worker/Vite，Docker运行数据库、Temporal、执行器、SSH模拟器及对象存储。本流程不构成生产部署或灾备验收。

## 2026-11-11修复结果

- 恢复API、Workflow/I/O/GPQA Worker、Outbox派发和对账进程。缺失Worker导致的accepted停留已通过诊断与流水线复测。
- SSH模拟器以sshd前台进程运行；实际容器重启后11项SSH测试通过。保留原主机密钥及批准指纹，旧容器以autoeval-ssh-sim-before-supervision保留回退。
- 现存84个证据对象逐个复制、读回校验，合计234815字节。原Moto端点9000未删除，新MinIO端点9002已启用。迁移后84个对象再次经历容器重启并逐个通过摘要比对。
- 仅从已批准CSV与固定原生Loader重建能匹配数据库原SHA-256的数据集内容，恢复26个清单对象，另1个已完整。没有重建模型输出、历史成绩或数据库快照。
- 两份历史真实报告及相关原文没有备份，无法恢复。原索引和成绩字段保留，页面隐藏未验证成绩，提示证据状态；榜单排除未验证报告，基准差值不计算。
- 当前数据库与可用对象已备份至backend/.secrets/backups/repair-2026-11-11-cade4c2f。该备份不包含已经丢失的历史对象，不得据此宣称历史完整。

## 存储镜像与启动

官方镜像拉取被拒绝后，使用GHCR社区备份，固定完整摘要而非latest：

`ghcr.io/l33tlamer/minio-backup@sha256:a1ea29fa28355559ef137d71fc570e508a214ec84ff8083e39bc5428980b015e`

实测二进制版本为RELEASE.2025-04-22T22-12-26Z。来源线索为[MinIO仓库讨论中的镜像备份记录](https://github.com/minio/minio/discussions/21320)。摘要保证当前镜像内容固定，不等同官方签名或生产安全验收。镜像授权为AGPLv3，生产选型需另行评审。

在仓库根目录执行前，须在受保护配置中设置AE_S3_ACCESS_KEY和AE_S3_SECRET_KEY，客户端与服务端保持一致；不要将凭据提交或发送到聊天。

```powershell
docker volume create autoeval-evidence-persistent
docker compose --env-file backend/.env -f deploy/compose.storage-durable.yaml up -d
```

主机backend/.env设置AE_S3_ENDPOINT=http://127.0.0.1:9002。该文件被忽略；修改后重启API与Worker。持久卷为外部卷，禁止删除卷；容器可重建。旧基础Compose的storage仍为Moto，只用于协议测试，不应再用于业务证据。上述独立存储端口是主机路径，不能直接当作API容器内部地址。

## 迁移与备份

所有uv命令在backend目录执行。切换前停止写入服务，保留源端点配置，先预览再执行：

```powershell
uv run python -m autoeval.migrate_storage --target-endpoint http://127.0.0.1:9002
uv run python -m autoeval.migrate_storage --target-endpoint http://127.0.0.1:9002 --apply
```

工具只接受本机开发目标；逐对象比较SHA-256，冲突拒绝覆盖，源对象不删除。源对象清单在迁移期间变化会拒绝宣布成功。所有校验通过后才修改客户端端点；切换后同源同目标命令会被拒绝，避免误报迁移。

新建受保护备份目录时可执行：

```powershell
uv run python -m autoeval.backup create --postgres-container autoeval-demo-postgres-1 --output .secrets/backups/manual-new
```

目标目录必须不存在。现有restore命令仅用于空scratch数据库/桶，不能直接覆盖当前工作空间。备份应独立于pytest临时目录和存储容器，定期验证；持久卷不替代备份。

## 可复现数据的精确恢复

```powershell
uv run python -m autoeval.repair_gpqa_evidence --csv <缓存CSV路径> --source tool-locks/gpqa-source.json --resource-id <已登记执行器UUID>
```

默认只预览，确认目标后加--apply。工具校验原始CSV出处、执行器身份、固定原生输出与数据库已有摘要，拒绝覆盖不同内容。它不恢复报告或case模型输出；不存在原始字节时必须保留缺失状态，不以新测评填补旧记录。

## SSH与业务进程

deploy/ssh-sim.Dockerfile以sshd作为前台主进程，setup_ssh_sim.py检测已有监听，避免重复启动守护进程。当前本机恢复镜像autoeval-ssh-sim-recovery:20261111保留该模拟实例的身份和文件，仅供该实例本机恢复；包含其主机私钥，不发布、不用作通用镜像。

API之外分别启动autoeval.dispatcher、autoeval.worker workflow、autoeval.worker io、autoeval.worker gpqa和autoeval.reconciler。启动前核对未确认的真实运行，不通过重提或删除占用解决未知状态。分析Worker仅在目标、资源和预算明确时开启。

## 验收解释

报告validity记录历史执行完整性；新增evidence_status表示当前报告对象校验状态，二者独立。missing、invalid、unavailable、not_checked均不参与榜单，不计算有效差值；不将缺失成绩补为零。

没有原始历史证据时，本轮真实报告页面只验收缺失提示与隔离分支。有证据的成功显示、评分及归档仍由模拟模型的真实SQL/S3/Temporal流水线和此前验证支撑；不将负向分支通过宣称为历史数据恢复或新真实测评通过。
