"use client";

import { useRouter } from "next/navigation";
import { useState } from "react";

import { callApi } from "@/lib/client";
import { GRADES } from "@/lib/format";

export interface Runtime {
  email_send_mode: string;
  outreach_min_grade: string;
  auto_send_min_grade: string;
  daily_send_limit: number;
  hourly_send_limit: number;
  per_domain_daily_limit: number;
  min_seconds_between_sends: number;
  send_window_start_hour: number;
  send_window_end_hour: number;
  send_on_weekends: boolean;
  followup_delays_days: number[];
  max_followups: number;
  company_cooldown_days: number;
  notify_min_grade: string;
}

const NUMBERS: [keyof Runtime, string][] = [
  ["daily_send_limit", "Daily send limit"],
  ["hourly_send_limit", "Hourly send limit"],
  ["per_domain_daily_limit", "Per company domain / day"],
  ["min_seconds_between_sends", "Seconds between sends"],
  ["send_window_start_hour", "Send window start (IST hour)"],
  ["send_window_end_hour", "Send window end (IST hour)"],
  ["max_followups", "Max follow-ups"],
  ["company_cooldown_days", "Company cool-down (days)"],
];

export default function SettingsForm({ initial }: { initial: Runtime }) {
  const router = useRouter();
  const [rt, setRt] = useState<Runtime>(initial);
  const [delays, setDelays] = useState(initial.followup_delays_days.join(", "));
  const [msg, setMsg] = useState<{ ok: boolean; text: string } | null>(null);

  const set = <K extends keyof Runtime>(k: K, v: Runtime[K]) => setRt((r) => ({ ...r, [k]: v }));

  async function save() {
    setMsg(null);
    const followup_delays_days = delays.split(",").map((s) => parseInt(s.trim(), 10)).filter((n) => !Number.isNaN(n));
    if (rt.email_send_mode === "auto" && initial.email_send_mode !== "auto" &&
        !window.confirm("Enable automatic sending? Emails for qualifying leads will be sent without review.")) return;
    try {
      await callApi("/settings", "PUT", { ...rt, followup_delays_days });
      setMsg({ ok: true, text: "Saved" });
      router.refresh();
    } catch (e) {
      setMsg({ ok: false, text: (e as Error).message });
    }
  }

  return (
    <div className="stack">
      <div className="grid grid-2">
        <label className="field">
          Email mode
          <select value={rt.email_send_mode} onChange={(e) => set("email_send_mode", e.target.value)}>
            <option value="dry_run">Dry run — render and log only</option>
            <option value="approval">Approval — every email reviewed by a person</option>
            <option value="auto">Automatic — send qualifying leads without review</option>
          </select>
        </label>
        <label className="field">
          Auto-send only for grade ≥
          <select value={rt.auto_send_min_grade} onChange={(e) => set("auto_send_min_grade", e.target.value)}>
            {GRADES.map((g) => <option key={g}>{g}</option>)}
          </select>
        </label>
        <label className="field">
          Draft outreach for grade ≥
          <select value={rt.outreach_min_grade} onChange={(e) => set("outreach_min_grade", e.target.value)}>
            {GRADES.map((g) => <option key={g}>{g}</option>)}
          </select>
        </label>
        <label className="field">
          Notify for grade ≥
          <select value={rt.notify_min_grade} onChange={(e) => set("notify_min_grade", e.target.value)}>
            {GRADES.map((g) => <option key={g}>{g}</option>)}
          </select>
        </label>
        {NUMBERS.map(([k, lbl]) => (
          <label className="field" key={k}>
            {lbl}
            <input type="number" min={0} value={rt[k] as number} onChange={(e) => set(k, Number(e.target.value) as never)} />
          </label>
        ))}
        <label className="field">
          Follow-up delays (days, comma separated)
          <input value={delays} onChange={(e) => setDelays(e.target.value)} />
        </label>
        <label className="field">
          Send on weekends
          <select value={rt.send_on_weekends ? "yes" : "no"} onChange={(e) => set("send_on_weekends", e.target.value === "yes")}>
            <option value="no">No</option>
            <option value="yes">Yes</option>
          </select>
        </label>
      </div>
      <div className="row">
        <button className="btn primary" onClick={save}>Save settings</button>
        {msg && <span className={msg.ok ? "small muted" : "error"}>{msg.text}</span>}
      </div>
    </div>
  );
}
