"use client";

import { useState } from "react";
import { fileUrl } from "@/lib/api";
import type { DocumentSummary } from "@/lib/types";

export function DocumentViewer({ documents }: { documents: DocumentSummary[] }) {
  const [active, setActive] = useState(0);
  if (documents.length === 0) return <p className="muted">No documents.</p>;
  const doc = documents[active];
  const url = fileUrl(doc.storage_key);
  const isPdf = doc.mime_type === "application/pdf";

  return (
    <div className="viewer">
      <div className="row" style={{ flexWrap: "wrap", marginBottom: 10 }}>
        {documents.map((d, i) => (
          <button
            key={d.doc_id}
            className={i === active ? "" : "secondary"}
            onClick={() => setActive(i)}
          >
            {d.doc_type ?? "DOC"} · {d.original_filename}
          </button>
        ))}
      </div>
      {isPdf ? <iframe src={url} title={doc.original_filename} /> : <img src={url} alt={doc.original_filename} />}
    </div>
  );
}
