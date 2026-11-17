"""One explicit UI submission. Run from backend with --submit after authorization."""

import argparse
import json
from datetime import UTC, datetime
from pathlib import Path

from playwright.sync_api import sync_playwright

parser = argparse.ArgumentParser()
parser.add_argument("--submit", action="store_true")
parser.add_argument(
    "--retry-approved",
    action="store_true",
    help="Requires explicit operator approval; preserves the previous failed run",
)
args = parser.parse_args()
statefile = Path(".secrets/automationbench-acceptance.json")
state = json.loads(statefile.read_text())
if args.retry_approved:
    if state.get("model_requests", 0) > 0:
        raise RuntimeError("This round has sent model requests; measurement retry is forbidden")
    if not args.submit or not state.get("real_run_id"):
        raise RuntimeError("An approved retry requires an existing run and --submit")
    state.setdefault("attempt_history", []).append(
        {
            "run_id": state.pop("real_run_id"),
            "submission_started_at": state.pop("submission_started_at", None),
            "retry_reason": "confirmed zero model requests; infrastructure/selection repaired",
            "retry_approved": True,
        }
    )
    statefile.write_text(json.dumps(state, indent=2))
if state.get("real_run_id"):
    print("Already submitted:", state["real_run_id"])
    raise SystemExit(0)
if state.get("submission_started_at"):
    raise RuntimeError("Previous submission outcome uncertain; inspect server before any repeat")
access = json.loads(Path(".secrets/intranet-20261113/deployment.json").read_text())
with sync_playwright() as p:
    browser = p.chromium.launch(channel="chrome", headless=True, args=["--no-proxy-server"])
    try:
        page = browser.new_page(
            http_credentials={"username": access["web_user"], "password": access["web_password"]},
            viewport={"width": 1600, "height": 1100},
        )
        page.goto("https://179.214.2.3/#console", wait_until="networkidle")
        page.locator("select").nth(0).select_option(state["target_id"])
        page.locator("select").nth(1).select_option("customer_ssh")
        page.locator("select").nth(2).select_option(state["resource_id"])
        row = page.get_by_role("row").filter(has=page.get_by_text("AutomationBench", exact=True))
        row.locator('input[type="checkbox"]').check()
        row.locator("select").nth(0).select_option(state["compilation_id"])
        row.locator("select").nth(1).select_option(state["manifest_id"])
        numeric = row.locator('input[type="number"]')
        if numeric.count():
            numeric.fill("1")
        page.get_by_role("button", name="环境检查", exact=True).click()
        page.get_by_text("检查通过", exact=True).first.wait_for(timeout=60000)
        page.get_by_role(
            "checkbox", name="确认所选数据集及范围，提交真实测评，可能产生模型调用费用"
        ).check()
        page.screenshot(
            path="../deliverables/automationbench-real-submission-review.png", full_page=True
        )
        assert row.locator("select").nth(0).input_value() == state["compilation_id"]
        assert row.locator("select").nth(1).input_value() == state["manifest_id"]
        if args.submit:
            state["submission_started_at"] = datetime.now(UTC).isoformat()
            statefile.write_text(json.dumps(state, indent=2))
            with page.expect_response(
                lambda r: (
                    r.request.method == "POST"
                    and r.url.endswith("/api/autoeval/v1/evaluation-tasks")
                ),
                timeout=45000,
            ) as result:
                page.get_by_role("button", name="提交测评", exact=True).click()
            response = result.value
            if response.status != 202:
                raise RuntimeError(
                    "Submission failed: " + str(response.status) + " " + response.text()[:400]
                )
            body = response.json()["data"]
            state["real_run_id"] = body["run_id"]
            statefile.write_text(json.dumps(state, indent=2))
            print("REAL_RUN_ID", body["run_id"], flush=True)
            page.wait_for_url("**/#run/" + body["run_id"], timeout=30000)
            page.screenshot(path="../deliverables/automationbench-real-started.png", full_page=True)
        else:
            print("Review and preflight passed; no model task submitted")
    finally:
        browser.close()
