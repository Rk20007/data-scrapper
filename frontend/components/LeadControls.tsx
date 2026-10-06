"use client";

import { useRouter } from "next/navigation";
import { useState } from "react";

import { callApi } from "@/lib/client";
import { label, LEAD_STATUSES } from "@/lib/format";
import type { Contact } from "@/lib/types";

export function LeadStatusEditor({ id, status, notes }: { id: number; status: string; notes: string | null }) {
  const router = useRouter();
  const [s, setS] = useState(status);
  const [n, setN] = useState(notes ?? "");
  const [err, setErr] = useState<string | null>(null);
  const [saved, setSaved] = useState(false);

  async function save() {
    setErr(null);
    setSaved(false);
    try {
      await callApi(`/leads/${id}`, "PATCH", { lead_status: s, notes: n });
      setSaved(true);
      router.refresh();
    } catch (e) {
      setErr((e as Error).message);
    }
  }

  return (
    <div className="stack" style={{ gap: 8 }}>
      <label className="field">
        Lead status
        <select value={s} onChange={(e) => setS(e.target.value)}>
          {LEAD_STATUSES.map((x) => <option key={x} value={x}>{label(x)}</option>)}
        </select>
      </label>
      <label className="field">
        Notes
        <textarea style={{ minHeight: 80, fontFamily: "inherit" }} value={n} onChange={(e) => setN(e.target.value)} />
      </label>
      <div className="row">
        <button className="btn primary sm" onClick={save}>Save</button>
        {saved && <span className="small muted">Saved</span>}
        {err && <span className="error">{err}</span>}
      </div>
    </div>
  );
}

export function StartOutreach({ leadId, contacts }: { leadId: number; contacts: Contact[] }) {
  const router = useRouter();
  const eligible = contacts.filter((c) => c.email && !c.do_not_contact && !["invalid", "bounced"].includes(c.email_status));
  const [cid, setCid] = useState(eligible[0]?.id ?? 0);
  const [err, setErr] = useState<string | null>(null);
  if (!eligible.length) return <p className="small muted">No contact with a public email yet — run “Find contacts”.</p>;

  async function start() {
    setErr(null);
    try {
      await callApi(`/leads/${leadId}/outreach`, "POST", { contact_id: cid });
      router.refresh();
    } catch (e) {
      setErr((e as Error).message);
    }
  }

  return (
    <div className="row">
      <select value={cid} onChange={(e) => setCid(Number(e.target.value))}>
        {eligible.map((c) => (
          <option key={c.id} value={c.id}>
            {(c.name ?? label(c.role_category)) + " — " + c.email}
          </option>
        ))}
      </select>
      <button className="btn sm" onClick={start}>Draft email</button>
      {err && <span className="error">{err}</span>}
    </div>
  );
}
