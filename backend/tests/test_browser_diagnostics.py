"""Browser through Vite proxy to real API, Temporal and Docker."""

import os

import pytest
from playwright.sync_api import expect, sync_playwright


@pytest.mark.skipif(not os.environ.get("AE_BROWSER_URL"), reason="Live services required")
def test_browser_diagnostic_execute_reload_and_cancel():
    with sync_playwright() as playwright:
        browser = playwright.chromium.launch(
            executable_path=os.environ.get("AE_CHROME_PATH") or None, headless=True
        )
        try:
            page = browser.new_page()
            page.set_default_timeout(15000)
            errors = []
            page.on("pageerror", lambda error: errors.append(str(error)))
            page.goto(os.environ["AE_BROWSER_URL"] + "/#tasks")
            submit = page.get_by_role("button", name="提交Docker诊断", exact=True)
            expect(submit).to_be_enabled()
            for cancel in (False, True):
                with page.expect_response(
                    lambda response: (
                        response.request.method == "POST"
                        and response.url.endswith("/diagnostics/runs")
                    )
                ) as response:
                    submit.click()
                assert response.value.status == 202, response.value.text()
                run_id = response.value.json()["data"]["run_id"]
                state = page.get_by_test_id("diagnostic-state")
                if cancel:
                    expect(state).to_have_text("诊断状态：running", timeout=30000)
                    page.get_by_role("button", name="取消Docker诊断", exact=True).click()
                expected = "cancelled" if cancel else "completed"
                expect(state).to_have_text("诊断状态：" + expected, timeout=60000)
                page.reload()
                select = page.get_by_label("已保存诊断任务", exact=True)
                expect(select.locator(f'option[value="{run_id}"]')).to_have_count(1)
                select.select_option(run_id)
                expect(state).to_have_text("诊断状态：" + expected)
            assert not errors
        finally:
            browser.close()
