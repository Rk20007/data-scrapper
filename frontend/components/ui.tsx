import Link from "next/link";

import { host, label } from "@/lib/format";
import type { Contact, Evidence, Grade } from "@/lib/types";

export function GradeBadge({ grade, score }: { grade: Grade; score?: number }) {
  return (
    <span className={`badge g-${grade}`} title={score !== undefined ? `Score ${score}/100` : undefined}>
      {grade}
      {score !== undefined ? ` · ${score}` : ""}
    </span>
  );
}

const GOOD = new Set(["sent", "interested", "replied", "contacted", "won", "mx_ok", "ok", "active"]);
const BAD = new Set([
  "failed", "not_interested", "unsubscribed", "lost", "disqualified", "bounced", "invalid", "error",
  "stopped_bounced", "stopped_unsubscribed", "stopped_declined", "cancelled",
]);
const WARN = new Set(["draft", "needs_contact", "approved", "sending", "dry_run", "outreach_queued", "skipped"]);

export function Pill({ value }: { value?: string | null }) {
  if (!value) return <span className="muted">—</span>;
  const tone = GOOD.has(value) ? "ok" : BAD.has(value) ? "bad" : WARN.has(value) ? "warn" : "";
  return <span className={`pill ${tone}`}>{label(value)}</span>;
}

const SOURCE_LABEL: Record<string, string> = {
  news_rss: "News",
  search: "Web search",
  listing: "RIICO / notice",
  tender_table: "e-Tender",
  company_website: "Company site",
  manual: "Manual",
};

export function EvidenceLink({ ev }: { ev: Evidence | null }) {
  if (!ev) return <span className="muted">—</span>;
  return (
    <div>
      <a href={ev.url} target="_blank" rel="noreferrer noopener" className="small">
        {SOURCE_LABEL[ev.source_kind] ?? ev.source_kind} · {host(ev.url)}
      </a>
    </div>
  );
}

export function ContactCell({ c }: { c: Contact | null }) {
  if (!c) return <span className="muted small">No contact yet</span>;
  return (
    <div className="small">
      <div>{c.name ?? <span className="muted">{label(c.role_category)} mailbox</span>}</div>
      {c.title && <div className="muted">{c.title}</div>}
      {c.email ? <div>{c.email}</div> : <div className="muted">no public email</div>}
    </div>
  );
}

export function CompanyLink({ company, fallback }: { company: { id: number; name: string } | null; fallback?: string | null }) {
  if (!company) return <span>{fallback ?? "—"}</span>;
  return <Link href={`/companies/${company.id}`}>{company.name}</Link>;
}

export function Empty({ children }: { children: React.ReactNode }) {
  return <div className="empty">{children}</div>;
}
