// TS mirror of backend/app/schemas/api.py (single FE contract source).

export type Decision = "APPROVE" | "REJECT" | "ESCALATE";
export type CaseStatus =
  | "RECEIVED"
  | "PROCESSING"
  | "APPROVED"
  | "REJECTED"
  | "ESCALATED"
  | "AWAITING_HUMAN";

export interface DocumentSummary {
  doc_id: string;
  doc_type: string | null;
  original_filename: string;
  storage_key: string;
  mime_type: string;
  classify_confidence: number | null;
}

export interface CaseCreatedResponse {
  case_id: string;
  status: string;
  documents: DocumentSummary[];
}

export type Role = "ADMIN" | "REVIEWER" | "EMPLOYER";

export interface CaseListItem {
  case_id: string;
  status: string;
  decision: Decision | null;
  decision_confidence: number | null;
  member_id: string | null;
  patient_name: string | null;
  submitted_by: string | null;
  created_at: string;
  updated_at: string | null;
}

export interface CaseList {
  cases: CaseListItem[];
  total: number;
  page: number;
  limit: number;
}

export interface AgentOutputItem {
  agent: string;
  output: Record<string, unknown>;
  confidence: number | null;
  created_at: string;
}

export interface AuditItem {
  actor: string;
  event_type: string;
  details: Record<string, unknown> | null;
  confidence: number | null;
  ts: string;
}

export interface CaseDetail {
  case_id: string;
  cluster_id: string | null;
  member_id: string | null;
  patient_name: string | null;
  submitted_by: string | null;
  status: string;
  decision: Decision | null;
  decision_confidence: number | null;
  decision_justification: string | null;
  override_decision: Decision | null;
  override_by: string | null;
  override_reason: string | null;
  created_at: string;
  updated_at: string;
  documents: DocumentSummary[];
  agent_outputs: AgentOutputItem[];
  audit_events: AuditItem[];
}

export interface OverrideResponse {
  case_id: string;
  original_decision: string | null;
  override_decision: string;
  override_by: string;
  override_at: string;
}

// ---- Auth / RBAC (Phase 9) ------------------------------------------------
export interface TokenResponse {
  access_token: string;
  token_type: string;
  username: string;
  role: Role;
}

export interface User {
  id: string;
  username: string;
  role: Role;
  email: string | null;
  first_name: string | null;
  last_name: string | null;
  status: string;
  created_at: string;
}

export interface UserList {
  users: User[];
  total: number;
}

export interface Member {
  member_id: string;
  name: string;
  policy_number: string;
  policy_type: string;
  date_of_birth: string | null;
  id_expiry_date: string | null;
  city: string | null;
  state: string | null;
}

export interface MemberList {
  members: Member[];
  total: number;
}

export interface PRF {
  precision: number;
  recall: number;
  f1: number;
}

export type EvalScope = "pipeline" | "retrieval";

export interface EvalMetrics {
  classification_accuracy: number;
  extraction_accuracy: number;
  retrieval_relevance_at_k: number;
  retrieval_mrr: number;
  decision_accuracy: number;
  kyc: PRF | null;
  fraud: PRF | null;
  weighted_grade: number;
  captured_cases: number;
  skipped_cases: number;
  decision_gate_passed: boolean;
  overall_gate_passed: boolean;
  passed: boolean;
  notes: string[];
  source: string;
}

export interface WsMessage {
  case_id: string;
  status?: string;
  decision?: Decision | null;
  agents?: string[];
  error?: string;
}
