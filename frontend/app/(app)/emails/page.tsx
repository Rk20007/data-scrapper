import Link from "next/link";

import ActionButton from "@/components/ActionButton";
import EmailCard from "@/components/EmailCard";
import { Empty, GradeBadge } from "@/components/ui";
import { api, qs } from "@/lib/api";
import type { Email, Page } from "@/lib/types";

export const dynamic = "force-dynamic";

const TABS = [
  { key: "draft", label: "Awaiting approval" },
  { key: "approved", label: "Queued" },
  { key: "sent", label: "Sent" },
  { key: "dry_run", label: "Dry run" },
  { key: "failed", label: "Failed" },
  { key: "skipped", label: "Skipped" },
  { key: "cancelled", label: "Cancelled" },
];

export default async function EmailsPage({ searchParams }: { searchParams: Promise<{ status?: string }> }) {
  const { status = "draft" } = await searchParams;
  const data = await api<Page<Email>>(`/emails${qs({ status, limit: "100" })}`);

  return (
    <>
      <div className="page-head">
        <div>
          <h1>Email queue</h1>
          <p className="sub">
            Every email is built only from verified project facts. Limits, send window and duplicate checks are enforced at send time.
          </p>
        </div>
        <div className="row">
          <ActionButton path="/jobs/schedule_followups" done="Queued">Draft due follow-ups</ActionButton>
          <ActionButton path="/jobs/poll_inbox" done="Queued">Check replies</ActionButton>
        </div>
      </div>

      <div className="row" style={{ marginBottom: 16 }}>
        {TABS.map((t) => (
          <Link key={t.key} href={`/emails?status=${t.key}`} className={`btn sm ${status === t.key ? "primary" : ""}`}>
            {t.label}
          </Link>
        ))}
      </div>

      {data.items.length === 0 ? (
        <div className="card"><Empty>Nothing here.</Empty></div>
      ) : (
        <div className="stack">
          {data.items.map((m) => (
            <EmailCard
              key={m.id}
              email={m}
              context={
                <div className="row small" style={{ marginTop: 6 }}>
                  {m.grade && <GradeBadge grade={m.grade} score={m.score} />}
                  <b>{m.company_name ?? "—"}</b>
                  <Link href={`/leads/${m.project_id}`}>{m.project_title}</Link>
                  <span className="muted">
                    → {m.contact_name ?? "mailbox"}
                    {m.contact_title ? `, ${m.contact_title}` : ""}
                  </span>
                </div>
              }
            />
          ))}
        </div>
      )}
    </>
  );
}
