"""Opt-in browser test against running Vite/API/PostgreSQL services."""

import os
import uuid

import pytest
from playwright.sync_api import sync_playwright


@pytest.mark.skipif(not os.environ.get("AE_BROWSER_URL"), reason="Live services required")
def test_browser_save_and_reload():
    label = "browser-" + uuid.uuid4().hex[:10]
    with sync_playwright() as playwright:
        browser = playwright.chromium.launch(
            executable_path=os.environ.get("AE_CHROME_PATH") or None, headless=True
        )
        try:
            page = browser.new_page(viewport={"width": 1440, "height": 1000})
            page.set_default_timeout(10000)
            errors = []
            page.on("pageerror", lambda error: errors.append(str(error)))
            page.goto(os.environ["AE_BROWSER_URL"] + "/#config")
            page.get_by_role("button", name="新建配置", exact=True).click()
            page.get_by_placeholder("例如：多模态验证-第三版").fill(label)
            with page.expect_response(
                lambda response: (
                    "/api/autoeval/v1/test-configs" in response.url
                    and response.request.method == "POST"
                )
            ) as response:
                page.get_by_role("button", name="保存配置", exact=True).click()
            assert response.value.status == 201, response.value.text()
            page.reload()
            page.get_by_role("tab", name="自定义配置", exact=True).click()
            page.get_by_label("搜索配置").fill(label)
            page.get_by_text(label, exact=True).first.wait_for()
            assert not errors
        finally:
            browser.close()


@pytest.mark.skipif(not os.environ.get("AE_BROWSER_URL"), reason="Live services required")
def test_browser_register_model_bind_and_reload_default():
    key = "model-browser-" + uuid.uuid4().hex[:10]
    with sync_playwright() as playwright:
        browser = playwright.chromium.launch(
            executable_path=os.environ.get("AE_CHROME_PATH") or None, headless=True
        )
        try:
            page = browser.new_page()
            page.set_default_timeout(10000)
            page.goto(os.environ["AE_BROWSER_URL"] + "/#console")
            response = page.request.post(
                os.environ["AE_BROWSER_URL"] + "/api/autoeval/v1/test-configs",
                data={
                    "config_key": key,
                    "display_name": key,
                    "version_label": "first",
                    "expected_version": 0,
                    "items": {
                        "GPQA": {
                            "output": 321,
                            "concurrency": 1,
                            "temperature": 0.5,
                            "top_p": 1,
                            "scope": "全量",
                        }
                    },
                },
            )
            assert response.status == 201
            config_id = response.json()["data"]["id"]
            page.reload()
            page.get_by_text("已登记模型与默认配置（真实后端）", exact=True).click()
            page.get_by_label("登记模型ID", exact=True).fill(key)
            page.get_by_label("登记模型名称", exact=True).fill(key)
            page.get_by_label("登记模型版本", exact=True).fill("v1")
            page.get_by_role("button", name="登记模型", exact=True).click()
            page.get_by_text("模型已登记，尚未配置调用服务。", exact=True).wait_for()
            page.get_by_label("绑定默认配置版本").select_option(config_id)
            page.get_by_role("button", name="保存默认绑定", exact=True).click()
            page.get_by_text("默认配置绑定已保存。", exact=True).wait_for()
            page.reload()
            page.get_by_text("已登记模型与默认配置（真实后端）", exact=True).click()
            page.get_by_label("已登记模型", exact=True).select_option(label=f"{key} · {key}")
            page.get_by_role("button", name="加载模型默认配置", exact=True).click()
            page.get_by_text("已加载默认配置；真实测评尚未启用。", exact=True).wait_for()
        finally:
            browser.close()
