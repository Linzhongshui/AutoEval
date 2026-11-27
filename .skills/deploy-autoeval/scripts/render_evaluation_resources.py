"""在目标 Linux 执行节点核对本地 Docker 和只读资源，输出一个 SSH 资源的绑定。"""

import argparse
import json
import os
import re
import subprocess
import sys
from pathlib import Path
from uuid import UUID

ACCURACY = {
    "gpqa": ("gpqa", "/benchmark/ais_bench/datasets/gpqa", "gpqa_diamond.csv"),
    "mmmu-pro": ("mmmu", "/benchmark/ais_bench/datasets/mmmu_pro", "MMMU_Pro_10c.tsv"),
}
AUTOMATION_TASKS = (
    "/home/chenluwen/autoeval-automationbench-acceptance-20261116/tasks-public"
)
IMAGE_ID = re.compile(r"sha256:[0-9a-f]{64}")
PROBE = """import subprocess, sys
from pathlib import Path
for raw in sys.argv[2:]:
    path = Path(raw)
    if path.is_dir():
        next(path.iterdir())
    else:
        with path.open("rb") as stream:
            if not stream.read(1):
                raise ValueError(f"Empty resource: {path}")
subprocess.run(["git", "-C", sys.argv[1], "rev-parse", "HEAD"], check=True)
"""


def posix_path(value):
    if (
        not value.startswith("/")
        or value.startswith("//")
        or str(Path(value)) != value
        or ".." in Path(value).parts
        or value == "/"
        or "," in value
        or "\n" in value
    ):
        raise ValueError(f"需要规范的 Linux 绝对路径 {value!r}")
    return value


def docker(*args):
    return subprocess.run(
        ["docker", *args], check=True, text=True, stdout=subprocess.PIPE, timeout=60
    ).stdout.strip()


def build_binding(args):
    base = Path(posix_path(args.assets))
    selected = set(args.datasets)
    harbor = bool(selected - ACCURACY.keys())
    if len(selected) != len(args.datasets) or (
        selected & ACCURACY.keys() and len(selected) != 1
    ):
        raise ValueError(
            "GPQA 和 MMMU-Pro 各自使用单独的资源项；两项 Harbor 可共用一项"
        )
    if not IMAGE_ID.fullmatch(args.image_id) or not re.fullmatch(
        "[a-f0-9]{40}", args.revision
    ):
        raise ValueError("需要已核验的完整镜像 ID 和 Profile 的 40 位工具提交")
    if (
        docker("image", "inspect", "--format", "{{.Id}}", args.image_id)
        != args.image_id
    ):
        raise ValueError("执行镜像身份不符")
    anchor = docker(
        "container",
        "inspect",
        "--format",
        "{{.Id}} {{.Image}} {{.State.Running}}",
        args.planning_container,
    ).split()
    if (
        len(anchor) != 3
        or not re.fullmatch("[a-f0-9]{64}", anchor[0])
        or not IMAGE_ID.fullmatch(anchor[1])
        or anchor[2] != "true"
    ):
        raise ValueError("目标规划容器未运行或 Docker 身份无效")
    mounts = []
    checks = []
    template = {
        "revision": args.revision,
        "image_id": args.image_id,
        "readonly_mounts": mounts,
    }

    def mount(relative, destination, *, file=False):
        source = base / relative
        if not (source.is_file() if file else source.is_dir()) or not os.access(
            source, os.R_OK
        ):
            raise ValueError(f"未找到可读的资源 {source}")
        mounts.append({"source": str(source), "target": posix_path(destination)})
        if file:
            checks.append(destination)
        return source

    for name in sorted(selected & ACCURACY.keys()):
        directory, destination, filename = ACCURACY[name]
        if not (mount(directory, destination) / filename).is_file():
            raise ValueError(f"{directory} 缺少 {filename}")
        checks.append(f"{destination}/{filename}")
    if harbor:
        if args.harbor_network_capacity is None or args.harbor_network_capacity <= 0:
            raise ValueError("需要目标 Docker 地址池核实后的网络容量")
        helper = base / "rootless/bin/autoeval-rootless-docker-seeded"
        if not helper.is_file() or not os.access(helper, os.X_OK):
            raise ValueError(f"缺少可执行的 Rootless Docker helper {helper}")
        if not re.fullmatch(r"/(?:[A-Za-z0-9_.-]+/)*[A-Za-z0-9_.-]+", str(helper)):
            raise ValueError("helper 路径包含平台不支持的字符")
        cli = mount("cache/docker-cli", "/opt/autoeval-r13/bin/docker", file=True)
        if not os.access(cli, os.X_OK):
            raise ValueError(f"Docker 包装脚本不可执行 {cli}")
        template.update(
            private_docker=True,
            shared_trial_workdir=True,
            rootless_docker_helper=str(helper),
            environment={
                "AE_HARBOR_NETWORK_CAPACITY": str(args.harbor_network_capacity)
            },
        )
    if "automationbench" in selected:
        mount("automationbench/tasks", AUTOMATION_TASKS)
        checks.append(f"{AUTOMATION_TASKS}/_runtime")
        mount(
            "cache/automationbench-base.tar",
            "/opt/autoeval-cache/automationbench-base.tar",
            file=True,
        )
    if "deepswe" in selected:
        mount("deepswe/tasks", "/data/deep-swe/tasks")
        mount("wheelhouse", "/acceptance/deepswe-lite-wheelhouse-20261120")
        checks.extend(
            [
                "/data/deep-swe/tasks/abs-module-cache-flags/task.toml",
                "/acceptance/deepswe-lite-wheelhouse-20261120/sha256sums",
            ]
        )
        mount(
            "cache/deepswe-85f743fa1c3b.tar",
            "/opt/autoeval-cache/deepswe-85f743fa1c3b.tar",
            file=True,
        )
    options = ["run", "--rm", "--pull=never", "--network", "none"]
    if harbor:
        options += ["--user", f"{os.getuid()}:{os.getgid()}", "--env", "HOME=/tmp"]
    for binding in mounts:
        options += [
            "--mount",
            f"type=bind,src={binding['source']},dst={binding['target']},readonly",
        ]
    actual = docker(
        *options,
        "--entrypoint",
        "python3",
        args.image_id,
        "-c",
        PROBE,
        posix_path(args.tool_root),
        *checks,
    )
    if actual != args.revision:
        raise ValueError(f"镜像工具提交 {actual} 与目标 Profile {args.revision} 不符")
    return {
        str(args.resource_id): {
            "container_id": anchor[0],
            "image_id": anchor[1],
            "executors": {"harbor" if harbor else "aisbench": template},
        }
    }


def main():
    cli = argparse.ArgumentParser(description=__doc__)
    cli.add_argument(
        "datasets", nargs="+", choices=[*ACCURACY, "automationbench", "deepswe"]
    )
    cli.add_argument("--assets", required=True)
    cli.add_argument("--resource-id", type=UUID, required=True)
    cli.add_argument("--planning-container", required=True)
    cli.add_argument("--image-id", required=True, help="来自已核验发布清单或本次构建")
    cli.add_argument(
        "--revision", required=True, help="目标 Profile 中的 tool.revision"
    )
    cli.add_argument("--tool-root", default="/benchmark")
    cli.add_argument("--harbor-network-capacity", type=int)
    args = cli.parse_args()
    try:
        binding = build_binding(args)
    except (ValueError, OSError, subprocess.SubprocessError) as exc:
        cli.exit(1, f"{exc}\n")
    json.dump(binding, sys.stdout, indent=2)
    print()


if __name__ == "__main__":
    main()
