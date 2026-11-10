import os

import pytest
from playwright.sync_api import expect, sync_playwright


@pytest.mark.skipif(
    not os.environ.get("AE_BROWSER_URL") or not os.environ.get("AE_REPORTS_TEST"),
    reason="Live real report required",
)
def test_browser_real_report_evidence_and_direct_reload():
    with sync_playwright() as playwright:
        browser = playwright.chromium.launch(
            executable_path=os.environ.get("AE_CHROME_PATH") or None, headless=True
        )
        try:
            page = browser.new_page()
            page.goto(os.environ["AE_BROWSER_URL"] + "/#reports")
            catalog = page.request.get(
                os.environ["AE_BROWSER_URL"] + "/api/autoeval/v1/reports?limit=1"
            )
            assert catalog.status == 200 and catalog.json()["data"]
            report_id = catalog.json()["data"][0]["id"]
            page.get_by_role("button", name=f"查看报告 {report_id[:8]}", exact=True).click()
            expect(page.get_by_test_id("real-report-detail")).to_contain_text(
                "本报告不代表全量成绩"
            )
            page.get_by_role("button", name="读取并校验报告证据", exact=True).click()
            expect(page.get_by_test_id("real-report-evidence")).to_contain_text("gpqa-report.v1")
            page.reload()
            expect(page.get_by_test_id("real-report-detail")).to_contain_text("GPQA Lite")
        finally:
            browser.close()
