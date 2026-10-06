export function fmtDate(v?: string | null, withTime = false): string {
  if (!v) return "—";
  const d = new Date(v);
  if (Number.isNaN(d.getTime())) return "—";
  return d.toLocaleString("en-IN", {
    day: "2-digit",
    month: "short",
    year: "numeric",
    ...(withTime ? { hour: "2-digit", minute: "2-digit" } : {}),
    timeZone: "Asia/Kolkata",
  });
}

export function ago(v?: string | null): string {
  if (!v) return "never";
  const s = (Date.now() - new Date(v).getTime()) / 1000;
  if (s < 60) return "just now";
  if (s < 3600) return `${Math.floor(s / 60)}m ago`;
  if (s < 86400) return `${Math.floor(s / 3600)}h ago`;
  return `${Math.floor(s / 86400)}d ago`;
}

export function label(v?: string | null): string {
  if (!v) return "—";
  return v.replace(/_/g, " ").replace(/^\w/, (c) => c.toUpperCase());
}

export function crore(v?: number | null): string {
  return v == null ? "—" : `₹${v.toLocaleString("en-IN")} Cr`;
}

export function host(url?: string | null): string {
  if (!url) return "";
  try {
    return new URL(url).hostname.replace(/^www\./, "");
  } catch {
    return url;
  }
}

export const GRADES = ["HOT", "HIGH", "WARM", "LOW"] as const;
export const LEAD_STATUSES = [
  "new", "needs_contact", "outreach_queued", "contacted", "replied", "interested",
  "not_interested", "unsubscribed", "won", "lost", "disqualified",
] as const;
export const PROJECT_TYPES = ["factory", "warehouse", "peb", "civil", "construction", "expansion", "epc", "industrial_park", "other"] as const;
export const CLUSTERS = ["Bhiwadi", "Khushkhera", "Tapukara", "Neemrana"] as const;
