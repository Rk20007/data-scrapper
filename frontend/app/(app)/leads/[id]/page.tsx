import Link from "next/link";

import ActionButton from "@/components/ActionButton";
import EmailCard from "@/components/EmailCard";
import { LeadStatusEditor, StartOutreach } from "@/components/LeadControls";
import { GradeBadge, Pill } from "@/components/ui";
import { api } from "@/lib/api";
import { crore, fmtDate, host, label } from "@/lib/format";
import type { LeadDetail } from "@/lib/types";

export const dynamic = "force-dynamic";

const BREAKDOWN_LABELS: Record<string, string> = {
  project_type: "Project type",
  stage: "Stage",
  recency: "Recency",
  location: "Location match",
  size: "Project size",
  company: "Company quality",
  evidence: "Evidence strength",
  contact: "Contact reachability",
};

export default async function LeadPage({ params }: { params: Promise<{ id: string }> }) {
  const { id } = await params;
  const l = await api<LeadDetail>(`/leads/${id}`);
  const b = l.score_breakdown ?? {};
  const activeOutreach = l.outreaches.find((o) => o.status === "active" || o.status === "paused");

  return (
    <>
      <div className="page-head">
        <div>
          <p className="sub small"><Link href="/leads">← Leads</Link></p>
          <h1>{l.title}</h1>
          <div className="row">
            <GradeBadge grade={l.grade} score={l.score} />
            <Pill value={l.lead_status} />
            <span className="pill">{l.kind === "tender" ? "Public tender" : "Private project"}</span>
            {!l.is_current && <span className="pill bad">Not current</span>}
            {!l.is_relevant && <span className="pill bad">Not relevant</span>}
            <span className="small muted">AI confidence {(l.ai_confidence * 100).toFixed(0)}%</span>
          </div>
        </div>
        <div className="row">
          <ActionButton path={`/leads/${l.id}/rescore`}>Rescore</ActionButton>
          {l.company && <ActionButton path={`/companies/${l.company.id}/enrich`} done="Contact search queued">Find contacts</ActionButton>}
        </div>
      </div>

      <div className="grid grid-3-1">
        <div className="stack">
          <div className="card">
            <h3>Project</h3>
            <dl className="kv">
              <dt>Company</dt>
              <dd>{l.company ? <Link href={`/companies/${l.company.id}`}>{l.company.name}</Link> : l.tender_authority ?? "—"}</dd>
              <dt>Type · stage</dt><dd>{label(l.project_type)} · {label(l.stage)}</dd>
              <dt>Location</dt><dd>{l.location_text ?? "—"} {l.cluster && <span className="pill">{l.cluster}</span>}</dd>
              <dt>Investment</dt><dd>{crore(l.investment_inr_crore)}</dd>
              {l.area_sqft != null && (<><dt>Area</dt><dd>{l.area_sqft.toLocaleString("en-IN")} sq ft</dd></>)}
              <dt>Timeline</dt><dd>{l.timeline ?? "—"}</dd>
              <dt>Announced</dt><dd>{fmtDate(l.announcement_date)}</dd>
              {l.kind === "tender" && (
                <>
                  <dt>Tender ref</dt><dd>{l.tender_ref ?? "—"}</dd>
                  <dt>Closing</dt><dd>{fmtDate(l.tender_closing_at, true)}</dd>
                  <dt>Value</dt><dd>{l.tender_value_inr ? `₹${l.tender_value_inr.toLocaleString("en-IN")}` : "—"}</dd>
                </>
              )}
              <dt>First seen</dt><dd>{fmtDate(l.first_seen_at, true)}</dd>
            </dl>
          </div>

          <div className="card">
            <h3>Verified facts</h3>
            {l.key_facts.length ? (
              <ul className="facts">{l.key_facts.map((f, i) => <li key={i}>{f}</li>)}</ul>
            ) : <p className="muted">None extracted.</p>}
            {l.ai_reason && <p className="small muted" style={{ marginBottom: 0 }}><b>AI assessment:</b> {l.ai_reason}</p>}
          </div>

          <div className="card">
            <h3>Evidence ({l.evidence.length})</h3>
            {l.evidence.map((e) => (
              <div className="evidence" key={e.id}>
                <a href={e.url} target="_blank" rel="noreferrer noopener">{e.title || host(e.url)}</a>
                <div className="small muted">{label(e.source_kind)} · {host(e.url)} · {fmtDate(e.published_at ?? e.created_at)}</div>
                {e.quote && <div className="small" style={{ marginTop: 4 }}>{e.quote}</div>}
              </div>
            ))}
          </div>

          {l.kind !== "tender" && (
            <div className="card">
              <div className="row between">
                <h3>Outreach</h3>
                {!activeOutreach && <StartOutreach leadId={l.id} contacts={l.contacts} />}
              </div>
              {l.outreaches.length === 0 && <p className="muted small">No emails yet. HIGH/HOT leads with a reachable contact are drafted automatically.</p>}
              {l.outreaches.map((o) => (
                <div key={o.id} className="stack" style={{ gap: 10, marginBottom: 12 }}>
                  <div className="row between">
                    <span className="small">
                      To <b>{o.contact.name ?? o.contact.email}</b> {o.contact.title && `(${o.contact.title})`} · <Pill value={o.status} />
                      {o.next_action_at && <span className="muted"> · next follow-up {fmtDate(o.next_action_at)}</span>}
                      {o.stopped_reason && <span className="muted"> · {o.stopped_reason}</span>}
                    </span>
                    {(o.status === "active" || o.status === "paused") && (
                      <ActionButton path={`/outreach/${o.id}/stop`} size="sm" variant="danger" confirm="Stop this sequence? Pending emails will be cancelled.">
                        Stop sequence
                      </ActionButton>
                    )}
                  </div>
                  {o.messages.map((m) => <EmailCard key={m.id} email={m} />)}
                </div>
              ))}
            </div>
          )}
        </div>

        <div className="stack">
          <div className="card">
            <h3>Score breakdown</h3>
            <dl className="kv">
              {Object.entries(BREAKDOWN_LABELS).map(([k, lbl]) =>
                b[k] !== undefined ? (
                  <div key={k} style={{ display: "contents" }}>
                    <dt>{lbl}</dt><dd>+{b[k]}</dd>
                  </div>
                ) : null,
              )}
              <dt>Confidence ×</dt><dd>{String(b.confidence_multiplier ?? "—")}</dd>
              {b.gate && (<><dt>Gate</dt><dd className="error">{String(b.gate)}</dd></>)}
              <dt><b>Score</b></dt><dd><b>{l.score}</b> / 100</dd>
            </dl>
          </div>

          <div className="card">
            <h3>Manage</h3>
            <LeadStatusEditor id={l.id} status={l.lead_status} notes={l.notes} />
          </div>

          {l.kind !== "tender" && (
            <div className="card">
              <h3>Contacts ({l.contacts.length})</h3>
              {l.contacts.length === 0 && <p className="small muted">None found yet.</p>}
              {l.contacts.map((c) => (
                <div key={c.id} className="small" style={{ marginBottom: 10 }}>
                  <div><b>{c.name ?? label(c.role_category) + " mailbox"}</b> {c.do_not_contact && <span className="pill bad">do not contact</span>}</div>
                  {c.title && <div className="muted">{c.title}</div>}
                  {c.email && <div>{c.email} <Pill value={c.email_status} /></div>}
                  {c.source_url && (
                    <a href={c.source_url} target="_blank" rel="noreferrer noopener" className="muted">source: {host(c.source_url)}</a>
                  )}
                </div>
              ))}
            </div>
          )}
        </div>
      </div>
    </>
  );
}
