"""Case-report PDF tests — the renderer (pure) + the download endpoint."""

from __future__ import annotations

from datetime import datetime

from app.schemas.api import AgentOutputItem, AuditItem, CaseDetail
from app.services.report_service import ReportService
from tests.test_api import FakeRepo, _client

_NOW = datetime(2026, 1, 1, 12, 0, 0)


def _detail() -> CaseDetail:
    return CaseDetail(
        case_id="c1",
        cluster_id="C_001",
        member_id="PT_19116",
        status="ESCALATED",
        decision="ESCALATE",
        decision_confidence=0.72,
        decision_justification="Fraud score 0.35 ≥ 0.30 → human review.",
        created_at=_NOW,
        updated_at=_NOW,
        agent_outputs=[
            AgentOutputItem(
                agent="FRAUD",
                output={"fraud_score": 0.35, "anomalies": ["duplicate_claim"]},
                confidence=0.8,
                created_at=_NOW,
            )
        ],
        audit_events=[
            AuditItem(actor="ORCHESTRATOR", event_type="COMPLETED", ts=_NOW),
        ],
    )


def test_render_produces_a_pdf() -> None:
    pdf = ReportService().render(_detail())
    assert pdf[:5] == b"%PDF-"
    assert len(pdf) > 500  # non-trivial document


def test_report_endpoint_serves_attachment() -> None:
    repo = FakeRepo()
    repo.cases["c1"] = {"status": "ESCALATED", "override": None, "decision": "ESCALATE"}
    client = _client(repo, role="REVIEWER")  # reviewer can view any case's report
    r = client.get("/api/cases/c1/report")
    assert r.status_code == 200
    assert r.headers["content-type"] == "application/pdf"
    assert "attachment" in r.headers["content-disposition"]
    assert r.headers["x-content-type-options"] == "nosniff"
    assert r.content[:5] == b"%PDF-"


def test_report_endpoint_404_for_missing_case() -> None:
    assert _client(FakeRepo(), role="REVIEWER").get("/api/cases/missing/report").status_code == 404
