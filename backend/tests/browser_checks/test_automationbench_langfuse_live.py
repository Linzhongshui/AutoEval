"""Explicit live platform-to-Langfuse navigation; uses protected local access files."""

import json
import os
from pathlib import Path

import pytest
from playwright.sync_api import sync_playwright

pytestmark = pytest.mark.skipif(
    os.getenv("AE_LANGFUSE_PLATFORM_TEST") != "1", reason="Live platform acceptance is opt-in"
)


def test_platform_trace_popup():
    run_id = os.environ["AE_LANGFUSE_PLATFORM_RUN_ID"]
    access = json.loads(Path(".secrets/intranet-20261113/deployment.json").read_text())
    langfuse = json.loads(Path(".secrets/langfuse-server.json").read_text())
    with sync_playwright() as p:
        browser = p.chromium.launch(
            channel="chrome",
            headless=True,
            args=[
                "--no-proxy-server",
                "--host-resolver-rules=MAP langfuse.autoeval.local 179.214.2.3",
            ],
        )
        try:
            context = browser.new_context(
                http_credentials={
                    "username": access["web_user"],
                    "password": access["web_password"],
                    "origin": "https://179.214.2.3",
                },
                viewport={"width": 1440, "height": 1000},
            )
            page = context.new_page()
            page.goto(langfuse["url"] + "/auth/sign-in", wait_until="networkidle")
            page.locator('input[name="email"]').fill(langfuse["email"])
            page.locator('input[name="password"]').fill(langfuse["password"])
            page.locator('button[type="submit"]').click()
            page.wait_for_url(langfuse["url"] + "/")
            page.goto("https://179.214.2.3/#run/" + run_id, wait_until="networkidle")
            links = page.get_by_role("link", name="查看 Trace")
            links.first.wait_for(timeout=30000)
            assert links.count() >= 1
            href = links.first.get_attribute("href")
            page.screenshot(
                path="../deliverables/automationbench-langfuse-platform.png", full_page=True
            )
            with page.expect_popup() as popup:
                links.first.click()
            trace = popup.value
            trace.wait_for_load_state("networkidle")
            assert trace.url == href
            trace.get_by_text("trial", exact=True).first.wait_for(timeout=30000)
            trace.screenshot(
                path="../deliverables/automationbench-langfuse-trace.png", full_page=True
            )
            assert "/auth/" not in trace.url
        finally:
            browser.close()
