"""LangGraph StateGraph assembling the full pipeline.

classify → [needs_human?] → preprocess → aggregate
        → (kyc ∥ claims ∥ policy) → fraud → orchestrate → [ESCALATE?] → await_human

`await_human` is guarded by `interrupt_before` so the graph pauses there for the
API to resume (HITL, Phase 5). Requires a checkpointer for interrupts to work.
"""

from __future__ import annotations

from typing import Any

from langgraph.graph import END, StateGraph

from app.agents.classifier import needs_human_review
from app.agents.state import PipelineDeps, PipelineState
from app.core.logging import get_logger
from app.schemas.agents import (
    ClaimsOutput,
    FraudOutput,
    KYCOutput,
    PolicyOutput,
    as_float,
    as_list,
)
from app.schemas.agents import ClassifierOutput as _ClassifierOutput
from app.schemas.enums import DocumentType
from app.services.image_forensics import ForensicsError

logger = get_logger(__name__)


def _tamper_suspected(deps: PipelineDeps, data: bytes) -> bool:
    """ELA tamper check on an ID image; unreadable input can't prove tampering."""
    try:
        return deps.forensics.is_tampered(data)
    except ForensicsError:
        logger.warning("ela_skip_undecodable_id")  # fail-open on detection only
        return False


def build_pipeline(deps: PipelineDeps, checkpointer: Any | None = None) -> Any:
    """Compile the pipeline graph with the injected agents/services."""

    async def classify(state: PipelineState) -> dict:
        docs = state["documents"]
        needs_human = False
        events: list[str] = []
        for d in docs:
            data = await deps.storage.get(d["storage_key"])
            out: _ClassifierOutput = await deps.classifier.classify(
                data,
                image_mime=d.get("mime", "image/png"),
                case_id=state["case_id"],
                document_id=d["doc_id"],
            )
            d["doc_type"] = out.doc_type.value
            d["classify_confidence"] = out.confidence
            if out.doc_type == DocumentType.ID_DOCUMENT:
                d["tamper_suspected"] = _tamper_suspected(deps, data)
            needs_human = needs_human or needs_human_review(out)
            events.append(f"classified:{d['doc_id']}={out.doc_type.value}")
        return {
            "documents": docs,
            "needs_human": needs_human,
            "agent_events": events,
            "current_stage": "CLASSIFIED",
        }

    def route_after_classify(state: PipelineState) -> str:
        return "await_human" if state.get("needs_human") else "preprocess"

    async def preprocess(state: PipelineState) -> dict:
        docs = state["documents"]
        events: list[str] = []
        for d in docs:
            dt = DocumentType(d.get("doc_type", DocumentType.UNKNOWN.value))
            data = await deps.storage.get(d["storage_key"])
            content = await deps.preprocessor.run(
                dt,
                data,
                mime=d.get("mime", "image/png"),
                case_id=state["case_id"],
                document_id=d["doc_id"],
            )
            d["content"] = content.model_dump(mode="json")
            events.append(f"preprocessed:{d['doc_id']}")
        return {"documents": docs, "agent_events": events, "current_stage": "PREPROCESSED"}

    def aggregate(state: PipelineState) -> dict:
        identity: dict = {}
        claim_fields: dict = {}
        cpt: list[str] = []
        icd: list[str] = []
        discharge = None
        claim_count = 0
        for d in state["documents"]:
            fields = (d.get("content") or {}).get("fields") or {}
            dt = d.get("doc_type")
            if dt == DocumentType.ID_DOCUMENT.value:
                identity.setdefault("name", fields.get("full_name") or fields.get("name"))
                if d.get("tamper_suspected"):
                    identity["tamper_suspected"] = True
            elif dt == DocumentType.CLAIM_FORM.value:
                claim_count += 1
                claim_fields = fields
                identity.setdefault("member_id", fields.get("member_id"))
                identity.setdefault("policy_number", fields.get("policy_number"))
                # Claim forms carry the patient name too — forward it so KYC can
                # resolve a member even without an ID doc in the bundle.
                identity.setdefault("name", fields.get("patient_name") or fields.get("full_name"))
                cpt = as_list(fields.get("cpt_codes") or fields.get("cpt_code"))
                icd = as_list(fields.get("icd_codes") or fields.get("icd_code"))
            elif dt == DocumentType.DISCHARGE_SUMMARY.value:
                discharge = fields.get("discharge_date")
        procedure = {"cpt": cpt, "icd": icd, "text": str(claim_fields.get("provider_name", ""))}
        fraud_context = {
            "member_id": identity.get("member_id"),
            "claim_doc_count": claim_count,
            "claim_amount": as_float(claim_fields.get("claim_amount")),
            "cpt_codes": cpt,
            "icd_codes": icd,
            "service_date": claim_fields.get("service_date"),
            "discharge_date": discharge,
        }
        return {
            "identity": identity,
            "claim_fields": claim_fields,
            "procedure": procedure,
            "fraud_context": fraud_context,
            "current_stage": "AGGREGATED",
        }

    async def kyc_node(state: PipelineState) -> dict:
        out = await deps.kyc.run(state["identity"], case_id=state["case_id"])
        return {"kyc": out.model_dump(mode="json"), "agent_events": ["kyc"]}

    async def claims_node(state: PipelineState) -> dict:
        out = await deps.claims.run(state["claim_fields"], case_id=state["case_id"])
        return {"claims": out.model_dump(mode="json"), "agent_events": ["claims"]}

    async def policy_node(state: PipelineState) -> dict:
        p = state["procedure"]
        out = await deps.policy.check(
            p["cpt"], p["icd"], p.get("text", ""), case_id=state["case_id"]
        )
        return {"policy": out.model_dump(mode="json"), "agent_events": ["policy"]}

    async def fraud_node(state: PipelineState) -> dict:
        ctx = dict(state.get("fraud_context") or {})
        ctx["kyc_flags"] = (state.get("kyc") or {}).get("flags", [])
        out = await deps.fraud.run(ctx, case_id=state["case_id"])
        return {"fraud": out.model_dump(mode="json"), "agent_events": ["fraud"]}

    def orchestrate(state: PipelineState) -> dict:
        out = deps.orchestrator(
            KYCOutput.model_validate(state["kyc"]),
            ClaimsOutput.model_validate(state["claims"]),
            PolicyOutput.model_validate(state["policy"]),
            FraudOutput.model_validate(state["fraud"]),
        )
        return {
            "decision": out.decision.value,
            "decision_confidence": out.confidence,
            "decision_justification": out.justification,
            "agent_summaries": out.agent_summaries,
            "current_stage": "DECIDED",
        }

    def route_after_orchestrate(state: PipelineState) -> str:
        return "await_human" if state.get("decision") == "ESCALATE" else END

    def await_human(state: PipelineState) -> dict:
        return {"current_stage": "AWAITING_HUMAN"}

    g = StateGraph(PipelineState)
    for name, fn in [
        ("classify", classify),
        ("preprocess", preprocess),
        ("aggregate", aggregate),
        ("kyc", kyc_node),
        ("claims", claims_node),
        ("policy", policy_node),
        ("fraud", fraud_node),
        ("orchestrate", orchestrate),
        ("await_human", await_human),
    ]:
        g.add_node(name, fn)

    g.set_entry_point("classify")
    g.add_conditional_edges(
        "classify",
        route_after_classify,
        {"await_human": "await_human", "preprocess": "preprocess"},
    )
    g.add_edge("preprocess", "aggregate")
    for specialist in ("kyc", "claims", "policy"):
        g.add_edge("aggregate", specialist)
        g.add_edge(specialist, "fraud")
    g.add_edge("fraud", "orchestrate")
    g.add_conditional_edges(
        "orchestrate",
        route_after_orchestrate,
        {"await_human": "await_human", END: END},
    )
    g.add_edge("await_human", END)

    return g.compile(checkpointer=checkpointer, interrupt_before=["await_human"])
