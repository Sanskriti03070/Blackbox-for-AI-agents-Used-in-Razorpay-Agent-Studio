import { useEffect, useMemo, useState } from "react";

const API_BASE = "/api/v1";

type EvidenceRef = {
  event_id: string;
  sequence: number;
  event_type: string;
  timestamp: string;
};

type Decision = {
  action: string;
  reason: string;
  confidence: number;
  evidence: EvidenceRef;
};

type Policy = {
  reason: string;
  allowed: boolean;
  threshold: number;
  confidence: number;
  evidence: EvidenceRef;
};

type Tool = {
  name: string | null;
  input: Record<string, any> | null;
  result: Record<string, any> | null;
  status: string | null;
  error?: string;
  evidence: EvidenceRef;
};

type StateChange = {
  entity: string;
  operation: string;
  before: Record<string, any> | null;
  after: Record<string, any> | null;
  evidence: EvidenceRef;
};

type Investigation = {
  run: {
    run_id: string;
    agent_name: string;
    agent_version: string;
    merchant_id: string | null;
    customer_id: string | null;
    subscription_id: string | null;
    payment_id: string | null;
    user_request: string;
    status: string;
    selected_action: string | null;
    confidence: number | null;
    outcome: string | null;
    started_at: string;
    completed_at: string | null;
    error_summary: string | null;
  };
  incident: {
    status: string;
    agent: string;
    request: string;
    payment_id: string | null;
  };
  timeline: {
    decision: Decision | null;
    policy: Policy | null;
    tool: Tool | null;
    state_changes: StateChange[];
    event_count: number;
  };
  conclusion: string;
  evidence_integrity: {
    status: string;
    issues: any[];
  };
  evidence: EvidenceRef[];
};

type RunSummary = {
  run_id: string;
  agent_name: string;
  agent_version: string;
  payment_id: string | null;
  status: string;
  selected_action: string | null;
  confidence: number | null;
  outcome: string | null;
  user_request: string;
  started_at: string;
  completed_at: string | null;
};

function statusLabel(status: string): { text: string; cls: string } {
  if (status === "completed") return { text: "Resolved", cls: "success-dot" };
  if (status === "failed") return { text: "Failed", cls: "blocked-dot" };
  return { text: "In progress", cls: "live-dot" };
}

function formatTime(iso: string): string {
  try {
    return new Date(iso).toLocaleString();
  } catch {
    return iso;
  }
}

function App() {
  const [runs, setRuns] = useState<RunSummary[] | null>(null);
  const [runsError, setRunsError] = useState<string | null>(null);
  const [selectedRunId, setSelectedRunId] = useState<string | null>(null);

  const [investigation, setInvestigation] = useState<Investigation | null>(null);
  const [investigationLoading, setInvestigationLoading] = useState(false);
  const [investigationError, setInvestigationError] = useState<string | null>(null);

  const [tab, setTab] = useState<"intelligence" | "trace" | "evidence">("intelligence");
  const [technicalOpen, setTechnicalOpen] = useState(false);

  useEffect(() => {
    fetch(`${API_BASE}/black-box/runs`)
      .then((res) => {
        if (!res.ok) throw new Error(`Failed to load runs (${res.status})`);
        return res.json();
      })
      .then((data: RunSummary[]) => {
        setRuns(data);
        setRunsError(null);
        if (data.length > 0) {
          setSelectedRunId(data[0].run_id);
        }
      })
      .catch((err) => {
        setRuns([]);
        setRunsError(err instanceof Error ? err.message : "Could not load runs");
      });
  }, []);

  useEffect(() => {
    if (!selectedRunId) return;
    setInvestigationLoading(true);
    setInvestigationError(null);
    setInvestigation(null);

    fetch(`${API_BASE}/black-box/investigations/${selectedRunId}`)
      .then((res) => {
        if (!res.ok) throw new Error(`Failed to load investigation (${res.status})`);
        return res.json();
      })
      .then((data: Investigation) => {
        setInvestigation(data);
        setInvestigationLoading(false);
      })
      .catch((err) => {
        setInvestigationError(
          err instanceof Error ? err.message : "Could not load investigation",
        );
        setInvestigationLoading(false);
      });
  }, [selectedRunId]);

  const decision = investigation?.timeline.decision ?? null;
  const policy = investigation?.timeline.policy ?? null;
  const tool = investigation?.timeline.tool ?? null;
  const stateChanges = investigation?.timeline.state_changes ?? [];

  const steps = useMemo(() => {
    if (!investigation) return [];
    const built: { number: string; title: string; body: string; type: string }[] = [];
    let n = 1;
    const pad = (x: number) => String(x).padStart(2, "0");

    built.push({
      number: pad(n++),
      title: "Agent triggered",
      body: investigation.run.payment_id
        ? `Triggered by: "${investigation.run.user_request}" for payment ${investigation.run.payment_id}.`
        : `Triggered by: "${investigation.run.user_request}".`,
      type: "normal",
    });

    if (decision) {
      built.push({
        number: pad(n++),
        title: "Decision generated",
        body: `The agent decided to ${decision.action.replace(/_/g, " ")} with ${Math.round(
          decision.confidence * 100,
        )}% confidence. Reason: ${decision.reason}`,
        type: "normal",
      });
    }

    if (policy) {
      built.push({
        number: pad(n++),
        title: "Safety check",
        body: policy.allowed
          ? `Allowed to proceed — confidence ${Math.round(
              policy.confidence * 100,
            )}% exceeded the ${Math.round(policy.threshold * 100)}% threshold.`
          : `Blocked — confidence ${Math.round(
              policy.confidence * 100,
            )}% did not meet the ${Math.round(policy.threshold * 100)}% threshold.`,
        type: policy.allowed ? "normal" : "blocked",
      });
    }

    if (tool) {
      built.push({
        number: pad(n++),
        title: `Tool called: ${tool.name ?? "unknown"}`,
        body:
          tool.status === "executed"
            ? "The tool executed successfully."
            : `The tool was rejected${tool.error ? `: ${tool.error}` : "."}`,
        type: tool.status === "executed" ? "success" : "blocked",
      });
    }

    stateChanges.forEach((sc) => {
      built.push({
        number: pad(n++),
        title: `State changed: ${sc.entity}`,
        body:
          sc.before && sc.after
            ? `${sc.entity} went from "${sc.before.status ?? JSON.stringify(sc.before)}" to "${
                sc.after.status ?? JSON.stringify(sc.after)
              }".`
            : `A new ${sc.entity} record was created.`,
        type: "success",
      });
    });

    built.push({
      number: pad(n++),
      title: "Final outcome",
      body: investigation.conclusion,
      type: investigation.run.status === "completed" ? "success" : "blocked",
    });

    return built;
  }, [investigation, decision, policy, tool, stateChanges]);

  const evidenceItems = useMemo(() => {
    if (!investigation) return [];
    const items: { title: string; body: string; ok: boolean }[] = [];

    if (decision) {
      items.push({
        title: "The agent made a decision",
        body: `Decision event recorded at sequence ${decision.evidence.sequence} (${decision.evidence.event_type}).`,
        ok: true,
      });
    }
    if (policy) {
      items.push({
        title: policy.allowed ? "The action was allowed" : "The action was blocked",
        body: `Policy check recorded at sequence ${policy.evidence.sequence} (${policy.evidence.event_type}).`,
        ok: true,
      });
    }
    if (tool) {
      items.push({
        title: tool.status === "executed" ? "The tool executed" : "The tool was rejected",
        body: `Tool execution recorded at sequence ${tool.evidence.sequence} (${tool.evidence.event_type}).`,
        ok: tool.status === "executed",
      });
    }
    stateChanges.forEach((sc) => {
      items.push({
        title: `State change recorded: ${sc.entity}`,
        body: `Recorded at sequence ${sc.evidence.sequence} (${sc.evidence.event_type}).`,
        ok: true,
      });
    });

    return items;
  }, [investigation, decision, policy, tool, stateChanges]);

  return (
    <div className="app">
      <aside className="sidebar">
        <div className="brand">
          <div className="brand-mark">r</div>
          <div>
            <strong>Razorpay</strong>
            <span>Business Agent Studio</span>
          </div>
        </div>

        <div className="workspace">
          <div className="workspace-icon">AC</div>
          <div>
            <strong>Acme Commerce</strong>
            <span>Business workspace</span>
          </div>
          <span className="down">⌄</span>
        </div>

        <nav>
          <div className="nav-label">WORKSPACE</div>
          <button className="nav-item">
            <span>⌂</span> Overview
          </button>
          <button className="nav-item">
            <span>↔</span> Payments
          </button>
          <button className="nav-item">
            <span>◈</span> Customers
          </button>
          <button className="nav-item">
            <span>◫</span> Subscriptions
          </button>

          <div className="nav-label second">AGENTS</div>
          <button className="nav-item">
            <span>✦</span> Agent Studio
          </button>
          <button className="nav-item active">
            <span>◉</span> Black Box
            {runs && runs.length > 0 ? <b>{runs.length}</b> : null}
          </button>
        </nav>

        <div className="sidebar-bottom">
          <div className="system">
            <i />
            <div>
              <strong>All systems operational</strong>
              <span>Agent infrastructure healthy</span>
            </div>
          </div>

          <div className="profile">
            <div className="profile-avatar">AS</div>
            <div>
              <strong>Admin</strong>
              <span>Workspace owner</span>
            </div>
            <span className="more">•••</span>
          </div>
        </div>
      </aside>

      <aside className="runs-panel">
        <div className="runs-panel-header">
          <span className="card-label">RECENT RUNS</span>
          <h3>Agent runs</h3>
        </div>

        {runs === null && (
          <div className="runs-state">Loading runs…</div>
        )}

        {runs !== null && runsError && (
          <div className="runs-state runs-state-error">
            Could not load runs.
            <span>{runsError}</span>
          </div>
        )}

        {runs !== null && !runsError && runs.length === 0 && (
          <div className="runs-state">No agent runs yet.</div>
        )}

        {runs !== null && !runsError && runs.length > 0 && (
          <div className="run-list">
            {runs.map((r) => {
              const s = statusLabel(r.status);
              return (
                <button
                  key={r.run_id}
                  className={`run-item ${r.run_id === selectedRunId ? "active" : ""}`}
                  onClick={() => setSelectedRunId(r.run_id)}
                >
                  <span className={`run-dot ${s.cls}`} />
                  <span className="run-item-body">
                    <strong>{r.selected_action ?? r.status}</strong>
                    <span className="run-item-meta">{formatTime(r.started_at)}</span>
                  </span>
                </button>
              );
            })}
          </div>
        )}
      </aside>

      <main className="main">
        <header className="topbar">
          <div className="crumbs">
            <span>Agent Studio</span>
            <b>/</b>
            <span>Incidents</span>
            <b>/</b>
            <strong>Black Box</strong>
          </div>

          <div className="top-actions">
            <span className="live-dot" />
            Live
            <button>?</button>
            <div className="top-avatar">AS</div>
          </div>
        </header>

        <div className="content">
          <div className="back">← Back to Agent Studio</div>

          <section className="hero">
            <div>
              <div className="eyebrow">BLACK BOX · INCIDENT REVIEW</div>
              <h1>How the agent handled this incident</h1>
              <p>
                A clear reconstruction of what happened, why the agent acted,
                and the evidence behind its decision.
              </p>
            </div>

            {investigation && (
              <div
                className={`incident-status ${
                  investigation.run.status !== "completed" ? "incident-status-bad" : ""
                }`}
              >
                <span
                  className={
                    investigation.run.status === "completed" ? "success-dot" : "blocked-dot"
                  }
                />
                {statusLabel(investigation.run.status).text}
              </div>
            )}
          </section>

          {investigationLoading && (
            <section className="incident-card state-card">Loading investigation…</section>
          )}

          {!investigationLoading && investigationError && (
            <section className="incident-card state-card state-card-error">
              Could not load this investigation.
              <span>{investigationError}</span>
            </section>
          )}

          {!investigationLoading && !investigationError && !investigation && runs && runs.length === 0 && (
            <section className="incident-card state-card">
              No agent runs recorded yet. Trigger the Subscription Recovery agent to see an
              investigation here.
            </section>
          )}

          {!investigationLoading && !investigationError && investigation && (
            <>
              <section className="incident-card">
                <div className="incident-icon">↻</div>

                <div className="incident-main">
                  <span className="card-label">RECOVERY INCIDENT</span>
                  <h2>{investigation.run.selected_action ?? investigation.run.status}</h2>
                  <p>{investigation.run.user_request}</p>
                </div>

                <div className="incident-meta">
                  <span>Payment</span>
                  <strong>{investigation.run.payment_id ?? "—"}</strong>
                </div>

                <div className="incident-meta">
                  <span>Agent</span>
                  <strong>{investigation.run.agent_name}</strong>
                </div>
              </section>

              <div className="tabs">
                <button
                  className={tab === "intelligence" ? "selected blue" : ""}
                  onClick={() => setTab("intelligence")}
                >
                  Intelligence
                </button>
                <button
                  className={tab === "trace" ? "selected dark" : ""}
                  onClick={() => setTab("trace")}
                >
                  Trace
                </button>
                <button
                  className={tab === "evidence" ? "selected light" : ""}
                  onClick={() => setTab("evidence")}
                >
                  Evidence
                </button>
              </div>

              {tab === "intelligence" && (
                <section className="intelligence">
                  <div className="section-heading">
                    <div>
                      <span className="eyebrow">INTELLIGENCE</span>
                      <h2>What happened?</h2>
                    </div>
                    {decision && (
                      <span className="confidence">
                        {Math.round(decision.confidence * 100)}% confidence
                      </span>
                    )}
                  </div>

                  <div className="insight-card">
                    <div className="insight-top">
                      <div className="ai-orb">✦</div>
                      <div>
                        <span className="card-label">BLACK BOX EXPLAINS</span>
                        <h3>{investigation.conclusion}</h3>
                      </div>
                      <span
                        className={
                          investigation.run.status === "completed"
                            ? "resolved-pill"
                            : "resolved-pill blocked-pill"
                        }
                      >
                        {statusLabel(investigation.run.status).text}
                      </span>
                    </div>

                    <div className="reason-grid">
                      <div>
                        <span>DECISION</span>
                        <strong>{decision ? decision.action.replace(/_/g, " ") : "No decision recorded"}</strong>
                        <p>{decision?.reason ?? "—"}</p>
                      </div>
                      <div>
                        <span>SAFETY CHECK</span>
                        <strong>{policy?.allowed ? "Allowed to proceed" : "Blocked"}</strong>
                        <p>
                          {policy
                            ? `Confidence ${Math.round(policy.confidence * 100)}% vs ${Math.round(
                                policy.threshold * 100,
                              )}% threshold.`
                            : "No policy check recorded."}
                        </p>
                      </div>
                    </div>
                  </div>

                  <div className="outcome-banner">
                    <div className="outcome-icon">
                      {investigation.run.status === "completed" ? "✓" : "!"}
                    </div>
                    <div>
                      <span>FINAL OUTCOME</span>
                      <strong>{investigation.run.outcome ?? "No outcome recorded"}</strong>
                      <p>{investigation.conclusion}</p>
                    </div>
                  </div>
                </section>
              )}

              {tab === "trace" && (
                <section className="trace-section">
                  <div className="section-heading">
                    <div>
                      <span className="eyebrow">TRACE</span>
                      <h2>What did the agent do?</h2>
                      <p>Every important step reconstructed in plain English.</p>
                    </div>
                  </div>

                  <div className="trace">
                    {steps.map((step) => (
                      <div className="trace-row" key={step.number}>
                        <div className={`step-number ${step.type}`}>{step.number}</div>
                        <div className="trace-card">
                          <strong>{step.title}</strong>
                          <p>{step.body}</p>
                        </div>
                      </div>
                    ))}
                  </div>
                </section>
              )}

              {tab === "evidence" && (
                <section className="evidence-section">
                  <div className="section-heading">
                    <div>
                      <span className="eyebrow">EVIDENCE</span>
                      <h2>How do we know?</h2>
                      <p>Black Box keeps the proof behind every important agent action.</p>
                    </div>

                    <div className="integrity">
                      <span>{investigation.evidence_integrity.status === "clean" ? "✓" : "!"}</span>
                      Evidence {investigation.evidence_integrity.status === "clean" ? "consistent" : "has issues"}
                    </div>
                  </div>

                  <div className="evidence-list">
                    {evidenceItems.map((item) => (
                      <div className="evidence-row" key={item.title}>
                        <span className="check">{item.ok ? "✓" : "!"}</span>
                        <strong>{item.title}</strong>
                        <p>{item.body}</p>
                      </div>
                    ))}
                    {evidenceItems.length === 0 && (
                      <div className="evidence-row">
                        <span className="check">–</span>
                        <strong>No evidence recorded</strong>
                        <p>This run has no reconstructable evidence events yet.</p>
                      </div>
                    )}
                  </div>
                </section>
              )}

              <section className="technical">
                <button onClick={() => setTechnicalOpen(!technicalOpen)}>
                  <span>View technical details</span>
                  <span>{technicalOpen ? "⌃" : "⌄"}</span>
                </button>

                {technicalOpen && (
                  <pre>
                    {JSON.stringify(
                      {
                        run_id: investigation.run.run_id,
                        decision,
                        policy,
                        tool,
                        state_changes: stateChanges,
                        evidence_integrity: investigation.evidence_integrity,
                      },
                      null,
                      2,
                    )}
                  </pre>
                )}
              </section>
            </>
          )}
        </div>
      </main>
    </div>
  );
}

export { App };
