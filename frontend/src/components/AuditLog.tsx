import type { AuditItem } from "@/lib/types";

export function AuditLog({ events }: { events: AuditItem[] }) {
  if (events.length === 0) return <p className="muted">No audit events.</p>;
  return (
    <table>
      <thead>
        <tr>
          <th>Time</th>
          <th>Actor</th>
          <th>Event</th>
          <th>Detail</th>
        </tr>
      </thead>
      <tbody>
        {events.map((e, i) => (
          <tr key={i}>
            <td className="muted">{new Date(e.ts).toLocaleTimeString()}</td>
            <td>{e.actor}</td>
            <td>{e.event_type}</td>
            <td className="mono">{e.details ? JSON.stringify(e.details) : "—"}</td>
          </tr>
        ))}
      </tbody>
    </table>
  );
}
