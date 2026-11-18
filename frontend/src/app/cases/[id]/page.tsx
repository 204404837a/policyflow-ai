"use client";

import { useCallback, useEffect, useState } from "react";
import { getCase } from "@/lib/api";
import { useRequireRole } from "@/lib/auth";
import type { CaseDetail } from "@/lib/types";
import { AgentOutputPanel } from "@/components/AgentOutputPanel";
import { AgentStatusTracker } from "@/components/AgentStatusTracker";
import { AuditLog } from "@/components/AuditLog";
import { DecisionPanel } from "@/components/DecisionPanel";
import { DocumentViewer } from "@/components/DocumentViewer";
import { OverrideModal } from "@/components/OverrideModal";
import { UploadWidget } from "@/components/UploadWidget";

const AWAITING = new Set(["ESCALATED", "AWAITING_HUMAN"]);
const ACTIVE = new Set(["RECEIVED", "PROCESSING"]);

export default function CasePage({ params }: { params: { id: string } }) {
  const caseId = params.id;
  const user = useRequireRole(); // any signed-in role; backend enforces ownership
  const [detail, setDetail] = useState<CaseDetail | null>(null);
  const [error, setError] = useState<string | null>(null);
  const [showOverride, setShowOverride] = useState(false);

  const load = useCallback(async () => {
    try {
      setDetail(await getCase(caseId));
    } catch (e) {
      setError((e as Error).message);
    }
  }, [caseId]);

  useEffect(() => {
    if (user) void load();
  }, [load, user]);

  if (!user) return null;
  if (error) return <p className="error">{error}</p>;
  if (!detail) return <p className="muted">Loading…</p>;

  const canReview = user.role === "REVIEWER";
  const canAddDocs = user.role === "EMPLOYER" && detail.submitted_by === user.id;

  return (
    <div>
      <div className="row spread">
        <h2>Case <span className="mono">{caseId.slice(0, 8)}…</span></h2>
        {canReview && AWAITING.has(detail.status) && (
          <button onClick={() => setShowOverride(true)}>Human override</button>
        )}
      </div>

      {ACTIVE.has(detail.status) && (
        <div className="card"><AgentStatusTracker caseId={caseId} /></div>
      )}

      <div className="grid-2">
        <div className="card">
          <h3 style={{ marginTop: 0 }}>Documents</h3>
          <DocumentViewer documents={detail.documents} />
        </div>
        <div className="stack">
          <div className="card"><DecisionPanel detail={detail} /></div>
          <div className="card">
            <h3 style={{ marginTop: 0 }}>Agent outputs</h3>
            <AgentOutputPanel outputs={detail.agent_outputs} />
          </div>
        </div>
      </div>

      {canAddDocs && (
        <div className="card">
          <h3 style={{ marginTop: 0 }}>Add documents</h3>
          <UploadWidget caseId={caseId} onDone={() => void load()} />
        </div>
      )}

      <div className="card">
        <h3 style={{ marginTop: 0 }}>Audit log</h3>
        <AuditLog events={detail.audit_events} />
      </div>

      {showOverride && (
        <OverrideModal
          caseId={caseId}
          onClose={() => setShowOverride(false)}
          onDone={() => { setShowOverride(false); void load(); }}
        />
      )}
    </div>
  );
}
