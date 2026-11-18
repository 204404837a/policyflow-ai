"use client";

// Root route: send each signed-in user to their role's home, else to login.
import { useEffect } from "react";
import { useRouter } from "next/navigation";
import { homeForRole, useAuth } from "@/lib/auth";

export default function Home() {
  const { user, loading } = useAuth();
  const router = useRouter();
  useEffect(() => {
    if (loading) return;
    router.replace(user ? homeForRole(user.role) : "/login");
  }, [user, loading, router]);
  return <p className="muted" style={{ margin: 48 }}>Loading…</p>;
}
