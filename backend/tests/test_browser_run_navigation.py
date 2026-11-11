"""Actual browser/API/SQL navigation. Never submit generation or score fixtures."""

import asyncio
import os
import uuid
from datetime import UTC, datetime, timedelta

import pytest
from playwright.sync_api import expect, sync_playwright
from sqlalchemy import delete, select

from autoeval.config import get_settings
from autoeval.configuration import TestConfigItem as ConfigItem
from autoeval.configuration import TestConfigVersion as ConfigVersion
from autoeval.db import create_database
from autoeval.profiles import ConfigDatasetBinding
from autoeval.registry import Asset, AssetVersion, ModelConfigBinding
from autoeval.resources import ResourceBinding, ResourceProvider
from autoeval.targets import TargetBinding

pytestmark = pytest.mark.skipif(
    not os.environ.get("AE_BROWSER_URL") or not os.environ.get("AE_REPORTS_TEST"),
    reason="Real browser, PostgreSQL and prior real report required",
)


def test_report_to_direct_run_snapshot_case_history_and_reload():
    with sync_playwright() as playwright:
        browser = playwright.chromium.launch(
            executable_path=os.environ.get("AE_CHROME_PATH") or None, headless=True
        )
        try:
            page = browser.new_page()
            errors = []
            page.on("pageerror", lambda error: errors.append(str(error)))
            base = os.environ["AE_BROWSER_URL"]
            reports = page.request.get(base + "/api/autoeval/v1/reports?limit=1").json()["data"]
            assert reports
            report = reports[0]
            page.goto(base + "/#report/" + report["id"])
            page.get_by_role("link", name="查看来源任务与case历史", exact=True).click()
            expect(page).to_have_url(base + "/#run/" + report["run_id"])
            expect(page.get_by_test_id("evaluation-detail")).to_be_visible()
            meta = page.get_by_test_id("evaluation-detail").locator(".execution-meta")
            expect(meta).to_contain_text("创建时间")
            expect(meta).to_contain_text("配置版本")
            expect(meta).to_contain_text("运行方式")
            page.get_by_text("本次冻结配置与证据标识", exact=True).click()
            expect(page.get_by_test_id("run-snapshot")).to_contain_text(report["snapshot_sha256"])
            history = page.get_by_test_id("evaluation-detail")
            expect(history.get_by_label("回溯运行ID", exact=True)).to_have_value(report["run_id"])
            history.get_by_role("button", name="查看第1次证据", exact=True).first.click()
            attempts = page.request.get(
                base + f"/api/autoeval/v1/runs/{report['run_id']}/case-executions?limit=1"
            ).json()["data"]
            original = page.request.get(
                base + f"/api/autoeval/v1/case-executions/{attempts[0]['id']}/evidence"
            )
            if original.status == 200:
                expect(history.get_by_test_id("case-evidence")).to_contain_text("case-evidence.v1")
            else:
                assert original.status == 503
                expect(history.get_by_role("status")).to_contain_text(
                    "Evidence missing or integrity check failed"
                )
                expect(history.get_by_test_id("case-evidence")).to_have_count(0)
            page.reload()
            expect(page.get_by_test_id("evaluation-detail")).to_contain_text(report["run_id"])
            expect(page.get_by_label("回溯运行ID", exact=True)).to_have_value(report["run_id"])
            page.get_by_role("link", name="查看完整报告", exact=True).click()
            expect(page).to_have_url(base + "/#report/" + report["id"])
            expect(page.get_by_test_id("real-report-detail")).to_be_visible()
            page.goto(base + "/#run/" + str(uuid.uuid4()))
            expect(
                page.get_by_text(
                    "任务不存在或查询失败；已显示的状态可能过期，请勿据此重新提交。", exact=True
                )
            ).to_be_visible()
            expect(page.get_by_test_id("evaluation-detail")).to_have_count(0)
            assert errors == []
        finally:
            browser.close()


async def seed_options(prefix):
    engine, sessions = create_database(get_settings())
    try:
        async with sessions() as session, session.begin():
            source = (
                await session.execute(
                    select(ConfigItem, ConfigDatasetBinding)
                    .join(
                        ConfigDatasetBinding, ConfigDatasetBinding.config_item_id == ConfigItem.id
                    )
                    .where(
                        ConfigItem.dataset_key == "GPQA",
                        ConfigItem.parameter_values["scope"].astext == "Lite",
                    )
                    .order_by(ConfigItem.created_at.desc())
                    .limit(1)
                )
            ).one()
            item, binding = source
            model = Asset(asset_key=prefix, kind="model", name=prefix)
            provider = ResourceProvider(name=prefix, kind="docker_local")
            session.add_all([model, provider])
            await session.flush()
            version = AssetVersion(asset_id=model.id, version="navigation-v1", metadata_json={})
            session.add(version)
            await session.flush()
            ids = {"model": str(model.id), "configs": []}
            ordered_at = datetime.now(UTC) + timedelta(hours=1)
            for index in range(23):
                config = ConfigVersion(
                    config_key=prefix + str(index),
                    display_name=prefix + str(index),
                    version=1,
                    version_label="v1",
                    kind="custom",
                    content_hash="a" * 64,
                    created_by="navigation-fixture",
                )
                target = TargetBinding(
                    model_version_id=version.id,
                    base_url="https://api.deepseek.com",
                    remote_model="deepseek-flash",
                    credential_ref="0" * 32,
                )
                resource = ResourceBinding(
                    provider_id=provider.id,
                    binding_key=prefix + str(index),
                    version=1,
                    container_id="0" * 64,
                    image_id="sha256:" + "0" * 64,
                )
                session.add_all([config, target, resource])
                for row in (config, target, resource):
                    row.created_at = ordered_at + timedelta(seconds=index)
                await session.flush()
                config_item = ConfigItem(
                    config_version_id=config.id,
                    dataset_key="GPQA",
                    parameter_values=item.parameter_values,
                )
                session.add(config_item)
                await session.flush()
                session.add(
                    ConfigDatasetBinding(
                        config_item_id=config_item.id,
                        profile_id=binding.profile_id,
                        manifest_id=binding.manifest_id,
                    )
                )
                if index < 2:
                    ids["configs"].append(str(config.id))
                if index == 0:
                    ids.update(target=str(target.id), resource=str(resource.id))
            session.add(
                ModelConfigBinding(
                    model_asset_id=model.id, default_config_version_id=uuid.UUID(ids["configs"][0])
                )
            )
        return ids
    finally:
        await engine.dispose()


async def remove_options(prefix):
    engine, sessions = create_database(get_settings())
    try:
        async with sessions() as session, session.begin():
            model_ids = select(Asset.id).where(Asset.asset_key == prefix)
            versions = select(AssetVersion.id).where(AssetVersion.asset_id.in_(model_ids))
            configs = select(ConfigVersion.id).where(ConfigVersion.config_key.like(prefix + "%"))
            items = select(ConfigItem.id).where(ConfigItem.config_version_id.in_(configs))
            await session.execute(
                delete(TargetBinding).where(TargetBinding.model_version_id.in_(versions))
            )
            await session.execute(
                delete(ModelConfigBinding).where(ModelConfigBinding.model_asset_id.in_(model_ids))
            )
            await session.execute(delete(AssetVersion).where(AssetVersion.asset_id.in_(model_ids)))
            await session.execute(delete(Asset).where(Asset.id.in_(model_ids)))
            await session.execute(
                delete(ConfigDatasetBinding).where(ConfigDatasetBinding.config_item_id.in_(items))
            )
            await session.execute(
                delete(ConfigItem).where(ConfigItem.config_version_id.in_(configs))
            )
            await session.execute(delete(ConfigVersion).where(ConfigVersion.id.in_(configs)))
            providers = select(ResourceProvider.id).where(ResourceProvider.name == prefix)
            await session.execute(
                delete(ResourceBinding).where(ResourceBinding.provider_id.in_(providers))
            )
            await session.execute(
                delete(ResourceProvider).where(ResourceProvider.id.in_(providers))
            )
    finally:
        await engine.dispose()


def test_service_launch_default_reload_and_cross_page_retry_without_backend_submission():
    prefix = "nav-browser-" + uuid.uuid4().hex[:12]
    ids = asyncio.run(seed_options(prefix))
    try:
        with sync_playwright() as playwright:
            browser = playwright.chromium.launch(
                executable_path=os.environ.get("AE_CHROME_PATH") or None, headless=True
            )
            try:
                page = browser.new_page()
                submitted = []
                page.on(
                    "request",
                    lambda request: (
                        submitted.append(request.url)
                        if request.method == "POST" and request.url.endswith("/runs")
                        else None
                    ),
                )
                base = os.environ["AE_BROWSER_URL"]
                page.goto(base + "/#console")
                panel = page.get_by_label("真实服务绑定", exact=True)
                panel.locator("summary").click()
                panel.get_by_role("button", name="下一页服务", exact=True).click()
                panel.get_by_label("已保存真实服务", exact=True).select_option(ids["target"])
                panel.get_by_role("link", name="使用此服务创建探索测评", exact=True).click()
                expect(page.get_by_label("探索模型服务", exact=True)).to_have_value(ids["target"])
                expect(page.get_by_label("探索配置", exact=True)).to_have_value(ids["configs"][0])
                page.get_by_role("button", name="下一页探索配置", exact=True).click()
                expect(page.get_by_label("探索配置", exact=True)).to_have_value(ids["configs"][0])
                page.get_by_role("button", name="下一页探索资源", exact=True).click()
                page.get_by_label("探索执行资源", exact=True).select_option(ids["resource"])
                page.get_by_role("button", name="上一页探索资源", exact=True).click()
                expect(page.get_by_label("探索执行资源", exact=True)).to_have_value(ids["resource"])
                # Explicit transport fixture: intercept before the backend, so no
                # task, outbox or billable request is created by these two clicks.
                retry_keys = []

                def lost_ack(route):
                    assert route.request.method == "POST"
                    retry_keys.append(route.request.headers["idempotency-key"])
                    route.fulfill(
                        status=503,
                        content_type="application/json",
                        body='{"error":{"message":"SUBMISSION_ACK_UNAVAILABLE_FIXTURE"}}',
                    )

                page.route("**/api/autoeval/v1/runs", lost_ack)
                page.get_by_role("button", name="提交真实GPQA Lite测评", exact=True).click()
                expect(
                    page.get_by_text("SUBMISSION_ACK_UNAVAILABLE_FIXTURE", exact=True)
                ).to_be_visible()
                page.reload()
                expect(page.get_by_label("探索配置", exact=True)).to_have_value(ids["configs"][0])
                page.get_by_role("button", name="下一页探索资源", exact=True).click()
                page.get_by_label("探索执行资源", exact=True).select_option(ids["resource"])
                page.get_by_role("button", name="提交真实GPQA Lite测评", exact=True).click()
                expect(
                    page.get_by_text("SUBMISSION_ACK_UNAVAILABLE_FIXTURE", exact=True)
                ).to_be_visible()
                assert len(retry_keys) == 2 and retry_keys[0] == retry_keys[1]
                response = page.request.put(
                    base + f"/api/autoeval/v1/models/{ids['model']}/default-test-config",
                    headers={"If-Match": "1"},
                    data={"config_version_id": ids["configs"][1]},
                )
                assert response.status == 200
                page.get_by_role("button", name="重新加载模型默认配置", exact=True).click()
                expect(page.get_by_label("探索配置", exact=True)).to_have_value(ids["configs"][1])
                page.reload()
                expect(page.get_by_label("探索模型服务", exact=True)).to_have_value(ids["target"])
                expect(page.get_by_label("探索配置", exact=True)).to_have_value(ids["configs"][1])
                expect(
                    page.get_by_role("button", name="提交真实GPQA Lite测评", exact=True)
                ).to_be_disabled()
                assert len(submitted) == 2  # Both intercepted; none dispatched to backend.
            finally:
                browser.close()
    finally:
        asyncio.run(remove_options(prefix))
