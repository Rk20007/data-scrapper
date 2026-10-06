"use client";

export default function DashboardError({ error, reset }: { error: Error & { digest?: string }; reset: () => void }) {
  return (
    <div className="card stack" style={{ maxWidth: 640 }}>
      <h1>Could not load data from the backend</h1>
      <p className="sub">
        The dashboard is running, but the API request failed. On Vercel this usually means an environment
        variable is missing on the project — most often <b>DATABASE_URL</b>, <b>SECRET_KEY</b> or <b>REDIS_URL</b> —
        or the deployment needs a redeploy after adding them.
      </p>
      <ol className="small" style={{ margin: 0, paddingLeft: 18 }}>
        <li>Vercel → Project → Settings → Environment Variables: check DATABASE_URL and the other values from .env.</li>
        <li>Deployments → latest → Redeploy.</li>
        <li>If it still fails: Deployments → Logs, filter by the backend service, and look for the error.</li>
      </ol>
      {error.digest && <p className="small muted">Error reference: {error.digest}</p>}
      <div className="row">
        <button className="btn primary" onClick={reset}>Try again</button>
        <button
          className="btn"
          onClick={async () => {
            await fetch("/api/session", { method: "DELETE" });
            window.location.href = "/login";
          }}
        >
          Sign out
        </button>
      </div>
    </div>
  );
}
