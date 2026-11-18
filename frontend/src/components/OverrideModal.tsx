"use client";

import { useState } from "react";
import { overrideCase } from "@/lib/api";

interface Props {
  caseId: string;
  onClose: () => void;
  onDone: () => void;
}

export function OverrideModal({ caseId, onClose, onDone }: Props) {
  const [decision, setDecision] = useState<"APPROVE" | "REJECT">("APPROVE");
  const [reason, setReason] = useState("");
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState<string | null>(null);

  async function submit() {
    if (!reason.trim()) {
      setError("A reason is required.");
      return;
    }
    setBusy(true);
    setError(null);
    try {
      await overrideCase(caseId, decision, reason);
      onDone();
    } catch (e) {
      setError((e as Error).message);
    } finally {
      setBusy(false);
    }
  }

  return (
    <div className="modal-backdrop" onClick={onClose}>
      <div className="modal" onClick={(e) => e.stopPropagation()}>
        <h3 style={{ marginTop: 0 }}>Override decision</h3>
        <div className="stack" style={{ gap: 12 }}>
          <label>
            Decision
            <select value={decision} onChange={(e) => setDecision(e.target.value as "APPROVE" | "REJECT")}>
              <option value="APPROVE">APPROVE</option>
              <option value="REJECT">REJECT</option>
            </select>
          </label>
          <label>
            Reason
            <textarea value={reason} onChange={(e) => setReason(e.target.value)} rows={3} />
          </label>
          {error && <p className="error">{error}</p>}
          <div className="row spread">
            <button className="secondary" onClick={onClose}>Cancel</button>
            <button onClick={() => void submit()} disabled={busy}>
              {busy ? "Submitting…" : "Submit override"}
            </button>
          </div>
        </div>
      </div>
    </div>
  );
}
