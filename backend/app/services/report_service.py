"""Case-report PDF export (Phase 8 bonus — FR-18).

Renders a `CaseDetail` (decision + per-agent evidence + audit trail) into a PDF
for the Compliance persona's audit needs. This is the *authorized* case-detail
export, so full values are included (unlike masked list views); it is served
read-only as an attachment (`nosniff`) by the API layer.

Pure and injectable: `render(detail) -> bytes`, no I/O, unit-testable.
"""

from __future__ import annotations

from typing import Any

from fpdf import FPDF

from app.schemas.api import AgentOutputItem, AuditItem, CaseDetail

_TITLE = "PolicyFlow AI — Case Report"


def _safe(text: object) -> str:
    """Core PDF fonts are latin-1 only; degrade gracefully rather than crash."""
    return str(text).encode("latin-1", "replace").decode("latin-1")


def _fmt_value(value: Any) -> str:
    if isinstance(value, list):
        return ", ".join(str(v) for v in value) if value else "—"
    if isinstance(value, float):
        return f"{value:.3f}"
    if value is None or value == "":
        return "—"
    return str(value)


class ReportService:
    def render(self, detail: CaseDetail) -> bytes:
        pdf = FPDF()
        pdf.set_auto_page_break(auto=True, margin=15)
        pdf.add_page()

        self._title(pdf)
        self._summary(pdf, detail)
        for output in detail.agent_outputs:
            self._agent_section(pdf, output)
        self._audit(pdf, detail.audit_events)

        return bytes(pdf.output())

    # -- sections ----------------------------------------------------------
    def _title(self, pdf: FPDF) -> None:
        pdf.set_font("Helvetica", "B", 16)
        pdf.cell(0, 10, _safe(_TITLE), new_x="LMARGIN", new_y="NEXT")
        pdf.ln(2)

    def _summary(self, pdf: FPDF, detail: CaseDetail) -> None:
        decision = detail.override_decision or detail.decision or "PENDING"
        rows = [
            ("Case ID", detail.case_id),
            ("Cluster", detail.cluster_id),
            ("Member", detail.member_id),
            ("Status", detail.status),
            ("Decision", decision),
            ("Confidence", _fmt_value(detail.decision_confidence)),
            ("Created", detail.created_at),
        ]
        pdf.set_font("Helvetica", "B", 12)
        pdf.cell(0, 8, "Decision Summary", new_x="LMARGIN", new_y="NEXT")
        pdf.set_font("Helvetica", size=10)
        for label, value in rows:
            pdf.cell(35, 6, _safe(f"{label}:"))
            pdf.cell(0, 6, _safe(_fmt_value(value)), new_x="LMARGIN", new_y="NEXT")
        if detail.decision_justification:
            pdf.ln(1)
            pdf.multi_cell(0, 6, _safe(f"Justification: {detail.decision_justification}"))
        if detail.override_decision:
            pdf.multi_cell(
                0,
                6,
                _safe(f"Human override by {detail.override_by}: {detail.override_reason}"),
            )
        pdf.ln(3)

    def _agent_section(self, pdf: FPDF, output: AgentOutputItem) -> None:
        pdf.set_font("Helvetica", "B", 12)
        conf = _fmt_value(output.confidence)
        pdf.cell(0, 8, _safe(f"{output.agent}  (confidence {conf})"), new_x="LMARGIN", new_y="NEXT")
        pdf.set_font("Helvetica", size=10)
        for key, value in (output.output or {}).items():
            pdf.set_x(pdf.l_margin)
            pdf.multi_cell(0, 6, _safe(f"{key}: {_fmt_value(value)}"))
        pdf.ln(2)

    def _audit(self, pdf: FPDF, events: list[AuditItem]) -> None:
        pdf.set_font("Helvetica", "B", 12)
        pdf.cell(0, 8, "Audit Trail", new_x="LMARGIN", new_y="NEXT")
        pdf.set_font("Helvetica", size=9)
        for ev in events:
            line = f"{ev.ts:%Y-%m-%d %H:%M:%S}  {ev.actor}  {ev.event_type}"
            pdf.multi_cell(0, 5, _safe(line))
