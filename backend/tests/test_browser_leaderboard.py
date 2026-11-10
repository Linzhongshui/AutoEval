import os

import pytest
from playwright.sync_api import expect, sync_playwright


@pytest.mark.skipif(not os.environ.get("AE_BROWSER_URL"), reason="Live Vite and API required")
def test_browser_real_leaderboard_groups_and_report_links():
    with sync_playwright() as playwright:
        browser = playwright.chromium.launch(
            executable_path=os.environ.get("AE_CHROME_PATH") or None, headless=True
        )
        try:
            page = browser.new_page()
            page.goto(os.environ["AE_BROWSER_URL"] + "/#leaderboard")
            expect(page.get_by_test_id("real-leaderboard")).to_be_visible()
            response = page.request.get(
                os.environ["AE_BROWSER_URL"]
                + "/api/autoeval/v1/leaderboard?dataset_key=GPQA&metric_name=accuracy"
            )
            assert response.status == 200
            groups = response.json()["data"]
            assert groups, "A verified complete real report is required"
            expected = sum(len(group["entries"]) for group in groups)
            expect(page.get_by_test_id("leaderboard-entry")).to_have_count(expected)
            first_report = groups[0]["entries"][0]["report_id"]
            page.get_by_role("button", name=f"来源报告 {first_report[:8]}", exact=True).click()
            expect(page.get_by_test_id("real-report-detail")).to_be_visible()
        finally:
            browser.close()
