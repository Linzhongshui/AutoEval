"""Browser interaction against fully intercepted artificial API data; no real writes."""

import json
import os
from pathlib import Path

import pytest
from playwright.sync_api import sync_playwright


@pytest.mark.skipif(not os.getenv("AE_BROWSER_URL"), reason="Explicit local browser URL required")
def test_planning_duration_apply_and_stale_input_invalidation():
    report = {
        "input_sha256": "a" * 64,
        "conditional": False,
        "confidence": "low",
        "warnings": ["TEST artificial planning data"],
        "representative_duration_sec": 122,
        "estimate": {"total_duration_sec": 120, "range": {"p10_sec": 100, "p90_sec": 150}},
        "plan": {
            "dataset_order": ["GPQA"],
            "dataset_concurrency": 1,
            "case_concurrency": {"GPQA": 2},
        },
        "tasks": [
            {
                "task_id": "GPQA",
                "standalone_duration_sec": 110,
                "scheduled_duration_sec": 122,
                "scheduled_start_sec": 0,
                "scheduled_end_sec": 122,
            }
        ],
    }
    calls = []
    submitted = []

    def api(route):
        request = route.request
        path = request.url.split("/api/autoeval/v1", 1)[-1].split("?", 1)[0]
        calls.append((request.method, path))
        data = []
        if path == "/system/capabilities":
            data = {"foundation": True, "workspace_mode": "single"}
        elif path == "/target-bindings":
            data = [
                {
                    "id": "target",
                    "remote_model": "TEST-model",
                    "base_url": "https://fixture.invalid",
                    "model_key": "TEST",
                    "model_version": "fixture",
                    "default_config_version_id": None,
                }
            ]
        elif path == "/resources":
            data = [{"id": "resource", "binding_key": "TEST-executor"}]
        elif path == "/planning/active-probe":
            data = None
        elif path == "/planning/options":
            data = {
                "compilations": [
                    {
                        "id": "compilation",
                        "dataset": "GPQA",
                        "sha256": "b" * 64,
                        "target_id": "target",
                        "input_ready": True,
                        "config": {"subcommand": "llm_accuracy", "params": {"batch_size": 1}},
                    }
                ],
                "manifests": [
                    {"id": "manifest", "dataset": "GPQA", "scope": "full", "sample_count": 2}
                ],
                "curves": [
                    {
                        "id": "curve",
                        "target_id": "target",
                        "resource_id": "resource",
                        "resource_kind": "docker_local",
                        "measured_at": "2026-11-12T00:00:00Z",
                    }
                ],
            }
        elif path == "/planning/resources/preflight":
            data = {
                "id": "preflight",
                "state": "completed",
                "result": {
                    "execution_ready": True,
                    "supported_datasets": ["GPQA"],
                    "tool_versions": {
                        "planner": {"expected": "a" * 40, "actual": "a" * 40},
                        "adaptor": {"expected": "b" * 40, "actual": "b" * 40},
                    },
                    "dataset_checks": [
                        {
                            "task_id": "GPQA",
                            "dataset": "GPQA",
                            "data_path": "/TEST/gpqa",
                            "tool_revision": "c" * 40,
                            "expected_tool_revision": "c" * 40,
                            "blocking_reasons": [],
                        }
                    ],
                    "blocking_reasons": [],
                },
            }
        elif path in {"/planning/probes", "/planning/probes/TEST-probe"}:
            data = {"id": "TEST-probe", "state": "running", "created_at": "2026-11-13T00:00:00Z", "updated_at": "2026-11-13T00:00:02Z", "result": {"progress": {"stage": "probing", "current_concurrency": 4, "completed_levels": 2, "total_levels": 4}}}
        elif path == "/evaluation-tasks" and request.method == "POST":
            submitted.append(request.post_data_json)
            data = {"run_id": "unified", "state": "accepted"}
        elif path == "/evaluation-tasks/unified":
            data = {"id": "unified", "state": "completed", "run_mode": "exploration", "snapshot": {"parameters": {}, "sample_count": 5}, "cleanup": {"state": "not_required", "attempt_count": 0}, "report": None, "datasets": []}
        elif path.endswith("/monitor"):
            data = {"collection_status": "not_collected", "stale": False}
        elif path == "/planning/plans":
            data = {"id": "advice" if request.post_data_json.get("recommend") else "plan", "state": "completed", "result": {"report": report}}
        elif path == "/planning/plans/plan/apply":
            data = {
                "execution_plan_id": "execution",
                "report": {
                    **report,
                    "estimate": {
                        "total_duration_sec": 180,
                        "range": {"p10_sec": 150, "p90_sec": 210},
                    },
                },
            }
        route.fulfill(
            status=200,
            content_type="application/json",
            body=json.dumps({"data": data, "next_offset": None}),
        )

    with sync_playwright() as playwright:
        browser = playwright.chromium.launch(
            **(
                {"executable_path": os.environ["AE_CHROME_PATH"]}
                if os.getenv("AE_CHROME_PATH")
                else {}
            )
        )
        context = browser.new_context(viewport={"width": 1440, "height": 1000})
        context.route("**/api/autoeval/v1/**", api)
        page = context.new_page()
        page.goto(os.environ["AE_BROWSER_URL"].rstrip("/") + "/#console")
        panel = page.get_by_role("region", name="发起测评")
        summary = page.get_by_role("complementary", name="任务摘要")
        panel.get_by_label("规划模型服务", exact=True).select_option("target")
        panel.get_by_label("规划执行资源", exact=True).select_option("resource")
        panel.get_by_role("checkbox", name="启用 GPQA", exact=True).check()
        panel.get_by_label("GPQA 执行配置").select_option("compilation")
        panel.get_by_label("GPQA 样本范围").select_option("manifest")
        # No curve or probe is necessary to submit the current configuration.
        panel.get_by_role("button", name="环境检查").click()
        panel.get_by_text("GPQA · 数据路径：/TEST/gpqa · 工具版本：cccccccccccc · 就绪").wait_for()
        summary.get_by_role("checkbox", name="确认所选数据集及范围，提交真实测评，可能产生模型调用费用").check()
        assert summary.get_by_role("button", name="提交测评").is_enabled()
        assert not any(method == "POST" and path in {"/planning/probes", "/planning/plans"} for method, path in calls)
        panel.get_by_label("吞吐来源").select_option("curve")
        panel.get_by_role("button", name="重新检查").click()
        panel.get_by_text("GPQA · 数据路径：/TEST/gpqa · 工具版本：cccccccccccc · 就绪").wait_for()
        # Selecting a ready throughput curve estimates without another click or model request.
        summary.get_by_text("0小时 2分 0秒", exact=True).wait_for()
        assert any(path == "/planning/plans" for _, path in calls)
        assert panel.get_by_role("group", name="数据集执行策略", exact=True).get_by_role("button", name="串行执行").get_attribute("aria-pressed") == "true"
        panel.get_by_role("group", name="GPQA 样本执行策略", exact=True).get_by_role("button", name="并行执行").click()
        assert panel.get_by_label("GPQA case 并发", exact=True).input_value() == "2"
        panel.get_by_role("group", name="GPQA 样本执行策略", exact=True).get_by_role("button", name="串行执行").click()
        summary.get_by_text("0小时 2分 0秒", exact=True).wait_for()
        summary.get_by_role("button", name="获取优化建议", exact=True).click()
        summary.get_by_text("查看优化建议与参数差异", exact=True).click()
        summary.get_by_role("heading", name="预计总耗时：0小时 2分 0秒").wait_for()
        assert summary.get_by_role("columnheader", name="单独执行耗时").is_visible()
        assert summary.get_by_role("columnheader", name="计划内耗时").is_visible()
        summary.get_by_role("button", name="采纳参数建议").click()
        assert panel.get_by_label("GPQA case 并发", exact=True).input_value() == "2"
        summary.get_by_text("输入已变化，旧估算及建议已失效，请重新估算。", exact=True).wait_for()
        assert not any(path.endswith("/apply") for _, path in calls)
        artifact = Path(os.getenv("AE_BROWSER_ARTIFACT_DIR", "../.screenshots/browser-checks"))
        artifact.mkdir(parents=True, exist_ok=True)
        page.screenshot(path=str(artifact / "task-planning.png"), full_page=True)
        panel.get_by_label("GPQA case 并发", exact=True).fill("3")
        assert summary.get_by_role("region", name="耗时估算与参数建议").count() == 0
        assert not any(
            method == "POST" and path in {"/planning/probes", "/planning/runs"}
            for method, path in calls
        )
        panel.locator(".planning-throughput > summary").click()
        panel.get_by_role("button", name="启动吞吐探测", exact=True).click()
        dialog = page.get_by_role("dialog", name="确认吞吐探测预算")
        dialog.get_by_text("32 次（含非流式回退）", exact=True).wait_for()
        assert not any(path == "/planning/probes" for _, path in calls)
        page.screenshot(path=str(artifact / "probe-budget.png"), full_page=True)
        dialog.get_by_role("button", name="确认预算并启动").click()
        progress = panel.get_by_role("region", name="吞吐探测进度")
        progress.get_by_text("探测任务：TEST-probe").wait_for()
        assert "已完成 2/4 档" in progress.inner_text()
        assert progress.get_by_role("progressbar").get_attribute("aria-valuenow") == "50"
        page.screenshot(path=str(artifact / "probe-progress.png"), full_page=True)
        panel.get_by_label("GPQA case 并发", exact=True).fill("2")
        # The single task action carries final form parameters, never a Planner artifact ID.
        panel.get_by_role("button", name="重新检查").click()
        panel.get_by_text("GPQA · 数据路径：/TEST/gpqa · 工具版本：cccccccccccc · 就绪").wait_for()
        summary.get_by_role("checkbox", name="确认所选数据集及范围，提交真实测评，可能产生模型调用费用").check()
        summary.get_by_role("button", name="提交测评", exact=True).click()
        page.wait_for_url("**/#run/unified")
        assert len(submitted) == 1
        assert set(submitted[0]) == {"target_id", "resource_id", "resource_kind", "tasks", "dataset_concurrency"}
        assert submitted[0]["tasks"][0]["concurrency"] == 2
        assert not any(path == "/planning/runs" or path.endswith("/apply") for _, path in calls)
        context.close()
        browser.close()
