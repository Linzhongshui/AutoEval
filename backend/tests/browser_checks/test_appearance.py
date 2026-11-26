"""Browser-local appearance preferences, using synthetic read responses."""

import json
import re
from pathlib import Path
from urllib.parse import urlsplit

import pytest
from playwright.sync_api import expect

KEY = "autoeval.appearance.v1"
VERSION = json.loads((Path(__file__).resolve().parents[3] / "frontend/package.json").read_text())[
    "version"
]


def mock_reads(page, workbench=False):
    def respond(route):
        assert route.request.method == "GET"
        path = route.request.url
        if "/system/capabilities" in path:
            data = {"evaluation_enabled": True, "data_workbench_enabled": workbench}
        elif "/planning/options" in path:
            data = {"compilations": [], "manifests": [], "curves": []}
        elif urlsplit(path).path.endswith(
            ("/target-bindings", "/resources", "/ssh-resources", "/reports")
        ):
            data = []
        else:
            # Detail pages may request an individual record. Exercise their missing-data state.
            return route.fulfill(status=404, json={"error": {"message": "无测试记录"}})
        return route.fulfill(json={"data": data, "next_offset": None})

    page.route("**/api/**", respond)


def settings(page):
    page.get_by_role("button", name="外观设置", exact=True).click()
    return page.get_by_role("dialog", name="外观设置")


def test_layouts_and_form_state(browser_page):
    page, url, artifacts = browser_page
    mock_reads(page, workbench=True)
    page.set_viewport_size({"width": 1440, "height": 960})
    page.goto(url + "/#console")
    checkbox = page.get_by_role("checkbox", name="启用 GPQA", exact=True)
    checkbox.check()
    nav = page.get_by_role("navigation", name="主菜单")
    expect(nav.get_by_role("link", name="数据工作台")).to_be_visible()
    for layout, label in [("sidebar", "左侧文字栏"), ("rail", "左侧图标栏"), ("top", "顶部横栏")]:
        dialog = settings(page)
        expect(dialog.get_by_text(f"AutoEval v{VERSION}")).to_be_visible()
        dialog.get_by_label(label).press("Space")
        expect(dialog.get_by_label(label)).to_be_checked()
        preset = {"sidebar": "紫色", "rail": "蓝色", "top": "青绿色"}[layout]
        dialog.get_by_role("button", name=preset).press("Enter")
        page.keyboard.press("Escape")
        expect(page.get_by_role("button", name="外观设置", exact=True)).to_be_focused()
        expect(checkbox).to_be_checked()
        expect(page).to_have_url(url + "/#console")
        assert (
            page.locator(".main").bounding_box()["x"]
            == {"sidebar": 232, "rail": 72, "top": 0}[layout]
        )
        if layout == "rail":
            link = nav.get_by_role("link", name="任务管理")
            link.focus()
            expect(link.locator(".menu-label")).to_be_visible()
        page.screenshot(path=artifacts / f"appearance-{layout}.png")

    dialog = settings(page)
    dialog.get_by_label("左侧图标栏").check()
    page.keyboard.press("Escape")
    for width in [601, 600, 390, 1024]:
        page.set_viewport_size({"width": width, "height": 900})
        assert page.locator(".main").bounding_box()["x"] == (72 if width > 600 else 0)
        if width <= 600:
            expect(nav.get_by_text("控制台")).to_be_visible()
            expect(page.get_by_role("button", name="外观设置", exact=True)).to_be_in_viewport()
            assert nav.evaluate("n => n.scrollWidth > n.clientWidth")
            if width == 390:
                page.screenshot(path=artifacts / "appearance-mobile.png")
    for route, label in [
        ("run/missing", "任务管理"),
        ("report/missing", "报告管理"),
        ("config/model", "测评配置"),
    ]:
        page.goto(url + "/#" + route)
        expect(nav.get_by_role("link", name=label)).to_have_attribute("aria-current", "page")


def relative_luminance(color):
    rgb = [int(channel) / 255 for channel in re.findall(r"\d+", color)[:3]]
    linear = [v / 12.92 if v <= 0.04045 else ((v + 0.055) / 1.055) ** 2.4 for v in rgb]
    return sum(v * weight for v, weight in zip(linear, [0.2126, 0.7152, 0.0722], strict=True))


def test_theme_reaches_badges_and_open_picker(browser_page):
    page, url, _ = browser_page
    mock_reads(page)
    page.goto(url + "/#leaderboard")
    dialog = settings(page)
    dialog.get_by_role("button", name="青绿色").click()
    page.keyboard.press("Escape")
    ink = page.locator(".sidebar .selected svg").evaluate("e => getComputedStyle(e).color")
    expect(page.locator(".breadcrumb .badge")).to_have_css("color", ink)
    expect(page.get_by_role("button", name="外观设置")).to_have_css("color", ink)
    source = page.locator(".leaderboard-filters select").filter(
        has=page.locator('option[value="official"]')
    )
    if page.evaluate("CSS.supports('appearance', 'base-select')"):
        source.click()
        expect(source.locator("option:checked")).to_have_css("color", ink)
        page.get_by_role("option", name="官方公开成绩").click()
    else:
        source.select_option("official")
    expect(source).to_have_value("official")


def contrast(a, b):
    light, dark = sorted([relative_luminance(a), relative_luminance(b)], reverse=True)
    return (light + 0.05) / (dark + 0.05)


def test_color_contrast_persistence_and_reset(browser_page):
    page, url, _ = browser_page
    mock_reads(page)
    page.goto(url + "/#home")
    expect(page.get_by_role("link", name="数据工作台")).to_have_count(0)
    expect(page.locator(".sidebar-foot")).to_contain_text(f"v{VERSION}")
    dialog = settings(page)
    field = dialog.get_by_label("自定义颜色")
    for label, color in [("青绿色", "#0f766e"), ("蓝色", "#2563eb"), ("金黄色", "#ffd700")]:
        dialog.get_by_role("button", name=label).click()
        expect(field).to_have_value(color)
    for color in ["#ffffff", "#000000"]:
        dialog.get_by_label("取色器").fill(color)
        expect(field).to_have_value(color)
        button = page.locator(".overview-hero .primary")
        fg, bg = button.evaluate(
            "e => [getComputedStyle(e).color, getComputedStyle(e).backgroundColor]"
        )
        assert contrast(fg, bg) >= 4.5
        link_color = page.locator(".link").last.evaluate("e => getComputedStyle(e).color")
        assert contrast(link_color, "rgb(255,255,255)") >= 4.5
        field.focus()
        page.keyboard.press("Tab")
        outline = page.locator(":focus").evaluate("e => getComputedStyle(e).outlineColor")
        assert contrast(outline, "rgb(255,255,255)") >= 3
    field.fill("#dc920a")
    field.fill("invalid")
    expect(field).to_have_attribute("aria-invalid", "true")
    expect(dialog.get_by_role("status")).to_be_visible()
    dialog.get_by_role("radio", name="顶部横栏").check()
    page.reload()
    dialog = settings(page)
    expect(dialog.get_by_label("自定义颜色")).to_have_value("#dc920a")
    expect(dialog.get_by_role("radio", name="顶部横栏")).to_be_checked()
    dialog.get_by_role("button", name="恢复默认").click()
    expect(dialog.get_by_role("radio", name="左侧文字栏")).to_be_checked()
    expect(dialog.get_by_label("自定义颜色")).to_have_value("#5138ff")


@pytest.mark.parametrize(
    ("stored", "layout", "color"),
    [
        ("{", "sidebar", "#5138ff"),
        (json.dumps({"color": "invalid", "layout": "top"}), "top", "#5138ff"),
        (json.dumps({"color": "#123456", "layout": ["rail"]}), "sidebar", "#123456"),
    ],
    ids=["bad-json", "bad-color", "bad-layout"],
)
def test_invalid_preferences(browser_page, stored, layout, color):
    page, url, _ = browser_page
    mock_reads(page)
    page.add_init_script(f"localStorage.setItem('{KEY}', {json.dumps(stored)})")
    page.goto(url + "/#home")
    expect(page.locator("html")).to_have_attribute("data-menu-layout", layout)
    expect(settings(page).get_by_label("自定义颜色")).to_have_value(color)


def test_storage_unavailable(browser_page):
    page, url, _ = browser_page
    mock_reads(page)
    page.add_init_script("""Object.defineProperty(window, 'localStorage', {
        get() { throw new DOMException('disabled', 'SecurityError') }
    })""")
    page.goto(url + "/#home")
    dialog = settings(page)
    dialog.get_by_role("radio", name="顶部横栏").check()
    page.keyboard.press("Escape")
    expect(page.locator("html")).to_have_attribute("data-menu-layout", "top")
