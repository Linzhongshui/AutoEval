"""Exercise the real task page and API over a disposable database and executor volume."""

import json
import os
import uuid
from pathlib import Path
from urllib.parse import urlsplit

import asyncpg
import httpx
from playwright.async_api import async_playwright
from pydantic import SecretStr
from sqlalchemy.engine import make_url

from autoeval.catalog.registry import Asset, AssetVersion
from autoeval.entrypoints.api import create_app
from autoeval.evaluation.models import DatasetExecution, ExecutionRound, ExecutionShard
from autoeval.infrastructure.config import get_settings
from autoeval.infrastructure.models import Base, EvaluationRun, RunSnapshot
from autoeval.infrastructure.secrets import FileSecretStore
from autoeval.resources.models import (
    ResourceBinding,
    ResourceProvider,
    SSHResourceBinding,
    TargetBinding,
)


async def verify_task_page(
    tmp_path, binding, original_id, image_id, jobs, secret, recreate, connection
):
    source = make_url(get_settings().database_url.get_secret_value())
    dbname = "ae_files_test_" + uuid.uuid4().hex
    admin = await asyncpg.connect(
        host=source.host,
        port=source.port or 5432,
        user=source.username,
        password=source.password,
        database=source.database,
    )
    await admin.execute(f'CREATE DATABASE "{dbname}"')
    config = tmp_path / "container.json"
    settings = get_settings().model_copy(
        update={
            "database_url": SecretStr(
                source.set(database=dbname).render_as_string(hide_password=False)
            ),
            "planning_container_config": str(config),
            "secret_store_path": tmp_path / "secrets",
            "billing_execution_config": None,
        }
    )
    app = create_app(settings)
    try:
        async with app.router.lifespan_context(app):
            async with app.state.engine.begin() as conn:
                await conn.run_sync(Base.metadata.create_all)
            async with app.state.sessions() as session, session.begin():
                asset = Asset(asset_key="fixture", kind="model", name="Fixture")
                provider = ResourceProvider(name="local-docker", kind="docker_local")
                session.add_all([asset, provider])
                await session.flush()
                version = AssetVersion(asset_id=asset.id, version="fixture", metadata_json={})
                resource = ResourceBinding(
                    provider_id=provider.id,
                    binding_key="test",
                    version=1,
                    container_id=original_id,
                    image_id=image_id,
                )
                if connection:
                    resource = SSHResourceBinding(
                        provider_id=provider.id,
                        binding_key="fixture",
                        version=1,
                        **connection.model_dump(exclude={"owner_id", "credential"}),
                        credential_ref=FileSecretStore(settings.secret_store_path).put(
                            connection.credential.get_secret_value()
                        ),
                    )
                session.add_all([resource, version])
                await session.flush()
                config.write_text(
                    json.dumps(
                        {str(resource.id): {"container_id": original_id, "image_id": image_id}}
                    )
                )
                target = TargetBinding(
                    model_version_id=version.id,
                    base_url="https://fixture.invalid",
                    remote_model="fixture",
                    credential_ref=FileSecretStore(settings.secret_store_path).put(secret),
                )
                run = EvaluationRun(
                    trigger_scope="local-operator:orchestration",
                    idempotency_key="fixture",
                    request_hash="a" * 64,
                    state="completed",
                    run_mode="exploration",
                    created_by="test",
                )
                session.add_all([run, target])
                await session.flush()
                rid = str(run.id)
                task = {"task_id": "dataset", "dataset": "GPQA", "samples": []}
                inputs = {
                    "tasks": [task],
                    "resource_kind": "customer_ssh" if connection else "docker_local",
                    "resource_id": str(resource.id),
                    "target_id": str(target.id),
                }
                session.add(
                    RunSnapshot(
                        run_id=run.id,
                        schema_version="planned-run.v1",
                        sha256="a" * 64,
                        canonical_body={"inputs": inputs, "resource": {"debug_storage": binding}},
                    )
                )
                session.add(
                    DatasetExecution(
                        id=uuid.UUID(jobs[0]),
                        run_id=run.id,
                        task_id="dataset",
                        state="succeeded",
                        payload=task,
                    )
                )
                for number, job in enumerate(jobs[1:], 2):
                    follow = ExecutionRound(
                        run_id=run.id,
                        number=number,
                        source_number=number - 1,
                        operation="resume" if number == 2 else "case_retry",
                        actor="fixture",
                        snapshot_sha256="a" * 64,
                        scope_sha256="b" * 64,
                        selection={"samples": []},
                        state="completed",
                    )
                    session.add(follow)
                    await session.flush()
                    session.add(
                        ExecutionShard(
                            id=uuid.UUID(job),
                            round_id=follow.id,
                            position=0,
                            task_id="dataset",
                            state="failed",
                            payload=task,
                        )
                    )
            async with (
                httpx.AsyncClient(
                    transport=httpx.ASGITransport(app), base_url="http://test"
                ) as client,
                async_playwright() as pw,
            ):
                browser = await pw.chromium.launch(executable_path=os.getenv("AE_CHROME_PATH"))
                page = await browser.new_page()

                async def api(route):
                    assert route.request.method == "GET"
                    url = urlsplit(route.request.url)
                    response = await client.get(url.path, params=url.query)
                    await route.fulfill(
                        status=response.status_code,
                        content_type="application/json",
                        body=response.content,
                    )

                await page.route("**/api/autoeval/v1/**", api)
                await page.goto(os.environ["AE_BROWSER_URL"].rstrip("/") + "/#run/" + rid)
                await page.get_by_role("button", name="执行器原始文件", exact=True).click()
                panel = page.get_by_role("region", name="执行器原始文件")
                selector = panel.get_by_role("combobox")
                await panel.get_by_role("button", name="output/case.txt", exact=True).wait_for()
                assert await selector.input_value() == jobs[-1]
                await selector.select_option(jobs[0])
                artifacts = Path(__file__).resolve().parents[3] / ".screenshots" / "browser-checks"
                artifacts.mkdir(exist_ok=True, parents=True)
                await panel.get_by_role("button", name="output/case.txt", exact=True).wait_for()
                await panel.evaluate("el => el.scrollIntoView({block: 'start'})")
                await page.screenshot(path=artifacts / "executor-outputs.png")
                await panel.get_by_role("button", name="下一页").click()
                await panel.get_by_text(
                    "output/outputs/trial/config.json · 仅元信息", exact=True
                ).wait_for()
                await panel.get_by_role(
                    "button", name="output/outputs/trial/114.json", exact=True
                ).click()
                await panel.get_by_text("{}", exact=True).wait_for()
                sidebar = panel.get_by_role("dialog", name="文件预览")
                assert await panel.get_by_text("第 2 页", exact=True).is_visible()
                await panel.get_by_role("button", name="output/outputs/trial/113.json").click()
                await sidebar.get_by_text("output/outputs/trial/113.json", exact=True).wait_for()
                await sidebar.get_by_role("button", name="关闭预览").click()
                await panel.get_by_role("button", name="上一页").click()
                await panel.get_by_role("button", name="output/case.txt", exact=True).click()
                preview = panel.locator("pre")
                await preview.wait_for()
                original = await preview.text_content()
                assert original == "fixed prediction"
                recreate()
                async with page.expect_response(
                    lambda reply: "/executor-files/" in reply.url and "case.txt" in reply.url
                ):
                    await panel.get_by_role("button", name="刷新文件").click()
                await panel.get_by_text("fixed prediction", exact=True).wait_for()
                assert await preview.text_content() == original
                await panel.get_by_role("button", name="作业目录", exact=True).click()
                await panel.get_by_role("button", name="tool.log", exact=True).click()
                await panel.get_by_text("已截断", exact=False).wait_for()
                assert secret not in (await preview.text_content())
                assert await preview.evaluate(
                    "el => el.scrollHeight > el.clientHeight && el.scrollTop > 0"
                )
                await panel.screenshot(path=artifacts / "executor-files.png")
                recreate(True)
                await panel.get_by_role("button", name="刷新文件").click()
                await panel.get_by_role("dialog").get_by_text("当前挂载与任务记录不一致", exact=True).wait_for()
                recreate()
                base = f"/api/autoeval/v1/evaluation-tasks/{rid}/executor-files"
                assert (await client.get(base + "/" + str(uuid.uuid4()))).status_code == 404
                app.state.settings = settings.model_copy(update={"environment": "production"})
                assert (await client.get(base)).status_code == 403
                assert (await client.get(base + "/" + jobs[0])).status_code == 403
                await browser.close()
    finally:
        await admin.execute(f'DROP DATABASE "{dbname}" WITH (FORCE)')
        await admin.close()
