"use client";

import Link from "next/link";
import { usePathname, useRouter } from "next/navigation";
import { useAuth } from "@/lib/auth";
import type { Role } from "@/lib/types";

// Each nav item carries an emoji glyph (kept dependency-free — no icon lib).
const LINKS: Record<Role, { href: string; label: string; icon: string }[]> = {
  ADMIN: [
    { href: "/admin", label: "Admin Console", icon: "🏠" },
    { href: "/claims", label: "All Claims", icon: "📄" },
    { href: "/policies", label: "Policy Docs", icon: "📚" },
  ],
  REVIEWER: [
    { href: "/queue", label: "Review Queue", icon: "🧾" },
    { href: "/claims", label: "All Claims", icon: "📄" },
    { href: "/policies", label: "Policy Docs", icon: "📚" },
  ],
  EMPLOYER: [
    { href: "/my-claims", label: "My Claims", icon: "📄" },
    { href: "/submit", label: "New Claim", icon: "➕" },
  ],
};

export function Sidebar() {
  const { user, logout } = useAuth();
  const pathname = usePathname();
  const router = useRouter();
  if (!user) return null;

  const onLogout = () => {
    logout();
    router.replace("/login");
  };

  return (
    <aside className="sidebar">
      <span className="brand">🛡️ PolicyFlow AI</span>
      <nav>
        {LINKS[user.role].map((l) => {
          const active = pathname === l.href || pathname.startsWith(`${l.href}/`);
          return (
            <Link key={l.href} href={l.href} className={active ? "active" : ""}>
              <span aria-hidden>{l.icon}</span>
              {l.label}
            </Link>
          );
        })}
      </nav>
      <div className="sidebar-foot">
        <button className="secondary" onClick={onLogout}>
          ↪ Log out
        </button>
      </div>
    </aside>
  );
}
