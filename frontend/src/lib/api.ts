// Typed fetch client — same-origin /api/* (proxied to the backend by next.config).
// Every request carries the stored JWT as a Bearer token (Phase 9 RBAC).

import type {
  CaseCreatedResponse,
  CaseDetail,
  CaseList,
  EvalMetrics,
  EvalScope,
  Member,
  MemberList,
  OverrideResponse,
  TokenResponse,
  User,
  UserList,
} from "./types";

const TOKEN_KEY = "cs_token";

export function getToken(): string | null {
  if (typeof window === "undefined") return null;
  return window.localStorage.getItem(TOKEN_KEY);
}

export function setToken(token: string | null): void {
  if (typeof window === "undefined") return;
  if (token) window.localStorage.setItem(TOKEN_KEY, token);
  else window.localStorage.removeItem(TOKEN_KEY);
}

/** Thrown on a 401 so the auth layer can redirect to /login. */
export class UnauthorizedError extends Error {}

async function request<T>(path: string, init?: RequestInit): Promise<T> {
  const token = getToken();
  const res = await fetch(path, {
    ...init,
    headers: {
      ...(init?.body instanceof FormData ? {} : { "Content-Type": "application/json" }),
      ...(token ? { Authorization: `Bearer ${token}` } : {}),
      ...init?.headers,
    },
    cache: "no-store",
  });
  if (!res.ok) {
    const detail = await res.json().catch(() => ({ detail: res.statusText }));
    const msg = detail.detail ?? `HTTP ${res.status}`;
    if (res.status === 401) throw new UnauthorizedError(msg);
    throw new Error(msg);
  }
  if (res.status === 204) return undefined as T;
  return res.json() as Promise<T>;
}

// ---- Auth ------------------------------------------------------------------
export function login(username: string, password: string): Promise<TokenResponse> {
  return request<TokenResponse>("/api/auth/login", {
    method: "POST",
    body: JSON.stringify({ username, password }),
  });
}

export function getMe(): Promise<User> {
  return request<User>("/api/auth/me");
}

// ---- Cases -----------------------------------------------------------------
export function listCases(
  opts: { status?: string; q?: string; page?: number; limit?: number } = {},
): Promise<CaseList> {
  const p = new URLSearchParams({
    page: String(opts.page ?? 1),
    limit: String(opts.limit ?? 20),
  });
  if (opts.status) p.set("status", opts.status);
  if (opts.q) p.set("q", opts.q);
  return request<CaseList>(`/api/cases?${p.toString()}`);
}

export function getCase(caseId: string): Promise<CaseDetail> {
  return request<CaseDetail>(`/api/cases/${caseId}`);
}

export function uploadCase(files: File[]): Promise<CaseCreatedResponse> {
  const fd = new FormData();
  files.forEach((f) => fd.append("files", f));
  return request<CaseCreatedResponse>("/api/cases", { method: "POST", body: fd });
}

export function appendDocuments(caseId: string, files: File[]): Promise<unknown> {
  const fd = new FormData();
  files.forEach((f) => fd.append("files", f));
  return request(`/api/cases/${caseId}/documents`, { method: "POST", body: fd });
}

export function overrideCase(
  caseId: string,
  decision: "APPROVE" | "REJECT",
  reason: string,
): Promise<OverrideResponse> {
  return request<OverrideResponse>(`/api/cases/${caseId}/override`, {
    method: "POST",
    body: JSON.stringify({ decision, reason }),
  });
}

export function fileUrl(storageKey: string): string {
  return `/api/files/${storageKey}`;
}

// ---- Admin: users ----------------------------------------------------------
export function listUsers(): Promise<UserList> {
  return request<UserList>("/api/admin/users");
}

export function createUser(body: {
  username: string;
  password: string;
  role: string;
  email?: string;
  first_name?: string;
  last_name?: string;
}): Promise<User> {
  return request<User>("/api/admin/users", { method: "POST", body: JSON.stringify(body) });
}

// ---- Admin: KYC members ----------------------------------------------------
export function listMembers(page = 1, limit = 50): Promise<MemberList> {
  return request<MemberList>(`/api/admin/members?page=${page}&limit=${limit}`);
}

export function createMember(body: Record<string, unknown>): Promise<Member> {
  return request<Member>("/api/admin/members", { method: "POST", body: JSON.stringify(body) });
}

export function bulkMembers(
  rows: Record<string, unknown>[],
): Promise<{ created: number; updated: number; errors: string[] }> {
  return request("/api/admin/members/bulk", { method: "POST", body: JSON.stringify(rows) });
}

// ---- Policy documents (RAG source) -----------------------------------------
// Ingestion runs in the worker (Docling is slow): submit returns a task_id,
// then poll the job status until SUCCESS/FAILURE.
export interface PolicyIngestAccepted {
  task_id: string;
  status: string;
  plan: string;
  storage_key: string;
}

export interface PolicyJobStatus {
  task_id: string;
  state: "PENDING" | "STARTED" | "SUCCESS" | "FAILURE" | string;
  chunks_created: number | null;
  error: string | null;
}

export function ingestPolicy(file: File, plan: "GOLD" | "SILVER"): Promise<PolicyIngestAccepted> {
  const fd = new FormData();
  fd.append("file", file);
  fd.append("plan", plan);
  return request<PolicyIngestAccepted>("/api/policies/ingest", { method: "POST", body: fd });
}

export function getPolicyJob(taskId: string): Promise<PolicyJobStatus> {
  return request<PolicyJobStatus>(`/api/policies/jobs/${taskId}`);
}

export interface PolicyDocItem {
  plan: string;
  chunk_count: number;
  section_count: number;
  sections: string[];
}

export function listPolicies(): Promise<{ policies: PolicyDocItem[]; total: number }> {
  return request("/api/policies");
}

// ---- Admin: live eval metrics ----------------------------------------------
export function getEvalMetrics(): Promise<EvalMetrics> {
  return request<EvalMetrics>("/api/eval/metrics");
}

export interface EvalRunAccepted {
  task_id: string;
  scope: EvalScope;
  status: string;
}

export interface EvalJobStatus {
  task_id: string;
  state: "PENDING" | "STARTED" | "SUCCESS" | "FAILURE" | string;
  scope: EvalScope | null;
  metrics: EvalMetrics | null;
  error: string | null;
}

export interface EvalRunStatus {
  running: boolean;
  task_id: string | null;
  scope: EvalScope | null;
  state: string | null;
}

export function runEval(scope: EvalScope, limit?: number): Promise<EvalRunAccepted> {
  const body: { scope: EvalScope; limit?: number } = { scope };
  if (scope === "pipeline" && limit) body.limit = limit;
  return request<EvalRunAccepted>("/api/eval/run", {
    method: "POST",
    body: JSON.stringify(body),
  });
}

export function getEvalJob(taskId: string): Promise<EvalJobStatus> {
  return request<EvalJobStatus>(`/api/eval/jobs/${taskId}`);
}

// Ask the server whether a run is in flight, so a refreshed page can resume
// polling instead of losing track of it (or double-triggering one).
export function getEvalStatus(): Promise<EvalRunStatus> {
  return request<EvalRunStatus>("/api/eval/status");
}

// ---- Admin: reset ingested claims ------------------------------------------
export interface ClearCasesResult {
  cases: number;
  documents: number;
  files_removed: number;
  files_failed: number;
  checkpoints_cleared: boolean;
}

export function clearAllClaims(): Promise<ClearCasesResult> {
  return request<ClearCasesResult>("/api/admin/cases", { method: "DELETE" });
}
