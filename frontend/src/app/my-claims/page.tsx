"use client";

import Link from "next/link";
import { useRequireRole } from "@/lib/auth";
import { ClaimsBrowser } from "@/components/ClaimsBrowser";

export default function MyClaimsPage() {
  const user = useRequireRole("EMPLOYER");
  if (!user) return null;
  return (
    <div className="card">
      <div className="row spread" style={{ marginBottom: 12 }}>
        <h2 style={{ margin: 0 }}>My Claims</h2>
        <Link href="/submit">
          <button>+ New Claim</button>
        </Link>
      </div>
      <p className="muted">Claims you have submitted. Search by patient, status, or case id.</p>
      <ClaimsBrowser emptyHint="You haven't submitted any claims yet." />
    </div>
  );
}
