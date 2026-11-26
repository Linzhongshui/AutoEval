"""核对原生 Pier 的 Linux x86_64 Docker 引擎与 DeepSWE v1.1 任务镜像。"""

import argparse
import json
import platform
import re
import subprocess
import sys
import tomllib
from pathlib import Path


def docker(*args):
    proc = subprocess.run(
        ["docker", *args], capture_output=True, text=True, timeout=30, check=False
    )
    if proc.returncode:
        raise ValueError(f"Docker 命令失败：{' '.join(args)}")
    return proc.stdout.strip()


def task_images(path):
    with path.open("rb") as file:
        config = tomllib.load(file)
    verifier = config["verifier"]
    if verifier.get("environment_mode") != "separate" or not verifier.get("collect"):
        raise ValueError(f"{path.parent.name} 缺少独立评分环境或补丁收集配置")
    primary = config["environment"]["docker_image"]
    grading = verifier.get("environment", {}).get("docker_image")
    if not grading:
        # Pier builds this release's independent verifier from the tests directory.
        dockerfile = (path.parent / "tests/Dockerfile").read_text(encoding="utf-8")
        bases = re.findall(r"^\s*FROM[ \t]+([^\n]+)", dockerfile, re.MULTILINE | re.IGNORECASE)
        if [base.strip() for base in bases] != [primary]:
            raise ValueError(f"{path.parent.name} 的评分镜像构建依赖已变化，请核对 tests/Dockerfile")
    return primary, grading


def check(args):
    if sys.platform != "linux" or platform.machine().lower() not in {"x86_64", "amd64"}:
        raise ValueError("请在实际运行 Pier 的 Linux x86_64 节点执行")
    engine = docker("info", "--format", "{{.OSType}}/{{.Architecture}}")
    if engine.lower() not in {"linux/x86_64", "linux/amd64"}:
        raise ValueError(f"Docker 服务端架构不符：{engine}")
    compose = docker("compose", "version", "--short")
    manifest = json.loads(args.manifest.read_bytes())
    if manifest["platform"] != "linux/amd64":
        raise ValueError("发布清单的平台不符")
    expected = manifest["archives"]["deepswe-full"]["refs"]
    if not isinstance(expected, dict) or not expected:
        raise ValueError("发布清单缺少 DeepSWE 任务镜像标签与 ID")
    if args.all:
        names = sorted(path.parent.name for path in args.tasks.glob("*/task.toml"))
        if not names or len(names) != manifest["deep_swe_task_tags"]:
            raise ValueError("本地任务数与发布清单不符")
    else:
        names = args.task
    if len(names) != len(set(names)):
        raise ValueError("重复的任务名称")
    primary_tags = set()
    checked = {}
    for name in names:
        if not re.fullmatch(r"[a-zA-Z0-9][a-zA-Z0-9._-]*", name):
            raise ValueError(f"任务名称无效：{name}")
        primary, grading = task_images(args.tasks / name / "task.toml")
        primary_tags.add(primary)
        for tag in (primary, grading or primary):
            if tag in checked:
                continue
            image_id = expected.get(tag, "")
            if not re.fullmatch(r"sha256:[0-9a-f]{64}", image_id):
                raise ValueError(f"{name} 的镜像未锁定在发布清单：{tag}")
            found = docker(
                "image", "inspect", "--format", "{{.Id}} {{.Os}}/{{.Architecture}}", "--", tag
            )
            if found != f"{image_id} linux/amd64":
                raise ValueError(f"{name} 的本地镜像 ID 或架构不符：{tag} ({found})")
            checked[tag] = image_id
    if args.all and primary_tags != set(expected):
        raise ValueError("全量任务引用的镜像与此版任务镜像清单不符")
    return {"engine": engine, "compose": compose, "tasks": len(names), "images": checked}


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--tasks", required=True, type=Path, help="DeepSWE tasks 目录")
    parser.add_argument("--manifest", required=True, type=Path, help="已核验的运行镜像清单")
    group = parser.add_mutually_exclusive_group(required=True)
    group.add_argument("--task", action="append", help="任务目录名，可重复指定")
    group.add_argument("--all", action="store_true", help="核对清单中的全部任务")
    try:
        result = check(parser.parse_args())
    except (OSError, ValueError, KeyError, TypeError, subprocess.TimeoutExpired) as exc:
        parser.exit(1, f"Pier 节点镜像检查失败：{exc}\n")
    print(json.dumps(result, indent=2))


if __name__ == "__main__":
    main()
