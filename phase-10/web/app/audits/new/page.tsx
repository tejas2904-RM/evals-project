"use client";

import Link from "next/link";
import { useRouter, useSearchParams } from "next/navigation";
import { Suspense, useEffect, useRef, useState } from "react";
import { Badge, Button, ButtonLink, Card, Field, INPUT, LoadState, Stepper, cx } from "@/components/ui";
import { ApiError, apiGet, apiPost, apiPostForm, clearApiCache } from "@/lib/api";
import { EMPTY_DRAFT, allowedInputs, checkCard, clearDraft, loadDraft, saveDraft, type AuditDraft } from "@/lib/draft";
import { usd } from "@/lib/format";
import { useAdmin, useMeta } from "@/lib/hooks";
import { ENGINE_LABELS, decisionLabel } from "@/lib/labels";
import type { CardDraft, ConnectionTest, Estimate, Job, Meta } from "@/lib/types";
import { useApi } from "@/lib/useApi";

const STEPS = [
  { id: 1, title: "Name", sub: "What you're auditing" },
  { id: 2, title: "Inputs", sub: "URL, card, code" },
  { id: 3, title: "Engines", sub: "What to run" },
  { id: 4, title: "Permission", sub: "Confirm you may test" },
  { id: 5, title: "Run", sub: "Live progress" },
];
const ENGINES = ["behaviour", "security", "code", "config"];
const POLL_MS = 1500;

export default function NewAuditPage() {
  return (
    <Suspense fallback={<LoadState loading error={null}>{null}</LoadState>}>
      <Wizard />
    </Suspense>
  );
}

function Wizard() {
  const router = useRouter();
  const params = useSearchParams();
  const meta = useMeta();
  const { signedIn } = useAdmin(meta.data);
  const step = Math.min(5, Math.max(1, Number(params.get("step")) || 1));
  const jobId = params.get("job");
  const [draft, setDraft] = useState<AuditDraft>(EMPTY_DRAFT);
  const [zip, setZip] = useState<File | null>(null);
  const [connection, setConnection] = useState<ConnectionTest | null>(null);
  const [error, setError] = useState<string | null>(null);

  useEffect(() => setDraft(loadDraft()), []);

  const allowed = allowedInputs(meta.data?.mode, signedIn);
  const card = checkCard(draft.cardJson);
  const has = {
    url: allowed.has("url") && /^https?:\/\/\S+/.test(draft.url.trim()),
    card: allowed.has("card") && Boolean(card?.ok),
    code: (allowed.has("code") && /^https:\/\/github\.com\/\S+/.test(draft.repo.trim())) || (allowed.has("code") && zip !== null),
  };
  const inputs = (Object.keys(has) as (keyof typeof has)[]).filter((k) => has[k]);
  const runnable = (engine: string) =>
    engine === "behaviour" ? has.url : engine === "security" ? has.url : engine === "code" ? has.code : has.card || has.code;
  const engines = draft.engines.filter(runnable);
  const estimateQuery = `/api/estimate?engines=${ENGINES.join(",")}&inputs=${inputs.join(",")}&ai_review=${draft.aiReview && (signedIn || Boolean(meta.data?.jobs_enabled))}`;
  const { data: estimate } = useApi<Estimate>(meta.data ? estimateQuery : null);

  const update = (patch: Partial<AuditDraft>) => {
    const next = { ...draft, ...patch };
    setDraft(next);
    saveDraft(next);
  };
  const go = (n: number) => router.push(`/audits/new/?step=${n}`);

  const submit = async () => {
    setError(null);
    const form = new FormData();
    form.set("name", draft.name || "Audit");
    form.set("engines", engines.join(","));
    if (has.url) {
      form.set("target_url", draft.url.trim());
      form.set("request_body", draft.requestBody);
      form.set("answer_path", draft.answerPath);
      form.set("authorized", String(draft.authorized));
    }
    if (has.card) form.set("system_card_json", draft.cardJson);
    if (has.code && zip) form.set("code_zip", zip);
    else if (has.code && draft.repo.trim()) form.set("repo", draft.repo.trim());
    if ((signedIn || Boolean(meta.data?.jobs_enabled)) && draft.aiReview && engines.includes("code")) form.set("ai_review", "true");
    try {
      const job = await apiPostForm<Job>("/api/audits", form);
      clearDraft();
      router.push(`/audits/new/?step=5&job=${job.job_id}`);
    } catch (err) {
      setError(err instanceof ApiError ? err.message : String(err));
    }
  };

  const canNext =
    step === 1 ? draft.name.trim().length > 0 : step === 2 ? inputs.length > 0 : step === 3 ? engines.length > 0 : step === 4 ? draft.authorized : false;

  return (
    <LoadState loading={meta.loading} error={meta.error} onRetry={meta.reload}>
      <div className="grid gap-6 md:grid-cols-[210px_1fr]">
        <Stepper steps={STEPS} current={step} onSelect={step < 5 ? go : undefined} />
        <div className="flex min-w-0 flex-col gap-4">
          <div>
            <div className="text-sm text-muted">Step {step} of 5</div>
            <h1 className="mt-1 text-[28px] font-normal leading-tight tracking-[-0.01em]">{TITLES[step]}</h1>
            <p className="mt-1 max-w-2xl text-sm text-muted">{SUBTITLES[step]}</p>
          </div>
          {meta.data && <ModeNotice meta={meta.data} signedIn={signedIn} />}

          {step === 1 && (
            <Card className="p-5">
              <Field label="Audit name" htmlFor="audit-name" hint="Shown in the audit list. The report title comes from the system card name when you add one.">
                <input id="audit-name" className={INPUT} value={draft.name} placeholder="GymCoach audit" maxLength={80} onChange={(e) => update({ name: e.target.value })} />
              </Field>
            </Card>
          )}
          {step === 2 && (
            <InputsStep draft={draft} update={update} allowed={allowed} zip={zip} setZip={setZip} connection={connection} setConnection={setConnection} maxMb={meta.data?.max_upload_mb ?? 5} />
          )}
          {step === 3 && <EnginesStep draft={draft} update={update} runnable={runnable} estimate={estimate} signedIn={signedIn} jobsEnabled={Boolean(meta.data?.jobs_enabled)} />}
          {step === 4 && <PermissionStep draft={draft} update={update} engines={engines} hasUrl={has.url} />}
          {step === 5 && <RunStep jobId={jobId} />}

          {error && (
            <p role="alert" className="text-sm text-fail">
              {error}
            </p>
          )}

          {step < 5 && (
            <div className="flex flex-col gap-3 border-t border-line pt-4 sm:flex-row sm:items-center sm:justify-between">
              <span className="text-sm text-muted">
                {estimate
                  ? estimate.paid
                    ? `Estimated OpenAI cost with these engines: about ${usd(estimate.total_usd)} · ${usd(estimate.remaining_usd)} left of your ${usd(estimate.budget_usd)} cap`
                    : `Offline engines: ${usd(0)} · ${usd(estimate.spent_usd)} of the ${usd(estimate.budget_usd)} cap spent so far`
                  : "Estimating cost…"}
              </span>
              <div className="flex gap-2">
                {step > 1 && <Button onClick={() => go(step - 1)}>Back</Button>}
                {step < 4 && (
                  <Button variant="primary" disabled={!canNext} onClick={() => go(step + 1)}>
                    {NEXT[step]}
                  </Button>
                )}
                {step === 4 && (
                  <Button variant="primary" disabled={!canNext || (estimate ? !estimate.fits_budget : false)} onClick={submit}>
                    Start audit
                  </Button>
                )}
              </div>
            </div>
          )}
        </div>
      </div>
    </LoadState>
  );
}

const TITLES: Record<number, string> = {
  1: "Name this audit",
  2: "What should we audit?",
  3: "Choose engines",
  4: "Confirm you may test it",
  5: "Running the audit",
};
const SUBTITLES: Record<number, string> = {
  1: "A short name so you can find it later.",
  2: "Add any combination. More inputs give a deeper audit: the URL tests behaviour, the system card checks the design, the code shows where problems live.",
  3: "Each engine needs certain inputs. Engines that can't run with what you added are greyed out.",
  4: "Security probes send real attack prompts to the bot. Only audit systems you own or have written permission to test.",
  5: "Engines run one after another. You can leave this page; the audit appears in the list when it's done.",
};
const NEXT: Record<number, string> = { 1: "Next: add inputs", 2: "Next: choose engines", 3: "Next: permission" };

function ModeNotice({ meta, signedIn }: { meta: Meta; signedIn: boolean }) {
  if (meta.mode === "admin" && signedIn) return null;
  if (meta.mode === "jobs") return null;
  const text =
    meta.mode === "admin"
      ? "Sign in with the admin token to use live URL audits, GitHub repos and AI review."
      : "This public site is read-only, so nothing can be submitted. Live audits run on the owner's machine in admin mode.";
  return (
    <div role="note" className="rounded-lg border border-warn-soft bg-warn-soft/60 px-4 py-3 text-sm text-warn">
      {text}{" "}
      <Link href="/admin/" className="underline">
        How admin mode works
      </Link>{" "}
      ·{" "}
      <Link href="/audits/" className="underline">
        See existing audits
      </Link>
    </div>
  );
}

function InputsStep(props: {
  draft: AuditDraft;
  update: (p: Partial<AuditDraft>) => void;
  allowed: Set<string>;
  zip: File | null;
  setZip: (f: File | null) => void;
  connection: ConnectionTest | null;
  setConnection: (c: ConnectionTest | null) => void;
  maxMb: number;
}) {
  const { draft, update, allowed, zip, setZip, connection, setConnection, maxMb } = props;
  const [testing, setTesting] = useState(false);
  const [testError, setTestError] = useState<string | null>(null);
  const [drafting, setDrafting] = useState(false);
  const [draftNotes, setDraftNotes] = useState<string[] | null>(null);
  const [draftError, setDraftError] = useState<string | null>(null);
  const cardFile = useRef<HTMLInputElement>(null);
  const zipFile = useRef<HTMLInputElement>(null);
  const card = checkCard(draft.cardJson);
  const urlOk = allowed.has("url");
  const codeOk = allowed.has("code");

  const test = async () => {
    setTesting(true);
    setTestError(null);
    setConnection(null);
    try {
      const result = await apiPost<ConnectionTest>("/api/connection-test", {
        url: draft.url,
        request_body: draft.requestBody,
        answer_path: draft.answerPath,
        authorized: draft.authorized,
      });
      setConnection(result);
      if (!result.ok) setTestError(result.error || `HTTP ${result.status}`);
    } catch (err) {
      setTestError(err instanceof ApiError ? err.message : String(err));
    } finally {
      setTesting(false);
    }
  };

  const draftFromCode = async () => {
    setDrafting(true);
    setDraftError(null);
    const form = new FormData();
    if (zip) form.set("code_zip", zip);
    else form.set("repo", draft.repo.trim());
    try {
      const result = await apiPostForm<CardDraft>("/api/system-card/draft", form);
      update({ cardJson: JSON.stringify(result.card, null, 2) });
      setDraftNotes(result.notes);
    } catch (err) {
      setDraftError(err instanceof ApiError ? err.message : String(err));
    } finally {
      setDrafting(false);
    }
  };

  const onZip = (file: File | null) => {
    if (file && file.size > maxMb * 1024 * 1024) {
      setDraftError(`The .zip is larger than ${maxMb} MB`);
      return;
    }
    setDraftError(null);
    setZip(file);
  };

  return (
    <>
      <Card className={cx("p-5", !urlOk && "opacity-70")}>
        <div className="flex items-center justify-between gap-3">
          <h2 className="text-[15px] font-normal">
            1. Bot URL <span className="font-normal text-muted">· live behaviour and security tests</span>
          </h2>
          {connection?.ok && <Badge tone="pass">Connected</Badge>}
          {!urlOk && <Badge tone="muted">not available on this site</Badge>}
        </div>
        <div className="mt-3 grid gap-3 md:grid-cols-3">
          <Field label="Endpoint URL" htmlFor="w-url">
            <input id="w-url" className={INPUT} disabled={!urlOk} value={draft.url} placeholder="https://your-bot.example.com/chat" onChange={(e) => { update({ url: e.target.value }); setConnection(null); }} />
          </Field>
          <Field label="Request body" htmlFor="w-body">
            <input id="w-body" className={cx(INPUT, "font-mono")} disabled={!urlOk} value={draft.requestBody} onChange={(e) => { update({ requestBody: e.target.value }); setConnection(null); }} />
          </Field>
          <Field label="Answer is at" htmlFor="w-path">
            <input id="w-path" className={cx(INPUT, "font-mono")} disabled={!urlOk} value={draft.answerPath} onChange={(e) => { update({ answerPath: e.target.value }); setConnection(null); }} />
          </Field>
        </div>
        <div className="mt-3 flex flex-wrap items-center gap-3">
          <Button disabled={!urlOk || !draft.url.trim() || testing || !draft.authorized} onClick={test} title={draft.authorized ? undefined : "Tick the permission box first"}>
            {testing ? "Testing…" : "Test connection"}
          </Button>
          {connection?.ok && <span className="rounded-lg bg-neutral-soft px-3 py-2 text-sm">Sample reply: &quot;{connection.sample_reply}&quot;</span>}
          {testError && <span className="text-sm text-fail">{testError}</span>}
          {urlOk && !draft.authorized && (
            <label className="flex items-center gap-2 text-xs text-muted">
              <input type="checkbox" checked={draft.authorized} onChange={(e) => update({ authorized: e.target.checked })} />I own this bot or may test it
            </label>
          )}
        </div>
        <p className="mt-2 text-xs text-muted">$QUESTION is replaced by each test question. The answer path is a dotted path into the JSON reply, like reply or data.answer.</p>
      </Card>

      <Card className={cx("p-5", !allowed.has("card") && "opacity-70")}>
        <div className="flex flex-wrap items-center justify-between gap-3">
          <h2 className="text-[15px] font-normal">
            2. System card JSON <span className="font-normal text-muted">· instructions, tools, data, guardrails</span>
          </h2>
          <div className="flex gap-2">
            <input
              ref={cardFile}
              type="file"
              accept=".json,application/json"
              className="hidden"
              onChange={async (e) => {
                const f = e.target.files?.[0];
                if (f) update({ cardJson: await f.text() });
                e.target.value = "";
              }}
            />
            <Button disabled={!allowed.has("card")} onClick={() => cardFile.current?.click()}>
              Upload file
            </Button>
            <Button disabled={!codeOk || drafting || (!zip && !draft.repo.trim())} onClick={draftFromCode} title="Needs the code below">
              {drafting ? "Drafting…" : "Draft from code"}
            </Button>
          </div>
        </div>
        <label htmlFor="w-card" className="mt-3 block text-sm font-medium">
          Paste JSON
        </label>
        <textarea
          id="w-card"
          rows={6}
          className={cx(INPUT, "mt-1.5 font-mono")}
          disabled={!allowed.has("card")}
          value={draft.cardJson}
          placeholder={'{"name": "GymCoach bot", "tools": [{"name": "book_session", "side_effects": "write"}], "guardrails_declared": []}'}
          onChange={(e) => update({ cardJson: e.target.value })}
        />
        {card && <div className={cx("mt-2 text-xs", card.ok ? "text-pass" : "text-fail")}>{card.message}</div>}
        {draftNotes && (
          <details className="mt-2 text-xs text-muted">
            <summary>Drafted from {draftNotes.length} clues in the code: check before you run</summary>
            <ul className="mt-1 list-disc pl-5">
              {draftNotes.map((n) => (
                <li key={n}>{n}</li>
              ))}
            </ul>
          </details>
        )}
        {draftError && <div className="mt-2 text-xs text-fail">{draftError}</div>}
      </Card>

      <Card className={cx("p-5", !codeOk && "opacity-70")}>
        <h2 className="text-[15px] font-normal">
          3. Code <span className="font-normal text-muted">· read only, never run · deleted after the audit</span>
        </h2>
        <div className="mt-3 flex flex-col gap-3 sm:flex-row sm:items-end">
          <div className="flex-1">
            <Field label="Public GitHub repo" htmlFor="w-repo" hint={codeOk ? "Public https://github.com/owner/repo only. A .zip upload works too." : undefined}>
              <input id="w-repo" className={INPUT} disabled={!codeOk || zip !== null} value={draft.repo} placeholder="https://github.com/your-friend/gymcoach" onChange={(e) => update({ repo: e.target.value })} />
            </Field>
          </div>
          <span className="pb-2.5 text-sm text-muted">or</span>
          <input ref={zipFile} type="file" accept=".zip,application/zip" className="hidden" onChange={(e) => onZip(e.target.files?.[0] ?? null)} />
          <div className="flex items-center gap-2">
            <Button disabled={!codeOk} onClick={() => zipFile.current?.click()}>
              {zip ? zip.name : `Upload .zip (max ${maxMb} MB)`}
            </Button>
            {zip && (
              <Button variant="ghost" onClick={() => setZip(null)}>
                Remove
              </Button>
            )}
          </div>
        </div>
      </Card>
    </>
  );
}

function EnginesStep({ draft, update, runnable, estimate, signedIn, jobsEnabled }: { draft: AuditDraft; update: (p: Partial<AuditDraft>) => void; runnable: (e: string) => boolean; estimate: Estimate | null; signedIn: boolean; jobsEnabled: boolean }) {
  const toggle = (e: string) => update({ engines: draft.engines.includes(e) ? draft.engines.filter((x) => x !== e) : [...draft.engines, e] });
  return (
    <div className="grid gap-3 sm:grid-cols-2">
      {ENGINES.map((e) => {
        const info = ENGINE_LABELS[e];
        const can = runnable(e);
        const on = can && draft.engines.includes(e);
        return (
          <Card key={e} className={cx("p-4", on && "border-brand-line bg-brand-soft", !can && "opacity-60")}>
            <label className="flex cursor-pointer items-start gap-3">
              <input type="checkbox" className="mt-1 h-4 w-4 accent-[var(--color-brand)]" disabled={!can} checked={on} onChange={() => toggle(e)} />
              <span className="flex-1">
                <span className="flex items-center justify-between gap-2">
                  <span className="text-sm font-semibold">{info?.name}</span>
                  <span className="text-xs text-muted">{estimate ? usd(estimate.per_engine[e] ?? 0) : ""}</span>
                </span>
                <span className="mt-0.5 block text-xs text-muted">{can ? info?.what : `Needs ${info?.needs}`}</span>
              </span>
            </label>
            {e === "code" && (signedIn || jobsEnabled) && (
              <label className="ml-7 mt-3 flex items-center gap-2 text-xs">
                <input type="checkbox" disabled={!on} checked={on && draft.aiReview} onChange={(ev) => update({ aiReview: ev.target.checked })} />
                AI code review of the riskiest files (gpt-5.4-mini; findings must quote real lines)
              </label>
            )}
          </Card>
        );
      })}
    </div>
  );
}

function PermissionStep({ draft, update, engines, hasUrl }: { draft: AuditDraft; update: (p: Partial<AuditDraft>) => void; engines: string[]; hasUrl: boolean }) {
  return (
    <Card className="flex flex-col gap-4 p-5">
      <ul className="list-disc pl-5 text-sm">
        {hasUrl && engines.includes("security") && <li>Up to 60 OWASP attack prompts go to {draft.url}, at most 2 per second.</li>}
        {hasUrl && engines.includes("behaviour") && <li>The 41 test questions go to the same endpoint.</li>}
        {engines.includes("code") && <li>Code is read as text only: never imported, built or run. The copy is deleted after the audit.</li>}
        <li>Every evidence excerpt is redacted for secrets before it is saved.</li>
      </ul>
      <label className="flex items-start gap-2 text-sm">
        <input type="checkbox" className="mt-0.5 h-4 w-4 accent-[var(--color-brand)]" checked={draft.authorized} onChange={(e) => update({ authorized: e.target.checked })} />
        <span>I own this bot or have written permission to test it. Security tests send attack prompts.</span>
      </label>
    </Card>
  );
}

const STATE_TONE: Record<string, "pass" | "fail" | "warn" | "muted" | "brand"> = {
  done: "pass",
  failed: "fail",
  running: "brand",
  queued: "muted",
  skipped: "muted",
};

function RunStep({ jobId }: { jobId: string | null }) {
  const [job, setJob] = useState<Job | null>(null);
  const [error, setError] = useState<string | null>(null);

  useEffect(() => {
    if (!jobId) return;
    let stop = false;
    let timer: ReturnType<typeof setTimeout>;
    const poll = async () => {
      try {
        const j = await apiGet<Job>(`/api/jobs/${encodeURIComponent(jobId)}`);
        if (stop) return;
        setJob(j);
        if (j.status === "done" || j.status === "failed") {
          clearApiCache();
          return;
        }
      } catch (err) {
        if (stop) return;
        setError(err instanceof ApiError ? err.message : String(err));
        return;
      }
      timer = setTimeout(poll, POLL_MS);
    };
    void poll();
    return () => {
      stop = true;
      clearTimeout(timer);
    };
  }, [jobId]);

  if (!jobId) return <Card className="p-5 text-sm text-muted">No audit is running. Start one from step 1.</Card>;
  if (error) return <Card className="p-5 text-sm text-fail" role="alert">{error}</Card>;
  return (
    <Card className="flex flex-col gap-4 p-5" aria-live="polite">
      <div className="flex items-center justify-between">
        <h2 className="text-[15px] font-normal">{job?.name || "Audit"}</h2>
        <Badge tone={job?.status === "done" ? "pass" : job?.status === "failed" ? "fail" : "brand"}>{job?.status ?? "starting"}</Badge>
      </div>
      <ul className="flex flex-col gap-2">
        {ENGINES.map((e) => {
          const state = job?.progress[e] ?? "queued";
          return (
            <li key={e} className="flex items-center justify-between rounded-lg border border-line bg-field px-3 py-2 text-sm">
              <span>{ENGINE_LABELS[e]?.name}</span>
              <Badge tone={STATE_TONE[state] ?? "muted"}>{state}</Badge>
            </li>
          );
        })}
      </ul>
      {job?.notes.map((n) => (
        <p key={n} className="text-xs text-muted">
          {n}
        </p>
      ))}
      {job?.status === "failed" && <p className="text-sm text-fail">{job.error}</p>}
      {job?.status === "done" && job.audit_id && (
        <div className="flex items-center gap-3">
          <span className="text-sm">Verdict: {decisionLabel(job.decision)}</span>
          <ButtonLink href={`/audits/view/?id=${job.audit_id}&tab=risks`} variant="primary">
            Open the report
          </ButtonLink>
        </div>
      )}
    </Card>
  );
}
