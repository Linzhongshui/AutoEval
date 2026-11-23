"""Pinned AISBench performance adapter, shipped into the owned SSH container."""

import csv
import hashlib
import json
import math
import os
import re
import subprocess
import sys
import tempfile
from datetime import UTC, datetime
from pathlib import Path

REVISION = "842d0dd6b87a3a8620b6931aafa1b9089d91485f"
AGENTX_PYTHON = "/opt/venvs/agentx113/bin/python"
CORPORA = {
    "256k": "e39cd2ff3eba21d4a3664be51da743ac3d2149a1933898cafc7bfeac8147eeef",
    "full": "29b6a19e751ff5230771519aab755f80a0f43a4ba9cf96b72d3a6a437ec99276",
}


def adapter_digest():
    files = [Path(__file__), Path(__file__).with_name("performance_model.py")]
    return hashlib.sha256(
        b"".join(p.read_bytes().replace(b"\r\n", b"\n") for p in files)
    ).hexdigest()


def arguments(params, folder, *, dry_run=False):
    # The native chat model appends v1/chat/completions itself.
    url = params["url"].rstrip("/").removesuffix("/v1")
    command = [sys.executable, "-m", "ais_bench.benchmark.cli.main"]
    output = str(folder / "output")
    if params["kind"] == "agentx":
        levels = params["concurrency"]
        command += [
            "--mode",
            "agentx",
            "--url",
            url,
            "--model-name",
            params["model"],
            "--path",
            params["tokenizer_path"],
            "--batch-size",
            *map(str, levels if isinstance(levels, list) else [levels]),
            "--agentx-dataset-variant",
            params["variant"],
            "--agentx-dataset-path",
            params["corpus_path"],
            "--agentx-run-mode",
            params["run_mode"],
            "--agentx-duration",
            str(params["duration"]),
            "--agentx-python",
            AGENTX_PYTHON,
            "--work-dir",
            output,
        ]
        if params.get("trace_limit") is not None:
            command += ["--agentx-trace-limit", str(params["trace_limit"])]
        if dry_run:
            command.append("--dry-run")
        return command
    model = {
        "abbr": "autoeval",
        "model": params["model"],
        "path": params["tokenizer_path"],
        "url": url,
        "max_out_len": params["max_output_tokens"],
        "batch_size": params["concurrency"],
        "enable_ssl": url.startswith("https://"),
        "retry": 1,
    }
    config = folder / "inference.py"
    config.write_text(
        "from mmengine.config import read_base\n"
        "with read_base():\n"
        "    from ais_bench.benchmark.configs.models.vllm_api.vllm_api_stream_chat import models\n"
        "    from ais_bench.benchmark.configs.datasets.synthetic.synthetic_gen_tokenid import synthetic_datasets as datasets\n"
        "    from ais_bench.benchmark.configs.summarizers.perf.default_perf import summarizer\n"
        f"models[0].update({model!r})\n"
        "models[0]['generation_kwargs'] = {}\n"
        "from performance_model import PerformanceChat\n"
        "models[0]['type'] = PerformanceChat\n"
        f"datasets[0]['config']['RequestCount'] = {params['requests']!r}\n"
        f"datasets[0]['config']['TokenIdConfig']['RequestSize'] = {params['input_tokens']!r}\n",
        encoding="utf-8",
    )
    return command + [str(config), "--mode", "perf", "--num-warmups", "0", "--work-dir", output]


def check_environment(params):
    if not (Path(params["tokenizer_path"]) / "tokenizer_config.json").is_file():
        raise ValueError("tokenizer_missing")
    # Parse the tokenizer locally without remote code or network fallback.
    from transformers import AutoTokenizer

    AutoTokenizer.from_pretrained(
        params["tokenizer_path"], local_files_only=True, trust_remote_code=False
    )
    if params["kind"] == "inference":
        from mmengine import Config

        with tempfile.TemporaryDirectory() as directory:
            folder = Path(directory)
            arguments(params, folder)
            Config.fromfile(str(folder / "inference.py"))
    else:
        subprocess.run(
            [
                AGENTX_PYTHON,
                "-c",
                "import importlib.metadata as m; assert m.version('agentx-harness') == '1.0.13'",
            ],
            check=True,
            timeout=15,
            stdout=subprocess.DEVNULL,
            stderr=subprocess.DEVNULL,
        )
        with (Path(params["corpus_path"]) / "traces.jsonl").open("rb") as source:
            if hashlib.file_digest(source, "sha256").hexdigest() != CORPORA[params["variant"]]:
                raise ValueError("corpus_hash_mismatch")
        with tempfile.TemporaryDirectory() as directory:
            subprocess.run(
                arguments(params, Path(directory), dry_run=True),
                check=True,
                timeout=180,
                stdout=subprocess.DEVNULL,
                stderr=subprocess.DEVNULL,
                cwd=params["ais_bench_root"],
            )


def execute(params, folder, key):
    env = {**os.environ, "HF_HUB_OFFLINE": "1"}
    env["PYTHONPATH"] = os.pathsep.join(
        filter(None, [str(Path(__file__).parent), env.get("PYTHONPATH")])
    )
    env["AISBENCH_AGENTX_API_KEY" if params["kind"] == "agentx" else "AE_PERFORMANCE_KEY"] = key
    # AISBench owns its native logs. Do not forward config dumps into ordinary platform logs.
    with subprocess.Popen(
        arguments(params, folder),
        cwd=params["ais_bench_root"],
        env=env,
        stdout=subprocess.DEVNULL,
        stderr=subprocess.DEVNULL,
    ) as process:
        observation = {
            "job_id": folder.name,
            "source": "aisbench_performance",
            "process_id": process.pid,
            "stage": "tool_running",
            "start_time": datetime.now(UTC).timestamp(),
            "observed_at": datetime.now(UTC).isoformat(),
            "snapshot_kind": "live",
        }
        temporary = folder / "progress.tmp"
        temporary.write_text(json.dumps(observation))
        temporary.replace(folder / "progress.json")
        output = folder / "output"
        while True:
            try:
                status = process.wait(timeout=10)
                break
            except subprocess.TimeoutExpired:
                if next(output.glob("*/performances/*/*_summary.csv"), None) or next(
                    output.glob("*/performances/*/synthetic.csv"), None
                ):
                    observation["stage"] = "native_summary"
                elif next(output.glob("*/performances/*/execution_plan.redacted.json"), None):
                    observation["stage"] = "replay_plan_ready"
                observation["observed_at"] = datetime.now(UTC).isoformat()
                temporary.write_text(json.dumps(observation))
                temporary.replace(folder / "progress.json")
        observation.update(
            stage="collecting",
            observed_at=datetime.now(UTC).isoformat(),
            snapshot_kind="final",
            tool_exit_code=status,
        )
        temporary.write_text(json.dumps(observation))
        temporary.replace(folder / "progress.json")
    return {"tool_exit_code": status}


def result_files(output, kind):
    paths = []
    for path in sorted(output.rglob("*")):
        if (
            not path.is_file()
            or path.is_symlink()
            or not path.resolve().is_relative_to(output.resolve())
        ):
            continue
        rel = path.relative_to(output)
        if "performances" not in rel.parts:
            continue
        if kind == "agentx":
            if "agentx_raw" not in rel.parts and path.name not in {
                "manifest.json",
                "execution_plan.redacted.json",
                "agentx_summary.csv",
                "agentx_summary.json",
            }:
                continue
        elif path.name not in {"synthetic.csv", "synthetic.json"}:
            continue
        paths.append(rel.as_posix())
    return paths


def metric_value(raw, default_unit):
    if type(raw) in (int, float):
        return (raw, default_unit) if math.isfinite(raw) else None
    if not isinstance(raw, str) or not raw.strip():
        return None
    parts = raw.strip().split(maxsplit=1)
    try:
        value = float(parts[0])
    except ValueError:
        return None
    return (value, parts[1] if len(parts) == 2 else default_unit) if math.isfinite(value) else None


def summarize(output, kind, paths):
    names = {
        Path(path).name: output / path for path in paths if "agentx_raw" not in Path(path).parts
    }
    result = {"parse_status": "missing", "metrics": [], "csv_preview": []}
    try:
        if len(names) != sum("agentx_raw" not in Path(p).parts for p in paths):
            raise ValueError("Ambiguous native results")
        if kind == "agentx":
            verdict = json.loads(names["manifest.json"].read_bytes())["result"]
            result.update(
                {
                    k: verdict.get(k)
                    for k in (
                        "status",
                        "parse_status",
                        "data_status",
                        "benchmark_valid",
                        "comparison_scope",
                        "invalid_reasons",
                    )
                }
            )
            values = json.loads(names["agentx_summary.json"].read_bytes())
            for name, metric in values.items():
                if not isinstance(metric, dict):
                    continue
                for stat in ("avg", "min", "max", "p50", "p75", "p90", "p99"):
                    value = metric.get(stat)
                    if type(value) in (float, int) and math.isfinite(value):
                        result["metrics"].append([name, stat, value, metric.get("unit") or ""])
            csv_path = names["agentx_summary.csv"]
        else:
            values = json.loads(names["synthetic.json"].read_bytes())
            for name, stages in values.items():
                if not isinstance(stages, dict):
                    continue
                for stage, value in stages.items():
                    unit = {"Request Throughput": "req/s", "Benchmark Duration": "ms"}.get(name, "")
                    if "Token Throughput" in name:
                        unit = "token/s"
                    elif name in {"Total Input Tokens", "Total Generated Tokens"}:
                        unit = "token"
                    measurement = metric_value(value, unit)
                    if measurement is not None:
                        result["metrics"].append([name, stage, *measurement])
            result["successful_requests"] = values["Success Requests"]["total"]
            result["total_requests"] = values["Total Requests"]["total"]
            csv_path = names["synthetic.csv"]
            result["parse_status"] = "success"
        with csv_path.open(encoding="utf-8-sig", newline="") as source:
            from itertools import islice

            preview = list(islice(csv.reader(source), 51))
        if len(preview) < 2 or not result["metrics"]:
            raise ValueError("Missing native metrics")
        if kind == "inference":
            units = {
                "E2EL": "ms",
                "TTFT": "ms",
                "TPOT": "ms",
                "ITL": "ms",
                "InputTokens": "token",
                "OutputTokens": "token",
                "OutputTokenThroughput": "token/s",
                "PrefillTokenThroughput": "token/s",
            }
            for fields in preview[1:]:
                row = dict(zip(preview[0], fields, strict=True))
                name = row["Performance Parameters"]
                for stat in ("Average", "Min", "Max", "Median", "P75", "P90", "P99"):
                    if row.get(stat) and name in units:
                        measurement = metric_value(row[stat], units[name])
                        if measurement is not None:
                            result["metrics"].append(
                                [name, row["Stage"] + " / " + stat, *measurement]
                            )
        result["csv_preview"] = preview
        result["csv_path"] = csv_path.relative_to(output).as_posix()
    except (AttributeError, KeyError, TypeError, ValueError, OSError, csv.Error):
        if result.get("parse_status") in {None, "success", "missing"}:
            result["parse_status"] = "invalid" if paths else "missing"
        result["metrics"] = []
        result["csv_preview"] = []
    return result


def parse_outputs(output, kind, paths):
    if kind != "agentx":
        return summarize(output, kind, paths)
    grouped = {}
    for path in paths:
        match = re.search(r"(?:^|/)performances/agentx_(?:256k|full)_batchsize_(\d+)/", path)
        if match:
            grouped.setdefault(int(match[1]), []).append(path)
    levels = []
    for concurrency, files in grouped.items():
        level = summarize(output, kind, files)
        plan = any(Path(p).name == "execution_plan.redacted.json" for p in files)
        raw = any("agentx_raw" in Path(p).parts for p in files)
        level["missing_artifacts"] = [
            name
            for name, present in (("execution_plan.redacted.json", plan), ("agentx_raw", raw))
            if not present
        ]
        levels.append({"concurrency": concurrency, **level})
    return {"levels": levels}


if __name__ == "__main__":
    output = Path(sys.argv[1])
    kind = sys.argv[2]
    paths = result_files(output, kind)
    print(json.dumps({"files": paths, **parse_outputs(output, kind, paths)}, allow_nan=False))
