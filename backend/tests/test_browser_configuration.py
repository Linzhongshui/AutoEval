"""Opt-in browser test against running Vite/API/PostgreSQL services."""

import os
import uuid
from urllib.parse import parse_qs, urlparse

import pytest
from playwright.sync_api import expect, sync_playwright


def install_configuration_fixtures(page):
    ids = {
        "target": str(uuid.uuid4()),
        "config": str(uuid.uuid4()),
        "resource": str(uuid.uuid4()),
        "run": str(uuid.uuid4()),
    }
    standard_v1 = {
        "id": str(uuid.uuid4()),
        "config_key": "approved-standard-real",
        "display_name": "Approved standard real",
        "version": 1,
        "version_label": "standard-v1",
        "kind": "standard",
        "items": {"GPQA": {"output": 32, "concurrency": 1, "temperature": 0, "top_p": 1, "scope": "Lite"}},
        "profile_bindings": {},
    }
    standard_v2 = {
        **standard_v1,
        "id": str(uuid.uuid4()),
        "version": 2,
        "version_label": "standard-v2",
        "items": {"GPQA": {"output": 64, "concurrency": 1, "temperature": 0, "top_p": 1, "scope": "Lite"}},
    }
    custom = {
        **standard_v1,
        "id": str(uuid.uuid4()),
        "config_key": "saved-custom-real",
        "display_name": "Saved custom real",
        "kind": "custom",
    }
    eligible = {
        **custom,
        "id": ids["config"],
        "config_key": "console-lite-real",
        "display_name": "Console Lite real",
        "version_label": "lite-v1",
        "profile_bindings": {"GPQA": str(uuid.uuid4())},
    }
    ineligible = {
        **eligible,
        "id": str(uuid.uuid4()),
        "display_name": "Full dataset must not be offered",
        "items": {"GPQA": {**eligible["items"]["GPQA"], "scope": "全量"}},
    }
    target = {
        "id": ids["target"],
        "model_key": "real-deepseek",
        "model_name": "real-deepseek",
        "model_version": "v-real",
        "default_config_version_id": ids["config"],
        "base_url": "https://api.deepseek.com",
        "remote_model": "deepseek-flash",
    }
    wrong_target = {**target, "id": str(uuid.uuid4()), "remote_model": "unsupported-model"}
    resource = {"id": ids["resource"], "binding_key": "real-docker"}
    submissions = []

    def respond(route):
        request = route.request
        parsed = urlparse(request.url)
        path = parsed.path.removeprefix("/api/autoeval/v1")
        query = parse_qs(parsed.query)
        if path == "/runs" and request.method == "POST":
            submissions.append(request)
            route.fulfill(status=201, json={"data": {"run_id": ids["run"]}})
            return
        if path.startswith("/runs/"):
            route.fulfill(status=404, json={"error": {"message": "intercepted detail"}})
            return
        rows = []
        if path == "/target-bindings":
            rows = [target] if query.get("target_id") else [target, wrong_target]
        elif path == "/test-configs":
            if query.get("config_id"):
                rows = [eligible]
            elif query.get("limit") == ["200"]:
                rows = [standard_v2, standard_v1, custom]
            else:
                rows = [eligible, ineligible]
        elif path == "/resources":
            rows = [resource]
        route.fulfill(status=200, json={"data": rows, "next_offset": None})

    page.route("**/api/autoeval/v1/**", respond)
    return ids, submissions


@pytest.mark.skipif(not os.environ.get("AE_BROWSER_URL"), reason="Live services required")
def test_console_uses_real_lite_options_and_intercepted_submission():
    with sync_playwright() as playwright:
        browser = playwright.chromium.launch(
            executable_path=os.environ.get("AE_CHROME_PATH") or None, headless=True
        )
        try:
            page = browser.new_page()
            page.set_default_timeout(10000)
            ids, submissions = install_configuration_fixtures(page)
            page.goto(os.environ["AE_BROWSER_URL"] + "/#console")
            expect(page.get_by_text("demo-vlm-001", exact=True)).to_have_count(0)
            expect(page.get_by_text("静态预览", exact=False)).to_have_count(0)
            expect(page.get_by_text("Release", exact=True)).to_have_count(0)
            expect(page.get_by_role("button", name="IP/Port 拉起", exact=True)).to_be_disabled()
            expect(page.get_by_role("radio", name="并行", exact=True)).to_be_disabled()

            service = page.get_by_label("控制台模型服务", exact=True)
            expect(service.locator(f'option[value="{ids["target"]}"]')).to_have_count(1)
            expect(service.locator("option").filter(has_text="unsupported-model")).to_have_count(0)
            service.select_option(ids["target"])
            config = page.get_by_label("控制台测评配置", exact=True)
            expect(config).to_have_value(ids["config"])
            expect(config.locator("option").filter(has_text="Full dataset must not be offered")).to_have_count(0)
            page.get_by_label("控制台执行资源", exact=True).select_option(ids["resource"])
            expect(page.get_by_role("checkbox", name="选择 GPQA", exact=True)).to_be_checked()
            expect(page.get_by_role("checkbox", name="选择 GPQA", exact=True)).to_be_disabled()
            expect(page.get_by_role("checkbox", name="选择 MMMU-Pro", exact=True)).to_be_disabled()
            expect(page.get_by_role("radio", name="串行", exact=True)).to_be_checked()

            submit = page.get_by_role("button", name="发起真实GPQA Lite测评", exact=True)
            expect(submit).to_be_enabled()
            submit.click()
            expect(page).to_have_url(os.environ["AE_BROWSER_URL"] + "/#run/" + ids["run"])
            assert len(submissions) == 1
            assert submissions[0].post_data_json == {
                "config_version_id": ids["config"],
                "target_id": ids["target"],
                "resource_id": ids["resource"],
                "resource_kind": "docker_local",
                "run_mode": "exploration",
                "max_model_requests": 5,
            }
        finally:
            browser.close()


@pytest.mark.skipif(not os.environ.get("AE_BROWSER_URL"), reason="Live services required")
def test_configuration_standard_and_custom_rows_come_from_backend():
    with sync_playwright() as playwright:
        browser = playwright.chromium.launch(
            executable_path=os.environ.get("AE_CHROME_PATH") or None, headless=True
        )
        try:
            page = browser.new_page()
            install_configuration_fixtures(page)
            page.goto(os.environ["AE_BROWSER_URL"] + "/#config")
            expect(page.get_by_text("Approved standard real", exact=True)).to_be_visible()
            expect(page.get_by_text("Demo Vision A 测评配置", exact=True)).to_have_count(0)
            versions = page.get_by_label("标准配置版本", exact=True)
            expect(versions.locator("option")).to_have_text(["standard-v2", "standard-v1"])
            page.get_by_role("button", name="查看", exact=True).click()
            output = page.get_by_label("输出长度", exact=True)
            expect(output).to_have_value("64")
            expect(output).to_be_disabled()
            page.get_by_role("button", name="关闭", exact=True).click()
            page.get_by_role("tab", name="自定义配置", exact=True).click()
            expect(page.get_by_text("Saved custom real", exact=True)).to_be_visible()
            expect(page.get_by_text("多模态验证", exact=True)).to_have_count(0)
        finally:
            browser.close()


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
            page.get_by_text(
                "已加载默认配置到当前表单；使用已保存服务的探索入口可创建真实任务。", exact=True
            ).wait_for()
        finally:
            browser.close()
