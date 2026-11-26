"""Exercise SSH pool navigation with mocked API responses and no remote writes."""

import os
from datetime import UTC, datetime, timedelta

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
        page.get_by_role("button", name="环境检查", exact=True).click()
        expect(submit).to_be_enabled()
        expect(page.get_by_text("计划启动 1 个独立容器")).to_be_visible()
        expect(config.locator("../small")).to_contain_text("AISBench " + "a" * 12)
        assert not submissions
        selector.click()
        page.get_by_role("checkbox", name="test-node").uncheck()
        page.get_by_role("button", name="完成选择").click()
        expect(submit).to_be_disabled()
        assert len(checks) == 1
        selector.click()
        page.get_by_role("checkbox", name="test-node").check()
        page.get_by_role("button", name="完成选择").click()
        page.get_by_role("button", name="环境检查", exact=True).click()
        expect(submit).to_be_enabled()
        submit.click()
        expect(page).to_have_url(page.url.split("#")[0] + "#run/run")
        assert len(submissions) == 1
        assert submissions[0]["resource_kind"] == "customer_ssh"
        assert submissions[0]["resource_ids"] == ["node"]


@pytest.mark.skipif(not os.getenv("AE_BROWSER_URL"), reason="Explicit local browser URL required")
def test_preflight_elapsed_and_all_pool_nodes():
    datasets = ["GPQA", "MMMU-Pro", "DeepSWE", "AutomationBench"]
    node_ids = ["worker", "standby", "unused"]
    attempts = []
    estimates = []
    finish = False
    path_missing = False
    submissions = []

    def mock(route):
        path = route.request.url.split("/api/autoeval/v1", 1)[1].split("?")[0]
        data = []
        if path == "/target-bindings":
            data = [{"id": "model", "remote_model": "Test model"}]
        elif path == "/planning/options":
            data = {
                "compilations": [
                    {"id": d, "dataset": d, "target_id": "model", "input_ready": True,
                     "config": {"subcommand": "llm_accuracy", "params": {}},
                     "runtime_config": {"resource_ids": node_ids[:2]}}
                    for d in datasets
                ],
                "manifests": [
                    {"id": d, "dataset": d, "scope": "full", "sample_count": 1} for d in datasets
                ],
                "curves": [{"id": "curve", "target_id": "model", "resource_id": "worker",
                            "resource_kind": "customer_ssh", "measured_at": "2026-11-21T00:00:00Z"}],
            }
        elif path == "/ssh-resources":
            data = [{"id": n, "binding_key": n, "host": "shared.test", "port": 22} for n in node_ids]
        elif path == "/planning/active-probe":
            data = None
        elif path == "/planning/resources/preflight":
            assert route.request.post_data_json["resource_ids"] == ["worker", "standby"]
            attempts.append(datetime.now(UTC))
            data = {"id": str(len(attempts)), "state": "pending"}
        elif path == "/planning/plans":
            estimates.append(route.request.post_data_json)
            data = {"id": "estimate", "state": "completed"}
        elif path.startswith("/planning/probes/"):
            index = int(path.rsplit("/", 1)[1])
            start = attempts[index - 1]
            data = {"id": str(index), "state": "running", "created_at": start.isoformat()}
            assigned = {d: ("standby" if d == "MMMU-Pro" else "worker") for d in datasets}
            progress = {"assignments": assigned, "events": [
                {"stage": "started", "dataset": None, "at": start.isoformat()},
                {"stage": "checking", "dataset": "GPQA", "at": start.isoformat()},
            ]}
            data["result"] = {"preflight_progress": progress}
            if finish:
                data.update(state="completed", updated_at=(start + timedelta(seconds=7)).isoformat(),
                            result={"preflight_progress": progress, "execution_ready": not path_missing, "supported_datasets": datasets,
                                    "dataset_checks": [
                                        {"task_id": d, "dataset": d, "assigned_resource_id": assigned[d],
                                         "warnings": ["dataset_not_validated"] if d == "GPQA" else [],
                                         "data_path": "/data/" + d,
                                         "blocking_reasons": ["dataset_path_missing"]
                                         if path_missing and d == "MMMU-Pro" else []} for d in datasets
                                    ]})
                if len(attempts) == 1:
                    data["result"]["preflight_valid_until"] = (start + timedelta(minutes=5)).isoformat()
        elif path == "/evaluation-tasks" and route.request.method == "POST":
            submissions.append(route.request.post_data_json)
            data = {"run_id": "four-datasets"}
        route.fulfill(json={"data": data, "next_offset": None})

    with sync_playwright() as playwright:
        chrome = os.getenv("AE_CHROME_PATH")
        browser = playwright.chromium.launch(**({"executable_path": chrome} if chrome else {}))
        page = browser.new_page()
        page.clock.install()
        page.route("**/api/autoeval/v1/**", mock)
        page.goto(os.environ["AE_BROWSER_URL"].split("#")[0] + "#console")
        page.get_by_label("规划模型服务", exact=True).click()
        page.get_by_text("Test model", exact=True).click()
        for dataset in datasets:
            page.get_by_label("启用 " + dataset).check()
        page.get_by_role("button", name="环境检查", exact=True).click()
        timer = page.get_by_role("timer", name="环境检查已耗时")
        expect(timer).to_be_visible()
        expect(timer).not_to_have_text(timer.inner_text())
        nodes = page.get_by_role("region", name="数据集执行节点")
        expect(nodes.get_by_text("GPQA · 校验工具与数据")).to_be_visible()
        expect(nodes.get_by_text("等待检查", exact=True)).to_have_count(3)
        finish = True
        expect(nodes.get_by_text("预检通过", exact=True)).to_have_count(4)
        expect(nodes.get_by_role("row")).to_have_count(5)
        expect(nodes.get_by_role("rowheader", name="shared.test:22")).to_have_count(1)
        for dataset in datasets:
            expect(nodes.get_by_role("cell", name=dataset, exact=True)).to_have_count(1)
        expect(timer).not_to_be_visible()
        summary = page.get_by_role("complementary", name="任务摘要")
        expect(summary.get_by_text("已选 1 台")).to_be_visible()
        expect(summary.get_by_text("4/4 通过")).to_be_visible()
        # A strategy edit must retain the same evidence across the auto-check debounce.
        check_count = len(attempts)
        page.locator(".planning-throughput > summary").click()
        page.get_by_label("吞吐来源").select_option("curve")
        page.get_by_role("button", name="MMMU-Pro 前移").click()
        page.get_by_role("button", name="GPQA 前移").click()
        page.get_by_role("group", name="GPQA 样本执行策略").get_by_role("button", name="并行执行").click()
        page.get_by_label("GPQA case 并发", exact=True).fill("6")
        page.clock.run_for(700)
        assert len(attempts) == check_count
        assert next(t for t in estimates[-1]["tasks"] if t["dataset"] == "GPQA")["concurrency"] == 6
        expect(summary.get_by_text("4/4 通过")).to_be_visible()
        expect(summary.get_by_text("· 耗时 7秒")).to_be_visible()
        expect(summary.locator(".planning-blocker")).to_have_count(0)
        expect(summary.get_by_role("button", name="提交测评")).to_be_enabled()
        details = page.locator(".preflight-details")
        expect(details).not_to_have_attribute("open", "")
        expect(page.get_by_text("GPQA 尚无小样本验收记录，首次试跑由你决定。")).to_be_visible()
        summary.get_by_text("执行说明", exact=True).click()
        expect(summary.get_by_text("标准参数校验", exact=False)).to_be_visible()
        path_missing = True
        finish = False
        page.clock.fast_forward(5 * 60 * 1000)
        expect(summary.get_by_text("已过期", exact=True)).to_be_visible()
        expect(summary.get_by_role("button", name="提交测评")).to_be_disabled()
        page.get_by_role("group", name="数据集执行策略").get_by_role("button", name="并行执行").click()
        page.get_by_role("button", name="重新检查", exact=True).click()
        expect(timer).to_be_visible()
        expect(nodes.get_by_text("预检通过", exact=True)).to_have_count(0)
        finish = True
        blocked_dataset = details.locator("details").filter(has_text="MMMU-Pro")
        expect(blocked_dataset.get_by_text("/data/MMMU-Pro", exact=True)).to_be_visible()
        expect(details.get_by_text("/data/GPQA", exact=True)).not_to_be_visible()
        expect(summary.get_by_text("MMMU-Pro · 配置缺少数据目录")).to_be_visible()
        expect(summary.get_by_role("button", name="提交测评")).to_be_disabled()
        blocked_dataset.locator("summary").click()
        details.get_by_text("查看环境检查详情", exact=True).click()
        summary.get_by_role("button", name="查看阻塞项").click()
        expect(blocked_dataset.locator("summary")).to_be_focused()
        expect(blocked_dataset.get_by_text("配置缺少数据目录", exact=True)).to_be_visible()
        path_missing = False
        page.get_by_role("group", name="数据集执行策略").get_by_role("button", name="并行执行").click()
        expect(page.get_by_label("数据集同时运行数")).to_have_value("4")
        page.get_by_role("button", name="重新检查").click()
        summary.get_by_role("button", name="提交测评").click()
        assert len(submissions) == 1
        assert submissions[0]["resource_ids"] == ["worker", "standby"]
        assert submissions[0]["dataset_concurrency"] == 4
        assert submissions[0]["tasks"][0]["concurrency"] == 6
        assert submissions[0]["resource_id"] == "worker"
        assert [t["dataset"] for t in submissions[0]["tasks"]] == datasets
        browser.close()


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
