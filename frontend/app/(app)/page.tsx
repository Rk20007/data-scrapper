import Link from "next/link";

import ActionButton from "@/components/ActionButton";
import { CompanyLink, ContactCell, Empty, EvidenceLink, GradeBadge, Pill } from "@/components/ui";
import { api } from "@/lib/api";
import { ago, label } from "@/lib/format";
import type { LeadRow, Source } from "@/lib/types";

interface Summary {
  totals: Record<string, number>;
  by_grade: Record<string, number>;
  by_status: Record<string, number>;
  hot_leads: LeadRow[];
  recent_replies: { id: number; from_email: string; subject: string; classification: string; summary: string | null; received_at: string }[];
  sources: { total: number; enabled: number; failing: Source[] };
  activity: { id: number; entity_type: string; entity_id: number | null; action: string; created_at: string }[];
  system: { ai_enabled: boolean; send_mode: string; daily_send_limit: number };
}

const GRADE_COLORS: Record<string, string> = {
  HOT: "var(--hot-fg)",
  HIGH: "var(--high-fg)",
  WARM: "var(--warm-fg)",
  LOW: "var(--low-fg)",
};

export const dynamic = "force-dynamic";

export default async function Dashboard() {
  const s = await api<Summary>("/dashboard/summary");
  const gradeTotal = Object.values(s.by_grade).reduce((a, b) => a + b, 0) || 1;

  return (
    <>
      <div className="page-head">
        <div>
          <h1>Dashboard</h1>
          <p className="sub">
            Email mode: <b>{label(s.system.send_mode)}</b> · Daily limit {s.system.daily_send_limit} · AI{" "}
            {s.system.ai_enabled ? "enabled" : <b className="error">not configured</b>}
          </p>
        </div>
        <div className="row">
          <ActionButton path="/jobs/dispatch_sources" done="Queued">Scan sources now</ActionButton>
          <ActionButton path="/jobs/plan_outreach" done="Queued">Plan outreach</ActionButton>
        </div>
      </div>

      {s.system.send_mode === "dry_run" && (
        <div className="notice">
          Dry-run mode: emails are generated and logged but not sent. Switch modes in <Link href="/settings">Settings</Link>.
        </div>
      )}

      <div className="grid grid-4" style={{ marginBottom: 16 }}>
        {[
          ["HOT + HIGH leads", (s.by_grade.HOT ?? 0) + (s.by_grade.HIGH ?? 0)],
          ["New projects (7d)", s.totals.new_projects_7d],
          ["Emails sent today", s.totals.emails_sent_today],
          ["Replies (7d)", s.totals.replies_7d],
          ["Companies tracked", s.totals.companies],
          ["Quality companies", s.totals.quality_companies],
          ["Contacts with email", s.totals.contacts_with_email],
          ["Drafts awaiting approval", s.totals.drafts_pending],
        ].map(([k, v]) => (
          <div className="card kpi" key={k as string}>
            <div className="value">{v as number}</div>
            <div className="label">{k}</div>
          </div>
        ))}
      </div>

      <div className="grid grid-3-1">
        <div className="stack">
          <div className="card">
            <div className="row between">
              <h2>Top current leads</h2>
              <Link href="/leads?grade=HOT&grade=HIGH" className="small">View all →</Link>
            </div>
            {s.hot_leads.length === 0 ? (
              <Empty>No HOT or HIGH leads yet. Sources are scanned every few hours.</Empty>
            ) : (
              <div className="table-wrap" style={{ border: 0 }}>
                <table>
                  <thead>
                    <tr><th>Grade</th><th>Company / project</th><th>Evidence</th><th>Contact</th><th>Status</th></tr>
                  </thead>
                  <tbody>
                    {s.hot_leads.map((l) => (
                      <tr key={l.id}>
                        <td><GradeBadge grade={l.grade} score={l.score} /></td>
                        <td>
                          <CompanyLink company={l.company} fallback={l.tender_authority} />
                          <div><Link href={`/leads/${l.id}`} className="small">{l.title}</Link></div>
                          <div className="muted small">{label(l.project_type)} · {l.cluster ?? "—"}</div>
                        </td>
                        <td><EvidenceLink ev={l.top_evidence} /></td>
                        <td><ContactCell c={l.contact} /></td>
                        <td><Pill value={l.lead_status} /></td>
                      </tr>
                    ))}
                  </tbody>
                </table>
              </div>
            )}
          </div>

          <div className="card">
            <h2>Recent replies</h2>
            {s.recent_replies.length === 0 ? (
              <Empty>No replies yet.</Empty>
            ) : (
              <table>
                <tbody>
                  {s.recent_replies.map((r) => (
                    <tr key={r.id}>
                      <td><Pill value={r.classification} /></td>
                      <td>
                        <div>{r.from_email}</div>
                        <div className="muted small">{r.summary ?? r.subject}</div>
                      </td>
                      <td className="muted small">{ago(r.received_at)}</td>
                    </tr>
                  ))}
                </tbody>
              </table>
            )}
          </div>
        </div>

        <div className="stack">
          <div className="card">
            <h2>Current leads by grade</h2>
            <div className="bar" style={{ marginBottom: 10 }}>
              {Object.entries(s.by_grade).map(([g, n]) => (
                <span key={g} style={{ width: `${(n / gradeTotal) * 100}%`, background: GRADE_COLORS[g] }} />
              ))}
            </div>
            <dl className="kv">
              {Object.entries(s.by_grade).map(([g, n]) => (
                <div key={g} style={{ display: "contents" }}>
                  <dt><Link href={`/leads?grade=${g}`}><span className={`badge g-${g}`}>{g}</span></Link></dt>
                  <dd className="num" style={{ textAlign: "left" }}>{n}</dd>
                </div>
              ))}
            </dl>
          </div>

          <div className="card">
            <h2>Pipeline</h2>
            <dl className="kv">
              {Object.entries(s.by_status).sort((a, b) => b[1] - a[1]).map(([k, v]) => (
                <div key={k} style={{ display: "contents" }}>
                  <dt><Link href={`/leads?status=${k}&current_only=false`}>{label(k)}</Link></dt>
                  <dd>{v}</dd>
                </div>
              ))}
            </dl>
          </div>

          <div className="card">
            <div className="row between">
              <h2>Source health</h2>
              <Link href="/sources" className="small">Manage →</Link>
            </div>
            <p className="small muted">{s.sources.enabled} of {s.sources.total} sources enabled</p>
            {s.sources.failing.length === 0 ? (
              <p className="small">All enabled sources healthy.</p>
            ) : (
              s.sources.failing.map((src) => (
                <div key={src.id} className="small" style={{ marginBottom: 8 }}>
                  <span className="pill bad">error</span> {src.name}
                  <div className="muted truncate">{src.last_error}</div>
                </div>
              ))
            )}
          </div>

          <div className="card">
            <h2>Activity</h2>
            {s.activity.map((a) => (
              <div key={a.id} className="small row between" style={{ marginBottom: 4 }}>
                <span>{label(a.entity_type)} #{a.entity_id} {a.action.replace(/_/g, " ")}</span>
                <span className="muted">{ago(a.created_at)}</span>
              </div>
            ))}
          </div>
        </div>
      </div>
    </>
  );
}
