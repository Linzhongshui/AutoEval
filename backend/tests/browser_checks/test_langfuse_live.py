"""Opt-in browser check against the separately deployed Langfuse instance."""

import base64
import hashlib
import json
import os
from pathlib import Path

import pytest
from cryptography import x509
from cryptography.hazmat.primitives import serialization
from playwright.sync_api import sync_playwright

pytestmark = pytest.mark.skipif(
    os.getenv("AE_LANGFUSE_LIVE_TEST") != "1", reason="Live Langfuse not enabled"
)


def test_langfuse_trace_page():
    access = json.loads(Path(".secrets/langfuse-server.json").read_text())
    cert = x509.load_pem_x509_certificate(Path(".secrets/langfuse-server.crt").read_bytes())
    spki = cert.public_key().public_bytes(
        serialization.Encoding.DER, serialization.PublicFormat.SubjectPublicKeyInfo
    )
    pin = base64.b64encode(hashlib.sha256(spki).digest()).decode()
    with sync_playwright() as playwright:
        browser = playwright.chromium.launch(
            channel="chrome",
            headless=True,
            args=[
                "--no-proxy-server",
                "--host-resolver-rules=MAP langfuse.autoeval.local 179.214.2.3",
                "--ignore-certificate-errors-spki-list=" + pin,
            ],
        )
        try:
            page = browser.new_page(viewport={"width": 1440, "height": 1000})
            base = access["url"]
            page.goto(base + "/auth/sign-in", wait_until="networkidle", timeout=45000)
            page.locator('input[name="email"]').fill(access["email"])
            page.locator('input[name="password"]').fill(access["password"])
            page.locator('button[type="submit"]').click()
            page.wait_for_url(base + "/", timeout=45000)
            page.goto(
                base + "/project/autoeval-harbor/traces/fbf4e49cda895dd58456c2c22fddf268",
                wait_until="networkidle",
                timeout=45000,
            )
            page.get_by_text("fbf4e49cda895dd58456c2c22fddf268", exact=True).first.wait_for(timeout=30000)
            page.get_by_text("llm", exact=True).first.wait_for(timeout=30000)
            content = page.locator("body").inner_text()
            assert "reward" in content and "1.00" in content
            assert "/auth/" not in page.url
            page.screenshot(path="../deliverables/langfuse-trace-2026-11-16.png", full_page=True)
        finally:
            browser.close()
