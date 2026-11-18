"use client";

import { useRef, useState } from "react";
import { appendDocuments, uploadCase } from "@/lib/api";

interface Props {
  caseId?: string; // when set → append mode
  onDone: (caseId?: string) => void;
}

export function UploadWidget({ caseId, onDone }: Props) {
  const [drag, setDrag] = useState(false);
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const inputRef = useRef<HTMLInputElement>(null);

  async function submit(files: FileList | null) {
    if (!files || files.length === 0) return;
    setBusy(true);
    setError(null);
    try {
      const arr = Array.from(files);
      if (caseId) {
        await appendDocuments(caseId, arr);
        onDone(caseId);
      } else {
        const res = await uploadCase(arr);
        onDone(res.case_id);
      }
    } catch (e) {
      setError((e as Error).message);
    } finally {
      setBusy(false);
    }
  }

  return (
    <div>
      <div
        className={`dropzone ${drag ? "drag" : ""}`}
        onClick={() => inputRef.current?.click()}
        onDragOver={(e) => { e.preventDefault(); setDrag(true); }}
        onDragLeave={() => setDrag(false)}
        onDrop={(e) => { e.preventDefault(); setDrag(false); void submit(e.dataTransfer.files); }}
      >
        {busy
          ? "Uploading…"
          : caseId
            ? "Drop or click to add documents to this case"
            : "Drop or click to upload documents (single or multiple → one case)"}
        <input
          ref={inputRef}
          type="file"
          multiple
          accept="image/png,image/jpeg,image/tiff,application/pdf"
          style={{ display: "none" }}
          onChange={(e) => void submit(e.target.files)}
        />
      </div>
      {error && <p className="error">{error}</p>}
    </div>
  );
}
