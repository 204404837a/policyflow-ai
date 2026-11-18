"use client";

import { useRequireRole } from "@/lib/auth";
import { ClaimsBrowser } from "@/components/ClaimsBrowser";

export default function QueuePage() {
  const user = useRequireRole("REVIEWER");
  if (!user) return null;
  return (
    <div className="card">
      <h2 style={{ marginTop: 0 }}>Review Queue</h2>
      <p className="muted">
        Cases escalated by the pipeline (low confidence or a fraud signal) awaiting a human
        decision. Open a case to override and finalize it.
      </p>
      <ClaimsBrowser
        fixedStatus="ESCALATED"
        showReason
        emptyHint="Nothing awaiting review. 🎉"
      />
    </div>
  );
}
