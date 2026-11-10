"""Read existing real evidence; no simulated record is labeled real by this test."""

import os

import httpx
import pytest
from sqlalchemy import select

from autoeval.api import create_app
from autoeval.evaluations import EvaluationReport

pytestmark = pytest.mark.skipif(
    not os.environ.get("AE_REPORTS_TEST"), reason="Verified real report required"
)


async def test_report_catalog_excludes_unverified_and_simulated_artifacts():
    app = create_app()
    async with (
        app.router.lifespan_context(app),
        httpx.AsyncClient(transport=httpx.ASGITransport(app=app), base_url="http://test") as api,
    ):
        async with app.state.sessions() as session:
            real = await session.scalar(
                select(EvaluationReport).where(EvaluationReport.execution_origin == "real").limit(1)
            )
            hidden = (
                await session.scalars(
                    select(EvaluationReport)
                    .where(EvaluationReport.execution_origin != "real")
                    .limit(10)
                )
            ).all()
            assert real is not None and hidden, "Real report plus test artifacts required"
        response = await api.get("/api/autoeval/v1/reports?limit=200")
        assert response.status_code == 200
        rows = response.json()["data"]
        assert all(r["execution_origin"] == "real" for r in rows)
        ids = {r["id"] for r in rows}
        assert not ids.intersection(str(r.id) for r in hidden)
        for report in hidden:
            assert (await api.get(f"/api/autoeval/v1/reports/{report.id}")).status_code == 404
        detail = await api.get(f"/api/autoeval/v1/reports/{real.id}")
        assert detail.json()["data"]["sha256"] == real.sha256
        evidence = await api.get(f"/api/autoeval/v1/reports/{real.id}/evidence")
        assert evidence.status_code == 200
        assert evidence.json()["data"]["snapshot_sha256"] == real.snapshot_sha256
        assert (await api.get("/api/autoeval/v1/reports?limit=0")).status_code == 422
