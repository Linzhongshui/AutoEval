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
            base = os.environ["AE_BROWSER_URL"]
            page.goto(base + "/#leaderboard")
            leaderboard = page.get_by_test_id("real-leaderboard")
            expect(leaderboard).to_be_visible()
            response = page.request.get(
                base + "/api/autoeval/v1/leaderboard?dataset_key=GPQA&metric_name=accuracy"
            )
            assert response.status == 200
            groups = response.json()["data"]
            if not groups:
                assert response.json()["excluded_unverified_reports"] > 0
                expect(leaderboard).to_contain_text("暂无可比完整报告")
                expect(page.get_by_test_id("leaderboard-entry")).to_have_count(0)
                return

            expect(leaderboard.locator("table.leader-table")).to_have_count(len(groups))
            expect(leaderboard.get_by_role("button", name="性能榜单", exact=True)).to_have_count(0)
            expected = sum(len(group["entries"]) for group in groups)
            expect(page.get_by_test_id("leaderboard-entry")).to_have_count(expected)
            for index, group in enumerate(groups):
                panel = page.get_by_test_id("leaderboard-group").nth(index)
                comparison = group["comparison"]
                expect(panel).to_contain_text(comparison["manifest_id"])
                expect(panel).to_contain_text(comparison["manifest_sha256"])
                expect(panel).to_contain_text(comparison["tool_revision"])
                for key, value in comparison["parameters"].items():
                    expected = f"{value:g}" if isinstance(value, (int, float)) else str(value)
                    expect(panel).to_contain_text(key)
                    expect(panel).to_contain_text(expected)
                expect(panel.get_by_test_id("leaderboard-entry")).to_have_count(
                    len(group["entries"])
                )
                for entry_index, entry in enumerate(group["entries"]):
                    row = panel.get_by_test_id("leaderboard-entry").nth(entry_index)
                    expect(row).to_contain_text(str(entry["rank"]).zfill(2))
                    expect(row).to_contain_text(entry["remote_model"])
                    expect(row).to_contain_text(f"{entry['value']:g}{group['unit']}")
                    expect(row).to_contain_text(entry["created_at"])

            page.set_viewport_size({"width": 390, "height": 844})
            assert page.evaluate("document.documentElement.scrollWidth <= window.innerWidth")
            first_report = groups[0]["entries"][0]["report_id"]
            page.get_by_role(
                "button", name=f"来源报告 {first_report[:8]}", exact=True
            ).first.click()
            expect(page.get_by_test_id("real-report-detail")).to_be_visible()
        finally:
            browser.close()
