import type { CaseDetail } from "@/lib/types";
import { StatusBadge } from "./StatusBadge";

export function DecisionPanel({ detail }: { detail: CaseDetail }) {
  return (
    <div className="stack">
      <div className="row spread">
        <strong>Decision</strong>
        <StatusBadge status={detail.status} />
      </div>
      <div className="row spread">
        <span className="muted">Automated</span>
        <span>
          {detail.decision ?? "—"}
          {detail.decision_confidence != null && (
            <span className="muted"> ({detail.decision_confidence.toFixed(2)})</span>
          )}
        </span>
      </div>
      {detail.override_decision && (
        <div className="row spread">
          <span className="muted">Human override</span>
          <span>
            {detail.override_decision} <span className="muted">by {detail.override_by}</span>
          </span>
        </div>
      )}
      {detail.decision_justification && (
        <p className="muted" style={{ marginTop: 8 }}>{detail.decision_justification}</p>
      )}
      <p className="muted" style={{ fontSize: 12 }}>
        AI-assisted, human-reviewable. Escalated/low-confidence cases require ops review.
      </p>
    </div>
  );
}
