"""Validation and compilation for versioned standard inputs."""

import copy
import hashlib
import json

from autoeval.catalog.adaptor_versions import separate_runtime

ADAPTOR_REVISION = "1fb877ace4a087cb805e9a3d5878dcce6349bc35"
BENCHMARKS = {
    "GPQA_Diamond": ("GPQA", "diamond", "llm_accuracy"),
    "MMMU-Pro": ("MMMU-Pro", "options10", "llm_accuracy"),
    "DeepSWE": ("DeepSWE", "v1.1", "harbor_agent"),
    "AutomationBench": ("AutomationBench", "v1.0.6", "harbor_agent"),
}
FILES = {"standard_config.json", "benchmark_config.json", "baseline.json"}
COMMON = {
    "abbr",
    "work_dir",
    "ais_bench_root",
    "python_executable",
    "timeout",
    "debug",
    "reuse",
    "max_num_workers",
    "execution",
    "datasets_dir",
    "container_name",
    "docker_image",
    "env_isolation",
    "monitor_port",
    "purge_exception_cases",
    "extra_cli_args",
    "base_image",
    "mounts",
    "case_images",
    "benchmark_version",
    "benchmark_repo",
    "benchmark_ref",
    "keep_container",
}
ACCURACY = {
    "model_type",
    "datasets",
    "dataset_test_range",
    "model_overrides",
    "num_prompts",
    "max_workers_per_gpu",
    "dump_eval_details",
    "dump_extract_rate",
    "merge_ds",
    "path",
    "model",
    "stream",
    "request_rate",
    "use_timestamp",
    "retry",
    "api_key",
    "host_ip",
    "host_port",
    "url",
    "max_out_len",
    "batch_size",
    "trust_remote_code",
    "generation_kwargs",
}
AGENT = {
    "dataset_abbr",
    "model_overrides",
    "agent_name",
    "agent_import_path",
    "model_names",
    "api_base",
    "api_key",
    "llm_kwargs",
    "model_info",
    "agent_kwargs",
    "agent_env",
    "deps_path",
    "n_concurrent",
    "concurrency_group",
    "skills",
    "mcp_servers",
    "resume_trajectory",
    "load_trajectory",
    "extra_allowed_hosts",
    "include_logs",
    "exclude_logs",
    "override_timeout_sec",
    "override_setup_timeout_sec",
    "max_timeout_sec",
    "path",
    "dataset_name_version",
    "n_attempts",
    "n_concurrent_trials",
    "install_only",
    "metrics",
    "artifacts",
    "extra_instruction_paths",
    "environment_type",
    "environment_force_build",
    "environment_delete",
    "environment_env",
    "environment_kwargs",
    "extra_docker_compose",
    "override_cpus",
    "override_memory_mb",
    "override_storage_mb",
    "override_gpus",
    "timeout_multiplier",
    "agent_timeout_multiplier",
    "verifier_timeout_multiplier",
    "agent_setup_timeout_multiplier",
    "environment_build_timeout_multiplier",
    "max_retries",
    "retry_include_exceptions",
    "retry_exclude_exceptions",
    "task_names",
    "exclude_task_names",
    "n_tasks",
    "disable_verification",
    "verifier_env",
    "verifier_import_path",
    "verifier_kwargs",
    "env_file",
    "registry_url",
    "registry_path",
    "quiet",
    "yes",
}
ENVIRONMENT = {
    "work_dir",
    "execution",
    "container_name",
    "api_key",
    "api_base",
    "url",
    "host_ip",
    "host_port",
    "model",
    "model_names",
    "abbr",
}


def digest(value):
    return hashlib.sha256(
        json.dumps(
            value, sort_keys=True, ensure_ascii=False, separators=(",", ":"), allow_nan=False
        ).encode()
    ).hexdigest()


def safe_json(raw):
    def pairs(items):
        result = {}
        for key, value in items:
            if key in result:
                raise ValueError("Duplicate JSON key")
            result[key] = value
        return result

    def constant(value):
        raise ValueError("Non-finite number")

    return json.loads(raw, object_pairs_hook=pairs, parse_constant=constant)


def reject_secrets(value):
    if isinstance(value, dict):
        for key, item in value.items():
            if (
                any(
                    word in key.lower()
                    for word in ("api_key", "password", "secret", "authorization", "access_token")
                )
                and item
            ):
                raise ValueError("Plaintext credentials are forbidden; use a target reference")
            reject_secrets(item)
    elif isinstance(value, list):
        for item in value:
            reject_secrets(item)


def validate_config(value):
    if (
        set(value) - {"tool", "subcommand", "params"}
        or value.get("tool") != "ais_bench"
        or value.get("subcommand") not in {"llm_accuracy", "harbor_agent"}
        or not isinstance(value.get("params"), dict)
    ):
        raise ValueError("Expected ais_bench tool/subcommand/params")
    allowed = COMMON | (ACCURACY if value["subcommand"] == "llm_accuracy" else AGENT)
    unknown = set(value["params"]) - allowed
    if unknown:
        raise ValueError("Unknown adaptor parameters: " + ", ".join(sorted(unknown)))
    if value["params"].get("model_overrides"):
        raise ValueError("model_overrides is not allowed: use explicit model fields")
    if value["params"].get("extra_cli_args"):
        raise ValueError("extra_cli_args can bypass standard constraints")
    params = value["params"]
    dictionaries = {
        "generation_kwargs",
        "llm_kwargs",
        "model_info",
        "agent_kwargs",
        "agent_env",
        "environment_env",
        "environment_kwargs",
        "verifier_kwargs",
        "model_overrides",
    }
    lists = {
        "datasets",
        "model_names",
        "skills",
        "mcp_servers",
        "extra_allowed_hosts",
        "include_logs",
        "exclude_logs",
        "artifacts",
        "extra_instruction_paths",
        "extra_docker_compose",
        "retry_include_exceptions",
        "retry_exclude_exceptions",
        "task_names",
        "exclude_task_names",
        "verifier_env",
        "mounts",
        "extra_cli_args",
    }
    integers = {
        "max_out_len",
        "batch_size",
        "retry",
        "host_port",
        "num_prompts",
        "max_workers_per_gpu",
        "max_num_workers",
        "monitor_port",
        "n_attempts",
        "n_concurrent_trials",
        "override_memory_mb",
        "override_storage_mb",
        "override_gpus",
        "max_retries",
        "n_tasks",
    }
    booleans = {
        "stream",
        "use_timestamp",
        "trust_remote_code",
        "debug",
        "purge_exception_cases",
        "keep_container",
        "dump_eval_details",
        "dump_extract_rate",
        "merge_ds",
        "resume_trajectory",
        "install_only",
        "environment_force_build",
        "environment_delete",
        "disable_verification",
        "quiet",
        "yes",
    }
    numbers = {
        "timeout",
        "request_rate",
        "override_timeout_sec",
        "override_setup_timeout_sec",
        "max_timeout_sec",
        "override_cpus",
        "timeout_multiplier",
        "agent_timeout_multiplier",
        "verifier_timeout_multiplier",
        "agent_setup_timeout_multiplier",
        "environment_build_timeout_multiplier",
    }
    integers |= {"n_concurrent"}
    for key, item in params.items():
        if item is None:
            raise ValueError("Null parameters must be omitted: " + key)
        expected = (
            dict
            if key in dictionaries
            else list
            if key in lists
            else int
            if key in integers
            else bool
            if key in booleans
            else (int, float)
            if key in numbers
            else str
        )
        if key in {"metrics"}:
            continue
        if not isinstance(item, expected) or (key in integers | numbers and isinstance(item, bool)):
            raise ValueError("Invalid adaptor parameter type: " + key)
        if key in lists - {"skills", "mcp_servers"} and any(not isinstance(v, str) for v in item):
            raise ValueError("Expected string array: " + key)
        if (
            key
            in {
                "max_out_len",
                "batch_size",
                "num_prompts",
                "max_workers_per_gpu",
                "max_num_workers",
                "n_attempts",
                "n_concurrent",
                "n_concurrent_trials",
            }
            and item < 1
        ):
            raise ValueError("Positive value required: " + key)
    if "datasets" in params and not params["datasets"]:
        raise ValueError("datasets cannot be empty")
    reject_secrets(value)
    return value


def leaves(value, prefix=""):
    result = {}
    for key, item in value.items():
        path = f"{prefix}.{key}" if prefix else key
        if isinstance(item, dict) and item:
            result.update(leaves(item, path))
        else:
            result[path] = item
    return result


def merge(base, overlay):
    result = copy.deepcopy(base)
    for key, value in overlay.items():
        result[key] = (
            merge(result[key], value)
            if isinstance(value, dict) and isinstance(result.get(key), dict)
            else copy.deepcopy(value)
        )
    return result


def discover(bundle):
    groups = {}
    for path, raw in bundle.files.items():
        model, benchmark, filename = path.split("/")
        groups.setdefault((model, benchmark), {})[filename] = {
            "path": path,
            "raw": raw,
            "sha256": hashlib.sha256(raw.encode()).hexdigest(),
        }
    result = []
    for (model, benchmark), files in sorted(groups.items()):
        if "standard_config.json" not in files:
            raise ValueError(f"Missing standard_config.json: {model}/{benchmark}")
        standard = validate_config(safe_json(files["standard_config.json"]["raw"]))
        if standard["subcommand"] != BENCHMARKS[benchmark][2]:
            raise ValueError("Benchmark/subcommand mismatch")
        if "benchmark_config.json" in files:
            startup = validate_config(safe_json(files["benchmark_config.json"]["raw"]))
            if startup["subcommand"] != standard["subcommand"]:
                raise ValueError("Startup/standard subcommand mismatch")
        result.append(
            {
                "source_model": model,
                "benchmark": benchmark,
                "files": files,
                "mapping": dict(zip(("dataset", "variant", "subcommand"), BENCHMARKS[benchmark])),
                "locked_fields": leaves(standard),
                "startup_missing": "benchmark_config.json" not in files,
            }
        )
    return result


def compile_config(entry, body, target=None):
    standard = safe_json(entry["files"]["standard_config.json"]["raw"])
    base = {"tool": "ais_bench", "subcommand": standard["subcommand"], "params": {}}
    origins = {}
    changes = []

    def apply(overlay, source):
        nonlocal base
        old = leaves(base)
        base = merge(base, overlay)
        for key, value in leaves(overlay).items():
            if key in old and old[key] != value:
                changes.append({"field": key, "before": old[key], "after": value, "source": source})
            origins[key] = source

    if "benchmark_config.json" in entry["files"]:
        apply(
            safe_json(entry["files"]["benchmark_config.json"]["raw"]), "standard-repository-startup"
        )
    for overlay, name in [
        (
            body.template if body.input_policy == "legacy" else {},
            "template:" + body.template_version,
        ),
        (body.adjustments, "user-adjustment"),
    ]:
        if overlay:
            if set(overlay) - {"tool", "subcommand", "params"}:
                raise ValueError("Only tool/subcommand/params accepted")
            if set(overlay.get("params", {})) & ENVIRONMENT:
                raise ValueError("Environment and target fields must use controlled inputs")
            apply(overlay, name)
    validate_config(base)
    apply(standard, "standard-lock")
    validate_config(base)
    blockers = []
    if entry["startup_missing"] and (
        body.input_policy == "repository" or not body.template.get("params")
    ):
        blockers.append("startup_template_required")
    if body.model_id is None:
        blockers.append("model_mapping_missing")
    if not target:
        blockers.append("target_missing")
    identity_hash = digest({"entry": entry, "body": body.model_dump(mode="json")})[:32]
    environment = {
        "execution": body.execution,
        "work_dir": "/work/autoeval/inputs/" + identity_hash,
        "container_name": "autoeval-input-" + identity_hash,
    }
    if target:
        environment["abbr"] = str(body.model_id)
        if standard["subcommand"] == "llm_accuracy":
            environment.update(model=target.remote_model, url=target.base_url)
        else:
            environment.update(model_names=[target.remote_model], api_base=target.base_url)
    if body.datasets_dir:
        environment["datasets_dir"] = body.datasets_dir
    if body.tool_root:
        environment["ais_bench_root"] = body.tool_root
    else:
        blockers.append("tool_root_missing")
    if not body.datasets_dir and standard["subcommand"] == "llm_accuracy":
        blockers.append("datasets_dir_missing")
    if body.task_path:
        environment["path"] = body.task_path
    for key, value in list(environment.items()):
        if key in standard["params"] and standard["params"][key] != value:
            blockers.append("environment_conflicts_with_standard:" + key)
            del environment[key]
    apply({"params": environment}, "platform-environment")
    params = base["params"]
    required = ["model_type", "datasets"] if standard["subcommand"] == "llm_accuracy" else []
    for key in required:
        if not params.get(key):
            blockers.append("required_parameter_missing:" + key)
    if standard["subcommand"] == "harbor_agent" and not (
        params.get("path") or params.get("dataset_name_version")
    ):
        blockers.append("task_path_missing")
    if standard["subcommand"] == "harbor_agent" and not (
        params.get("agent_name") or params.get("agent_import_path")
    ):
        blockers.append("agent_missing")
    validate_config(base)
    final = leaves(base)
    for key, value in leaves(standard).items():
        if final.get(key) != value:
            blockers.append("standard_lock_conflict:" + key)
    tool_config, runtime_config, cli_flags = separate_runtime(base, body.adaptor_revision)
    result = {
        "input_policy": body.input_policy,
        "config": tool_config,
        "runtime_config": runtime_config,
        "template_version": body.template_version,
        "template_sha256": digest(body.template),
        "field_sources": origins,
        "overrides": changes,
        "locked_fields": leaves(standard),
        "blocking_reasons": sorted(set(blockers)),
        "input_ready": not blockers,
        "execution_enabled": False,
        "approval_status": "not_required",
        "adaptor_revision": body.adaptor_revision,
        "cli_flags": cli_flags,
        "credential_binding": {"target_id": str(target.id), "injection": "runtime-only"}
        if target
        else None,
    }
    result["sha256"] = digest(result)
    return result
