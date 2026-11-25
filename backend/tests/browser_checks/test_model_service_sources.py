from urllib.parse import urlsplit

import pytest
from playwright.sync_api import expect


@pytest.mark.parametrize("kind", ["local", "official"])
def test_configure_service_by_source(browser_page, kind):
    page, url, _ = browser_page
    services = []
    writes = []
    version_reads = 0
    labels = {"local": "标准本地模型服务", "official": "官方模型服务"}

    def mock(route):
        nonlocal version_reads
        path = urlsplit(route.request.url).path.split("/api/autoeval/v1")[-1]
        data = []
        if route.request.method == "POST":
            writes.append(path)
            if path == "/credentials":
                data = {"credential_ref": "fixture-ref"}
            elif path == "/target-bindings":
                body = route.request.post_data_json
                assert body["service_kind"] == kind
                assert body["model_version_id"] == "version"
                assert body["remote_model"] == "test-deployment"
                services.append({**body, "id": "binding", "service_name": "test-deployment"})
                data = {"id": "binding"}
        elif route.request.method == "PATCH" and path == "/target-bindings/binding":
            writes.append(path)
            if writes.count(path) == 1:
                route.fulfill(status=503, json={"error": {"message": "fixture"}})
                return
            services[0].update(route.request.post_data_json)
        elif path == "/target-bindings":
            data = services
        elif path == "/models":
            data = [{"id": "model", "model_id": "Team/Example", "name": "Example"}]
        elif path == "/models/model/versions":
            version_reads += 1
            if kind == "local" and version_reads == 1:
                route.fulfill(status=503, json={"error": {"message": "fixture"}})
                return
            data = [{"id": "version", "version": "v1"}]
        elif path == "/planning/options":
            data = {"compilations": [], "manifests": [], "curves": []}
        route.fulfill(json={"data": data, "next_offset": None})

    page.route("**/api/autoeval/v1/**", mock)
    page.goto(url + "/#console/performance")
    page.get_by_role("button", name="管理模型服务").click()
    page.get_by_role("button", name="新增服务").click()
    drawer = page.get_by_role("dialog", name="新增服务")
    local = drawer.get_by_role("button", name=labels["local"], exact=False)
    official = drawer.get_by_role("button", name=labels["official"], exact=False)
    expect(local).to_have_attribute("aria-pressed", "true")
    drawer.get_by_label("本地服务 Base URL").fill("https://example.invalid/v1")
    drawer.get_by_label("部署的模型名").fill("local-draft")
    drawer.get_by_label("本地服务访问密钥").fill("fixture-only")
    official.click()
    expect(drawer.get_by_label("厂商 API Base URL")).to_have_value("")
    expect(drawer.get_by_label("厂商模型 ID")).to_have_value("")
    expect(drawer.get_by_label("厂商 API Key")).to_have_value("")
    if kind == "local":
        local.click()
    assert writes == []
    model = drawer.locator("summary").nth(0)
    version = drawer.locator("summary").nth(1)
    expect(version).to_have_text("请先选择模型")
    expect(version).to_have_attribute("aria-disabled", "true")
    model.focus()
    model.press("Enter")
    drawer.get_by_label("服务绑定模型搜索").press("Escape")
    expect(model).to_be_focused()
    model.click()
    drawer.get_by_label("服务绑定模型", exact=True).select_option("model")
    if kind == "local":
        expect(version).to_have_text("读取版本失败")
        drawer.get_by_role("button", name="重新读取版本").click()
    expect(version).to_have_text("请选择模型版本")
    version.click()
    drawer.get_by_label("服务绑定模型版本", exact=True).select_option("version")
    drawer.get_by_label("本地服务 Base URL" if kind == "local" else "厂商 API Base URL").fill(
        "https://model.example.invalid/v1"
    )
    drawer.get_by_label("部署的模型名" if kind == "local" else "厂商模型 ID").fill("test-deployment")
    drawer.get_by_label("本地服务访问密钥" if kind == "local" else "厂商 API Key").fill("fixture")
    drawer.get_by_role("button", name="保存服务绑定").click()
    expect(drawer.get_by_text("服务绑定已保存，尚未检测。")).to_be_visible()
    drawer.get_by_role("button", name="关闭新增服务").click()
    manager = page.get_by_role("dialog", name="管理模型服务")
    manager.get_by_label("服务来源").select_option(kind)
    expect(manager.get_by_role("cell", name=labels[kind])).to_be_visible()
    manager.get_by_label("服务来源").select_option("official" if kind == "local" else "local")
    expect(manager.get_by_text("暂无匹配的模型服务")).to_be_visible()
    assert writes == ["/credentials", "/target-bindings"]
    manager.get_by_label("服务来源").select_option(kind)
    manager.get_by_role("button", name="编辑服务").click()
    editor = page.get_by_role("dialog", name="编辑服务")
    editor.get_by_label("服务名称").fill("updated-service")
    editor.get_by_role("button", name="保存").click()
    expect(editor.get_by_role("alert")).to_be_visible()
    editor.get_by_role("button", name="保存").click()
    expect(editor).to_have_count(0)
    expect(manager.get_by_text("updated-service", exact=False).first).to_be_visible()

@pytest.mark.parametrize("entry", ["accuracy", "performance", "direct"])
def test_use_saved_service(browser_page, entry):
    page, url, _ = browser_page
    row = {"id": "binding", "service_name": "Example", "remote_model": "Example",
           "service_kind": "local", "base_url": "https://model.invalid"}
    writes = []

    def mock(route):
        path = urlsplit(route.request.url).path
        if route.request.method != "GET":
            writes.append(path)
        data = [row] if path.endswith("/target-bindings") else []
        if path.endswith("/planning/options"):
            data = {"compilations": [], "manifests": [], "curves": []}
        route.fulfill(json={"data": data, "next_offset": None})

    page.route("**/api/autoeval/v1/**", mock)
    perf = entry == "performance"
    page.goto(url + ("/#console/performance" if perf else "/#console"))
    if entry == "direct":
        page.get_by_label("规划模型服务", exact=True).click()
        page.get_by_role("button", name="新增模型服务", exact=False).last.click()
    else:
        page.get_by_role("button", name="管理模型服务" if perf else "管理服务", exact=True).click()
        page.get_by_role("button", name="新增服务", exact=True).click()
    page.get_by_role("button", name="使用此服务").click()
    expect(page.get_by_role("dialog")).to_have_count(0)
    if perf:
        expect(page.get_by_label("模型服务", exact=True)).to_have_value("binding")
    else:
        expect(page.get_by_label("规划模型服务", exact=True)).to_contain_text("Example")
    assert writes == []
