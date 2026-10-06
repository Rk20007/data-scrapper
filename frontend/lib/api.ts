import { cookies } from "next/headers";
import { redirect } from "next/navigation";

export const BACKEND_URL = process.env.BACKEND_URL ?? "http://localhost:8000";
export const TOKEN_COOKIE = "le_token";

/** Server-side fetch to the FastAPI backend using the session cookie. */
export async function api<T = any>(path: string, init: RequestInit = {}): Promise<T> {
  const token = (await cookies()).get(TOKEN_COOKIE)?.value;
  if (!token) redirect("/login");
  const res = await fetch(`${BACKEND_URL}/api${path}`, {
    ...init,
    cache: "no-store",
    headers: { ...(init.headers ?? {}), Authorization: `Bearer ${token}`, "Content-Type": "application/json" },
  });
  if (res.status === 401) redirect("/login");
  if (!res.ok) throw new Error(`API ${path} failed: ${res.status} ${await res.text()}`);
  return res.json() as Promise<T>;
}

export function qs(params: Record<string, string | string[] | undefined>): string {
  const sp = new URLSearchParams();
  for (const [k, v] of Object.entries(params)) {
    if (v === undefined || v === "") continue;
    for (const item of Array.isArray(v) ? v : [v]) if (item) sp.append(k, item);
  }
  const s = sp.toString();
  return s ? `?${s}` : "";
}
