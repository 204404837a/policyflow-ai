"use client";

import { useEffect, useRef, useState } from "react";
import { getEvalJob, getEvalMetrics, getEvalStatus, runEval } from "@/lib/api";
import type { EvalMetrics, EvalScope } from "@/lib/types";

const pct = (x: number | null | undefined) =>
  x === null || x === undefined ? "—" : `${(x * 100).toFixed(1)}%`;

type Gate = boolean | null;

interface Track {
  name: string;
  group: EvalScope; // pipeline (one graph pass) vs retrieval (standalone)
  desc: string;
  result: (m: EvalMetrics) => string;
  gate: (m: EvalMetrics) => Gate; // null = informational (no pass/fail gate)
}

// The 5 pipeline tracks are all products of ONE graph pass, so they run
// together (group "pipeline"). Retrieval is a cheap standalone RAG spot-check
// (no vision calls) and runs on its own. Real gates exist only on Decision
// (≥60%) and the weighted Overall grade (≥70%); the rest are informational.
const TRACKS: Track[] = [
  { name: "Classification", group: "pipeline", desc: "Predicted doc type vs label", result: (m) => pct(m.classification_accuracy), gate: () => null },
  { name: "Extraction", group: "pipeline", desc: "Claim-field completeness", result: (m) => pct(m.extraction_accuracy), gate: () => null },
  { name: "Decision", group: "pipeline", desc: "Final decision vs oracle (gate ≥60%)", result: (m) => pct(m.decision_accuracy), gate: (m) => m.decision_gate_passed },
  { name: "KYC", group: "pipeline", desc: "Identity-flag P / R / F1", result: (m) => (m.kyc ? `${m.kyc.precision.toFixed(2)} / ${m.kyc.recall.toFixed(2)} / ${m.kyc.f1.toFixed(2)}` : "—"), gate: () => null },
  { name: "Fraud", group: "pipeline", desc: "Fraud-signal P / R / F1", result: (m) => (m.fraud ? `${m.fraud.precision.toFixed(2)} / ${m.fraud.recall.toFixed(2)} / ${m.fraud.f1.toFixed(2)}` : "—"), gate: () => null },
  { name: "Retrieval @k", group: "retrieval", desc: "Relevant clause retrieved", result: (m) => `${pct(m.retrieval_relevance_at_k)} · MRR ${m.retrieval_mrr.toFixed(2)}`, gate: () => null },
  { name: "Overall grade", group: "pipeline", desc: "Rubric-weighted (gate ≥70%)", result: (m) => pct(m.weighted_grade), gate: (m) => m.overall_gate_passed },
];

const GROUP_LABEL: Record<EvalScope, string> = {
  pipeline: "Pipeline (one graph pass)",
  retrieval: "Retrieval (standalone)",
};

function StatusBadge({ gate }: { gate: Gate }) {
  if (gate === null) return <span className="muted">informational</span>;
  return <span className={`badge ${gate ? "approved" : "rejected"}`}>{gate ? "✅ Passed" : "❌ Failed"}</span>;
}

export function EvalDashboard() {
  const [metrics, setMetrics] = useState<EvalMetrics | null>(null);
  // Which group is currently running (null = idle). Survives refresh via the
  // server /status endpoint, and gates every run button (one run at a time).
  const [runningScope, setRunningScope] = useState<EvalScope | null>(null);
  const [status, setStatus] = useState<string | null>(null);
  const [error, setError] = useState<string | null>(null);
  const [limit, setLimit] = useState(3);
  const timer = useRef<ReturnType<typeof setTimeout> | null>(null);

  const refresh = () => {
    getEvalMetrics()
      .then(setMetrics)
      .catch(() => setMetrics(null));
  };

  // On mount: load the last metrics AND ask the server if a run is already in
  // flight (e.g. this is a page reload mid-run) so we resume rather than idle.
  useEffect(() => {
    refresh();
    getEvalStatus()
      .then((s) => {
        if (s.running && s.task_id && s.scope) {
          setRunningScope(s.scope);
          setStatus(`Resuming ${s.scope} run in progress… (${(s.state ?? "").toLowerCase()})`);
          poll(s.task_id);
        }
      })
      .catch(() => {});
    return () => {
      if (timer.current) clearTimeout(timer.current);
    };
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, []);

  // A long live run outlasts transient network blips; tolerate a few
  // consecutive poll failures before giving up rather than aborting the run.
  const MAX_POLL_ERRORS = 5;

  const poll = (taskId: string, errorStreak = 0) => {
    timer.current = setTimeout(async () => {
      try {
        const job = await getEvalJob(taskId);
        if (job.state === "SUCCESS" && job.metrics) {
          setMetrics(job.metrics);
          setStatus(null);
          setRunningScope(null);
        } else if (job.state === "FAILURE") {
          setError(`Run failed: ${job.error ?? "unknown error"}`);
          setRunningScope(null);
        } else {
          setStatus(`Running over the dataset… (${job.state.toLowerCase()})`);
          poll(taskId, 0); // healthy response resets the error streak
        }
      } catch (e) {
        if (errorStreak + 1 >= MAX_POLL_ERRORS) {
          setError(`Lost contact with the run after ${MAX_POLL_ERRORS} tries: ${(e as Error).message}`);
          setRunningScope(null);
          return;
        }
        setStatus(`Reconnecting to the run… (attempt ${errorStreak + 1}/${MAX_POLL_ERRORS})`);
        poll(taskId, errorStreak + 1);
      }
    }, 3000);
  };

  const run = async (scope: EvalScope) => {
    if (runningScope) return; // one run at a time (server also enforces via 409)
    setRunningScope(scope);
    setError(null);
    setStatus("Queued…");
    try {
      const res = await runEval(scope, scope === "pipeline" ? limit || undefined : undefined);
      poll(res.task_id);
    } catch (e) {
      const msg = (e as Error).message;
      // 409 → another run beat us here; re-sync from the server instead of erroring.
      if (msg.includes("409") || /in progress/i.test(msg)) {
        const s = await getEvalStatus().catch(() => null);
        if (s?.running && s.task_id && s.scope) {
          setRunningScope(s.scope);
          setStatus(`A ${s.scope} run is already in progress — following it…`);
          poll(s.task_id);
          return;
        }
      }
      setError(msg);
      setRunningScope(null);
    }
  };

  const RunButton = ({ scope, label }: { scope: EvalScope; label: string }) => (
    <button onClick={() => void run(scope)} disabled={runningScope !== null}>
      {runningScope === scope ? "Running…" : label}
    </button>
  );

  return (
    <div>
      <div className="card">
        <h2 style={{ margin: "0 0 4px" }}>📊 Evaluation</h2>
        <p className="muted" style={{ margin: 0 }}>
          {metrics ? (
            <>
              Last run: <span className="mono">{metrics.source}</span> ·{" "}
              <span className={metrics.passed ? "badge approved" : "badge rejected"}>
                {metrics.passed ? "GATES PASSED" : "GATES FAILED"}
              </span>{" "}
              · gates: decision ≥60%, overall ≥70%
            </>
          ) : (
            "No run yet · gates: decision ≥60%, overall ≥70%"
          )}
        </p>

        <div className="row" style={{ gap: 10, marginTop: 14, flexWrap: "wrap", alignItems: "center" }}>
          <RunButton scope="pipeline" label="▶ Run pipeline" />
          <RunButton scope="retrieval" label="▶ Run retrieval" />
          <button className="secondary" onClick={refresh} disabled={runningScope !== null}>
            🔄 Refresh
          </button>
          <label style={{ color: "var(--muted)", fontWeight: 600 }}>
            Pipeline sample (cases)
            <input
              type="number"
              min={1}
              value={limit}
              onChange={(e) => setLimit(Number(e.target.value))}
              style={{ width: 84, marginLeft: 8 }}
              disabled={runningScope !== null}
            />
          </label>
        </div>

        {runningScope && (
          <p className="muted" style={{ margin: "10px 0 0" }}>
            <span className="badge" style={{ background: "var(--accent, #2563eb)", color: "#fff" }}>
              ● {GROUP_LABEL[runningScope]} running
            </span>{" "}
            {status ?? "…"}
          </p>
        )}
        {!runningScope && status && <p className="muted" style={{ margin: "10px 0 0" }}>{status}</p>}

        {metrics && (
          <p className="muted" style={{ margin: "10px 0 0" }}>
            Captured <strong>{metrics.captured_cases}</strong> case-bundle(s)
            {metrics.skipped_cases > 0 && (
              <> · <span className="badge rejected">{metrics.skipped_cases} skipped</span></>
            )}
          </p>
        )}
        {metrics && metrics.captured_cases === 0 && (
          <p className="error" style={{ margin: "10px 0 0" }}>
            ⚠ No cases ran — the pipeline produced zero predictions. Check the LLM gateway /
            rate limits and the worker logs; the scores below are not meaningful.
          </p>
        )}
        {error && <p className="error" style={{ margin: "10px 0 0" }}>{error}</p>}
      </div>

      <div className="card">
        <table>
          <thead>
            <tr>
              <th>Track</th>
              <th>Group</th>
              <th>Status</th>
              <th>Result</th>
            </tr>
          </thead>
          <tbody>
            {(["pipeline", "retrieval"] as EvalScope[]).map((group) => (
              <GroupRows
                key={group}
                group={group}
                metrics={metrics}
                running={runningScope === group}
              />
            ))}
          </tbody>
        </table>
        {!metrics && (
          <p className="muted" style={{ marginBottom: 0 }}>
            No results yet — click <strong>Run pipeline</strong> to populate the tracks.
          </p>
        )}
      </div>

      {metrics && (
        <div className="card">
          <h3 style={{ marginTop: 0 }}>Run output</h3>
          {TRACKS.map((t) => {
            const gate = t.gate(metrics);
            const icon = gate === null ? "•" : gate ? "✅" : "❌";
            return (
              <details key={t.name} style={{ borderBottom: "1px solid var(--border)", padding: "8px 0" }}>
                <summary style={{ cursor: "pointer" }}>
                  {icon} {t.name} — <span className="mono">{t.result(metrics)}</span>
                </summary>
                <p className="muted" style={{ margin: "8px 0 0 18px" }}>{t.desc}</p>
              </details>
            );
          })}
          {metrics.notes.length > 0 && (
            <ul className="muted" style={{ marginBottom: 0 }}>
              {metrics.notes.map((n, i) => (
                <li key={i}>{n}</li>
              ))}
            </ul>
          )}
        </div>
      )}
    </div>
  );
}

function GroupRows({
  group,
  metrics,
  running,
}: {
  group: EvalScope;
  metrics: EvalMetrics | null;
  running: boolean;
}) {
  const rows = TRACKS.filter((t) => t.group === group);
  // A capture with 0 pipeline cases (e.g. a retrieval-only run) has no real
  // pipeline scores — show "not run" instead of a misleading 0.0% FAILED.
  const pipelineNotRun = group === "pipeline" && !!metrics && metrics.captured_cases === 0;
  return (
    <>
      <tr>
        <td colSpan={4} style={{ background: "var(--bg-subtle, rgba(127,127,127,0.08))", fontWeight: 700 }}>
          {GROUP_LABEL[group]}
          {running && <span className="muted" style={{ fontWeight: 400 }}> · running…</span>}
        </td>
      </tr>
      {rows.map((t) => (
        <tr key={t.name}>
          <td style={{ fontWeight: 600, paddingLeft: 18 }}>{t.name}</td>
          <td className="muted">{t.group}</td>
          <td>
            {running ? (
              <span className="muted">⏳ running</span>
            ) : pipelineNotRun ? (
              <span className="muted">not run</span>
            ) : metrics ? (
              <StatusBadge gate={t.gate(metrics)} />
            ) : (
              <span className="muted">—</span>
            )}
          </td>
          <td>{pipelineNotRun ? <span className="muted">—</span> : metrics ? t.result(metrics) : "—"}</td>
        </tr>
      ))}
    </>
  );
}
