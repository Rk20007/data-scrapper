import Link from "next/link";

import ActionButton from "@/components/ActionButton";
import { AddContactForm } from "@/components/Forms";
import { Empty, EvidenceLink, GradeBadge, Pill } from "@/components/ui";
import { api } from "@/lib/api";
import { ago, host, label } from "@/lib/format";
import type { Company, Contact, LeadRow } from "@/lib/types";

export const dynamic = "force-dynamic";

export default async function CompanyPage({ params }: { params: Promise<{ id: string }> }) {
  const { id } = await params;
  const c = await api<Company & { contacts: Contact[]; projects: LeadRow[] }>(`/companies/${id}`);

  return (
    <>
      <div className="page-head">
        <div>
          <p className="sub small"><Link href="/companies">← Companies</Link></p>
          <h1>{c.name}</h1>
          <div className="row">
            <GradeBadge grade={c.grade} score={c.score} />
            <span className="pill">{label(c.size_tier)}</span>
            {c.is_quality && <span className="pill ok">quality</span>}
            {c.website && <a href={c.website} target="_blank" rel="noreferrer noopener" className="small">{host(c.website)}</a>}
          </div>
        </div>
        <div className="row">
          <ActionButton path={`/companies/${c.id}/monitor`} done="Website scan queued">Scan website</ActionButton>
          <ActionButton path={`/companies/${c.id}/enrich`} done="Contact search queued">Find contacts</ActionButton>
          <ActionButton path={`/companies/${c.id}/assess`} done="Assessment queued">Assess size</ActionButton>
        </div>
      </div>

      <div className="grid grid-3-1">
        <div className="stack">
          <div className="card">
            <h3>Projects ({c.projects.length})</h3>
            {c.projects.length === 0 ? (
              <Empty>No projects detected yet.</Empty>
            ) : (
              <table>
                <tbody>
                  {c.projects.map((p) => (
                    <tr key={p.id}>
                      <td><GradeBadge grade={p.grade} score={p.score} /></td>
                      <td>
                        <Link href={`/leads/${p.id}`}>{p.title}</Link>
                        <div className="muted small">{label(p.project_type)} · {label(p.stage)} · {p.cluster ?? "—"}</div>
                      </td>
                      <td><EvidenceLink ev={p.top_evidence} /></td>
                      <td><Pill value={p.lead_status} /></td>
                    </tr>
                  ))}
                </tbody>
              </table>
            )}
          </div>

          <div className="card">
            <h3>Contacts ({c.contacts.length})</h3>
            {c.contacts.length > 0 && (
              <div className="table-wrap" style={{ marginBottom: 12 }}>
                <table>
                  <thead><tr><th>Name / role</th><th>Email</th><th>Source</th><th></th></tr></thead>
                  <tbody>
                    {c.contacts.map((ct) => (
                      <tr key={ct.id}>
                        <td>
                          {ct.name ?? <span className="muted">{label(ct.role_category)} mailbox</span>}
                          <div className="muted small">{ct.title ?? label(ct.role_category)}</div>
                        </td>
                        <td className="small">
                          {ct.email ?? <span className="muted">—</span>} {ct.email && <Pill value={ct.email_status} />}
                          {ct.do_not_contact && <div><span className="pill bad">do not contact</span></div>}
                        </td>
                        <td className="small">
                          {ct.source_url?.startsWith("http") ? (
                            <a href={ct.source_url} target="_blank" rel="noreferrer noopener">{host(ct.source_url)}</a>
                          ) : (ct.source_url ?? "—")}
                        </td>
                        <td>
                          {!ct.do_not_contact && (
                            <ActionButton path={`/contacts/${ct.id}`} method="PATCH" body={{ do_not_contact: true }} size="sm" variant="danger">
                              Do not contact
                            </ActionButton>
                          )}
                        </td>
                      </tr>
                    ))}
                  </tbody>
                </table>
              </div>
            )}
            <AddContactForm companyId={c.id} />
          </div>
        </div>

        <div className="stack">
          <div className="card">
            <h3>Profile</h3>
            <dl className="kv">
              <dt>Cluster</dt><dd>{c.cluster ?? "—"}</dd>
              <dt>Industry</dt><dd>{c.industry ?? "—"}</dd>
              <dt>Employees</dt><dd>{c.employee_estimate?.toLocaleString("en-IN") ?? "—"}</dd>
              <dt>Source</dt><dd>{label(c.source)}</dd>
              <dt>Website scan</dt><dd>{ago(c.last_monitored_at)}</dd>
              <dt>Contact search</dt><dd>{ago(c.last_enriched_at)}</dd>
            </dl>
            {c.quality_reason && <p className="small muted">{c.quality_reason}</p>}
          </div>
          <div className="card">
            <h3>Monitoring</h3>
            <p className="small">Website monitoring is <b>{c.monitor_website ? "on" : "off"}</b>.</p>
            <ActionButton path={`/companies/${c.id}`} method="PATCH" body={{ monitor_website: !c.monitor_website }} size="sm">
              {c.monitor_website ? "Turn off" : "Turn on"}
            </ActionButton>
          </div>
        </div>
      </div>
    </>
  );
}
