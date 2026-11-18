// Branded two-column wrapper for the pre-auth pages (login / register):
// a hero panel that says what PolicyFlow is, beside the form.
export function AuthShell({ children }: { children: React.ReactNode }) {
  return (
    <div className="auth-shell">
      <aside className="auth-hero">
        <div className="brand-lg">🛡️ PolicyFlow AI</div>
        <p className="auth-tag">Multi-agent claim document intake for PolicyFlow Demo.</p>
        <ul className="auth-points">
          <li>Classifies &amp; extracts scanned claim documents</li>
          <li>Checks policy coverage and scores fraud</li>
          <li>Decides Approve / Reject / Escalate with a full audit trail</li>
          <li>Human-in-the-loop review for escalated cases</li>
        </ul>
      </aside>
      <div className="auth-form">{children}</div>
    </div>
  );
}
