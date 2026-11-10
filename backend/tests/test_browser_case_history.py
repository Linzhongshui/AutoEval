import os
import uuid

import pytest
from playwright.async_api import async_playwright, expect

from autoeval.case_history import AttemptEvidence, AttemptInput, begin_attempt, finish_attempt
from autoeval.config import get_settings
from autoeval.db import create_database
from autoeval.models import EvaluationRun


@pytest.mark.skipif(not os.environ.get("AE_BROWSER_URL"), reason="Live services required")
async def test_browser_original_pages_have_no_prototype_panels():
    async with async_playwright() as playwright:
        browser = await playwright.chromium.launch(
            executable_path=os.environ.get("AE_CHROME_PATH") or None, headless=True
        )
        try:
            page = await browser.new_page()
            await page.goto(os.environ["AE_BROWSER_URL"] + "/#tasks")
            await expect(page.locator(".evaluation-tasks")).to_be_visible()
            await expect(page.locator(".task-stats")).to_be_visible()
            await expect(page.locator(".task-stats")).to_contain_text("当前页")
            await expect(page.get_by_text("查看原型示例任务", exact=True)).to_have_count(0)
            await expect(page.get_by_text("其余为示例数据", exact=False)).to_have_count(0)
            await expect(page.get_by_text("case历史回溯（真实后端）", exact=True)).to_have_count(0)
            await expect(
                page.get_by_text("GPQA Lite探索测评（真实模型调用）", exact=True)
            ).to_have_count(0)
        finally:
            await browser.close()


@pytest.mark.skipif(not os.environ.get("AE_BROWSER_URL"), reason="Live services required")
async def test_browser_home_uses_real_recent_reports():
    async with async_playwright() as playwright:
        browser = await playwright.chromium.launch(
            executable_path=os.environ.get("AE_CHROME_PATH") or None, headless=True
        )
        try:
            page = await browser.new_page()
            await page.goto(os.environ["AE_BROWSER_URL"] + "/#home")
            await expect(page.get_by_text("查看示例报告", exact=True)).to_have_count(0)
            await expect(page.get_by_text("示例测评报告", exact=True)).to_have_count(0)
            recent = page.get_by_test_id("recent-reports")
            await expect(recent).to_be_visible()
            reports = await page.request.get(
                os.environ["AE_BROWSER_URL"] + "/api/autoeval/v1/reports?limit=3&offset=0"
            )
            rows = (await reports.json())["data"]
            if rows:
                await expect(recent).to_contain_text(rows[0]["remote_model"])
        finally:
            await browser.close()


@pytest.mark.skipif(not os.environ.get("AE_BROWSER_URL"), reason="Live services required")
async def test_browser_failed_attempt_is_still_available_after_success():
    settings = get_settings()
    engine, sessions = create_database(settings)
    try:
        async with sessions() as session, session.begin():
            run = EvaluationRun(
                trigger_scope="browser-case-fixture",
                idempotency_key=uuid.uuid4().hex,
                request_hash="a" * 64,
                run_mode="exploration",
                created_by="integration-test",
            )
            session.add(run)
            await session.flush()
            run_id = run.id
        for number, state in [(1, "failed"), (2, "succeeded")]:
            attempt_id = await begin_attempt(
                sessions,
                AttemptInput(
                    run_id=run_id,
                    dataset_key="fixture",
                    sample_id="fixture-case",
                    attempt_no=number,
                    operation_key=str(number),
                ),
            )
            await finish_attempt(
                sessions,
                settings,
                attempt_id,
                AttemptEvidence(
                    state=state,
                    prompt="Fixture-only prompt",
                    response="A" if state == "succeeded" else None,
                    error_code="UPSTREAM_TIMEOUT" if state == "failed" else None,
                ),
            )
        async with async_playwright() as playwright:
            browser = await playwright.chromium.launch(
                executable_path=os.environ.get("AE_CHROME_PATH") or None, headless=True
            )
            try:
                page = await browser.new_page()
                await page.goto(os.environ["AE_BROWSER_URL"] + "/#tasks")
                await page.get_by_text("Case 执行历史", exact=True).click()
                await page.get_by_label("回溯运行ID", exact=True).fill(str(run_id))
                await page.get_by_role("button", name="查询case历史", exact=True).click()
                attempts = page.get_by_test_id("case-attempts")
                await expect(attempts).to_contain_text("UPSTREAM_TIMEOUT")
                await expect(attempts.get_by_role("columnheader", name="执行状态", exact=True)).to_be_visible()
                await expect(attempts.get_by_role("columnheader", name="创建时间", exact=True)).to_be_visible()
                await expect(page.get_by_text("判分通过", exact=True)).to_have_count(0)
                await page.get_by_role("button", name="查看第2次证据", exact=True).click()
                await expect(page.get_by_test_id("case-evidence")).to_contain_text(
                    '"state": "succeeded"'
                )
                await page.get_by_role("button", name="查看第1次证据", exact=True).click()
                await expect(page.get_by_test_id("case-evidence")).to_contain_text(
                    "UPSTREAM_TIMEOUT"
                )
            finally:
                await browser.close()
    finally:
        await engine.dispose()
