"use client";

import { useCallback, useEffect, useState } from "react";
import { listCases } from "@/lib/api";
import type { CaseListItem } from "@/lib/types";
import { CaseTable } from "./CaseTable";

const STATUSES = ["", "RECEIVED", "PROCESSING", "APPROVED", "REJECTED", "ESCALATED", "AWAITING_HUMAN"];

interface Props {
  /** Fixed status filter (reviewer pending queue); hides the status selector. */
  fixedStatus?: string;
  showReason?: boolean;
  emptyHint?: string;
}

// Shared searchable claims list. Ownership scoping is enforced server-side by
// the JWT role (employers get only their own; reviewer/admin get all).
export function ClaimsBrowser({ fixedStatus, showReason, emptyHint }: Props) {
  const [cases, setCases] = useState<CaseListItem[]>([]);
  const [status, setStatus] = useState(fixedStatus ?? "");
  const [q, setQ] = useState("");
  const [error, setError] = useState<string | null>(null);

  const load = useCallback(async () => {
    setError(null);
    try {
      const res = await listCases({ status: status || undefined, q: q || undefined });
      setCases(res.cases);
    } catch (e) {
      setError((e as Error).message);
    }
  }, [status, q]);

  useEffect(() => {
    void load();
  }, [load]);

  return (
    <div>
      <div className="row spread" style={{ marginBottom: 12 }}>
        <form
          className="row"
          onSubmit={(e) => {
            e.preventDefault();
            void load();
          }}
        >
          <input
            value={q}
            onChange={(e) => setQ(e.target.value)}
            placeholder="Search patient / status / case id…"
            style={{ width: 280 }}
          />
          <button type="submit" className="secondary">
            Search
          </button>
        </form>
        {!fixedStatus && (
          <select value={status} onChange={(e) => setStatus(e.target.value)} style={{ width: 180 }}>
            {STATUSES.map((s) => (
              <option key={s} value={s}>
                {s || "All statuses"}
              </option>
            ))}
          </select>
        )}
      </div>
      {error && <p className="error">{error}</p>}
      {cases.length === 0 && emptyHint ? (
        <p className="muted">{emptyHint}</p>
      ) : (
        <CaseTable cases={cases} showReason={showReason} />
      )}
    </div>
  );
}
