import Link from "next/link";
import { AuthShell } from "@/components/AuthShell";

// Accounts are provisioned by an admin (roles are admin-assigned, never
// self-chosen) — see backend/app/api/auth.py. This page explains that flow
// rather than exposing open self-registration.
export default function RegisterPage() {
  return (
    <AuthShell>
      <div className="card" style={{ maxWidth: 440, margin: "0 auto" }}>
        <h2 style={{ marginTop: 0 }}>Request access</h2>
        <p>
          PolicyFlow accounts are created by an administrator, who assigns your role
          (<strong>Employer</strong>, <strong>Reviewer</strong>, or <strong>Admin</strong>).
          Self-service registration is disabled so roles cannot be self-chosen.
        </p>
        <p className="muted" style={{ marginBottom: 0 }}>
          Ask your PolicyFlow Demo administrator to create an account, then{" "}
          <Link href="/login">sign in</Link>.
        </p>
      </div>
    </AuthShell>
  );
}
