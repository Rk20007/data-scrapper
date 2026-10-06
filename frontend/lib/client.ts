"use client";

/** Browser-side calls go through the Next.js proxy, which attaches the httpOnly token. */
export async function callApi<T = any>(path: string, method = "POST", body?: unknown): Promise<T> {
  const res = await fetch(`/api/backend${path}`, {
    method,
    headers: body instanceof FormData ? undefined : { "Content-Type": "application/json" },
    body: body instanceof FormData ? body : body !== undefined ? JSON.stringify(body) : undefined,
  });
  if (res.status === 401) {
    window.location.href = "/login";
    throw new Error("Session expired");
  }
  const data = await res.json().catch(() => ({}));
  if (!res.ok) throw new Error(typeof data.detail === "string" ? data.detail : `Request failed (${res.status})`);
  return data as T;
}
