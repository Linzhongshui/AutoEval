"""对目标环境发起 SSH 预检，按明确授权提交一次测评，回读同一运行的报告与 Case 证据。"""

import argparse
import hashlib
import json
import os
import tempfile
import time
from contextlib import contextmanager
from datetime import datetime
from functools import partial
from pathlib import Path
from uuid import uuid4

from check_evaluation_readiness import (
    CheckError,
    StalePreflight,
    check,
    platform_api,
    read_pages,
    rows,
    selection_arguments,
    uuid_string,
)


@contextmanager
def state_lock(path):
    """系统锁在进程退出时释放，锁文件可保留。"""
    with Path(str(path) + ".lock").open("a+b") as handle:
        handle.seek(0)
        try:
            if os.name == "nt":
                import msvcrt

                msvcrt.locking(handle.fileno(), msvcrt.LK_NBLCK, 1)
            else:
                import fcntl

                fcntl.flock(handle, fcntl.LOCK_EX | fcntl.LOCK_NB)
        except OSError:
            raise CheckError("此验收状态正在使用，请等待使用同一状态文件的命令退出。") from None
        yield


def save(path, state):
    with tempfile.NamedTemporaryFile(
        dir=path.parent, delete=False, mode="w", encoding="utf-8"
    ) as out:
        temp = Path(out.name)
        try:
            json.dump(state, out, sort_keys=True, indent=2)
            out.flush()
            os.fsync(out.fileno())
        except BaseException:
            out.close()
            temp.unlink(missing_ok=True)
            raise
    try:
        os.replace(temp, path)
        if os.name != "nt":
            fd = os.open(path.parent, os.O_RDONLY)
            try:
                os.fsync(fd)
            finally:
                os.close(fd)
    finally:
        temp.unlink(missing_ok=True)


def wait_next(deadline, interval):
    remaining = deadline - time.monotonic()
    if remaining <= 0:
        raise CheckError("轮询已到期。请保留原状态文件，使用相同选择继续查询。")
    time.sleep(min(interval, remaining))


def data(api, route, **kwargs):
    value = api(route, **kwargs)["data"]
    if not isinstance(value, dict):
        raise CheckError("平台响应的 data 格式异常。")
    return value


def verified_evidence(api, run, args):
    snapshot = run.get("snapshot") or {}
    expected = snapshot.get("sample_count")
    configs = snapshot.get("dataset_configurations") or []
    if (
        snapshot.get("target_id") != args.target_id
        or snapshot.get("resource_id") != args.resource_id
        or snapshot.get("execution_origin") != "real"
        or type(expected) is not int
        or expected < 1
        or len(configs) != 1
        or configs[0].get("dataset") != args.dataset
        or configs[0].get("compilation_id") != args.compilation_id
        or configs[0].get("manifest_id") != args.manifest_id
    ):
        raise CheckError("冻结的运行来源、选择或样本数与验收输入不符。")
    report_id = uuid_string((run.get("report") or {}).get("id"))
    report = data(api, f"reports/{report_id}")
    if (
        report.get("id") != report_id
        or report.get("run_id") != run["id"]
        or report.get("execution_origin") != "real"
        or report.get("validity") != "complete"
        or report.get("evidence_status") != "verified"
    ):
        raise CheckError("正式报告的运行、来源、完整性或对象回读未通过。")
    sample_ids = set()
    attempt_count = 0
    first_case = None
    # 抽读一份正文，输出仅含标识和计数。
    for page in read_pages(api, f"runs/{run['id']}/case-executions"):
        for row in rows(page, "case-executions"):
            if row.get("dataset_key") != args.dataset:
                raise CheckError("Case 历史包含范围外的数据集。")
            attempt_count += 1
            if (
                row.get("state") == "succeeded"
                and row.get("evidence_available") is True
                and isinstance(row.get("sample_id"), str)
                and row["sample_id"]
            ):
                sample_ids.add(row["sample_id"])
                if first_case is None:
                    first_case = row
    if len(sample_ids) != expected or first_case is None:
        raise CheckError("有成功证据的独立样本数与运行快照不符。")
    evidence_id = uuid_string(first_case["id"])
    evidence = data(api, f"case-executions/{evidence_id}/evidence")
    if (
        not first_case.get("evidence_sha256")
        or evidence.get("original_evidence_sha256") != first_case["evidence_sha256"]
    ):
        raise CheckError("抽查的 Case 证据与历史记录的摘要不符。")
    if evidence.get("schema_version") == "unified-case.v1":
        if any(
            evidence.get(key) != first_case[key]
            for key in ("sample_id", "dataset_key", "attempt_no")
        ):
            raise CheckError("统一 Case 证据与记录的样本、数据集或尝试编号不符。")
    elif (
        evidence.get("schema_version") != "case-evidence.v1"
        or evidence.get("attempt_id") != evidence_id
    ):
        raise CheckError("抽查的 Case 证据格式或尝试 ID 不符。")
    return {
        "report_id": report_id,
        "sample_count": expected,
        "case_attempt_rows": attempt_count,
        "successful_cases_with_evidence": len(sample_ids),
        "verified_case_attempt_id": evidence_id,
    }


def monitor(api, args, state, deadline):
    run_id = uuid_string(state["run_id"])
    while True:
        run = data(api, f"evaluation-tasks/{run_id}")
        if run.get("id") != run_id:
            raise CheckError("任务详情返回了不同的运行 ID。")
        status = run.get("state")
        if run.get("execution_unresolved") or any(
            row.get("state") == "unresolved" for row in run.get("datasets", [])
        ):
            raise CheckError("执行结果待查证。请保留运行及状态文件，并查询原运行。")
        if status == "completed":
            if not (run.get("report") or {}).get("id"):
                raise CheckError("运行已完成，正式报告尚无可读取的 ID。请稍后沿用原状态查询。")
            evidence = verified_evidence(api, run, args)
            if (
                evidence["sample_count"] != state["preflight_samples"]
                or evidence["sample_count"] > state["authorization"]["max_samples"]
            ):
                raise CheckError("运行的冻结样本数超出本次验收授权。")
            state.update(evidence, status="verified")
            save(args.state_file, state)
            return
        if status in {"failed", "cancelled"}:
            state["status"] = status
            save(args.state_file, state)
            raise CheckError("运行已失败或取消。请根据原运行 ID 检查任务事件。")
        if status not in {
            "accepted",
            "queued",
            "preparing",
            "running",
            "aggregating",
            "cancelling",
        }:
            raise CheckError("平台返回未知运行状态，请根据原运行 ID 检查。")
        wait_next(deadline, args.interval)


def accept(args, api, state, selection):
    deadline = time.monotonic() + args.timeout
    if state.get("run_id"):
        monitor(api, args, state, deadline)
        return
    authorization = None
    if args.submit:
        authorization = {
            "max_samples": args.max_samples,
            "max_attempts": args.max_attempts,
            "budget_ref_sha256": hashlib.sha256(args.budget_ref.encode("utf-8")).hexdigest(),
        }
    if state.get("status") == "submission_pending":
        if not args.submit or state["authorization"] != authorization:
            raise CheckError("提交回应待查。请使用相同状态文件、授权参数和 --submit 取回原提交。")
    else:
        catalog = check(args, partial(read_pages, api))
        if not catalog["catalog_selectable"]:
            raise CheckError("；".join(catalog["blockers"]))
        pair = catalog["examples"][0]
        if state["status"] in {"preflight_blocked", "preflight_expired", "preflight_stale"}:
            state.setdefault("previous_preflights", []).append(state.pop("preflight_job_id"))
            state.update(status="created", preflight_key=str(uuid4()))
            save(args.state_file, state)
        if not state.get("preflight_job_id"):
            job = data(
                api, "planning/resources/preflight", body=selection, key=state["preflight_key"]
            )
            state["preflight_job_id"] = uuid_string(job.get("id"))
            save(args.state_file, state)
        job_id = uuid_string(state["preflight_job_id"])
        while True:
            job = data(api, f"planning/probes/{job_id}")
            if job.get("kind") != "preflight" or job.get("id") != job_id:
                raise CheckError("预检任务的 ID 或类型不符。")
            if job.get("state") not in {"pending", "running"}:
                break
            wait_next(deadline, args.interval)
        result = job.get("result") or {}
        if job.get("state") != "completed" or result.get("execution_ready") is not True:
            if job.get("state") in {"completed", "failed", "cancelled"}:
                state["status"] = "preflight_blocked"
                save(args.state_file, state)
            raise CheckError("目标环境预检未通过。请按预检 ID 查看节点、镜像、数据及工具检查结果。")
        expires = result.get("preflight_valid_until")
        if expires and datetime.fromisoformat(expires).timestamp() <= time.time():
            state["status"] = "preflight_expired"
            save(args.state_file, state)
            raise CheckError("预检已过期。请沿用原状态文件重新预检。")
        tasks = result.get("tasks") or []
        if (
            result.get("target_id") != args.target_id
            or len(tasks) != 1
            or tasks[0].get("assigned_resource_id") != args.resource_id
            or tasks[0].get("subset_scope") != args.scope
            or any(tasks[0].get(k) != v for k, v in selection["tasks"][0].items())
        ):
            raise CheckError("预检冻结的任务范围、模型或执行节点与选择不符。")
        samples = tasks[0].get("samples")
        attempts = tasks[0].get("attempts")
        if (
            not isinstance(samples, list)
            or not 1 <= len(samples) <= pair["sample_count"]
            or type(attempts) is not int
            or attempts < 1
        ):
            raise CheckError("预检回执缺少有效的冻结样本数或每样本尝试数。")
        state.update(
            status="preflight_passed",
            manifest_samples=pair["sample_count"],
            preflight_samples=len(samples),
            attempts_per_sample=attempts,
        )
        save(args.state_file, state)
        if not args.submit:
            return
        if len(samples) > args.max_samples or attempts > args.max_attempts:
            raise CheckError("预检冻结样本数或每样本工具尝试次数超过授权。")
        state.update(status="submission_pending", authorization=authorization)
        save(args.state_file, state)
    # 先持久化意图再发 POST。回应丢失时使用完全相同的请求和幂等键取回原运行。
    try:
        submitted = data(api, "evaluation-tasks", body=selection, key=state["submission_key"])
    except StalePreflight:
        state["status"] = "preflight_stale"
        save(args.state_file, state)
        raise
    state.update(run_id=uuid_string(submitted.get("run_id")), status="submitted")
    save(args.state_file, state)
    monitor(api, args, state, deadline)


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    selection_arguments(parser, require_ids=True)
    parser.add_argument(
        "--state-file", required=True, type=Path, help="持久化验收状态，重入沿用同一路径"
    )
    parser.add_argument("--submit", action="store_true", help="授权向目标模型提交记录的测评组合")
    parser.add_argument("--max-samples", type=int, help="授权的最大样本数")
    parser.add_argument("--max-attempts", type=int, help="授权的每样本工具尝试数上限")
    parser.add_argument("--budget-ref", help="外部已批准预算或目标账本引用；由目标方实施额度")
    parser.add_argument("--timeout", type=int, default=1800, help="本次轮询秒数，超时保留运行")
    parser.add_argument("--interval", type=int, default=5, help="轮询间隔秒数")
    args = parser.parse_args()
    if min(args.timeout, args.interval) <= 0:
        parser.error("超时及轮询间隔须为正整数")
    if args.submit and (
        not args.budget_ref
        or not args.budget_ref.strip()
        or (args.max_samples or 0) < 1
        or (args.max_attempts or 0) < 1
    ):
        parser.error("--submit 需要 --budget-ref、正整数 --max-samples 和 --max-attempts")
    selection = {
        "resource_kind": "customer_ssh",
        "target_id": args.target_id,
        "resource_id": args.resource_id,
        "dataset_concurrency": 1,
        "tasks": [
            {
                "task_id": "acceptance",
                "dataset": args.dataset,
                "compilation_id": args.compilation_id,
                "manifest_id": args.manifest_id,
                "concurrency": 1,
            }
        ],
    }
    identity = {"base_url": args.base_url.rstrip("/"), "scope": args.scope, "selection": selection}
    state = {}
    try:
        api = platform_api(args)
        args.state_file = args.state_file.resolve()
        with state_lock(args.state_file):
            if args.state_file.exists():
                state = json.loads(args.state_file.read_text(encoding="utf-8"))
                if not isinstance(state, dict) or state.get("identity") != identity:
                    raise CheckError("已有状态与本次网关或任务选择不一致。")
                uuid_string(state["preflight_key"])
                uuid_string(state["submission_key"])
            else:
                state = {
                    "identity": identity,
                    "status": "created",
                    "preflight_key": str(uuid4()),
                    "submission_key": str(uuid4()),
                }
                save(args.state_file, state)
            accept(args, api, state, selection)
        error = None
    except CheckError as exc:
        error = str(exc)
    except (OSError, ValueError, TypeError, KeyError, AttributeError, EOFError):
        error = "状态文件、平台响应或连接配置异常。请保留现有验收记录并核对目标。"
    summary = {
        key: state[key]
        for key in (
            "status",
            "preflight_job_id",
            "manifest_samples",
            "preflight_samples",
            "attempts_per_sample",
            "run_id",
            "report_id",
            "sample_count",
            "case_attempt_rows",
            "successful_cases_with_evidence",
            "verified_case_attempt_id",
        )
        if isinstance(state, dict) and key in state
    }
    if error:
        summary["error"] = error
    print(json.dumps(summary, ensure_ascii=False, indent=2))
    return 1 if error else 0


if __name__ == "__main__":
    raise SystemExit(main())
