# DeepSWE e968d1b 离线 Agent 修复

适用范围为 Linux AMD64 的 **DeepSWE 执行节点**。平台 API 和数据库无需变更。基础镜像为 `autoeval/deepswe:offline-e968d1b-20261126`，ID 为 `sha256:dd90e0520919a049e10a195f05c1abcbc4b81872e542f258e0d74a6f06113bce`。任务数据、样本基础镜像、SSH 资源、模型服务及其密钥继续使用目标环境的配置。

## 更新执行节点

从本目录运行 `bash install.sh`。需要 Bash、Python 3、Docker 和 sha256sum。在线下载还需要有 aisbench 桶读取权限的 obsutil。先核对 Docker context 是 Harbor 作业使用的引擎。离线环境可从 [release.json](./release.json) 的 URI 预先下载文件，将 `ARCHIVE` 指向目标机上已传输的归档，再执行同一命令。

1. 在维护窗口备份 DeepSWE 执行模板，保留旧镜像 ID、工具目录和挂载清单。等待当前资源上的在途任务结束。
2. 将 DeepSWE 专用模板的 `image_id` 设置为脚本核对的完整 ID。移除覆盖 MiniSweAgent、Harbor factory 等模块的现场临时文件，检查 `PYTHONPATH` 和任务使用的解释器（镜像中为 `/opt/venvs/harbor/bin/python`）。
3. 默认 AISBench runner 位于新镜像的 `/benchmark`。若作业使用单独挂载的工具根，例如日志中的 `/opt/autoeval-cache/pier`，请复制该工具根到**新版本目录**，在该副本上运行下方命令，再将新模板指向副本并保存其摘要。直接替换全套工具目录可能覆盖标准仓自定义适配。
4. 在两个资源上分别执行无模型测试。获得授权后，各提交一次 `abs-module-cache-flags`，尝试一次、重试零次；核对 run、report、原生评分、token、`validity` 和取证状态。回退时恢复原模板和工具目录。冻结的在途任务继续引用原快照。

```bash
python3 patch_runner.py "$STAGED_TOOL_ROOT/ais_bench/benchmark/runners/harbor_runner.py"
```

该脚本要求 Python 3.9+，针对 `HarborRunner._launch_inline` 中的异常日志。AISLogger 要求错误码枚举；使用 `RUNNER_CODES.TASK_FAILED` 并传入 `exc_info=True` 可保留原始异常。

在执行节点的本目录验证发布镜像，以下测试使用断网容器，输出最后一行应包含 `Offline install/reuse` 和 `passed`。中途出现的 `ValueError: original failure` 是异常日志测试主动触发的。若模板挂载了独立工具根，请按模板添加相同的只读挂载及 Python 模块搜索路径，再执行一次。

```bash
image_id=$(python3 -c 'import json; print(json.load(open("release.json"))["image_id"])')
docker run --rm --network none -e LITELLM_LOCAL_MODEL_COST_MAP=True \
  -v "$PWD/verify.py:/tmp/verify.py:ro" --entrypoint python "$image_id" /tmp/verify.py
```

## 平台派发配置

使用平台派发任务时，请同步更新携带 `autoeval_runtime/planning_runtime.py` 的执行 Worker。Worker 向 SSH 执行环境传送该运行时代码。对标准 DeepSWE v1.1 的内置 Mini-SWE 和显式 API Base，运行时会在调用适配器前将裸模型名转换成 `openai/<服务模型名>`，并为作业和 Agent 设置 `LITELLM_LOCAL_MODEL_COST_MAP=True`。配置快照仍保留登记的服务模型名。下一次新作业的 Harbor Job Config 应能直接看到带前缀的 `model_name`。已启动的作业继续使用其启动时的配置。

## 从源码重建与验证

在固定基础镜像已加载的 AMD64 构建机，从本目录复制 Dockerfile、offline_agent.py、patch_runner.py 到空构建目录，并将已核验的 Mini-SWE 2.4.6 / Python 3.12 Linux wheelhouse 放入其 wheels 子目录。Dockerfile 会核对清单及文件摘要。执行：

```bash
set -eu
test "$(docker inspect -f '{{.Id}}' autoeval/deepswe:offline-e968d1b-20261126)" = sha256:dd90e0520919a049e10a195f05c1abcbc4b81872e542f258e0d74a6f06113bce
docker build --network none --pull=false -t autoeval/deepswe:issue38-build "$BUILD_DIR"
docker run --rm --network none -e LITELLM_LOCAL_MODEL_COST_MAP=True \
  -v "$PWD/verify.py:/tmp/verify.py:ro" --entrypoint python \
  autoeval/deepswe:issue38-build /tmp/verify.py
```

测试由真实 Harbor 工厂构造 Agent，检查嵌套配置、供应商前缀、断网安装及复用，再捕获推理命令并验证 AISLogger 异常分支。测试不发送模型请求。裸模型名仅在 Agent 注入了 OpenAI 兼容服务地址时补 `openai/`，已有 provider 保留。安装阶段在任务用户环境检查 mini-swe-agent 的版本和可启动性；缺少 CLI 时使用镜像随附的哈希锁定 wheelhouse。
