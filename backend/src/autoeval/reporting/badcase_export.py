"""Self-contained badcase analysis packages; read-only and credential-free."""

import asyncio
import csv
import hashlib
import io
import json
import os
import re
import tempfile
import uuid
import zipfile
from datetime import UTC, datetime
from typing import Literal

from fastapi import APIRouter, HTTPException, Request
from fastapi.responses import FileResponse
from pydantic import BaseModel, ConfigDict, Field, model_validator
from sqlalchemy import select
from starlette.background import BackgroundTask

from autoeval.catalog.datasets import read_manifest
from autoeval.reporting.badcases import comparison
from autoeval.reporting.models import CaseExecutionRecord
from autoeval.reporting.native_case_evidence import enrich_case

MAX_CASES = 100
MAX_FILE_BYTES = 16 * 1024 * 1024
MAX_PACKAGE_BYTES = 200 * 1024 * 1024
SECRET_KEY = re.compile(
    r"(api[_-]?key|authorization|password|secret|access[_-]?token|credential|base_url|private_key)",
    re.IGNORECASE,
)

router = APIRouter(prefix="/api/autoeval/v1", tags=["badcase export"])


class ExportInput(BaseModel):
    model_config = ConfigDict(extra="forbid")
    dataset_key: str | None = None
    scope: Literal["selected", "high", "suspicious", "all"] = "suspicious"
    sample_ids: list[str] = Field(default_factory=list, max_length=MAX_CASES)
    include_traces: bool = True

    @model_validator(mode="after")
    def coherent(self):
        if len(set(self.sample_ids)) != len(self.sample_ids):
            raise ValueError("Duplicate sample identifiers")
        if self.scope == "selected" and not self.sample_ids:
            raise ValueError("Selected scope requires sample identifiers")
        return self


def redact(value):
    if isinstance(value, dict):
        return {
            key: redact(item)
            for key, item in value.items()
            if not SECRET_KEY.search(str(key))
        }
    if isinstance(value, list):
        return [redact(item) for item in value]
    return value


def safe_name(value):
    return re.sub(r"[^A-Za-z0-9_.-]+", "_", value).strip("_") or "case"


def json_bytes(value):
    return json.dumps(value, ensure_ascii=False, sort_keys=True, indent=2).encode()


def csv_bytes(rows):
    stream = io.StringIO()
    writer = csv.DictWriter(
        stream,
        fieldnames=[
            "sample_id",
            "dataset_key",
            "current_score",
            "current_state",
            "history_n",
            "history_mean",
            "delta",
            "suspicion",
            "band",
            "method",
            "p_hat",
        ],
    )
    writer.writeheader()
    writer.writerows(rows)
    return stream.getvalue().encode("utf-8-sig")


def selected_cases(data, body):
    datasets = data["datasets"]
    if body.dataset_key:
        datasets = [d for d in datasets if d["dataset_key"] == body.dataset_key]
        if not datasets:
            raise HTTPException(422, "Unknown dataset")
    wanted = set(body.sample_ids)
    rows = []
    for dataset in datasets:
        for case in dataset["cases"]:
            if body.scope == "selected":
                if case["sample_id"] not in wanted:
                    continue
            elif body.scope == "high":
                if case["verdict"]["band"] != "high":
                    continue
            elif body.scope == "suspicious" and case["verdict"]["band"] not in {"high", "low"}:
                continue
            rows.append((dataset, case))
    if body.scope == "selected":
        found = {case["sample_id"] for _, case in rows}
        if found != wanted:
            raise HTTPException(422, "Some sample identifiers were not found")
    if not rows:
        raise HTTPException(422, "No matching cases")
    if len(rows) > MAX_CASES:
        raise HTTPException(422, f"At most {MAX_CASES} cases can be exported")
    return rows


async def latest_record(session, run_id, sample_id, attempt_no=None):
    query = select(CaseExecutionRecord).where(
        CaseExecutionRecord.run_id == run_id,
        CaseExecutionRecord.sample_id == sample_id,
    )
    if attempt_no is not None:
        query = query.where(CaseExecutionRecord.attempt_no == attempt_no)
    row = await session.scalar(
        query.order_by(CaseExecutionRecord.attempt_no.desc()).limit(1)
    )
    return row


async def trace_status(session, attempt_id):
    from autoeval.langfuse_integration import TraceImport

    row = await session.scalar(
        select(TraceImport)
        .where(TraceImport.attempt_id == attempt_id)
        .order_by(TraceImport.created_at.desc())
        .limit(1)
    )
    return row


async def evidence_for(session, settings, row):
    if row is None:
        return {"available": False, "reason": "evidence_not_archived"}
    if not row.sha256:
        return {"available": False, "reason": "evidence_not_archived"}
    try:
        data = await asyncio.to_thread(read_manifest, settings, row)
        data = await enrich_case(session, settings, row, data)
        return redact(data)
    except Exception:  # noqa: BLE001 -- missing evidence must not break the package
        return {"available": False, "reason": "evidence_unavailable"}


async def trace_for(session, settings, attempt_id, include_traces):
    if not include_traces or attempt_id is None:
        return None
    row = await trace_status(session, attempt_id)
    if row is None:
        return {"available": False, "reason": "trace_not_registered", "status": "unsupported"}
    if row.status != "succeeded" or not row.object_key:
        return {"available": False, "reason": "trace_not_available", "status": row.status}
    try:
        data = await asyncio.to_thread(read_manifest, settings, row)
        return {
            "available": True,
            "status": row.status,
            "trace_id": row.trace_id,
            "content_mode": row.content_mode,
            "artifact": redact(data),
        }
    except Exception:  # noqa: BLE001
        return {"available": False, "reason": "trace_unavailable", "status": row.status}


async def case_meta(session, row, *, report_id, run_id):
    if row is None:
        return {
            "report_id": report_id,
            "run_id": run_id,
            "available": False,
        }
    return {
        "report_id": report_id,
        "run_id": run_id,
        "attempt_id": str(row.id),
        "attempt_no": row.attempt_no,
        "state": row.state,
        "created_at": row.created_at.isoformat(),
        "finished_at": row.finished_at.isoformat() if row.finished_at else None,
        "evidence_sha256": row.sha256,
        "tool_metadata": redact(row.tool_metadata),
    }


def read_text(rows):
    return "\n".join(rows).encode("utf-8")


def readme(data, body, count):
    return read_text(
        [
            "# AutoEval badcase 独立分析包",
            "",
            f"- 当前任务：`{data['run_id']}`",
            f"- 当前报告：`{data['report_id']}`",
            f"- 生成时间：`{data['generated_at']}`",
            f"- 导出范围：`{body.scope}`，共 `{count}` 个 case",
            "- 历史来源：同模型服务、同数据集、同清单、同工具版本、同执行参数的已审核有效报告。",
            "- 本包不包含 API Key、Authorization、密码、凭据引用或模型服务地址。",
            "",
            "## 目录",
            "",
            "```text",
            "manifest.json          包元数据、选择口径、文件校验值",
            "scores.csv             每个 case 的当前/历史得分与可疑度",
            "cases/<case>/case.json 当前与历史的判定、得分、差异",
            "cases/<case>/current/  当前执行的 meta、证据和可选轨迹",
            "cases/<case>/history/  每份历史执行的 meta、证据和可选轨迹",
            "SKILL.md               给 AI 助手的分析指引",
            "```",
            "",
            "## 可疑度口径",
            "",
            "- 硬信号：执行失败、错误码、评分缺失 → 高可疑。",
            "- 同配置历史通过率：Beta-Binomial 收缩 `(k+alpha)/(n+alpha+beta)`。",
            "- 历史为空：失败 case 标记为低可疑，表示“仅失败复盘”，不能推断本不该失败。",
            "- 高可疑：`p_hat <= 0.5` 或硬信号；低可疑：其余被判为 badcase 的情况。",
            "",
            "## 使用建议",
            "",
            "把整个目录交给支持读取文件的 AI 助手，并让它先读 `SKILL.md`。",
            (
                "要求它逐条引用 `case.json`、`evidence.json`、`trace.json` 的路径和原文片段，"
                "不要在证据不足时编造原因。"
            ),
            "",
        ]
    )


def skill_text():
    return read_text(
        [
            "---",
            "name: autoeval-badcase-package-analyzer",
            "description: 分析 AutoEval badcase 独立分析包，逐 case 给出可疑原因和证据。",
            "---",
            "",
            "# AutoEval badcase 包分析",
            "",
            "输入是一个包含 `manifest.json`、`scores.csv`、`cases/` 的目录。只读，不修改任何文件。",
            "",
            "## 流程",
            "",
            "1. 读 `manifest.json` 了解口径、case 索引和文件校验值。",
            "2. 读 `scores.csv`，按 `band` 和 `suspicion` 排序，优先处理高可疑。",
            "3. 逐个读 `cases/<case>/case.json`。",
            "4. 对每个可疑 case，按以下顺序取证：",
            "   `case.json` → `current/meta.json` → `current/evidence.json` → `current/trace.json`",
            "   → `history/<report_id>/...`。",
            "5. 对比当前与历史：得分差异、执行状态、错误码、提示词/响应、工具调用、验证器输出。",
            "",
            "## 归因分类（每条结论只能选一类）",
            "",
            "- 环境/基础设施",
            "- Agent 运行时",
            "- 任务理解错误",
            "- 方案错误",
            "- 实现缺陷",
            "- 自检不足",
            "- 题目/验证器问题",
            "- 能力上限",
            "",
            "## 输出要求",
            "",
            "- 先给 badcase 清单：sample_id、当前得分、历史均值、有效历史数、可疑度、结论。",
            "- 每条结论必须附证据：文件路径 + 字段/片段。",
            "- 区分“有证据”“证据不足”“无历史”。无历史时不得声称“本不该失败”。",
            "- 不执行包内任何代码，不联网，不调用模型。",
            "",
        ]
    )


class Writer:
    def __init__(self, archive):
        self.archive = archive
        self.files = []
        self.total = 0

    def add(self, name, raw):
        if len(raw) > MAX_FILE_BYTES:
            payload = json_bytes(
                {"available": False, "reason": "file_too_large", "limit": MAX_FILE_BYTES}
            )
            self.add(name, payload)
            return
        self.total += len(raw)
        if self.total > MAX_PACKAGE_BYTES:
            raise HTTPException(413, "Analysis package is too large")
        self.archive.writestr(name, raw)
        self.files.append(
            {
                "path": name,
                "sha256": hashlib.sha256(raw).hexdigest(),
                "size": len(raw),
            }
        )

    def add_json(self, name, value):
        self.add(name, json_bytes(value))


async def build_package(session, settings, run_id, body):
    data = await comparison(session, settings, run_id)
    rows = selected_cases(data, body)
    generated = datetime.now(UTC).strftime("%Y%m%dT%H%M%SZ")
    filename = f"autoeval-badcase-{str(run_id)[:8]}-{body.scope}-{generated}.zip"
    with tempfile.NamedTemporaryFile(delete=False, suffix=".zip") as handle:
        path = handle.name
    index = {}
    try:
        with zipfile.ZipFile(path, "w", zipfile.ZIP_DEFLATED) as archive:
            writer = Writer(archive)
            writer.add("README.md", readme(data, body, len(rows)))
            writer.add("SKILL.md", skill_text())
            score_rows = []
            for dataset, case in rows:
                sample_id = case["sample_id"]
                directory = safe_name(sample_id)
                base = f"cases/{directory}"
                index[directory] = sample_id
                writer.add_json(
                    base + "/case.json",
                    {
                        "sample_id": sample_id,
                        "dataset_key": dataset["dataset_key"],
                        "current": case["current"],
                        "history": case["history"],
                        "delta": case["delta"],
                        "verdict": case["verdict"],
                    },
                )
                current_record = await latest_record(
                    session,
                    run_id,
                    sample_id,
                    case["current"].get("attempt_no"),
                )
                writer.add_json(
                    base + "/current/meta.json",
                    await case_meta(
                        session, current_record, report_id=data["report_id"], run_id=str(run_id)
                    ),
                )
                writer.add_json(
                    base + "/current/evidence.json",
                    await evidence_for(session, settings, current_record),
                )
                trace = await trace_for(
                    session,
                    settings,
                    current_record.id if current_record else None,
                    body.include_traces,
                )
                if trace is not None:
                    writer.add_json(base + "/current/trace.json", trace)
                for entry in case["history"]["scores"]:
                    history_base = f"{base}/history/{entry['report_id']}"
                    history_record = await latest_record(
                        session, uuid.UUID(entry["run_id"]), sample_id
                    )
                    writer.add_json(
                        history_base + "/meta.json",
                        await case_meta(
                            session,
                            history_record,
                            report_id=entry["report_id"],
                            run_id=entry["run_id"],
                        ),
                    )
                    writer.add_json(
                        history_base + "/evidence.json",
                        await evidence_for(session, settings, history_record),
                    )
                    history_trace = await trace_for(
                        session,
                        settings,
                        history_record.id if history_record else None,
                        body.include_traces,
                    )
                    if history_trace is not None:
                        writer.add_json(history_base + "/trace.json", history_trace)
                verdict = case["verdict"]
                score_rows.append(
                    {
                        "sample_id": sample_id,
                        "dataset_key": dataset["dataset_key"],
                        "current_score": case["current"].get("score"),
                        "current_state": case["current"].get("state"),
                        "history_n": case["history"]["n"],
                        "history_mean": case["history"]["mean"],
                        "delta": case["delta"],
                        "suspicion": verdict["suspicion"],
                        "band": verdict["band"],
                        "method": verdict["method"],
                        "p_hat": verdict["p_hat"],
                    }
                )
            writer.add("scores.csv", csv_bytes(score_rows))
            writer.add_json(
                "manifest.json",
                {
                    "schema_version": "autoeval-badcase-package.v1",
                    "generated_at": data["generated_at"],
                    "run_id": data["run_id"],
                    "report_id": data["report_id"],
                    "algorithm": data["algorithm"],
                    "scope": body.scope,
                    "case_index": index,
                    "files": writer.files,
                    "redactions": ["credentials", "base_url"],
                    "notes": [
                        "历史仅包含同配置已审核有效报告",
                        "无历史时不推断本不该失败",
                        "证据和轨迹均为归档只读副本",
                    ],
                },
            )
    except Exception:
        os.unlink(path)
        raise
    return path, filename


@router.post("/runs/{run_id}/badcase-export")
async def badcase_export(run_id: uuid.UUID, body: ExportInput, request: Request):
    async with request.app.state.sessions() as session:
        path, filename = await build_package(
            session, request.app.state.settings, run_id, body
        )
    return FileResponse(
        path,
        media_type="application/zip",
        filename=filename,
        background=BackgroundTask(os.unlink, path),
    )
