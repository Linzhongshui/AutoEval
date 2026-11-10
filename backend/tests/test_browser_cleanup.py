"""Observe persisted cleanup via the real Vite/API/SQL path; never submit a model call."""

import os

import pytest
from playwright.sync_api import expect, sync_playwright


@pytest.mark.skipif(
    not os.environ.get("AE_BROWSER_URL") or not os.environ.get("AE_SSH_SIM_TEST"),
    reason="Live browser and previously archived SSH run required",
)
def test_browser_persisted_ssh_cleanup_status_after_reload():
    with sync_playwright() as playwright:
        browser = playwright.chromium.launch(
            executable_path=os.environ.get("AE_CHROME_PATH") or None, headless=True
        )
        try:
            page = browser.new_page()
            errors = []
            page.on("pageerror", lambda error: errors.append(str(error)))
            base = os.environ["AE_BROWSER_URL"]
            page.goto(base + "/#tasks")
            response = page.request.get(base + "/api/autoeval/v1/runs?limit=100")
            assert response.status == 200
            selected = None
            for row in response.json()["data"]:
                detail = page.request.get(base + "/api/autoeval/v1/runs/" + row["id"])
                assert detail.status == 200
                data = detail.json()["data"]
                if data["cleanup"]["state"] == "cleaned":
                    selected = data
                    break
            assert selected is not None, "A verified reclaimed SSH run must be prepared first"
            for reload in (False, True):
                if reload:
                    page.reload()
                page.get_by_label("已保存探索任务", exact=True).select_option(selected["id"])
                expect(page.get_by_test_id("cleanup-state")).to_contain_text("清理已确认")
                expect(page.get_by_test_id("evaluation-state")).to_contain_text(selected["state"])
                expect(page.get_by_role("button", name="重试资源清理", exact=True)).to_have_count(0)
            assert errors == []
        finally:
            browser.close()
