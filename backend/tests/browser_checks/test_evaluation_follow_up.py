"""Browser contracts for confirming follow-ups from the original task."""

import os

import pytest
from playwright.sync_api import sync_playwright


@pytest.mark.skipif(not os.getenv("AE_BROWSER_URL"), reason="Explicit browser URL required")
@pytest.mark.parametrize("operation", ["resume", "case-retry"])
def test_confirm_from_original_task(operation):
    requests = []
    base = "/evaluation-tasks/task"
    target = {"dataset_key": "GPQA", "sample_id": "q2"}
    missing = {**target, "category": "remaining", "has_attempts": False}

    def api(route):
        path = route.request.url.split("/api/autoeval/v1", 1)[-1].split("?", 1)[0]
        data = []
        if path == "/evaluation-tasks":
            data = [
                {
                    "id": "task",
                    "state": "cancelled",
                    "created_at": "2026-11-20T00:00:00Z",
                    "follow_up_enabled": True,
                }
            ]
        elif path == base:
            data = {
                "id": "task",
                "state": "cancelled",
                "run_mode": "exploration",
                "follow_up_enabled": True,
                "snapshot": {"parameters": {}, "sample_count": 2, "remote_model": "Fixture"},
                "cleanup": {"state": "cleaned", "attempt_count": 1},
                "report": None,
                "datasets": [{"id": "g", "dataset": "GPQA", "state": "cancelled"}],
            }
        elif path in {base + "/resume-preview", base + "/case-retry-preview"}:
            data = {
                "source_round": 1,
                "scope_sha256": ("b" if "case-retry" in path else "a") * 64,
                "sample_count": 1,
                "blockers": [],
                "samples": [missing],
            }
        elif path == base + "/" + operation:
            requests.append((route.request.post_data_json, route.request.headers))
            route.fulfill(status=202, json={"data": {"run_id": "task", "round": 2}})
            return
        elif path == base + "/rounds":
            data = {
                "rounds": [
                    {"number": 1, "operation": "initial", "state": "cancelled"},
                    {
                        "number": 2,
                        "operation": "case_retry",
                        "state": "completed",
                        "shards": [{"id": "shard", "dataset": "GPQA", "state": "succeeded"}],
                    },
                ]
            }
        elif path == "/runs/task/monitor/log":
            assert "round_number=2" in route.request.url and "shard_id=shard" in route.request.url
            data = {"content": "已归档的分片日志"}
        route.fulfill(status=200, json={"data": data, "next_offset": None, "total": 0})

    with sync_playwright() as p:
        browser = p.chromium.launch(
            **(
                {"executable_path": os.environ["AE_CHROME_PATH"]}
                if os.getenv("AE_CHROME_PATH")
                else {}
            )
        )
        page = browser.new_page()
        page.route("**/api/autoeval/v1/**", api)
        origin = os.environ["AE_BROWSER_URL"].rstrip("/")
        if operation == "case-retry":
            page.goto(origin + "/#run/task")
            page.get_by_text("执行轮次", exact=True).click()
            page.get_by_text("第 1 轮 · 首次执行", exact=True).wait_for()
            page.get_by_role("button", name="查看分片日志", exact=True).click()
            page.get_by_text("已归档的分片日志", exact=True).wait_for()
            page.get_by_role("button", name="查看 Case", exact=True).click()
            table = page.get_by_test_id("case-attempts")
            table.get_by_role("columnheader", name="证据与轨迹", exact=True).wait_for()
            table.get_by_role("columnheader", name="重试", exact=True).wait_for()
            pending = table.get_by_role("row").filter(has_text="q2")
            pending.get_by_text("待执行", exact=True).wait_for()
            pending.get_by_role("button", name="重试此 Case", exact=True).click()
            page.get_by_role("dialog", name="重试此 Case").get_by_text(
                "GPQA · q2", exact=False
            ).wait_for()
            page.get_by_role("button", name="确认重试此 Case", exact=True).click()
        else:
            page.goto(origin + "/#tasks")
            page.get_by_role("row").get_by_role("button", name="续跑测评", exact=True).click()
            page.get_by_role("button", name="确认续跑测评", exact=True).click()
        page.get_by_text("执行请求已受理，任务详情将显示本轮状态。", exact=True).wait_for()
        assert len(requests) == 1
        payload, headers = requests[0]
        expected = {"source_round": 1, "scope_sha256": "a" * 64}
        if operation == "case-retry":
            expected.update(target, scope_sha256="b" * 64)
        assert payload == expected
        assert headers.get("idempotency-key")
        browser.close()
