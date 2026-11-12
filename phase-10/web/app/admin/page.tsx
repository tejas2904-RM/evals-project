"use client";

import { useState } from "react";
import { Badge, Button, Card, CardTitle, INPUT, LoadState, PageHeader } from "@/components/ui";
import { API_BASE, ApiError, apiGet, clearApiCache } from "@/lib/api";
import { setAdminToken, useAdminToken } from "@/lib/admin";
import { useMeta } from "@/lib/hooks";

const STEPS = [
  ["Start the admin API (your OpenAI key stays in phase-10/.env)", "cd phase-10\nevalpilot serve --admin"],
  ["Start the web app locally", "cd phase-10/web\nnpm run dev"],
  ["Open the local site and paste the token it printed", "http://localhost:3000/admin/"],
];

export default function AdminPage() {
  const meta = useMeta();
  const token = useAdminToken();
  const [value, setValue] = useState("");
  const [status, setStatus] = useState<string | null>(null);
  const serverAdmin = Boolean(meta.data?.admin);

  const signIn = async () => {
    setStatus(null);
    setAdminToken(value.trim());
    try {
      await apiGet("/api/admin/session");
      clearApiCache();
      setValue("");
    } catch (err) {
      setAdminToken(null);
      setStatus(err instanceof ApiError ? err.message : String(err));
    }
  };

  return (
    <div className="flex flex-col gap-5">
      <PageHeader eyebrow="Owner only" title="Admin mode" />
      <LoadState loading={meta.loading} error={meta.error} onRetry={meta.reload}>
        {serverAdmin ? (
          <Card className="flex max-w-xl flex-col gap-3 p-5">
            <CardTitle right={token ? <Badge tone="pass">Signed in</Badge> : <Badge tone="muted">Signed out</Badge>}>
              Admin API at {API_BASE}
            </CardTitle>
            <p className="text-sm text-muted">
              Provider {meta.data?.provider} · ${meta.data?.budget.spent_usd.toFixed(2)} spent of ${meta.data?.budget.budget_usd.toFixed(2)}. Live URL
              audits, GitHub repos, AI review, labels and free-text playground questions are on.
            </p>
            {token ? (
              <Button
                className="self-start"
                onClick={() => {
                  setAdminToken(null);
                  clearApiCache();
                }}
              >
                Sign out
              </Button>
            ) : (
              <>
                <label className="flex flex-col gap-1.5 text-sm font-medium">
                  <span>
                    Admin token (printed by <code className="font-mono">evalpilot serve --admin</code>)
                  </span>
                  <input className={INPUT} type="password" autoComplete="off" value={value} onChange={(e) => setValue(e.target.value)} />
                </label>
                <Button variant="primary" className="self-start" disabled={!value.trim()} onClick={signIn}>
                  Sign in
                </Button>
              </>
            )}
            {status && (
              <p role="alert" className="text-sm text-fail">
                {status}
              </p>
            )}
          </Card>
        ) : (
          <Card className="flex max-w-2xl flex-col gap-4 p-5">
            <p className="text-sm">
              {meta.data?.jobs_enabled ? (
                <>
                  Anyone can start a URL or public GitHub audit on this site. Labelling, free-text playground questions and re-runs of local audits
                  still run in <strong>admin mode on your own machine</strong>, under the same $3 budget guard as the CLI.
                </>
              ) : (
                <>
                  This site talks to the public, read-only API: no OpenAI key, no URL probing. Live audits of your own bot, AI code review, labelling and
                  free-text playground questions run in <strong>admin mode on your own machine</strong>, under the same $3 budget guard as the CLI.
                </>
              )}
            </p>
            <ol className="flex flex-col gap-3">
              {STEPS.map(([title, code], i) => (
                <li key={title} className="text-sm">
                  <div className="font-medium">
                    {i + 1}. {title}
                  </div>
                  <pre className="mt-1 overflow-x-auto rounded-lg bg-ink p-3 font-mono text-xs text-zinc-100">{code}</pre>
                </li>
              ))}
            </ol>
            <p className="text-xs text-muted">Admin mode binds to 127.0.0.1 only and refuses to start on a hosted service.</p>
          </Card>
        )}
      </LoadState>
    </div>
  );
}
