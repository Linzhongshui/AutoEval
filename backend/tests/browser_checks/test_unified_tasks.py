"""Unified list and historical links with intercepted artificial data, no real writes."""

import json
import os

import pytest
from playwright.sync_api import sync_playwright


@pytest.mark.skipif(not os.getenv("AE_BROWSER_URL"), reason="Explicit browser URL required")
def test_one_list_global_statistics_and_legacy_detail_links():
    calls = []

    def api(route):
        path = route.request.url.split("/api/autoeval/v1", 1)[-1].split("?", 1)[0]
        calls.append(path)
        data = []
        extra = {}
        if path == "/system/capabilities":
            data = {"foundation": True}
        elif path == "/evaluation-tasks":
            data = [
                {
                    "id": "task",
                    "state": "running",
                    "remote_model": "TEST-display",
                    "resource_kind": "customer_ssh",
                    "created_at": "2026-11-16T01:00:00Z",
                    "datasets": ["GPQA", "MMMU-Pro"],
                }
            ]
            extra = {
                "statistics": {"total": 12, "active": 7, "completed": 4, "failed_cancelled": 1}
            }
        elif path == "/evaluation-tasks/task":
            data = {
                "id": "task",
                "state": "running",
                "run_mode": "exploration",
                "snapshot": {"parameters": {}, "sample_count": 10, "remote_model": "TEST-display"},
                "cleanup": {"state": "not_required", "attempt_count": 0},
                "report": None,
                "datasets": [
                    {"id": "g", "dataset": "GPQA", "state": "running"},
                    {
                        "id": "m",
                        "dataset": "MMMU-Pro",
                        "state": "failed",
                        "summary": {"reason": "TEST-failure"},
                    },
                ],
            }
        elif path.endswith("/monitor"):
            data = {"collection_status": "not_collected", "stale": False}
        route.fulfill(
            status=200,
            content_type="application/json",
            body=json.dumps({"data": data, "next_offset": None, **extra}),
        )

    with sync_playwright() as p:
        browser = p.chromium.launch(
            **(
                {"executable_path": os.environ["AE_CHROME_PATH"]}
                if os.getenv("AE_CHROME_PATH")
                else {}
            )
        )
        context = browser.new_context(viewport={"width": 1440, "height": 1000})
        context.route("**/api/autoeval/v1/**", api)
        page = context.new_page()
        base = os.environ["AE_BROWSER_URL"].rstrip("/")
        page.goto(base + "/#tasks")
        page.get_by_label("筛选结果任务统计").get_by_text("12", exact=True).wait_for()
        assert page.get_by_role("button", name="编排测评任务", exact=True).count() == 0
        assert "12" in page.get_by_label("筛选结果任务统计").inner_text()
        page.get_by_role("cell", name="GPQA、MMMU-Pro", exact=True).wait_for()
        page.goto(base + "/#planned-run/task")
        page.wait_for_url("**/#run/task")
        results = page.get_by_label("数据集执行结果")
        results.get_by_role("cell", name="MMMU-Pro", exact=True).wait_for()
        assert "TEST-failure" in results.inner_text()
        page.get_by_role("button", name="取消测评", exact=True).click()
        page.wait_for_timeout(200)
        assert "/evaluation-tasks/task/cancel" in calls
        assert not any(x.startswith("/planning/runs") for x in calls)
        page.goto(base + "/#console")
        page.get_by_label("发起测评", exact=True).wait_for()
        assert page.get_by_role("button", name="GPQA Lite 快速验证", exact=True).count() == 0
        context.close()
        browser.close()


@pytest.mark.skipif(not os.getenv("AE_BROWSER_URL"), reason="Explicit browser URL required")
@pytest.mark.parametrize("probe_state", ["pending", "unresolved"])
def test_unresolved_probe_is_restored_and_blocks_duplicate_start(probe_state):
    writes = []
    from datetime import UTC, datetime, timedelta
    unresolved = {
        "id": "old-probe",
        "state": probe_state,
        "created_at": (datetime.now(UTC) - timedelta(days=3)).isoformat(),
        "result": {"reason": "TEST unknown remote result", "dispatch_blocked": probe_state == "pending"},
    }

    def api(route):
        path = route.request.url.split("/api/autoeval/v1", 1)[-1].split("?", 1)[0]
        if route.request.method == "POST":
            writes.append(path)
        data = []
        if path == "/system/capabilities":
            data = {}
        elif path == "/target-bindings":
            data = [{"id": "target", "remote_model": "TEST", "base_url": "https://fixture.invalid"}]
        elif path == "/ssh-resources":
            data = [{"id": "resource", "binding_key": "TEST resource", "host": "fixture.invalid", "port": 22}]
        elif path == "/planning/options":
            data = {"compilations": [], "manifests": [], "curves": []}
        elif path in {"/planning/active-probe", "/planning/probes/old-probe"}:
            data = None if unresolved["state"] == "failed" else unresolved
        elif path == "/planning/probes/old-probe/reconcile":
            unresolved["result"]["remote_check"] = {"state": "unknown", "checked_at": datetime.now(UTC).isoformat()}
            data = unresolved
        elif path == "/planning/probes/old-probe/close":
            unresolved["state"] = "failed"
            data = unresolved
        route.fulfill(status=200, content_type="application/json", body=json.dumps({"data": data}))

    with sync_playwright() as p:
        browser = p.chromium.launch(
            **(
                {"executable_path": os.environ["AE_CHROME_PATH"]}
                if os.getenv("AE_CHROME_PATH")
                else {}
            )
        )
        context = browser.new_context()
        context.route("**/api/autoeval/v1/**", api)
        page = context.new_page()
        page.goto(os.environ["AE_BROWSER_URL"].rstrip("/") + "/#console")
        page.get_by_label("规划模型服务", exact=True).click()
        page.get_by_text("TEST", exact=True).click()
        page.get_by_label("规划执行资源", exact=True).click()
        page.get_by_role("checkbox", name="TEST resource").check()
        page.get_by_role("button", name="完成选择").click()
        page.locator(".planning-throughput > summary").click()
        page.get_by_text("探测任务：old-probe", exact=True).wait_for()
        assert page.get_by_role("button", name="启动吞吐探测", exact=True).is_disabled()
        assert page.get_by_role("button", name="查询探测状态", exact=True).is_enabled()
        assert page.get_by_role("button", name="取消探测", exact=True).is_enabled()
        text = page.get_by_role("region", name="吞吐探测进度").inner_text()
        assert ("已等待：" in text and "天" in text) if probe_state == "pending" else "执行耗时：未确认" in text
        assert not writes
        page.get_by_role("button", name="查询探测状态", exact=True).click()
        page.get_by_text("当前固定环境未找到原作业", exact=False).wait_for()
        assert writes == ["/planning/probes/old-probe/reconcile"]
        if probe_state == "unresolved":
            page.get_by_text("历史异常记录处理", exact=True).click()
            assert page.get_by_role("button", name="结束历史记录", exact=True).is_disabled()
            page.get_by_label("历史探测处理原因", exact=True).fill("TEST 历史证据无法恢复，保留未知用量")
            page.get_by_role("checkbox", name="确认原执行结果及用量仍未知，保留历史后结束此记录", exact=True).check()
            page.get_by_role("button", name="结束历史记录", exact=True).click()
            page.get_by_role("button", name="启动吞吐探测", exact=True).wait_for()
            page.wait_for_timeout(100)
            assert writes == ["/planning/probes/old-probe/reconcile", "/planning/probes/old-probe/close"]
        context.close()
        browser.close()
