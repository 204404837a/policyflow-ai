"use client";

import { useRouter } from "next/navigation";
import { useRequireRole } from "@/lib/auth";
import { UploadWidget } from "@/components/UploadWidget";

export default function SubmitPage() {
  const router = useRouter();
  const user = useRequireRole("EMPLOYER");
  if (!user) return null;
  return (
    <div className="card" style={{ maxWidth: 640, margin: "0 auto" }}>
      <h2 style={{ marginTop: 0 }}>Submit a new claim</h2>
      <p className="muted">
        Upload the claim documents (claim form, ID, discharge summary, prescription). They are
        classified, extracted, coverage-checked, and fraud-scored automatically.
      </p>
      <UploadWidget
        onDone={(id) => router.push(id ? `/cases/${id}` : "/my-claims")}
      />
    </div>
  );
}
