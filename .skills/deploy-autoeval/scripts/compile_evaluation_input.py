"""Compile one imported startup recipe for a target using the authenticated platform API."""

import argparse
import json
import sys
from pathlib import Path, PurePosixPath
from urllib.parse import urlsplit

from check_evaluation_readiness import (
    CheckError,
    platform_api,
    read_pages,
    rows,
    uuid_string,
)
from evaluation_seed import SeedError, require
from startup_inputs import ADAPTOR, FORMAT, normalized, safe_json


def container_path(value):
    if not value.startswith("/") or ".." in PurePosixPath(value).parts or "\n" in value:
        raise argparse.ArgumentTypeError("需要容器内的绝对 POSIX 路径")
    return value


def compile_input(api, args):
    require(args.file.stat().st_size <= 2_000_000, "启动配置包超过 2 MB")
    kit = safe_json(args.file.read_text(encoding="utf-8"))
    require(kit.get("format") == FORMAT, "不兼容的启动配置格式")
    benchmark = "GPQA_Diamond" if args.dataset == "GPQA" else args.dataset
    recipes = [
        normalized(r) for r in kit["recipes"] if r["source"]["benchmark"] == benchmark
    ]
    if args.input_id:
        recipes = [r for r in recipes if r["id"] == args.input_id]
    require(len(recipes) == 1, "请在包内选择唯一的基准配置，多条时通过 --input-id 指定")
    recipe = recipes[0]
    route = "standard-inputs/" + recipe["id"]
    registered = api(route)["data"]
    require(
        registered.get("repository") == recipe["repository"]
        and registered.get("sha256") == recipe["content_sha256"],
        "目标启动配置与包内版本不符",
    )
    targets = rows(
        api(f"target-bindings?target_id={args.target_id}")["data"], "target-bindings"
    )
    require(
        len(targets) == 1
        and targets[0]["id"] == args.target_id
        and not targets[0]["archived"],
        "需要已注册且未归档的目标服务",
    )
    target = targets[0]
    model = uuid_string(target["model_id"])
    require(not args.model_id or model == args.model_id, "目标服务与指定模型资产不匹配")
    opts = {
        "input_policy": "repository",
        "adaptor_revision": ADAPTOR,
        "model_id": model,
        "target_id": args.target_id,
        "tool_root": args.tool_root,
        "execution": "docker",
    }
    if args.dataset in {"DeepSWE", "AutomationBench"}:
        require(
            args.task_path and not args.datasets_dir,
            "Harbor 需传入 --task-path 容器内离线任务目录",
        )
        opts["task_path"] = args.task_path
    else:
        require(
            args.datasets_dir and not args.task_path,
            "AISBench 需传入 --datasets-dir 容器数据目录",
        )
        opts["datasets_dir"] = args.datasets_dir
    if recipe["payload"]["requires_target_agent_base_url"]:
        endpoint = urlsplit(target["base_url"])
        require(
            endpoint.scheme == "https"
            and endpoint.hostname
            and not endpoint.username
            and not endpoint.password
            and not endpoint.query
            and not endpoint.fragment,
            "运行 Agent 需要目标服务的 HTTPS 地址",
        )
        opts["adjustments"] = {
            "params": {"agent_kwargs": {"base_url": target["base_url"]}}
        }
    if args.python_executable:
        opts.setdefault("adjustments", {}).setdefault("params", {})[
            "python_executable"
        ] = args.python_executable
    data = api(route + "/autocomplete", body=opts)["data"]
    preview = data["preview"]
    require(
        preview.get("input_ready") is True
        and preview.get("blocking_reasons") == []
        and preview.get("standard_config_status") == "complete",
        "编译预览未就绪：" + ", ".join(preview.get("blocking_reasons", [])),
    )
    params = preview["config"]["params"]
    if args.task_path:
        require(params.get("path") == args.task_path, "已锁定的任务目录与指定目录冲突")
    if args.python_executable:
        require(
            params.get("python_executable") == args.python_executable,
            "所选解释器与启动配置锁定值不符",
        )
    if recipe["payload"]["requires_target_agent_base_url"]:
        require(
            params.get("agent_kwargs", {}).get("base_url") == target["base_url"],
            "Agent 未绑定当前模型服务",
        )
    require(
        data["candidate"]["target_id"] == args.target_id
        and data["candidate"]["model_id"] == model
        and data["candidate"]["adaptor_revision"] == ADAPTOR
        and preview["credential_binding"]["target_id"] == args.target_id,
        "编译预览中的目标或适配器与所选版本不符",
    )
    compiled = api(route + "/compile", body=data["candidate"])["data"]
    require(
        compiled.get("input_ready") is True
        and compiled.get("blocking_reasons") == []
        and compiled.get("input_id") == recipe["id"]
        and compiled.get("model_id") == model
        and compiled["credential_binding"]["target_id"] == args.target_id
        and compiled["config"] == preview["config"]
        and compiled["runtime_config"] == preview["runtime_config"],
        "平台返回的编译结果与已确认的预览不符",
    )
    for page in read_pages(api, "planning/options"):
        for choice in rows(page["compilations"], "planning/options.compilations"):
            if choice["sha256"] == compiled["sha256"]:
                require(
                    choice.get("target_id") == args.target_id
                    and choice.get("input_ready") is True
                    and choice.get("dataset") == args.dataset
                    and choice.get("adaptor_revision") == ADAPTOR,
                    "返回的规划选项与编译输入不符",
                )
                return {
                    "dataset": args.dataset,
                    "input_id": recipe["id"],
                    "model_id": model,
                    "target_id": args.target_id,
                    "compilation_id": choice["id"],
                    "compilation_sha256": compiled["sha256"],
                }
    raise SeedError("在规划选项中未查到刚编译的 SHA，检查归档设置和 API 版本")


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--base-url", required=True)
    parser.add_argument("--ca-file")
    parser.add_argument(
        "--user", help="网关用户名。密码通过交互或 AUTOEVAL_GATEWAY_PASSWORD 获取"
    )
    parser.add_argument("--target-id", type=uuid_string, required=True)
    parser.add_argument(
        "--model-id", type=uuid_string, help="校验目标服务所绑定模型的资产 ID"
    )
    parser.add_argument("--file", type=Path, required=True)
    parser.add_argument("--input-id", type=uuid_string, help="同一基准多版本时指定")
    parser.add_argument(
        "--dataset",
        choices=("GPQA", "MMMU-Pro", "DeepSWE", "AutomationBench"),
        required=True,
    )
    parser.add_argument("--tool-root", type=container_path, required=True)
    parser.add_argument("--datasets-dir", type=container_path)
    parser.add_argument("--task-path", type=container_path)
    parser.add_argument(
        "--python-executable",
        type=container_path,
        help="目标 Harbor 工具镜像中的解释器",
    )
    args = parser.parse_args()
    print(
        json.dumps(
            compile_input(platform_api(args), args), ensure_ascii=False, indent=2
        )
    )


if __name__ == "__main__":
    try:
        main()
    except (CheckError, SeedError) as exc:
        sys.exit(str(exc))
    except (OSError, ValueError, TypeError, KeyError) as exc:
        sys.exit(f"启动配置、路径或 API 响应不兼容（{type(exc).__name__}）")
