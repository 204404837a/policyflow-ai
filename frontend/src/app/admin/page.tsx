"use client";

import { useState } from "react";
import { useRequireRole } from "@/lib/auth";
import { AdminUsers } from "@/components/admin/AdminUsers";
import { AdminMembers } from "@/components/admin/AdminMembers";
import { EvalDashboard } from "@/components/admin/EvalDashboard";
import { ClearClaimsButton } from "@/components/admin/ClearClaimsButton";
import { ClaimsBrowser } from "@/components/ClaimsBrowser";

const TABS = ["Users", "Members", "All Claims", "Eval"] as const;
type Tab = (typeof TABS)[number];

export default function AdminConsole() {
  const user = useRequireRole("ADMIN");
  const [tab, setTab] = useState<Tab>("Users");
  const [claimsKey, setClaimsKey] = useState(0); // bump to force ClaimsBrowser reload
  if (!user) return null;

  return (
    <div>
      <h2>Admin Console</h2>
      <div className="tabs">
        {TABS.map((t) => (
          <button
            key={t}
            className={`tab ${t === tab ? "active" : ""}`}
            onClick={() => setTab(t)}
          >
            {t}
          </button>
        ))}
      </div>

      {tab === "Users" && <AdminUsers />}
      {tab === "Members" && <AdminMembers />}
      {tab === "All Claims" && (
        <div className="card">
          <div className="row spread" style={{ marginBottom: 12, gap: 12, flexWrap: "wrap" }}>
            <p className="muted" style={{ margin: 0 }}>
              Every claim across all submitters (read-only). Open one for its audit trail.
            </p>
            <ClearClaimsButton onCleared={() => setClaimsKey((k) => k + 1)} />
          </div>
          <ClaimsBrowser key={claimsKey} />
        </div>
      )}
      {tab === "Eval" && <EvalDashboard />}
    </div>
  );
}
