"""Register requested benchmark identity without claiming tool or dataset availability."""

import asyncio

from sqlalchemy import select, text

from autoeval.config import get_settings
from autoeval.db import create_database
from autoeval.registry import Asset, AssetVersion


async def register():
    engine, sessions = create_database(get_settings())
    try:
        async with sessions() as session, session.begin():
            await session.execute(
                text("SELECT pg_advisory_xact_lock(hashtext('dataset:AutomationBench'))")
            )
            asset = await session.scalar(select(Asset).where(Asset.asset_key == "AutomationBench"))
            if asset is None:
                asset = Asset(asset_key="AutomationBench", kind="dataset", name="AutomationBench")
                session.add(asset)
                await session.flush()
            if asset.kind != "dataset":
                raise ValueError("Asset identity already belongs to another kind")
            existing = await session.scalar(
                select(AssetVersion).where(
                    AssetVersion.asset_id == asset.id, AssetVersion.version == "registration.v1"
                )
            )
            if existing is None:
                session.add(
                    AssetVersion(
                        asset_id=asset.id,
                        version="registration.v1",
                        metadata_json={
                            "registration_status": "pending_verification",
                            "category": "Agent 工作流",
                            "aisbench_supported": False,
                            "execution_enabled": False,
                            "source": "user_requested_registration",
                            "dataset_version": None,
                            "notes": "仅登记名称。工具实现、来源、数据版本、评分及样本清单待核验；不等同 DeepSWE。",
                        },
                    )
                )
        print("AutomationBench registered; AISBench support unverified; execution disabled")
    finally:
        await engine.dispose()


if __name__ == "__main__":
    asyncio.run(register())
