"use client";

// Client-side auth context (Phase 9): holds the current user, persists the JWT,
// and exposes role guards. The token is attached to every request in lib/api.

import { createContext, useCallback, useContext, useEffect, useState } from "react";
import { useRouter } from "next/navigation";
import { getMe, login as apiLogin, setToken } from "./api";
import type { Role, User } from "./types";

interface AuthState {
  user: User | null;
  loading: boolean;
  login: (username: string, password: string) => Promise<User>;
  logout: () => void;
}

const AuthContext = createContext<AuthState | null>(null);

/** Landing route for each role after login / when hitting a forbidden page. */
export function homeForRole(role: Role): string {
  switch (role) {
    case "ADMIN":
      return "/admin";
    case "REVIEWER":
      return "/queue";
    case "EMPLOYER":
      return "/my-claims";
  }
}

export function AuthProvider({ children }: { children: React.ReactNode }) {
  const [user, setUser] = useState<User | null>(null);
  const [loading, setLoading] = useState(true);

  // Rehydrate from a stored token on first mount.
  useEffect(() => {
    let active = true;
    (async () => {
      try {
        const me = await getMe();
        if (active) setUser(me);
      } catch {
        setToken(null);
      } finally {
        if (active) setLoading(false);
      }
    })();
    return () => {
      active = false;
    };
  }, []);

  const login = useCallback(async (username: string, password: string) => {
    const res = await apiLogin(username, password);
    setToken(res.access_token);
    const me = await getMe();
    setUser(me);
    return me;
  }, []);

  const logout = useCallback(() => {
    setToken(null);
    setUser(null);
  }, []);

  return (
    <AuthContext.Provider value={{ user, loading, login, logout }}>{children}</AuthContext.Provider>
  );
}

export function useAuth(): AuthState {
  const ctx = useContext(AuthContext);
  if (!ctx) throw new Error("useAuth must be used within AuthProvider");
  return ctx;
}

/**
 * Guard a page to the given role(s). Redirects to /login when signed out and to
 * the caller's own home when signed in with the wrong role. Returns the user
 * once authorised (null while loading/redirecting).
 */
export function useRequireRole(...roles: Role[]): User | null {
  const { user, loading } = useAuth();
  const router = useRouter();
  useEffect(() => {
    if (loading) return;
    if (!user) {
      router.replace("/login");
    } else if (roles.length && !roles.includes(user.role)) {
      router.replace(homeForRole(user.role));
    }
  }, [user, loading, router, roles]);
  if (loading || !user) return null;
  if (roles.length && !roles.includes(user.role)) return null;
  return user;
}
