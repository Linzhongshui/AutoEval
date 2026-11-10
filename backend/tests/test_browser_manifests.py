import json
import os
import uuid

import pytest
from playwright.sync_api import expect, sync_playwright


@pytest.mark.skipif(not os.environ.get("AE_BROWSER_URL"), reason="Live services required")
def test_browser_register_manifest_and_reload():
    key = "browser-fixture-" + uuid.uuid4().hex[:12]
    with sync_playwright() as playwright:
        browser = playwright.chromium.launch(
            executable_path=os.environ.get("AE_CHROME_PATH") or None, headless=True
        )
        try:
            page = browser.new_page()
            page.goto(os.environ["AE_BROWSER_URL"] + "/#config")
            page.get_by_text("数据集样本清单（真实后端）", exact=True).click()
            page.get_by_label("样本清单JSON", exact=True).fill(
                json.dumps(
                    {
                        "dataset_key": key,
                        "name": "Browser fixture, not benchmark",
                        "version": "v1",
                        "manifest_key": key,
                        "scope": "full",
                        "samples": [{"sample_id": "fixture-only", "sha256": "a" * 64}],
                    }
                )
            )
            with page.expect_response(
                lambda response: (
                    response.url.endswith("/dataset-manifests")
                    and response.request.method == "POST"
                )
            ) as response:
                page.get_by_role("button", name="登记样本清单", exact=True).click()
            assert response.value.status == 201, response.value.text()
            page.reload()
            page.get_by_text("数据集样本清单（真实后端）", exact=True).click()
            expect(page.get_by_text(key + " · full · 1个样本", exact=False)).to_be_visible()
        finally:
            browser.close()
