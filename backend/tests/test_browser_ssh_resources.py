import json
import os
import uuid

import pytest
from playwright.sync_api import expect, sync_playwright

from autoeval.config import get_settings
from autoeval.secrets import FileSecretStore


@pytest.mark.skipif(
    not os.environ.get("AE_BROWSER_URL") or not os.environ.get("AE_SSH_SIM_TEST"),
    reason="Live API/Vite and local OpenSSH simulator required",
)
def test_browser_register_private_key_and_preflight_local_ssh():
    settings = get_settings()
    config = json.loads((settings.secret_store_path / "ssh-simulator.json").read_text())
    key = FileSecretStore(settings.secret_store_path).get(config["credential_ref"])
    label = "browser-ssh-" + uuid.uuid4().hex[:12]
    with sync_playwright() as playwright:
        browser = playwright.chromium.launch(
            executable_path=os.environ.get("AE_CHROME_PATH") or None, headless=True
        )
        try:
            page = browser.new_page()
            page.goto(os.environ["AE_BROWSER_URL"] + "/#console")
            page.get_by_text("客户SSH服务器（真实后端）", exact=True).click()
            for field, value in [
                ("SSH资源名称", label),
                ("SSH主机地址", config["host"]),
                ("SSH端口", str(config["port"])),
                ("SSH用户名", config["username"]),
                ("已批准主机指纹", config["fingerprint"]),
                ("SSH执行目录", config["workdir"]),
            ]:
                page.get_by_label(field, exact=True).fill(value)
            page.get_by_label("SSH凭据类型", exact=True).select_option("private_key")
            page.get_by_label("SSH凭据", exact=True).fill(key)
            with page.expect_response(
                lambda response: (
                    response.url.endswith("/ssh-resources") and response.request.method == "POST"
                )
            ) as response:
                page.get_by_role("button", name="登记SSH资源", exact=True).click()
            assert response.value.status == 201
            expect(page.get_by_label("SSH凭据", exact=True)).to_have_value("")
            page.get_by_role("button", name=f"预检SSH资源 {label}", exact=True).click()
            page.get_by_text(
                "SSH预检通过：主机指纹已核验，Python3及SFTP可用；当前仅支持框架诊断，测评工具尚未接入。",
                exact=True,
            ).wait_for()
            page.reload()
            page.get_by_text("客户SSH服务器（真实后端）", exact=True).click()
            expect(
                page.get_by_role("button", name=f"预检SSH资源 {label}", exact=True)
            ).to_be_visible()
        finally:
            browser.close()
