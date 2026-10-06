import Link from "next/link";

import { AddCompanyForm, ImportCsvForm } from "@/components/Forms";
import { Empty, GradeBadge } from "@/components/ui";
import { api, qs } from "@/lib/api";
import { ago, CLUSTERS, GRADES, label } from "@/lib/format";
import type { Company, Page } from "@/lib/types";

export const dynamic = "force-dynamic";
const PAGE = 50;

export default async function CompaniesPage({ searchParams }: { searchParams: Promise<Record<string, string | undefined>> }) {
  const sp = await searchParams;
  const page = Math.max(1, Number(sp.page ?? 1));
  const params = {
    q: sp.q, cluster: sp.cluster, grade: sp.grade, quality_only: sp.quality_only,
    limit: String(PAGE), offset: String((page - 1) * PAGE),
  };
  const data = await api<Page<Company>>(`/companies${qs(params)}`);
  const pages = Math.max(1, Math.ceil(data.total / PAGE));
  const link = (p: number) => `/companies${qs({ ...params, limit: undefined, offset: undefined, page: String(p) })}`;

  return (
    <>
      <div className="page-head">
        <div>
          <h1>Companies</h1>
          <p className="sub">{data.total} industrial companies discovered or added</p>
        </div>
      </div>

      <div className="card stack" style={{ marginBottom: 16, gap: 8 }}>
        <AddCompanyForm />
        <ImportCsvForm />
      </div>

      <form className="filters" method="get">
        <label className="field">Search<input name="q" defaultValue={sp.q} /></label>
        <label className="field">Cluster
          <select name="cluster" defaultValue={sp.cluster ?? ""}>
            <option value="">All</option>
            {CLUSTERS.map((c) => <option key={c}>{c}</option>)}
          </select>
        </label>
        <label className="field">Grade
          <select name="grade" defaultValue={sp.grade ?? ""}>
            <option value="">All</option>
            {GRADES.map((g) => <option key={g}>{g}</option>)}
          </select>
        </label>
        <label className="field">Quality
          <select name="quality_only" defaultValue={sp.quality_only ?? ""}>
            <option value="">All</option>
            <option value="true">Quality only</option>
          </select>
        </label>
        <button className="btn primary">Apply</button>
      </form>

      {data.items.length === 0 ? (
        <div className="card"><Empty>No companies yet.</Empty></div>
      ) : (
        <div className="table-wrap">
          <table>
            <thead>
              <tr><th>Grade</th><th>Company</th><th>Cluster</th><th>Size</th><th className="num">Projects</th><th className="num">Contacts (email)</th><th>Monitored</th></tr>
            </thead>
            <tbody>
              {data.items.map((c) => (
                <tr key={c.id}>
                  <td><GradeBadge grade={c.grade} score={c.score} /></td>
                  <td>
                    <Link href={`/companies/${c.id}`}>{c.name}</Link>
                    <div className="muted small">{c.domain ?? "no website"}{c.industry ? ` · ${c.industry}` : ""}</div>
                  </td>
                  <td>{c.cluster ?? "—"}</td>
                  <td>
                    {label(c.size_tier)}
                    {c.is_quality && <span className="pill ok" style={{ marginLeft: 6 }}>quality</span>}
                  </td>
                  <td className="num">{c.project_count}</td>
                  <td className="num">{c.contact_count} ({c.email_contact_count})</td>
                  <td className="small muted">{ago(c.last_monitored_at)}</td>
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
