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
            base = os.environ["AE_BROWSER_URL"]
            page.goto(base + "/#reports")
            response = page.request.get(base + "/api/autoeval/v1/reports?limit=1")
            assert response.status == 200 and response.json()["data"]
            report = response.json()["data"][0]
            summary = report["summary"]

            catalog = page.get_by_test_id("real-report-catalog")
            expect(catalog).to_be_visible()
            expect(catalog.locator("table.reports-table")).to_be_visible()
            expect(catalog).to_contain_text(report["run_id"])
            expect(catalog).to_contain_text(report["created_at"])
            expect(catalog).to_contain_text(report["execution_origin"])
            page.get_by_role("button", name=f"查看报告 {report['id'][:8]}", exact=True).click()

            detail = page.get_by_test_id("real-report-detail")
            expect(detail).to_be_visible()
            meta = detail.locator(".execution-meta")
            expect(meta).to_contain_text(report["remote_model"])
            expect(meta).to_contain_text(report["run_id"])
            expect(meta).to_contain_text(report["created_at"])
            expect(meta).to_contain_text(report["validity"])
            expect(meta).to_contain_text(report["execution_origin"])
            expect(meta).to_contain_text("not_applicable")
            expect(meta).to_contain_text(str(summary["subset_scope"]))
            expect(meta).to_contain_text(str(summary["metric_scope"]))
            expect(meta).to_contain_text("scoring_status")

            stats = detail.locator(".report-summary-stats")
            keys = (
                "expected_samples",
                "executed_attempts",
                "successful_samples",
                "failed_samples",
                "missing_samples",
                "accuracy",
                "dataset_samples",
            )
            expect(stats.locator(":scope > div")).to_have_count(len(keys))
            for index, key in enumerate(keys):
                value = (
                    None
                    if key == "accuracy" and report["evidence_status"] != "verified"
                    else summary[key]
                )
                expected = (
                    "—"
                    if key == "accuracy" and value is None
                    else f"{value:g}"
                    if isinstance(value, float)
                    else str(value)
                )
                expect(stats.locator(":scope > div").nth(index)).to_contain_text(key)
                expect(stats.locator(":scope > div").nth(index)).to_contain_text(expected)
            if report["validity"] == "partial":
                expect(detail).to_contain_text("仅成功样本")
            expect(detail).to_contain_text("运行 completed 不等于报告 complete")
            expect(detail).to_contain_text(report["sha256"])
            expect(detail).to_contain_text(report["snapshot_sha256"])

            baseline = page.get_by_test_id("baseline-comparison")
            status = report["baseline_comparison"]["status"]
            expected_baseline = {
                "matched": "基准对比",
                "missing": "暂无基准",
                "incomparable": "不可直接比较",
            }[status]
            expect(baseline).to_contain_text(expected_baseline)
            expect(page.get_by_test_id("analysis-status")).to_be_visible()
            expect(detail.get_by_role("button", name="性能结果", exact=True)).to_have_count(0)
            expect(detail.get_by_role("button", name="样本明细", exact=True)).to_have_count(0)

            evidence_requests = []
            page.on(
                "request",
                lambda request: (
                    evidence_requests.append(request.url)
                    if request.url.endswith(f"/reports/{report['id']}/evidence")
                    else None
                ),
            )
            assert evidence_requests == []
            detail.get_by_role("button", name="报告证据", exact=True).click()
            detail.get_by_role("button", name="读取并校验报告证据", exact=True).click()
            drawer = page.get_by_role("dialog", name="报告证据详情", exact=True)
            expect(drawer).to_be_visible()
            if report["evidence_status"] == "verified":
                expect(page.get_by_test_id("real-report-evidence")).to_contain_text(
                    "gpqa-report.v1"
                )
            else:
                expect(page.get_by_test_id("report-evidence-health")).to_be_visible()
                expect(page.get_by_test_id("real-report-evidence")).to_have_count(0)
                expect(drawer.get_by_role("status")).to_contain_text("不能据此确认报告有效")
            assert len(evidence_requests) == 1
            drawer.get_by_role("button", name="关闭", exact=True).click()

            page.reload()
            expect(page.get_by_test_id("real-report-detail")).to_contain_text(
                report["remote_model"]
            )
            expect(page.get_by_test_id("real-report-evidence")).to_have_count(0)
            page.set_viewport_size({"width": 390, "height": 844})
            expect(page.get_by_test_id("real-report-detail")).to_be_visible()
            assert page.evaluate("document.documentElement.scrollWidth <= window.innerWidth")
        finally:
            browser.close()
