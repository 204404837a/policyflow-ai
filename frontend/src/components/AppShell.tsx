"use client";

import { useAuth } from "@/lib/auth";
import { Sidebar } from "./Sidebar";
import { TopBar } from "./TopBar";

// Authenticated chrome = left sidebar + top bar. Pre-auth pages (login,
// register) and the initial loading tick render bare so they can center
// their own content without the shell.
export function AppShell({ children }: { children: React.ReactNode }) {
  const { user } = useAuth();
  if (!user) return <>{children}</>;
  return (
    <div className="app-shell">
      <Sidebar />
      <div className="app-main">
        <TopBar />
        <main className="container">{children}</main>
      </div>
    </div>
  );
}
