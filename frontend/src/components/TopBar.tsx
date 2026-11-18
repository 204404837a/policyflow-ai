"use client";

import { useAuth } from "@/lib/auth";

export function TopBar() {
  const { user } = useAuth();
  if (!user) return null;

  const initials = (user.first_name?.[0] ?? user.username[0] ?? "?").toUpperCase();

  return (
    <div className="appbar">
      {/* Global search — visual only for now; wiring lands in a later pass. */}
      <div className="searchbar">
        <span className="search-icon" aria-hidden>
          🔍
        </span>
        <input type="search" placeholder="Search…" aria-label="Search" />
      </div>
      <div className="account">
        <span className="avatar" aria-hidden>
          {initials}
        </span>
        <span className="muted">
          {user.username} · {user.role}
        </span>
      </div>
    </div>
  );
}
