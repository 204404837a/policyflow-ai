"use client";

import { useEffect, useState } from "react";
import { useRouter } from "next/navigation";
import Link from "next/link";
import { homeForRole, useAuth } from "@/lib/auth";
import { AuthShell } from "@/components/AuthShell";

export default function LoginPage() {
  const { user, loading, login } = useAuth();
  const router = useRouter();
  const [username, setUsername] = useState("");
  const [password, setPassword] = useState("");
  const [error, setError] = useState<string | null>(null);
  const [busy, setBusy] = useState(false);

  // Already signed in → bounce to the role's home.
  useEffect(() => {
    if (!loading && user) router.replace(homeForRole(user.role));
  }, [user, loading, router]);

  const submit = async (e: React.FormEvent) => {
    e.preventDefault();
    setError(null);
    setBusy(true);
    try {
      const me = await login(username, password);
      router.replace(homeForRole(me.role));
    } catch (err) {
      setError((err as Error).message);
    } finally {
      setBusy(false);
    }
  };

  return (
    <AuthShell>
      <div className="card" style={{ maxWidth: 400, margin: "0 auto" }}>
        <h2 style={{ marginTop: 0 }}>Sign in</h2>
      <form onSubmit={submit} className="col" style={{ gap: 12 }}>
        <label>
          Username
          <input value={username} onChange={(e) => setUsername(e.target.value)} autoFocus />
        </label>
        <label>
          Password
          <input
            type="password"
            value={password}
            onChange={(e) => setPassword(e.target.value)}
          />
        </label>
        {error && <p className="error">{error}</p>}
        <button type="submit" disabled={busy || !username || !password}>
          {busy ? "Signing in…" : "Sign in"}
        </button>
      </form>
        <p className="muted" style={{ marginBottom: 0 }}>
          No account? <Link href="/register">Register</Link> (role assigned by an admin).
        </p>
      </div>
    </AuthShell>
  );
}
