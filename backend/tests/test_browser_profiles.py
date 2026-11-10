import json
import os
import uuid

import pytest
from playwright.sync_api import expect, sync_playwright


@pytest.mark.skipif(not os.environ.get("AE_BROWSER_URL"), reason="Live services required")
def test_browser_profile_registration_and_configuration_binding():
    key = "browser-" + uuid.uuid4().hex[:12]
    with sync_playwright() as playwright:
        browser = playwright.chromium.launch(
            executable_path=os.environ.get("AE_CHROME_PATH") or None, headless=True
        )
        try:
            page = browser.new_page()
            base = os.environ["AE_BROWSER_URL"]
            api = base + "/api/autoeval/v1"
            full = page.request.post(
                api + "/dataset-manifests",
                data={
                    "dataset_key": key,
                    "name": "Browser fixture",
                    "version": "v1",
                    "manifest_key": "full",
                    "scope": "full",
                    "samples": [{"sample_id": "a", "sha256": "a" * 64}],
                },
            )
            assert full.status == 201
            config = page.request.post(
                api + "/test-configs",
                data={
                    "config_key": key,
                    "display_name": key,
                    "version_label": "draft",
                    "expected_version": 0,
                    "items": {
                        "GPQA": {
                            "output": 16,
                            "concurrency": 1,
                            "temperature": 0,
                            "top_p": 1,
                            "scope": "全量",
                        }
                    },
                },
            )
            assert config.status == 201
            page.goto(base + "/#config")
            page.get_by_text("Profile与配置执行绑定（真实后端）", exact=True).click()
            page.get_by_text("登记Profile契约", exact=True).first.click()
            page.get_by_label("Profile契约JSON", exact=True).fill(
                json.dumps(
                    {
                        "profile_key": key,
                        "version": "v1",
                        "dataset_name": "GPQA",
                        "full_manifest_id": full.json()["data"]["id"],
                        "tool": {
                            "family": "aisbench",
                            "source_url": "https://example.invalid/fixture",
                            "revision": "a" * 40,
                            "scorer_reference": "fixture-only",
                            "scorer_sha256": "b" * 64,
                            "parallelism_owner": "tool",
                        },
                    }
                )
            )
            with page.expect_response(
                lambda response: (
                    response.url.endswith("/profiles") and response.request.method == "POST"
                )
            ) as profile:
                page.get_by_role("button", name="登记Profile契约", exact=True).click()
            assert profile.value.status == 201
            profile_id = profile.value.json()["data"]["id"]
            page.get_by_label("待绑定配置版本", exact=True).select_option(
                config.json()["data"]["id"]
            )
            selector = page.get_by_label("GPQA执行Profile", exact=True)
            expect(selector.locator(f'option[value="{profile_id}"]')).to_have_count(1)
            selector.select_option(profile_id)
            page.get_by_label("绑定后版本名称", exact=True).fill("bound")
            with page.expect_response(
                lambda response: (
                    response.url.endswith("/test-configs") and response.request.method == "POST"
                )
            ) as bound:
                page.get_by_role("button", name="保存执行绑定新版本", exact=True).click()
            assert bound.value.status == 201
            bound_id = bound.value.json()["data"]["id"]
            page.reload()
            page.get_by_text("Profile与配置执行绑定（真实后端）", exact=True).click()
            page.get_by_label("待绑定配置版本", exact=True).select_option(bound_id)
            expect(page.get_by_label("GPQA执行Profile", exact=True)).to_have_value(profile_id)
        finally:
            browser.close()
