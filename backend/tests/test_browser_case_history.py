import os
import uuid

import pytest
from playwright.async_api import async_playwright, expect

from autoeval.case_history import AttemptEvidence, AttemptInput, begin_attempt, finish_attempt
from autoeval.config import get_settings
from autoeval.db import create_database
from autoeval.models import EvaluationRun


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
                await page.get_by_text("case历史回溯（真实后端）", exact=True).click()
                await page.get_by_label("回溯运行ID", exact=True).fill(str(run_id))
                await page.get_by_role("button", name="查询case历史", exact=True).click()
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
