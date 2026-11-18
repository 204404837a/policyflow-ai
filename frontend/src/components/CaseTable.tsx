import Link from "next/link";
import type { CaseListItem } from "@/lib/types";
import { StatusBadge } from "./StatusBadge";

const AWAITING = new Set(["ESCALATED", "AWAITING_HUMAN"]);

// Reason shown in the reviewer queue for why a case needs a human.
function reviewReason(c: CaseListItem): string {
  if (c.status === "ESCALATED" || c.status === "AWAITING_HUMAN") {
    return "Low confidence / fraud signal — needs human review";
  }
  return "—";
}

interface Props {
  cases: CaseListItem[];
  /** Show the "Reason" column (reviewer pending queue). */
  showReason?: boolean;
}

export function CaseTable({ cases, showReason = false }: Props) {
  if (cases.length === 0) {
    return <p className="muted">No cases yet.</p>;
  }
  return (
    <table>
      <thead>
        <tr>
          <th>Case</th>
          <th>Patient</th>
          <th>Status</th>
          <th>Decision</th>
          {showReason && <th>Reason</th>}
          <th>Created</th>
          <th>Updated</th>
        </tr>
      </thead>
      <tbody>
        {cases.map((c) => (
          <tr key={c.case_id}>
            <td className="mono">
              <Link href={`/cases/${c.case_id}`}>{c.case_id.slice(0, 8)}…</Link>
            </td>
            <td>{c.patient_name ?? "—"}</td>
            <td>
              <StatusBadge status={c.status} />
            </td>
            <td>{c.decision ?? "—"}</td>
            {showReason && (
              <td className={AWAITING.has(c.status) ? "" : "muted"}>{reviewReason(c)}</td>
            )}
            <td className="muted">{new Date(c.created_at).toLocaleString()}</td>
            <td className="muted">
              {c.updated_at ? new Date(c.updated_at).toLocaleString() : "—"}
            </td>
          </tr>
        ))}
      </tbody>
    </table>
  );
}
