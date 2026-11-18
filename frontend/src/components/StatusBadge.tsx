export function StatusBadge({ status }: { status: string }) {
  const cls = status.toLowerCase();
  return <span className={`badge ${cls}`}>{status}</span>;
}
