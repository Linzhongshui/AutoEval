from urllib.parse import parse_qs, urlsplit

import pytest
from playwright.sync_api import expect


@pytest.mark.parametrize("submit_agentx", [True, False])
def test_console_tabs_drafts_pool_and_explicit_submit(browser_page, submit_agentx):
    page, url, artifacts = browser_page
    writes = []

    def mock(route):
        request = route.request
        path = urlsplit(request.url).path.split("/api/autoeval/v1")[-1]
        data = []
        if request.method == "POST":
            writes.append((path, request.post_data_json))
        if path == "/ssh-resources":
            data = [
                {"id": "node", "binding_key": "CPU Client", "host": "fixture.invalid", "port": 22}
            ]
        elif path == "/target-bindings":
            data = [
                {"id": "model", "remote_model": "Fixture", "base_url": "https://fixture.invalid"}
            ]
        elif path == "/planning/options":
            data = {"compilations": [], "manifests": [], "curves": []}
        elif path == "/planning/resources/preflight":
            data = {"id": "check", "state": "pending"}
        elif path == "/planning/probes/check":
            data = {"id": "check", "state": "completed", "result": {"execution_ready": True}}
        elif path == "/evaluation-tasks" and request.method == "POST":
            data = {"run_id": "performance-run"}
        elif path == "/planning/active-probe":
            data = None
        route.fulfill(json={"data": data, "next_offset": None})

    page.route("**/api/autoeval/v1/**", mock)
    page.goto(url + "/#console")
    accuracy = page.get_by_role("tab", name="精度测评")
    perf = page.get_by_role("tab", name="性能测评")
    expect(accuracy).to_have_attribute("aria-selected", "true")
    page.get_by_label("规划模型服务", exact=True).click()
    page.get_by_role("tabpanel", name="精度测评").get_by_text("Fixture", exact=True).click()
    perf.click()
    expect(page).to_have_url(url + "/#console/performance")
    page.reload()
    expect(perf).to_have_attribute("aria-selected", "true")
    expect(page.get_by_role("link", name="控制台")).to_have_class("selected")
    page.get_by_label("模型服务", exact=True).select_option("model")
    page.get_by_label("SSH 执行节点").select_option("node")
    page.get_by_label("最大输出长度（token）").fill("45")
    page.get_by_label("测评方式").select_option("agentx")
    page.get_by_label("会话并发档位").fill("1,4")
    page.get_by_label("Trace 数量上限", exact=False).fill("2")
    accuracy.click()
    page.get_by_label("规划模型服务", exact=True).click()
    page.get_by_role("tabpanel", name="精度测评").get_by_text("Fixture", exact=True).click()
    page.go_back()
    expect(page.get_by_label("Trace 数量上限", exact=False)).to_have_value("2")
    page.go_forward()
    expect(page.get_by_label("规划模型服务", exact=True)).to_contain_text("Fixture")
    perf.click()
    page.get_by_role("button", name="管理 SSH 资源池").click()
    page.go_back()
    expect(perf).to_have_attribute("aria-selected", "true")
    page.go_forward()
    page.get_by_role("button", name="返回控制台").click()
    expect(perf).to_have_attribute("aria-selected", "true")
    expect(page.get_by_label("模型服务", exact=True)).to_have_value("model")
    if submit_agentx:
        page.screenshot(path=str(artifacts / "console-performance.png"), full_page=True)
    else:
        page.get_by_label("测评方式").select_option("inference")
        expect(page.get_by_label("最大输出长度（token）")).to_have_value("45")
        page.get_by_label("目标输入长度（token）").fill("32")
        page.get_by_label("并发数", exact=True).fill("2")
        page.get_by_label("请求数", exact=True).fill("3")
    assert writes == []
    page.get_by_role("button", name="环境预检").click()
    page.get_by_role("button", name="提交性能测评").click()
    expect(page).to_have_url(url + "/#run/performance-run")
    assert [p for p, _ in writes] == ["/planning/resources/preflight", "/evaluation-tasks"]
    assert writes[0][1] == writes[1][1]
    if not submit_agentx:
        assert writes[1][1]["performance"] == {
            "kind": "inference",
            "input_tokens": 32,
            "max_output_tokens": 45,
            "concurrency": 2,
            "requests": 3,
        }
        return
    assert writes[1][1]["performance"] == {
        "kind": "agentx",
        "duration": 60,
        "run_mode": "smoke",
        "variant": "256k",
        "concurrency": [1, 4],
        "trace_limit": 2,
    }


def test_filter_and_view_performance_csv(browser_page):
    page, url, _ = browser_page
    filters = []
    row = {
        "id": "perf",
        "run_id": "perf-run",
        "remote_model": "Fixture",
        "task_type": "performance",
        "evidence_status": "verified",
        "validity": "complete",
        "analysis_status": "not_requested",
        "review_status": "pending",
        "created_at": "2026-11-23T00:00:00Z",
        "summary": {
            "accuracy": None,
            "performance": {
                "config": {"kind": "agentx"},
                "parse_status": "success",
                "comparison_scope": "smoke",
                "metrics": [["TTFT", "p90", 0.25, "s"]],
                "files": [{"path": "agentx_summary.csv"}],
                "csv_preview": [["metric", "p90"], ["TTFT", "0.25"]],
            },
        },
    }

    def mock(route):
        incoming = urlsplit(route.request.url)
        next_offset = None
        if incoming.path.endswith("/reports"):
            params = parse_qs(incoming.query)
            filters.append(params)
            records = [
                *[{**row, "id": f"older-{i}"} for i in range(5)],
                {**row, "id": "other-model", "remote_model": "Another model"},
                {**row, "id": "other-analysis", "analysis_status": "completed"},
                row,
            ]
            for param, field in (("model", "remote_model"), ("analysis_status", "analysis_status")):
                if param in params:
                    records = [r for r in records if r[field] == params[param][0]]
            offset, limit = int(params["offset"][0]), int(params["limit"][0])
            route.fulfill(json={
                "data": records[offset:offset + limit],
                "total": len(records),
                "next_offset": offset + limit if offset + limit < len(records) else None,
                "filters": {"models": ["Another model", "Fixture"], "analysis_statuses": ["not_requested", "completed"]},
            })
            return
        elif incoming.path.endswith("/reports/perf"):
            data = row
        else:
            data = {}
        route.fulfill(json={"data": data, "next_offset": next_offset})

    page.route("**/api/autoeval/v1/**", mock)
    page.goto(url + "/#reports")
    page.get_by_label("任务类型").select_option("performance")
    page.get_by_label("模型").select_option("Fixture")
    page.get_by_label("分析状态").select_option("not_requested")
    page.get_by_label("报告每页条数").select_option("5")
    expect(page.get_by_text("共 6 条 · 第 1 / 2 页")).to_be_visible()
    assert all(request["offset"] == ["0"] for request in filters)
    page.get_by_role("button", name="下一页").click()
    expect(page.get_by_text("共 6 条 · 第 2 / 2 页")).to_be_visible()
    page.get_by_role("button", name="查看报告").click()
    expect(page.get_by_role("heading", name="AgentX 轨迹回放性能报告")).to_be_visible()
    expect(page.get_by_text("可比范围 · smoke", exact=False)).to_be_visible()
    expect(page.get_by_role("link", name="下载 agentx_summary.csv")).to_have_attribute(
        "href", "/api/autoeval/v1/reports/perf/performance-csv?path=agentx_summary.csv"
    )
    assert filters[-1] == {
        "summary_only": ["true"], "task_type": ["performance"], "model": ["Fixture"],
        "analysis_status": ["not_requested"], "limit": ["5"], "offset": ["5"],
    }
