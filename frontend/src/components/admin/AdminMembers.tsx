"use client";

import { useCallback, useEffect, useState } from "react";
import { bulkMembers, createMember, listMembers } from "@/lib/api";
import type { Member } from "@/lib/types";

export function AdminMembers() {
  const [members, setMembers] = useState<Member[]>([]);
  const [total, setTotal] = useState(0);
  const [form, setForm] = useState({
    member_id: "",
    name: "",
    policy_number: "",
    policy_type: "GOLD",
  });
  const [bulkText, setBulkText] = useState("");
  const [error, setError] = useState<string | null>(null);
  const [msg, setMsg] = useState<string | null>(null);

  const load = useCallback(async () => {
    try {
      const res = await listMembers();
      setMembers(res.members);
      setTotal(res.total);
    } catch (e) {
      setError((e as Error).message);
    }
  }, []);

  useEffect(() => {
    void load();
  }, [load]);

  const addOne = async (e: React.FormEvent) => {
    e.preventDefault();
    setError(null);
    setMsg(null);
    try {
      await createMember(form);
      setForm({ member_id: "", name: "", policy_number: "", policy_type: "GOLD" });
      setMsg("Member added.");
      await load();
    } catch (err) {
      setError((err as Error).message);
    }
  };

  const uploadBulk = async () => {
    setError(null);
    setMsg(null);
    let rows: Record<string, unknown>[];
    try {
      rows = JSON.parse(bulkText);
      if (!Array.isArray(rows)) throw new Error("expected a JSON array of member objects");
    } catch (err) {
      setError(`Invalid JSON: ${(err as Error).message}`);
      return;
    }
    try {
      const res = await bulkMembers(rows);
      setMsg(`Created ${res.created}, updated ${res.updated}.${res.errors.length ? ` ${res.errors.length} error(s).` : ""}`);
      if (res.errors.length) setError(res.errors.join("; "));
      setBulkText("");
      await load();
    } catch (err) {
      setError((err as Error).message);
    }
  };

  return (
    <div>
      <div className="grid-2">
        <div className="card">
          <h3 style={{ marginTop: 0 }}>Add KYC member</h3>
          <form onSubmit={addOne} className="col">
            <label>
              Member ID
              <input
                value={form.member_id}
                onChange={(e) => setForm({ ...form, member_id: e.target.value })}
                placeholder="PT_000123"
              />
            </label>
            <label>
              Name
              <input value={form.name} onChange={(e) => setForm({ ...form, name: e.target.value })} />
            </label>
            <label>
              Policy number
              <input
                value={form.policy_number}
                onChange={(e) => setForm({ ...form, policy_number: e.target.value })}
              />
            </label>
            <label>
              Policy type
              <select
                value={form.policy_type}
                onChange={(e) => setForm({ ...form, policy_type: e.target.value })}
              >
                <option value="GOLD">GOLD</option>
                <option value="SILVER">SILVER</option>
              </select>
            </label>
            <button type="submit" disabled={!form.member_id || !form.name || !form.policy_number}>
              Add member
            </button>
          </form>
        </div>

        <div className="card">
          <h3 style={{ marginTop: 0 }}>Bulk upload (JSON)</h3>
          <p className="muted">
            Paste a JSON array of member objects. Each needs member_id, name, policy_number,
            policy_type; rows upsert by member_id.
          </p>
          <textarea
            value={bulkText}
            onChange={(e) => setBulkText(e.target.value)}
            rows={8}
            placeholder='[{"member_id":"PT_1","name":"Jane","policy_number":"MED-GLD-1","policy_type":"GOLD"}]'
          />
          <button style={{ marginTop: 8 }} onClick={() => void uploadBulk()} disabled={!bulkText.trim()}>
            Upload
          </button>
        </div>
      </div>

      {msg && <p style={{ color: "var(--green)" }}>{msg}</p>}
      {error && <p className="error">{error}</p>}

      <div className="card">
        <h3 style={{ marginTop: 0 }}>KYC members ({total})</h3>
        <p className="muted">Member IDs are masked in this list view (PHI).</p>
        <table>
          <thead>
            <tr>
              <th>Member</th>
              <th>Name</th>
              <th>Policy</th>
              <th>Type</th>
              <th>Location</th>
            </tr>
          </thead>
          <tbody>
            {members.map((m) => (
              <tr key={m.member_id}>
                <td className="mono">{m.member_id}</td>
                <td>{m.name}</td>
                <td className="mono">{m.policy_number}</td>
                <td>{m.policy_type}</td>
                <td className="muted">
                  {[m.city, m.state].filter(Boolean).join(", ") || "—"}
                </td>
              </tr>
            ))}
          </tbody>
        </table>
      </div>
    </div>
  );
}
