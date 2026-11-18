"use client";

import { useCaseSocket } from "@/lib/useWebSocket";

const PIPELINE = ["CLASSIFIER", "PREPROCESSOR", "KYC", "CLAIMS", "POLICY", "FRAUD", "ORCHESTRATOR"];

export function AgentStatusTracker({ caseId }: { caseId: string }) {
  const msg = useCaseSocket(caseId);
  const done = new Set((msg?.agents ?? []).map((a) => a.toUpperCase()));

  return (
    <div className="stack">
      <div className="row spread">
        <strong>Live status</strong>
        <span className="muted">{msg?.status ?? "connecting…"}</span>
      </div>
      <div className="row" style={{ flexWrap: "wrap" }}>
        {PIPELINE.map((a) => (
          <span key={a} className="mono" style={{ color: done.has(a) ? "var(--green)" : "var(--muted)" }}>
            {done.has(a) ? "✅" : "○"} {a}
          </span>
        ))}
      </div>
    </div>
  );
}
