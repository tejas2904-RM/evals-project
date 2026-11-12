"use client";

import Link from "next/link";
import { useRouter } from "next/navigation";
import { useEffect, useMemo, useState } from "react";
import { Badge, Button, Card, INPUT, cx } from "@/components/ui";
import { DEFAULT_ANSWER_PATH, DEFAULT_BODY, EMPTY_DRAFT, allowedInputs, checkCard, loadDraft, saveDraft, type AuditDraft, type InputKind } from "@/lib/draft";
import { blockingRisks, shortDate, usd } from "@/lib/format";
import { useAdmin, useAudits, useMeta } from "@/lib/hooks";
import type { Estimate } from "@/lib/types";
import { useApi } from "@/lib/useApi";

const TILES: { id: InputKind; title: string; sub: string; optional?: boolean }[] = [
  { id: "url", title: "Bot URL", sub: "Live behaviour and attack tests" },
  { id: "card", title: "System card JSON", sub: "Prompt, tools, data, guardrails" },
  { id: "code", title: "GitHub repo", sub: "Code scan with file and line evidence", optional: true },
];

const STEPS = [
  { n: "1 · Add inputs", title: "Any mix of URL, JSON and code", text: "More inputs mean a deeper audit. A URL alone already tests behaviour and security." },
  { n: "2 · We test, attack and read", title: "Four engines run in the background", text: "Quality checks, security probes, code scan and config review. Usually a few minutes." },
  { n: "3 · Get the report", title: "Verdict, risks and guardrails", text: "Every risk links to the failing answer or the line of code. Export it as a PDF." },
];

export default function HomePage() {
  const router = useRouter();
  const { data: meta } = useMeta();
  const { signedIn } = useAdmin(meta);
  const { data: audits } = useAudits();
  const [draft, setDraft] = useState<AuditDraft>(EMPTY_DRAFT);
  const [tile, setTile] = useState<InputKind>("url");
  const [advanced, setAdvanced] = useState(false);

  useEffect(() => setDraft(loadDraft()), []);

  const allowed = allowedInputs(meta?.mode, signedIn);
  const card = checkCard(draft.cardJson);
  const added: Record<InputKind, boolean> = {
    url: /^https?:\/\/\S+/.test(draft.url.trim()),
    card: Boolean(card?.ok),
    code: /^https:\/\/github\.com\/[\w.-]+\/[\w.-]+/.test(draft.repo.trim()),
  };
  const usable = (Object.keys(added) as InputKind[]).filter((k) => added[k] && allowed.has(k));
  const inputsParam = usable.join(",");
  const { data: estimate } = useApi<Estimate>(`/api/estimate${inputsParam ? `?inputs=${inputsParam}&ai_review=true` : ""}`);
  const canStart = usable.length > 0 && draft.authorized;

  const demo = audits?.find((a) => a.role === "bot");
  const recent = useMemo(() => (signedIn ? audits?.find((a) => a.source === "local") : undefined), [audits, signedIn]);

  const update = (patch: Partial<AuditDraft>) => {
    const next = { ...draft, ...patch };
    setDraft(next);
    saveDraft(next);
  };

  const start = () => {
    saveDraft(draft);
    router.push("/audits/new/?step=1");
  };

  const reason =
    meta && allowed.size === 0
      ? "This public site is read-only. Live audits run on the owner's machine (Admin sign in explains how)."
      : meta && !allowed.has(tile)
        ? "This input needs admin mode on the owner's machine."
        : null;

  return (
    <div className="flex flex-col gap-10">
      <section className="relative">
        <div className="px-2 pt-10 text-center">
          <span className="inline-block rounded-full border border-brand-line bg-brand/20 px-3 py-1 text-xs text-brand">
            Mapped to the OWASP Top 10 for LLM Applications 2026
          </span>
          <h1 className="mx-auto mt-4 max-w-3xl text-[34px] font-normal leading-tight tracking-[-0.01em] sm:text-[42px]">
            Is your AI chatbot safe to ship?
          </h1>
          <p className="mx-auto mt-3 max-w-2xl text-[17px] text-muted">
            Test its answers, attack it the way a hacker would, and read its code. Get a scorecard, a risk register and a guardrail map, with
            evidence for every finding.
          </p>
        </div>

        <Card className="relative mx-auto mt-8 max-w-[800px] p-5">
          <div role="radiogroup" aria-label="Audit inputs" className="grid gap-3 sm:grid-cols-3">
            {TILES.map((t) => (
              <button
                key={t.id}
                type="button"
                role="radio"
                aria-checked={tile === t.id}
                onClick={() => setTile(t.id)}
                className={cx(
                  "rounded-lg border p-3 text-left",
                  tile === t.id ? "border-brand-line bg-brand-soft" : "border-line bg-field hover:border-faint",
                )}
              >
                <span className="flex items-center justify-between gap-2">
                  <span className="text-sm font-semibold">{t.title}</span>
                  {added[t.id] ? <Badge tone="pass">Added</Badge> : t.optional ? <Badge tone="muted">Optional</Badge> : null}
                </span>
                <span className="mt-0.5 block text-xs text-muted">{t.sub}</span>
              </button>
            ))}
          </div>

          <div className="mt-4">
            {tile === "url" && (
              <div className="flex flex-col gap-1.5">
                <label htmlFor="home-url" className="text-sm font-medium">
                  Your bot&apos;s chat endpoint
                </label>
                <input
                  id="home-url"
                  className={INPUT}
                  placeholder="https://your-bot.example.com/chat"
                  value={draft.url}
                  disabled={!allowed.has("url")}
                  onChange={(e) => update({ url: e.target.value })}
                />
                <div className="text-xs text-muted">
                  We send it test questions and attack prompts, then read its replies.{" "}
                  <button type="button" className="text-brand underline" onClick={() => setAdvanced((a) => !a)} aria-expanded={advanced}>
                    Advanced: request and answer format
                  </button>
                </div>
                {advanced && (
                  <div className="mt-2 grid gap-3 sm:grid-cols-2">
                    <label className="flex flex-col gap-1 text-sm">
                      Request body
                      <input
                        className={cx(INPUT, "font-mono")}
                        value={draft.requestBody}
                        placeholder={DEFAULT_BODY}
                        disabled={!allowed.has("url")}
                        onChange={(e) => update({ requestBody: e.target.value })}
                      />
                    </label>
                    <label className="flex flex-col gap-1 text-sm">
                      Answer is at
                      <input
                        className={cx(INPUT, "font-mono")}
                        value={draft.answerPath}
                        placeholder={DEFAULT_ANSWER_PATH}
                        disabled={!allowed.has("url")}
                        onChange={(e) => update({ answerPath: e.target.value })}
                      />
                    </label>
                  </div>
                )}
              </div>
            )}
            {tile === "card" && (
              <div className="flex flex-col gap-1.5">
                <label htmlFor="home-card" className="text-sm font-medium">
                  System card JSON
                </label>
                <textarea
                  id="home-card"
                  rows={4}
                  className={cx(INPUT, "font-mono")}
                  placeholder='{"name": "My bot", "tools": [], "guardrails_declared": []}'
                  value={draft.cardJson}
                  disabled={!allowed.has("card")}
                  onChange={(e) => update({ cardJson: e.target.value })}
                />
                {card && <div className={cx("text-xs", card.ok ? "text-pass" : "text-fail")}>{card.message}</div>}
              </div>
            )}
            {tile === "code" && (
              <div className="flex flex-col gap-1.5">
                <label htmlFor="home-repo" className="text-sm font-medium">
                  Public GitHub repo
                </label>
                <input
                  id="home-repo"
                  className={INPUT}
                  placeholder="https://github.com/your-friend/your-bot"
                  value={draft.repo}
                  disabled={!allowed.has("code")}
                  onChange={(e) => update({ repo: e.target.value })}
                />
                <div className="text-xs text-muted">Read only, never run. A .zip upload is in the next step.</div>
              </div>
            )}
            {reason && <p className="mt-2 text-xs text-warn">{reason}</p>}
          </div>

          <div className="mt-4 flex flex-col gap-3 border-t border-line pt-4 sm:flex-row sm:items-center sm:justify-between">
            <label className="flex max-w-md items-start gap-2 text-sm">
              <input
                type="checkbox"
                className="mt-0.5 h-4 w-4 accent-[var(--color-brand)]"
                checked={draft.authorized}
                onChange={(e) => update({ authorized: e.target.checked })}
              />
              <span>I own this bot or have written permission to test it. Security tests send attack prompts.</span>
            </label>
            <div className="flex items-center gap-3">
              <span className="text-sm text-muted">
                {usable.length} of 3 inputs added · est. {usd(estimate?.total_usd ?? 0)}
              </span>
              <Button variant="primary" disabled={!canStart} onClick={start}>
                Start audit
              </Button>
            </div>
          </div>
        </Card>
      </section>

      <section className="grid gap-6 sm:grid-cols-3">
        {STEPS.map((s) => (
          <div key={s.n}>
            <div className="text-xs font-semibold text-brand">{s.n}</div>
            <h2 className="mt-1 text-[15px] font-normal">{s.title}</h2>
            <p className="mt-1 text-sm text-muted">{s.text}</p>
          </div>
        ))}
      </section>

      <section className="grid gap-4 sm:grid-cols-2">
        <Link href={demo ? `/audits/view/?id=${demo.audit_id}&tab=risks` : "/audits/"} className="block">
          <Card className="h-full p-5 hover:border-faint">
            <div className="text-sm text-muted">No bot handy?</div>
            <h2 className="mt-1 text-[17px] font-normal">See the demo audit</h2>
            <p className="mt-1 text-sm text-muted">A mutual-fund FAQ bot tested in three versions, from blocked to ship it.</p>
          </Card>
        </Link>
        <Link href="/playground/" className="block">
          <Card className="h-full p-5 hover:border-faint">
            <div className="text-sm text-muted">Two minutes</div>
            <h2 className="mt-1 text-[17px] font-normal">Try to break the demo bot</h2>
            <p className="mt-1 text-sm text-muted">Ask the old and new versions the same question in the playground.</p>
          </Card>
        </Link>
      </section>

      {recent && (
        <Link href={`/audits/view/?id=${recent.audit_id}`} className="block">
          <Card className="p-5 hover:border-faint">
            <div className="text-sm text-muted">Admin · recent</div>
            <h2 className="mt-1 text-[17px] font-normal">{recent.target} audit</h2>
            <p className={cx("mt-1 text-sm", recent.decision === "SHIP" ? "text-pass" : "text-fail")}>
              {recent.decision === "SHIP" ? "Ship it" : "Blocked"} · {blockingRisks(recent.counts)} · {shortDate(recent.finished)}
            </p>
          </Card>
        </Link>
      )}
    </div>
  );
}
