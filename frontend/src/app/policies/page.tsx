"use client";

import { useCallback, useEffect, useRef, useState } from "react";
import { useRequireRole } from "@/lib/auth";
import { getPolicyJob, ingestPolicy, listPolicies, type PolicyDocItem } from "@/lib/api";

export default function PoliciesPage() {
  const user = useRequireRole("ADMIN", "REVIEWER");
  const [policies, setPolicies] = useState<PolicyDocItem[]>([]);
  const [loadErr, setLoadErr] = useState<string | null>(null);
  const [file, setFile] = useState<File | null>(null);
  const [plan, setPlan] = useState<"GOLD" | "SILVER">("GOLD");
  const [busy, setBusy] = useState(false);
  const [msg, setMsg] = useState<string | null>(null);
  const [error, setError] = useState<string | null>(null);
  const timer = useRef<ReturnType<typeof setTimeout> | null>(null);

  const load = useCallback(async () => {
    try {
      setPolicies((await listPolicies()).policies);
    } catch (e) {
      setLoadErr((e as Error).message);
    }
  }, []);

  useEffect(() => {
    void load();
    return () => {
      if (timer.current) clearTimeout(timer.current);
    };
  }, [load]);

  if (!user) return null;
  const isAdmin = user.role === "ADMIN";

  const poll = (taskId: string) => {
    timer.current = setTimeout(async () => {
      try {
        const job = await getPolicyJob(taskId);
        if (job.state === "SUCCESS") {
          setMsg(`Ingested ${job.chunks_created} clause chunk(s) into the policy store.`);
          setBusy(false);
          void load(); // refresh the list
        } else if (job.state === "FAILURE") {
          setError(`Ingestion failed: ${job.error ?? "unknown error"}`);
          setBusy(false);
        } else {
          setMsg("Parsing PDF and embedding clauses… (this can take a couple of minutes)");
          poll(taskId); // still PENDING/STARTED — keep polling
        }
      } catch (err) {
        setError((err as Error).message);
        setBusy(false);
      }
    }, 2500);
  };

  const submit = async (e: React.FormEvent) => {
    e.preventDefault();
    if (!file) return;
    setBusy(true);
    setError(null);
    setMsg(null);
    try {
      const res = await ingestPolicy(file, plan);
      setMsg("Ingestion queued — processing in the background…");
      setFile(null);
      poll(res.task_id);
    } catch (err) {
      setError((err as Error).message);
      setBusy(false);
    }
  };

  return (
    <div>
      <h2>Policy Documents</h2>
      <p className="muted">
        Coverage decisions cite clauses retrieved from these policy PDFs (GOLD / SILVER plans).
      </p>

      {/* Ingested policies — visible to admin and reviewer */}
      <div className="card">
        <div className="row spread" style={{ marginBottom: 12 }}>
          <h3 style={{ margin: 0 }}>Ingested policies ({policies.length})</h3>
          <button className="secondary" onClick={() => void load()}>
            Refresh
          </button>
        </div>
        {loadErr && <p className="error">{loadErr}</p>}
        {policies.length === 0 ? (
          <p className="muted">
            No policy documents ingested yet.
            {isAdmin ? " Upload one below." : " Ask an administrator to add one."}
          </p>
        ) : (
          <table>
            <thead>
              <tr>
                <th>Plan</th>
                <th>Clause chunks</th>
                <th>Sections</th>
                <th>Section headings</th>
              </tr>
            </thead>
            <tbody>
              {policies.map((p) => (
                <tr key={p.plan}>
                  <td>
                    <span className="badge approved">{p.plan}</span>
                  </td>
                  <td>{p.chunk_count}</td>
                  <td>{p.section_count}</td>
                  <td className="muted">
                    {p.sections.length ? p.sections.join(", ") : "—"}
                  </td>
                </tr>
              ))}
            </tbody>
          </table>
        )}
      </div>

      {/* Upload — admin only */}
      {isAdmin && (
        <div className="card" style={{ maxWidth: 640 }}>
          <h3 style={{ marginTop: 0 }}>Add / update a policy</h3>
          <p className="muted" style={{ marginTop: 0 }}>
            Re-ingesting a plan replaces its existing clauses.
          </p>
          <form onSubmit={submit} className="col">
            <label>
              Plan
              <select value={plan} onChange={(e) => setPlan(e.target.value as "GOLD" | "SILVER")}>
                <option value="GOLD">GOLD</option>
                <option value="SILVER">SILVER</option>
              </select>
            </label>
            <label>
              Policy PDF
              <input
                type="file"
                accept="application/pdf"
                onChange={(e) => setFile(e.target.files?.[0] ?? null)}
              />
            </label>
            {msg && <p style={{ color: "var(--green)" }}>{msg}</p>}
            {error && <p className="error">{error}</p>}
            <button type="submit" disabled={busy || !file}>
              {busy ? "Ingesting…" : "Ingest policy"}
            </button>
          </form>
        </div>
      )}
    </div>
  );
}
