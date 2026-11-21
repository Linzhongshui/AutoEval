"""Exercise SSH pool navigation with mocked API responses and no remote writes."""

import os

import pytest
from playwright.sync_api import expect, sync_playwright


@pytest.mark.skipif(not os.getenv("AE_BROWSER_URL"), reason="Explicit local browser URL required")
def test_add_ssh_node_preserves_planning_form():
    nodes = []
    checks = []
    submissions = []

    def mock(route):
        request = route.request
        path = request.url.split("/api/autoeval/v1", 1)[1].split("?", 1)[0]
        data = []
        if path == "/target-bindings":
            data = [
                {"id": "model", "remote_model": "Test model", "base_url": "https://example.invalid"}
            ]
        elif path == "/planning/options":
            data = {
                "compilations": [
                    {
                        "id": "config",
                        "sha256": "a" * 64,
                        "target_id": "model",
                        "dataset": "GPQA",
                        "input_ready": True,
                        "config": {"subcommand": "llm_accuracy", "params": {}},
                    },
                    {
                        "id": "duplicate",
                        "sha256": "b" * 64,
                        "target_id": "model",
                        "dataset": "GPQA",
                        "input_ready": True,
                        "config": {"subcommand": "llm_accuracy", "params": {}},
                    },
                    {
                        "id": "alternative",
                        "sha256": "c" * 64,
                        "target_id": "model",
                        "dataset": "GPQA",
                        "input_ready": True,
                        "config": {"subcommand": "llm_accuracy", "params": {"batch_size": 2}},
                    },
                ],
                "manifests": [
                    {"id": "full", "dataset": "GPQA", "scope": "full", "sample_count": 2}
                ],
                "curves": [],
            }
        elif path == "/ssh-resources/credentials":
            data = {"credential_ref": "test-reference"}
        elif path == "/ssh-resources":
            if request.method == "POST":
                data = {"id": "node", **request.post_data_json}
                nodes.append(data)
            else:
                data = nodes
        elif path == "/ssh-resources/node/validate":
            checks.append(path)
            data = {"evaluation_ready": False}
        elif path == "/planning/active-probe":
            data = None
        elif path == "/planning/resources/preflight":
            data = {
                "id": "preflight",
                "state": "completed",
                "result": {
                    "execution_ready": True,
                    "supported_datasets": ["GPQA"],
                    "dataset_checks": [
                        {
                            "task_id": "GPQA",
                            "dataset": "GPQA",
                            "assigned_resource_id": "node",
                            "tool_revision": "a" * 40,
                            "blocking_reasons": [],
                        }
                    ],
                },
            }
        elif path == "/evaluation-tasks" and request.method == "POST":
            submissions.append(request.post_data_json)
            data = {"run_id": "run"}
        route.fulfill(json={"data": data, "next_offset": None})

    with sync_playwright() as playwright:
        chrome = os.getenv("AE_CHROME_PATH")
        browser = playwright.chromium.launch(**({"executable_path": chrome} if chrome else {}))
        page = browser.new_page(viewport={"width": 1440, "height": 1000})
        page.route("**/api/autoeval/v1/**", mock)
        page.goto(os.environ["AE_BROWSER_URL"])
        page.get_by_label("规划模型服务", exact=True).click()
        page.get_by_text("Test model", exact=True).click()
        page.get_by_label("启用 GPQA").check()
        config = page.get_by_label("GPQA 执行配置")
        expect(config).to_have_value("config")
        expect(config.locator("option")).to_have_count(3)
        expect(config.locator("option:checked")).to_have_text("GPQA · 精度测评 · 方案 1")
        expect(page.get_by_label("GPQA 样本范围")).to_have_value("full")

        page.get_by_role("button", name="添加 SSH 节点").click()
        for label, value in {
            "节点名称": "test-node",
            "主机地址": "example.invalid",
            "用户名": "tester",
            "已批准主机指纹": "SHA256:" + "a" * 43,
            "SSH 执行目录": "/tmp/autoeval",
            "SSH 凭据": "synthetic-test-password",
        }.items():
            page.get_by_label(label, exact=True).fill(value)
        page.get_by_role("button", name="保存节点").click()
        page.get_by_role("button", name="验证 SSH 连接").click()
        expect(page.get_by_text("主机指纹、Python 3 和 SFTP 已通过检查。")).to_be_visible()
        page.get_by_role("button", name="返回控制台").click()

        expect(page.get_by_label("启用 GPQA")).to_be_checked()
        expect(page.get_by_label("GPQA 样本范围")).to_have_value("full")
        selector = page.get_by_label("规划执行资源", exact=True)
        submit = page.get_by_role("button", name="提交测评")
        expect(submit).to_be_enabled()
        expect(page.get_by_text("1 个数据集将分别使用 1 个独立容器，按容量启动")).to_be_visible()
        expect(config.locator("../small")).to_contain_text("AISBench " + "a" * 12)
        assert not submissions
        page.get_by_role("button", name="移除 test-node").click()
        expect(submit).to_be_disabled()
        assert len(checks) == 1
        selector.click()
        page.get_by_role("checkbox", name="test-node").check()
        page.get_by_role("button", name="完成选择").click()
        expect(submit).to_be_enabled()
        submit.click()
        expect(page).to_have_url(page.url.split("#")[0] + "#run/run")
        assert len(submissions) == 1
        assert submissions[0]["resource_kind"] == "customer_ssh"
        assert submissions[0]["resource_ids"] == ["node"]


@pytest.mark.skipif(not os.getenv("AE_BROWSER_URL"), reason="Explicit local browser URL required")
def test_dataset_environment_waits_for_allocation_and_reports_cleanup():
    run_id = "fixture-containers"
    environment = {"host": "worker.test", "resource_id": "node", "tool": "aisbench",
                   "revision": "a" * 40, "container_id": None, "state": "waiting_capacity"}
    child = {"id": "child", "dataset": "GPQA", "state": "pending", "selected_cases": 2,
             "execution_environment": environment}
    run = {"id": run_id, "state": "queued", "datasets": [child], "snapshot": None, "report": None,
           "events": [], "cleanup": {"state": "pending"}, "created_at": "2026-11-20T00:00:00Z"}

    def mock(route):
        path = route.request.url.split("/api/autoeval/v1", 1)[-1].split("?")[0]
        data = run if path == "/evaluation-tasks/" + run_id else []
        route.fulfill(json={"data": data, "next_offset": None, "statistics": {
            "total": 0, "active": 0, "completed": 0, "failed_cancelled": 0,
        }})

    with sync_playwright() as playwright:
        chrome = os.getenv("AE_CHROME_PATH")
        browser = playwright.chromium.launch(**({"executable_path": chrome} if chrome else {}))
        page = browser.new_page()
        page.route("**/api/autoeval/v1/**", mock)
        page.goto(os.environ["AE_BROWSER_URL"].split("#")[0] + "#run/" + run_id)
        table = page.get_by_role("region", name="数据集执行结果")
        expect(table).to_contain_text("等待容量")
        expect(table).to_contain_text("SSH 主机 worker.test")
        expect(table).not_to_contain_text("容器 ")
        run["state"] = "completed"
        child.update(state="succeeded", summary={"observed_cases": 2})
        environment.update(state="cleanup_pending", container_id="0123456789ab")
        expect(table).to_contain_text("容器 0123456789ab · 待清理")
        environment["state"] = "cleaned"
        expect(table).to_contain_text("容器 0123456789ab · 已回收")
        expect(table).to_contain_text("2 / 2")
        browser.close()
