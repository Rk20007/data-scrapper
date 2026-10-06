"use client";

import { useRouter } from "next/navigation";
import { useState } from "react";

import { Pill } from "@/components/ui";
import { callApi } from "@/lib/client";
import { fmtDate } from "@/lib/format";
import type { Email } from "@/lib/types";

export default function EmailCard({ email, context }: { email: Email; context?: React.ReactNode }) {
  const router = useRouter();
  const editable = email.status === "draft" || email.status === "approved";
  const [editing, setEditing] = useState(false);
  const [subject, setSubject] = useState(email.subject);
  const [body, setBody] = useState(email.body_text ?? "");
  const [err, setErr] = useState<string | null>(null);
  const [busy, setBusy] = useState(false);

  async function act(path: string, method = "POST", payload?: unknown) {
    setBusy(true);
    setErr(null);
    try {
      await callApi(path, method, payload);
      setEditing(false);
      router.refresh();
    } catch (e) {
      setErr((e as Error).message);
    } finally {
      setBusy(false);
    }
  }

  return (
    <div className="card" style={{ padding: 14 }}>
      <div className="row between">
        <div className="row">
          <Pill value={email.status} />
          <span className="small muted">
            {email.step === 0 ? "Initial email" : `Follow-up ${email.step}`} · to {email.to_email} · {email.generated_by}
          </span>
        </div>
        <span className="small muted">
          {email.sent_at ? `Sent ${fmtDate(email.sent_at, true)}` : `Created ${fmtDate(email.created_at, true)}`}
        </span>
      </div>
      {context}
      {editing ? (
        <div className="stack" style={{ gap: 8, marginTop: 10 }}>
          <input value={subject} onChange={(e) => setSubject(e.target.value)} />
          <textarea value={body} onChange={(e) => setBody(e.target.value)} />
        </div>
      ) : (
        <>
          <div style={{ fontWeight: 600, marginTop: 10 }}>{email.subject}</div>
          <div className="email-body">{email.body_text}</div>
        </>
      )}
      {email.error && <div className="error">{email.error}</div>}
      {err && <div className="error">{err}</div>}
      {editable && (
        <div className="row" style={{ marginTop: 8 }}>
          {editing ? (
            <>
              <button className="btn primary sm" disabled={busy}
                onClick={() => act(`/emails/${email.id}`, "PATCH", { subject, body_text: body })}>Save</button>
              <button className="btn sm" onClick={() => setEditing(false)}>Discard</button>
            </>
          ) : (
            <>
              {email.status === "draft" && (
                <button className="btn primary sm" disabled={busy} onClick={() => act(`/emails/${email.id}/approve`)}>
                  Approve &amp; queue
                </button>
              )}
              <button className="btn sm" onClick={() => setEditing(true)}>Edit</button>
              <button className="btn danger sm" disabled={busy}
                onClick={() => window.confirm("Cancel this email?") && act(`/emails/${email.id}/cancel`)}>Cancel</button>
            </>
          )}
        </div>
      )}
    </div>
  );
}
