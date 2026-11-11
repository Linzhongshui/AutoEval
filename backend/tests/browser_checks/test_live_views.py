"""Read-only navigation using discovered local reports, never hard-coded IDs."""

import pytest
from playwright.sync_api import expect


def test_task_and_report_details(live_page):
    page, url, _ = live_page
    # This is a read-only GET through the frontend's configured API proxy.
    response = page.request.get(url + "/api/autoeval/v1/reports?limit=1&offset=0")
    assert response.ok, "Report API unavailable; start backend and frontend proxy"
    rows = response.json()["data"]
    if not rows:
        pytest.skip("No archived local reports; no evaluation is created by this check")
    report = rows[0]
    page.goto(url + "/#run/" + report["run_id"])
    expect(page.get_by_role("heading", name="任务总览", exact=True)).to_be_visible()
    expect(page.locator("body")).not_to_contain_text("Invalid Date")
    page.get_by_role("button", name="查看明细", exact=True).click()
    page.get_by_role("button", name="Case 明细", exact=True).click()
    expect(page.get_by_role("button", name="查询case历史", exact=True)).to_be_visible()
    expect(page.get_by_label("回溯运行ID", exact=True)).to_have_count(0)
    page.get_by_role("button", name="返回任务总览", exact=True).click()
    page.get_by_role("button", name="配置快照", exact=True).click()
    expect(page.get_by_role("heading", name="本次配置快照", exact=True)).to_be_visible()
    page.goto(url + "/#report/" + report["id"])
    expect(page.get_by_role("heading", name="数据集结果", exact=True)).to_be_visible()
    page.get_by_role("button", name="查看结果", exact=True).click()
    page.get_by_role("button", name="样本明细", exact=True).click()
    expect(page.get_by_role("button", name="查询case历史", exact=True)).to_be_visible()
    page.get_by_role("button", name="返回报告总览", exact=True).click()
    expect(page.get_by_role("heading", name="数据集结果", exact=True)).to_be_visible()


def test_data_workbench_navigation(live_page):
    page, url, _ = live_page
    with page.expect_response(lambda r: "/data-workbench/entries?" in r.url) as response:
        page.goto(url + "/#data-workbench")
    assert response.value.ok, "Workbench unavailable; use dev frontend and migrate backend"
    expect(page.get_by_role("heading", name="数据工作台", exact=True)).to_be_visible()
    page.get_by_role("button", name="新建录入", exact=True).click()
    expect(page.get_by_role("button", name="保存待评审", exact=True)).to_be_visible()
    with page.expect_response(lambda r: "/reports?" in r.url) as response:
        page.get_by_role("button", name="刷新数据", exact=True).click()
    assert response.value.ok
    reports = response.value.json()["data"]
    page.get_by_role("button", name="报告评审入榜", exact=True).click()
    for report in reports:
        if report["evidence_status"] != "verified":
            row = page.locator("tr").filter(has_text=report["id"])
            expect(row.get_by_role("button", name="提名评审", exact=True)).to_be_disabled()
    page.get_by_role("button", name="官方数据导入", exact=True).click()
    page.get_by_role("button", name="填入格式模板", exact=True).click()
    assert '"source_type": "official"' in page.get_by_label("官方数据JSON").input_value()
    page.get_by_role("button", name="环境诊断", exact=True).click()
    expect(page.get_by_text("本机 Docker 诊断", exact=True)).to_be_visible()
    page.goto(url + "/#leaderboard")
    expect(page.get_by_role("heading", name="已评审榜单", exact=True)).to_be_visible()
