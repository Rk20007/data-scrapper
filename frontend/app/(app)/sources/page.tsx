import ActionButton from "@/components/ActionButton";
import { AddSourceForm } from "@/components/Forms";
import { Empty, Pill } from "@/components/ui";
import { api } from "@/lib/api";
import { ago, label } from "@/lib/format";
import type { Source } from "@/lib/types";

export const dynamic = "force-dynamic";

export default async function SourcesPage() {
  const { items } = await api<{ items: Source[] }>("/sources");

  return (
    <>
      <div className="page-head">
        <div>
          <h1>Sources</h1>
          <p className="sub">News, web search, RIICO notices and e-tender portals monitored on a schedule. Company websites are monitored daily from the Companies list.</p>
        </div>
        <div className="row">
          <ActionButton path="/sources/seed" done="Defaults restored">Restore default sources</ActionButton>
          <ActionButton path="/jobs/discover_companies" done="Discovery queued">Discover companies</ActionButton>
          <ActionButton path="/jobs/monitor_websites" done="Queued">Scan all company sites</ActionButton>
        </div>
      </div>

      <div className="card" style={{ marginBottom: 16 }}>
        <h2>Add a source</h2>
        <AddSourceForm />
      </div>

      {items.length === 0 ? (
        <div className="card"><Empty>No sources yet.</Empty></div>
      ) : (
        <div className="table-wrap">
          <table>
            <thead>
              <tr><th>Source</th><th>Kind</th><th>Every</th><th>Last run</th><th>Status</th><th className="num">New items</th><th></th></tr>
            </thead>
            <tbody>
              {items.map((s) => (
                <tr key={s.id} style={{ opacity: s.enabled ? 1 : 0.55 }}>
                  <td>
                    {s.name}
                    <div className="muted small truncate">
                      {s.url ?? (s.config?.query as string | undefined) ?? ""}
                    </div>
                  </td>
                  <td className="small">{label(s.kind)}</td>
                  <td className="small">{s.interval_minutes >= 60 ? `${Math.round(s.interval_minutes / 60)}h` : `${s.interval_minutes}m`}</td>
                  <td className="small muted">{ago(s.last_run_at)}</td>
                  <td>
                    {s.enabled ? <Pill value={s.last_status ?? "pending"} /> : <span className="pill">disabled</span>}
                    {s.last_error && <div className="error small truncate" title={s.last_error}>{s.last_error}</div>}
                  </td>
                  <td className="num">{s.items_last_run}</td>
                  <td>
                    <div className="row" style={{ flexWrap: "nowrap" }}>
                      <ActionButton path={`/sources/${s.id}/run`} size="sm" done="Queued">Run</ActionButton>
                      <ActionButton path={`/sources/${s.id}`} method="PATCH" body={{ enabled: !s.enabled }} size="sm">
                        {s.enabled ? "Disable" : "Enable"}
                      </ActionButton>
                      <ActionButton path={`/sources/${s.id}`} method="DELETE" size="sm" variant="danger" confirm={`Delete "${s.name}"?`}>
                        Delete
                      </ActionButton>
                    </div>
                  </td>
                </tr>
              ))}
            </tbody>
          </table>
        </div>
      )}
    </>
  );
}
