import ActionButton from "@/components/ActionButton";
import { SuppressionForm } from "@/components/Forms";
import SettingsForm, { type Runtime } from "@/components/SettingsForm";
import { api } from "@/lib/api";
import { fmtDate, label } from "@/lib/format";
import type { Page } from "@/lib/types";

export const dynamic = "force-dynamic";

interface SettingsView {
  runtime: Runtime;
  system: {
    ai_enabled: boolean;
    openai_model: string;
    search_provider: string;
    smtp_configured: boolean;
    imap_configured: boolean;
    sender: string | null;
    sender_address_set: boolean;
    notifications: string[];
    target_clusters: string[];
    timezone: string;
  };
}

interface SuppressionRow {
  id: number;
  email: string | null;
  domain: string | null;
  reason: string;
  note: string | null;
  created_at: string;
}

function Check({ ok, children }: { ok: boolean; children: React.ReactNode }) {
  return (
    <div className="row small" style={{ marginBottom: 4 }}>
      <span className={`pill ${ok ? "ok" : "bad"}`}>{ok ? "ok" : "missing"}</span> {children}
    </div>
  );
}

export default async function SettingsPage() {
  const [s, sup] = await Promise.all([
    api<SettingsView>("/settings"),
    api<Page<SuppressionRow>>("/suppressions?limit=200"),
  ]);
  const sys = s.system;

  return (
    <>
      <div className="page-head">
        <div>
          <h1>Settings</h1>
          <p className="sub">Runtime controls take effect immediately. Credentials are set in the server .env file.</p>
        </div>
      </div>

      <div className="grid grid-3-1">
        <div className="stack">
          <div className="card">
            <h2>Email automation</h2>
            <SettingsForm initial={s.runtime} />
          </div>

          <div className="card">
            <h2>Suppression list ({sup.total})</h2>
            <p className="small muted">
              Unsubscribes, declines and bounces are added automatically and checked before every send.
            </p>
            <SuppressionForm />
            <div className="table-wrap">
              <table>
                <thead><tr><th>Email / domain</th><th>Reason</th><th>Added</th><th></th></tr></thead>
                <tbody>
                  {sup.items.map((r) => (
                    <tr key={r.id}>
                      <td>{r.email ?? `*@${r.domain}`}<div className="muted small">{r.note}</div></td>
                      <td>{label(r.reason)}</td>
                      <td className="small muted">{fmtDate(r.created_at)}</td>
                      <td>
                        {r.reason !== "unsubscribe" && (
                          <ActionButton path={`/suppressions/${r.id}`} method="DELETE" size="sm" confirm="Remove from suppression list?">
                            Remove
                          </ActionButton>
                        )}
                      </td>
                    </tr>
                  ))}
                </tbody>
              </table>
            </div>
          </div>
        </div>

        <div className="stack">
          <div className="card">
            <h2>System checks</h2>
            <Check ok={sys.ai_enabled}>OpenAI ({sys.openai_model})</Check>
            <Check ok={sys.search_provider !== "none"}>Web search provider ({sys.search_provider})</Check>
            <Check ok={sys.smtp_configured}>SMTP sending</Check>
            <Check ok={sys.imap_configured}>IMAP reply detection</Check>
            <Check ok={!!sys.sender}>Sender identity {sys.sender && <span className="muted">{sys.sender}</span>}</Check>
            <Check ok={sys.sender_address_set}>Postal address in footer</Check>
            <Check ok={sys.notifications.length > 0}>Notifications {sys.notifications.join(", ")}</Check>
            <p className="small muted">Clusters: {sys.target_clusters.join(", ")} · {sys.timezone}</p>
          </div>
          <div className="card">
            <h2>Run jobs now</h2>
            <div className="stack" style={{ gap: 8 }}>
              {[
                ["process_documents", "Re-process pending documents"],
                ["assess_companies", "Assess new companies"],
                ["enrich_contacts", "Find contacts for top leads"],
                ["rescore", "Rescore all leads"],
                ["send_queue", "Send next queued email"],
                ["daily_digest", "Send digest notification"],
              ].map(([job, text]) => (
                <ActionButton key={job} path={`/jobs/${job}`} size="sm" done="Queued">{text}</ActionButton>
              ))}
            </div>
          </div>
        </div>
      </div>
    </>
  );
}
