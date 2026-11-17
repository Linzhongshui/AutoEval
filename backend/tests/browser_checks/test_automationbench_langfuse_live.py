"""Explicit live platform-to-Langfuse navigation; uses protected local access files."""

import json
import os
from pathlib import Path
from urllib.parse import parse_qs, urlparse

import pytest
from playwright.sync_api import sync_playwright

pytestmark = pytest.mark.skipif(
    os.getenv("AE_LANGFUSE_PLATFORM_TEST") != "1", reason="Live platform acceptance is opt-in"
)


@pytest.mark.parametrize("authenticated", [False, True])
def test_platform_trace_popup(authenticated):
    run_id = os.environ["AE_LANGFUSE_PLATFORM_RUN_ID"]
    public_trace = os.getenv("AE_LANGFUSE_PLATFORM_PUBLIC") == "1"
    access = json.loads(Path(".secrets/intranet-20261113/deployment.json").read_text())
    langfuse = json.loads(Path(".secrets/langfuse-server.json").read_text())
    with sync_playwright() as p:
        browser = p.chromium.launch(
            channel="chrome",
            headless=True,
            args=[
                "--no-proxy-server",
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
            if authenticated:
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
            full_content = page.get_by_text("正文轨迹已导入", exact=False).count() > 0
            evidence_button = page.get_by_role("button", name="查看第1次证据", exact=True).first
            evidence_box, trace_box = evidence_button.bounding_box(), links.first.bounding_box()
            assert evidence_box and trace_box
            assert (
                evidence_box["x"] + evidence_box["width"] <= trace_box["x"]
                or evidence_box["y"] + evidence_box["height"] <= trace_box["y"]
            ), "Evidence and Trace actions must not overlap"
            page.screenshot(
                path="../deliverables/automationbench-langfuse-platform.png", full_page=True
            )
            with page.expect_popup() as popup:
                links.first.click()
            trace = popup.value
            trace.wait_for_load_state("networkidle")
            if not authenticated and not public_trace:
                trace.locator('input[name="email"]').wait_for(timeout=30000)
                assert parse_qs(urlparse(trace.url).query)["targetPath"] == [urlparse(href).path]
                assert trace.get_by_text("You do not have access to this trace.").count() == 0
                trace.locator('input[name="email"]').fill(langfuse["email"])
                trace.locator('input[name="password"]').fill(langfuse["password"])
                trace.locator('button[type="submit"]').click()
            trace.wait_for_url(href, timeout=30000)
            trace.get_by_text("trial", exact=True).first.wait_for(timeout=30000)
            if not authenticated and public_trace:
                assert not any("session-token" in cookie["name"] for cookie in context.cookies())
            trace.screenshot(
                path=(
                    "../.screenshots/automationbench-langfuse-full-trace.png"
                    if full_content
                    else "../deliverables/automationbench-langfuse-public-trace.png"
                    if public_trace and not authenticated
                    else "../deliverables/automationbench-langfuse-trace.png"
                ),
                full_page=True,
            )
            assert "/auth/" not in trace.url
        finally:
            browser.close()


def test_unshared_trace_still_requires_login():
    private_url = os.getenv("AE_LANGFUSE_PRIVATE_TRACE_URL")
    if not private_url:
        pytest.skip("Specify a non-public trace URL for the access isolation check")
    langfuse = json.loads(Path(".secrets/langfuse-server.json").read_text())
    with sync_playwright() as playwright:
        browser = playwright.chromium.launch(
            channel="chrome", headless=True, args=["--no-proxy-server"]
        )
        try:
            page = browser.new_page()
            page.goto(private_url, wait_until="networkidle")
            page.locator('input[name="email"]').wait_for(timeout=30000)
            assert page.url.startswith(langfuse["url"] + "/auth/sign-in?")
            assert parse_qs(urlparse(page.url).query)["targetPath"] == [urlparse(private_url).path]
        finally:
            browser.close()
