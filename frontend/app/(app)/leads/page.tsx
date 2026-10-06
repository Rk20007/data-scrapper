import Link from "next/link";

import { CompanyLink, ContactCell, Empty, EvidenceLink, GradeBadge, Pill } from "@/components/ui";
import { api, qs } from "@/lib/api";
import { CLUSTERS, crore, fmtDate, GRADES, label, LEAD_STATUSES, PROJECT_TYPES } from "@/lib/format";
import type { LeadRow, Page } from "@/lib/types";

export const dynamic = "force-dynamic";

type SP = Record<string, string | string[] | undefined>;
const PAGE = 50;

function arr(v: string | string[] | undefined): string[] {
  return v === undefined ? [] : Array.isArray(v) ? v : [v];
}

export default async function LeadsPage({ searchParams }: { searchParams: Promise<SP> }) {
  const sp = await searchParams;
  const page = Math.max(1, Number(sp.page ?? 1));
  const isTender = sp.kind === "tender";
  const params = {
    grade: arr(sp.grade),
    status: arr(sp.status),
    cluster: sp.cluster as string | undefined,
    project_type: sp.project_type as string | undefined,
    kind: sp.kind as string | undefined,
    q: sp.q as string | undefined,
    sort: (sp.sort as string) ?? "score",
    current_only: (sp.current_only as string) ?? "true",
    limit: String(PAGE),
    offset: String((page - 1) * PAGE),
  };
  const data = await api<Page<LeadRow>>(`/leads${qs(params)}`);
  const pages = Math.max(1, Math.ceil(data.total / PAGE));
  const link = (p: number) => `/leads${qs({ ...params, limit: undefined, offset: undefined, page: String(p) })}`;

  return (
    <>
      <div className="page-head">
        <div>
          <h1>{isTender ? "Tenders" : "Leads"}</h1>
          <p className="sub">{data.total} opportunities · evidence-backed and AI-verified</p>
        </div>
      </div>

      <form className="filters card" method="get">
        <label className="field">Search<input name="q" defaultValue={params.q} placeholder="Company or project" /></label>
        <label className="field">Grade
          <select name="grade" defaultValue={params.grade[0] ?? ""}>
            <option value="">All</option>
            {GRADES.map((g) => <option key={g}>{g}</option>)}
          </select>
        </label>
        <label className="field">Cluster
          <select name="cluster" defaultValue={params.cluster ?? ""}>
            <option value="">All</option>
            {CLUSTERS.map((c) => <option key={c}>{c}</option>)}
          </select>
        </label>
        <label className="field">Type
          <select name="project_type" defaultValue={params.project_type ?? ""}>
            <option value="">All</option>
            {PROJECT_TYPES.map((t) => <option key={t} value={t}>{label(t)}</option>)}
          </select>
        </label>
        <label className="field">Kind
          <select name="kind" defaultValue={params.kind ?? ""}>
            <option value="">All</option>
            <option value="private_project">Private projects</option>
            <option value="tender">Tenders</option>
          </select>
        </label>
        <label className="field">Lead status
          <select name="status" defaultValue={params.status[0] ?? ""}>
            <option value="">All</option>
            {LEAD_STATUSES.map((s) => <option key={s} value={s}>{label(s)}</option>)}
          </select>
        </label>
        <label className="field">Show
          <select name="current_only" defaultValue={params.current_only}>
            <option value="true">Current &amp; relevant</option>
            <option value="false">Everything</option>
          </select>
        </label>
        <label className="field">Sort
          <select name="sort" defaultValue={params.sort}>
            <option value="score">Score</option>
            <option value="recent">Newest</option>
            <option value="evidence">Latest evidence</option>
          </select>
        </label>
        <button className="btn primary" type="submit">Apply</button>
        <Link className="btn" href="/leads">Reset</Link>
      </form>

      {data.items.length === 0 ? (
        <div className="card"><Empty>No leads match these filters.</Empty></div>
      ) : (
        <div className="table-wrap">
          <table>
            <thead>
              <tr>
                <th>Score</th>
                <th>Company</th>
                <th>Project</th>
                <th>Evidence / source</th>
                <th>{isTender ? "Closes" : "Contact"}</th>
                <th>Email</th>
                <th>Lead status</th>
              </tr>
            </thead>
            <tbody>
              {data.items.map((l) => (
                <tr key={l.id}>
                  <td><GradeBadge grade={l.grade} score={l.score} /></td>
                  <td>
                    <CompanyLink company={l.company} fallback={l.tender_authority ?? "Public tender"} />
                    {l.company && <div className="muted small">{label(l.company.size_tier)}{l.company.is_quality ? " · quality" : ""}</div>}
                  </td>
                  <td style={{ maxWidth: 360 }}>
                    <Link href={`/leads/${l.id}`}>{l.title}</Link>
                    <div className="muted small">
                      {label(l.project_type)} · {label(l.stage)} · {l.cluster ?? l.location_text ?? "—"}
                      {l.investment_inr_crore ? ` · ${crore(l.investment_inr_crore)}` : ""}
                    </div>
                  </td>
                  <td>
                    <EvidenceLink ev={l.top_evidence} />
                    <div className="muted small">
                      {l.evidence_count} source{l.evidence_count === 1 ? "" : "s"} · {fmtDate(l.last_evidence_at)}
                    </div>
                  </td>
                  <td>{isTender ? <span className="small">{fmtDate(l.tender_closing_at, true)}</span> : <ContactCell c={l.contact} />}</td>
                  <td><Pill value={l.email_status} /></td>
                  <td><Pill value={l.lead_status} /></td>
                </tr>
              ))}
            </tbody>
          </table>
        </div>
      )}

      {pages > 1 && (
        <div className="row" style={{ marginTop: 16 }}>
          {page > 1 && <Link className="btn sm" href={link(page - 1)}>← Prev</Link>}
          <span className="small muted">Page {page} of {pages}</span>
          {page < pages && <Link className="btn sm" href={link(page + 1)}>Next →</Link>}
        </div>
      )}
    </>
  );
}
