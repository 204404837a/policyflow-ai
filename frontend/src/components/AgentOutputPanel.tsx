"use client";

import { useState } from "react";
import type { AgentOutputItem } from "@/lib/types";

function Panel({ item }: { item: AgentOutputItem }) {
  const [open, setOpen] = useState(false);
  return (
    <div style={{ borderBottom: "1px solid var(--border)" }}>
      <div className="collapsible-header" onClick={() => setOpen((o) => !o)}>
        <strong>{item.agent}</strong>
        <span className="muted">
          {item.confidence != null ? `conf ${item.confidence.toFixed(2)}` : ""} {open ? "▲" : "▼"}
        </span>
      </div>
      {open && <pre className="json">{JSON.stringify(item.output, null, 2)}</pre>}
    </div>
  );
}

export function AgentOutputPanel({ outputs }: { outputs: AgentOutputItem[] }) {
  if (outputs.length === 0) return <p className="muted">No agent outputs yet.</p>;
  return (
    <div>
      {outputs.map((o, i) => (
        <Panel key={`${o.agent}-${i}`} item={o} />
      ))}
    </div>
  );
}
