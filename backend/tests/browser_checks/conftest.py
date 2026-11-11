"""Opt-in, bounded browser checks; no persistent Chrome profiles or fixed ports."""

import os
from pathlib import Path
from urllib.parse import urlparse

import pytest
from playwright.sync_api import sync_playwright


@pytest.fixture
def browser_page(request):
    if os.getenv("AE_BROWSER_TEST") != "1":
        pytest.skip("Set AE_BROWSER_TEST=1 and start the frontend")
    url = os.getenv("AE_BROWSER_URL", "http://127.0.0.1:5173").rstrip("/")
    parsed = urlparse(url)
    if parsed.scheme not in {"http", "https"} or parsed.hostname not in {"localhost", "127.0.0.1"}:
        pytest.fail("Browser checks require a local frontend URL")
    mutations = []
    with sync_playwright() as playwright:
        executable = os.getenv("AE_CHROME_PATH")
        browser = playwright.chromium.launch(
            **({"executable_path": executable} if executable else {})
        )
        context = browser.new_context(viewport={"width": 1920, "height": 1400})
        page = context.new_page()
        page.set_default_timeout(15000)

        def guard(route):
            incoming = route.request
            target = urlparse(incoming.url)
            if target.netloc != parsed.netloc:
                route.abort()
            elif incoming.method not in {"GET", "HEAD", "OPTIONS"}:
                mutations.append(incoming.url)
                route.abort()
            else:
                route.continue_()

        context.route("**/*", guard)
        artifact_dir = Path(os.getenv(
            "AE_BROWSER_ARTIFACT_DIR",
            str(Path(__file__).resolve().parents[3] / ".screenshots" / "browser-checks"),
        ))
        artifact_dir.mkdir(parents=True, exist_ok=True)
        try:
            yield page, url, artifact_dir
        finally:
            try:
                page.screenshot(path=str(artifact_dir / f"{request.node.name}.png"), full_page=True)
            finally:
                context.close()
                browser.close()
    assert not mutations, "Browser check attempted a real write request"


@pytest.fixture
def live_page(browser_page):
    if os.getenv("AE_BROWSER_LIVE_TEST") != "1":
        pytest.skip("Set AE_BROWSER_LIVE_TEST=1 for read-only local API checks")
    return browser_page
