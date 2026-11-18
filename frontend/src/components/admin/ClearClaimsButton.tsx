"use client";

import { useState } from "react";
import { clearAllClaims } from "@/lib/api";

// Destructive reset: wipes all ingested claims (cases/docs/files/checkpoints),
// preserving members, users, and policy vectors. Guarded by a typed confirm.
export function ClearClaimsButton({ onCleared }: { onCleared: () => void }) {
  const [confirming, setConfirming] = useState(false);
  const [busy, setBusy] = useState(false);
  const [msg, setMsg] = useState<string | null>(null);
  const [error, setError] = useState<string | null>(null);

  const run = async () => {
    setBusy(true);
    setError(null);
    setMsg(null);
    try {
      const r = await clearAllClaims();
      setMsg(
        `Cleared ${r.cases} case(s) and ${r.documents} document(s); ` +
          `${r.files_removed} file(s) removed. Members and users preserved.`,
      );
      setConfirming(false);
      onCleared();
    } catch (e) {
      setError((e as Error).message);
    } finally {
      setBusy(false);
    }
  };

  return (
    <div className="row" style={{ gap: 12, flexWrap: "wrap" }}>
      {!confirming ? (
        <button className="danger" onClick={() => setConfirming(true)}>
          Clear all claims
        </button>
      ) : (
        <div className="row" style={{ gap: 8 }}>
          <span className="muted">Delete every claim, document, and file? This cannot be undone.</span>
          <button className="danger" onClick={() => void run()} disabled={busy}>
            {busy ? "Clearing…" : "Yes, clear everything"}
          </button>
          <button className="secondary" onClick={() => setConfirming(false)} disabled={busy}>
            Cancel
          </button>
        </div>
      )}
      {msg && <span style={{ color: "var(--green)" }}>{msg}</span>}
      {error && <span className="error">{error}</span>}
    </div>
  );
}
