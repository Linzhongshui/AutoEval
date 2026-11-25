"""从目标平台读取任务规划选项，核对指定测评组合。仅使用 Python 标准库。"""

import argparse
import base64
import getpass
import json
import os
import ssl
import sys
from functools import partial
from http.client import HTTPException
from urllib.error import HTTPError, URLError
from urllib.parse import urlsplit
from urllib.request import HTTPRedirectHandler, HTTPSHandler, Request, build_opener
from uuid import UUID


class CheckError(Exception):
    pass


class StalePreflight(CheckError):
    pass


class NoRedirect(HTTPRedirectHandler):
    def redirect_request(self, req, fp, code, msg, headers, newurl):
        return None


def uuid_string(value):
    try:
        return str(UUID(value))
    except (ValueError, TypeError, AttributeError):
        raise ValueError("标识须为 UUID") from None


def request_json(opener, base, headers, route, *, body=None, key=None):
    request_headers = headers.copy()
    payload = None
    if body is not None:
        payload = json.dumps(body).encode("utf-8")
        request_headers["Content-Type"] = "application/json"
    if key is not None:
        request_headers["Idempotency-Key"] = key
    request = Request(f"{base}/api/autoeval/v1/{route}", headers=request_headers, data=payload)
    name = route.split("?", 1)[0]
    try:
        with opener.open(request, timeout=30) as response:
            result = json.load(response)
    except HTTPError as exc:
        if exc.code == 409 and name == "evaluation-tasks":
            try:
                detail = json.loads(exc.read(8192)).get("detail")
            except (ValueError, AttributeError, OSError, HTTPException):
                detail = None
            if detail in (
                "Fresh resource preflight required",
                "SSH execution templates changed; run preflight again",
            ):
                raise StalePreflight(
                    "平台已拒绝过期或模板变更后的预检，请沿用原状态文件重新预检。"
                ) from None
        raise CheckError(f"{name} 返回 HTTP {exc.code}，请核对网关、认证及服务端事件。") from None
    except (URLError, OSError, HTTPException):
        raise CheckError(f"{name} 连接失败，请核对目标地址、网络和 TLS 证书。") from None
    except ValueError:
        raise CheckError(f"{name} 未返回有效的 JSON，请核对网关的 /api/ 转发。") from None
    if not isinstance(result, dict) or "data" not in result:
        raise CheckError(f"{name} 响应缺少 data，请核对平台版本。")
    return result


def read_pages(api, route):
    offset = 0
    while True:
        page = api(f"{route}?offset={offset}&limit=100")
        if not isinstance(page, dict) or "data" not in page or "next_offset" not in page:
            raise CheckError(f"{route} 分页响应缺少 data 或 next_offset，请核对发布版本。")
        yield page["data"]
        next_offset = page["next_offset"]
        if next_offset is None:
            return
        if type(next_offset) is not int or next_offset <= offset:
            raise CheckError(f"{route} 返回无效的下一页偏移量。")
        offset = next_offset


def rows(value, route):
    if not isinstance(value, list) or any(not isinstance(row, dict) for row in value):
        raise CheckError(f"{route} 的选项列表格式异常，请核对平台 API 版本。")
    for row in value:
        try:
            uuid_string(row.get("id"))
        except ValueError:
            raise CheckError(f"{route} 的选项缺少有效 UUID。") from None
    return value


def allows(runtime, key, selected):
    allowed = runtime.get(key)
    return allowed is None or (isinstance(allowed, list) and selected in allowed)


def check(args, pages):
    blockers = []
    for route, selected, name in (
        ("target-bindings", args.target_id, "模型服务"),
        ("ssh-resources", args.resource_id, "SSH 执行资源"),
    ):
        ids = {
            row["id"]
            for page in pages(route)
            for row in rows(page, route)
            if not row.get("archived", False)
        }
        if not ids:
            blockers.append(f"{name}列表为空，请在目标环境登记{name}。")
        elif selected not in ids:
            blockers.append(f"目标环境的{name}列表中没有指定 ID，请核对目标环境登记值。")

    compilations, manifests = {}, {}
    for page in pages("planning/options"):
        if not isinstance(page, dict):
            raise CheckError("planning/options 响应格式异常。")
        for kind, index in (("compilations", compilations), ("manifests", manifests)):
            for row in rows(page.get(kind), f"planning/options.{kind}"):
                if row.get("dataset") == args.dataset:
                    index[row["id"]] = row

    selected_manifests = [
        m
        for m in manifests.values()
        if m.get("scope") == args.scope
        and (not args.manifest_id or m["id"] == args.manifest_id)
        and type(m.get("sample_count")) is int
        and m["sample_count"] > 0
    ]
    if not manifests:
        blockers.append("规划选项缺少该数据集的可见清单，请登记完整清单并绑定工具和评分配置。")
    elif not selected_manifests:
        blockers.append("没有匹配所选范围、清单 ID 且样本数大于零的清单。")

    bound = [
        c
        for c in compilations.values()
        if c.get("target_id") == args.target_id
        and (not args.compilation_id or c["id"] == args.compilation_id)
    ]
    ready = [c for c in bound if c.get("input_ready") is True]
    compatible = []
    for compilation in ready:
        runtime = compilation.get("runtime_config")
        if not isinstance(runtime, dict):
            raise CheckError("编译配置的 runtime_config 格式异常。")
        if allows(runtime, "resource_ids", args.resource_id):
            compatible.append(compilation)
    if not compilations:
        blockers.append("规划选项缺少该数据集的编译配置，请同步标准输入并在目标环境编译。")
    elif not bound:
        blockers.append("没有绑定到所选模型服务的匹配编译配置，请核对目标绑定和编译 ID。")
    elif not ready:
        blockers.append("匹配的编译配置尚未就绪，请查看标准输入的编译诊断。")
    elif not compatible:
        blockers.append("编译配置未允许所选 SSH 资源，请核对目标环境的 resource_ids。")

    match_count = 0
    examples = []
    for compilation in compatible:
        for manifest in selected_manifests:
            if allows(compilation["runtime_config"], "manifest_ids", manifest["id"]):
                match_count += 1
                if len(examples) < 5:
                    examples.append(
                        {
                            "compilation_id": compilation["id"],
                            "manifest_id": manifest["id"],
                            "sample_count": manifest["sample_count"],
                        }
                    )
    if selected_manifests and compatible and not match_count:
        blockers.append("编译配置未允许所选清单，请核对目标环境的 manifest_ids。")
    return {
        "catalog_selectable": not blockers,
        "dataset": args.dataset,
        "scope": args.scope,
        "target_id": args.target_id,
        "resource_id": args.resource_id,
        "dataset_compilations": len(compilations),
        "dataset_manifests": len(manifests),
        "matching_pairs": match_count,
        "examples": examples,
        "blockers": blockers,
        "verification_scope": "仅核对规划目录。SSH、模板、镜像、数据挂载及对象回读须经目标预检；"
        "真实测评须另行提交并按运行 ID 核对报告。",
    }


def selection_arguments(parser, require_ids=False):
    parser.add_argument(
        "--base-url", required=True, help="平台或网关根地址，支持 HTTPS 和本机 HTTP"
    )
    parser.add_argument(
        "--target-id", required=True, type=uuid_string, help="目标环境模型服务绑定 ID"
    )
    parser.add_argument(
        "--resource-id", required=True, type=uuid_string, help="目标环境 SSH 资源 ID"
    )
    parser.add_argument(
        "--dataset", required=True, choices=("GPQA", "MMMU-Pro", "DeepSWE", "AutomationBench")
    )
    parser.add_argument("--scope", required=True, choices=("lite", "full"))
    parser.add_argument(
        "--compilation-id", required=require_ids, type=uuid_string, help="只检查指定编译配置"
    )
    parser.add_argument(
        "--manifest-id", required=require_ids, type=uuid_string, help="只检查指定清单"
    )
    parser.add_argument("--ca-file", help="内网网关的受信 CA 证书文件（PEM）")
    parser.add_argument(
        "--user", help="网关 Basic 用户名，密码由交互输入或 AUTOEVAL_GATEWAY_PASSWORD 提供"
    )


def platform_api(args):
    base = args.base_url.rstrip("/")
    parsed = urlsplit(base)
    if (
        not parsed.hostname
        or parsed.username is not None
        or parsed.password is not None
        or parsed.query
        or parsed.fragment
        or parsed.scheme not in {"https", "http"}
    ):
        raise CheckError("请提供无凭据、查询参数和片段的平台根地址。")
    if parsed.scheme == "http" and parsed.hostname not in {"localhost", "127.0.0.1", "::1"}:
        raise CheckError("远程网关请使用 HTTPS，本机开发可使用回环 HTTP 地址。")
    context = ssl.create_default_context(cafile=args.ca_file)
    headers = {"Accept": "application/json"}
    if args.user:
        password = os.environ.get("AUTOEVAL_GATEWAY_PASSWORD")
        if password is None:
            if not sys.stdin.isatty():
                raise CheckError(
                    "非交互运行请通过受保护环境变量 AUTOEVAL_GATEWAY_PASSWORD 提供网关密码。"
                )
            password = getpass.getpass("网关密码：")
        token = base64.b64encode(f"{args.user}:{password}".encode()).decode("ascii")
        headers["Authorization"] = f"Basic {token}"
    opener = build_opener(NoRedirect(), HTTPSHandler(context=context))
    return partial(request_json, opener, base, headers)


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    selection_arguments(parser)
    args = parser.parse_args()
    try:
        api = platform_api(args)
        result = check(args, partial(read_pages, api))
    except CheckError as exc:
        result = {"catalog_selectable": None, "error": str(exc)}
    except (OSError, ValueError, EOFError):
        result = {"catalog_selectable": None, "error": "请核对网关地址、CA 文件和凭据读取环境。"}
    print(json.dumps(result, ensure_ascii=False, indent=2))
    if result["catalog_selectable"] is None:
        return 2
    return 0 if result["catalog_selectable"] else 1


if __name__ == "__main__":
    raise SystemExit(main())
