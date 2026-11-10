"""Browser pagination through Vite, the real API and PostgreSQL."""

import asyncio
import os
import uuid

import pytest
from playwright.sync_api import expect, sync_playwright
from sqlalchemy import delete, select

from autoeval.config import get_settings
from autoeval.configuration import TestConfigItem as ConfigItem
from autoeval.configuration import TestConfigVersion as ConfigVersion
from autoeval.db import create_database
from autoeval.registry import Asset, AssetVersion
from autoeval.resources import ResourceBinding, ResourceProvider
from autoeval.targets import TargetBinding

PREFIX = "browser-page-" + uuid.uuid4().hex[:10]


async def seed():
    engine, sessions = create_database(get_settings())
    try:
        async with sessions() as session, session.begin():
            provider = ResourceProvider(name=PREFIX, kind="docker_local")
            session.add(provider)
            await session.flush()
            for index in range(21):
                key = f"{PREFIX}-{index:02d}"
                model = Asset(asset_key=key, kind="model", name=key)
                config = ConfigVersion(
                    config_key=key,
                    display_name=key,
                    version=1,
                    version_label="v1",
                    kind="custom",
                    content_hash="a" * 64,
                    created_by="browser-pagination-test",
                )
                session.add_all([model, config])
                await session.flush()
                session.add_all([
                    AssetVersion(asset_id=model.id, version="v1", metadata_json={}),
                    ConfigItem(
                        config_version_id=config.id,
                        dataset_key="GPQA",
                        parameter_values={
                            "output": 16,
                            "concurrency": 1,
                            "temperature": 0,
                            "top_p": 1,
                            "scope": "全量",
                        },
                    ),
                    ResourceBinding(
                        provider_id=provider.id,
                        binding_key=key,
                        version=1,
                        container_id="0" * 64,
                        image_id="sha256:" + "0" * 64,
                    ),
                ])
                await session.flush()
                version = await session.scalar(
                    select(AssetVersion).where(AssetVersion.asset_id == model.id)
                )
                session.add(
                    TargetBinding(
                        model_version_id=version.id,
                        base_url="https://api.deepseek.com",
                        remote_model=key,
                        credential_ref="0" * 32,
                    )
                )
    finally:
        await engine.dispose()


async def cleanup():
    engine, sessions = create_database(get_settings())
    try:
        async with sessions() as session, session.begin():
            model_ids = select(Asset.id).where(Asset.asset_key.like(PREFIX + "-%"))
            version_ids = select(AssetVersion.id).where(AssetVersion.asset_id.in_(model_ids))
            await session.execute(
                delete(TargetBinding).where(TargetBinding.model_version_id.in_(version_ids))
            )
            await session.execute(delete(AssetVersion).where(AssetVersion.asset_id.in_(model_ids)))
            await session.execute(delete(Asset).where(Asset.id.in_(model_ids)))
            config_ids = select(ConfigVersion.id).where(
                ConfigVersion.config_key.like(PREFIX + "-%")
            )
            await session.execute(
                delete(ConfigItem).where(ConfigItem.config_version_id.in_(config_ids))
            )
            await session.execute(
                delete(ConfigVersion).where(ConfigVersion.id.in_(config_ids))
            )
            await session.execute(
                delete(ResourceBinding).where(ResourceBinding.binding_key.like(PREFIX + "-%"))
            )
            await session.execute(delete(ResourceProvider).where(ResourceProvider.name == PREFIX))
    finally:
        await engine.dispose()


def turn_page(page, endpoint, select_label, next_name, previous_name):
    selector = page.get_by_label(select_label, exact=True)
    with page.expect_response(
        lambda response: (
            endpoint in response.url
            and "offset=20" in response.url
            and "limit=20" in response.url
            and response.request.method == "GET"
        )
    ) as response:
        page.get_by_role("button", name=next_name, exact=True).click()
    assert response.value.status == 200, response.value.text()
    row = response.value.json()["data"][0]
    expect(selector.locator(f'option[value="{row["id"]}"]')).to_have_count(1)
    with page.expect_response(
        lambda response: (
            endpoint in response.url
            and "offset=0" in response.url
            and "limit=20" in response.url
            and response.request.method == "GET"
        )
    ) as response:
        page.get_by_role("button", name=previous_name, exact=True).click()
    assert response.value.status == 200, response.value.text()
    row = response.value.json()["data"][0]
    expect(selector.locator(f'option[value="{row["id"]}"]')).to_have_count(1)


@pytest.mark.skipif(not os.environ.get("AE_BROWSER_URL"), reason="Live services required")
def test_browser_registry_pages_use_server_offsets():
    asyncio.run(seed())
    try:
        with sync_playwright() as playwright:
            browser = playwright.chromium.launch(
                executable_path=os.environ.get("AE_CHROME_PATH") or None, headless=True
            )
            try:
                page = browser.new_page()
                page.set_default_timeout(15000)
                errors = []
                page.on("pageerror", lambda error: errors.append(str(error)))
                page.goto(os.environ["AE_BROWSER_URL"] + "/#console")
                page.get_by_text("已登记模型与默认配置（真实后端）", exact=True).click()
                model_selector = page.get_by_label("已登记模型", exact=True)
                model_id = model_selector.locator("option").nth(1).get_attribute("value")
                model_selector.select_option(model_id)
                turn_page(
                    page, "/models?", "已登记模型", "下一页模型", "上一页模型"
                )
                expect(model_selector).to_have_value("")
                config_selector = page.get_by_label("绑定默认配置版本", exact=True)
                config_id = config_selector.locator("option").nth(1).get_attribute("value")
                config_selector.select_option(config_id)
                turn_page(
                    page,
                    "/test-configs?",
                    "绑定默认配置版本",
                    "下一页配置",
                    "上一页配置",
                )
                expect(config_selector).to_have_value("")
                page.get_by_text("真实模型服务绑定与连接检测", exact=True).click()
                turn_page(
                    page,
                    "/target-bindings?",
                    "已保存真实服务",
                    "下一页服务",
                    "上一页服务",
                )
                page.goto(os.environ["AE_BROWSER_URL"] + "/#tasks")
                turn_page(
                    page,
                    "/resources?",
                    "诊断执行资源",
                    "下一页资源",
                    "上一页资源",
                )
                assert not errors
            finally:
                browser.close()
    finally:
        asyncio.run(cleanup())
