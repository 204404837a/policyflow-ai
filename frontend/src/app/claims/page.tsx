"use client";

import { useRequireRole } from "@/lib/auth";
import { ClaimsBrowser } from "@/components/ClaimsBrowser";

// Read-only, all-claims view shared by reviewers and admins.
export default function AllClaimsPage() {
  const user = useRequireRole("REVIEWER", "ADMIN");
  if (!user) return null;
  return (
    <div className="card">
      <h2 style={{ marginTop: 0 }}>All Claims</h2>
      <p className="muted">Every claim across all submitters. Search and filter by status.</p>
      <ClaimsBrowser />
    </div>
  );
}
