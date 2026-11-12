"use client";

import { useRouter, useSearchParams } from "next/navigation";
import { Suspense, useMemo, useState } from "react";
import { Badge, Button, ButtonLink, Card, Chip, FilterChip, INPUT, LoadState, SourceBadge, cx } from "@/components/ui";
import { ApiError, apiPost, clearApiCache } from "@/lib/api";
import { useAdmin, useMeta, useRun } from "@/lib/hooks";
import { CATEGORY_LABELS, GRADER_LABELS, UNTRUSTED_SOURCES, graderOrder, label } from "@/lib/labels";
import type { CaseAnswer, CaseItem, CasePage, RunSummary } from "@/lib/types";
import { useApi } from "@/lib/useApi";

const FILTERS = ["all", "failed", "passed", "critical"] as const;
type Filter = (typeof FILTERS)[number];

export default function CasesPage() {
  return (
    <Suspense fallback={<LoadState loading error={null}>{null}</LoadState>}>
      <Cases />
    </Suspense>
  );
}

function matches(c: CaseItem, v: string, filter: Filter, check: string, q: string): boolean {
  const t = c.versions[v];
  if (!t?.status) return false;
  if (filter === "failed" && t.status.passed) return false;
  if (filter === "passed" && !t.status.passed) return false;
  if (filter === "critical" && !t.status.critical) return false;
  if (check !== "all" && !t.status.failing.includes(check)) return false;
  if (q) {
    const needle = q.toLowerCase();
    if (!c.query.toLowerCase().includes(needle) && !t.answer.toLowerCase().includes(needle) && !c.id.includes(needle)) return false;
  }
  return true;
}

function Cases() {
  const router = useRouter();
  const params = useSearchParams();
  const meta = useMeta();
  const run = useRun(meta.data);
  const runId = meta.data?.runs[0] ?? null;
  const versions = meta.data?.versions ?? ["v1", "v2", "v3"];
  const version = versions.includes(params.get("version") ?? "") ? (params.get("version") as string) : "v2";
  const filter: Filter = FILTERS.includes(params.get("filter") as Filter) ? (params.get("filter") as Filter) : "all";
  const check = params.get("check") ?? "all";
  const q = params.get("q") ?? "";
  const page = useApi<CasePage>(runId ? `/api/runs/${runId}/cases?case_version=${version}&limit=100` : null);

  const set = (patch: Record<string, string | null>) => {
    const next = new URLSearchParams(params.toString());
    for (const [k, v] of Object.entries(patch)) {
      if (v === null || v === "" || (k === "filter" && v === "all") || (k === "check" && v === "all")) next.delete(k);
      else next.set(k, v);
    }
    router.replace(`/cases/?${next.toString()}`, { scroll: false });
  };

  const items = page.data?.items ?? [];
  const counts = useMemo(() => {
    const out: Record<Filter, number> = { all: 0, failed: 0, passed: 0, critical: 0 };
    for (const c of items) for (const f of FILTERS) if (matches(c, version, f, check, q)) out[f] += 1;
    return out;
  }, [items, version, check, q]);
  const shown = items.filter((c) => matches(c, version, filter, check, q));
  const selected = shown.find((c) => c.id === params.get("case")) ?? shown[0];

  return (
    <div className="flex flex-col gap-5">
      <div className="flex flex-wrap items-end justify-between gap-4">
        <div>
          <div className="flex items-center gap-2 text-sm text-muted">
            Run {version}-{run.data?.meta.provider ?? "…"} · {meta.data?.bots[0]?.name.replace(" (demo)", "") ?? "Demo bot"} <SourceBadge source={page.source} />
          </div>
          <h1 className="mt-1 text-[28px] font-normal leading-tight tracking-[-0.01em]">Case explorer</h1>
        </div>
        <label className="flex w-full max-w-[290px] flex-col gap-1 text-sm text-muted">
          Search questions and answers
          <input className={INPUT} type="search" value={q} placeholder="guaranteed returns" onChange={(e) => set({ q: e.target.value, case: null })} />
        </label>
      </div>

      <div className="flex flex-wrap items-center justify-between gap-3">
        <div className="flex flex-wrap gap-2" role="group" aria-label="Filter cases">
          {FILTERS.map((f) => (
            <FilterChip key={f} active={filter === f} onClick={() => set({ filter: f, case: null })}>
              {f.charAt(0).toUpperCase() + f.slice(1)} ({counts[f]})
            </FilterChip>
          ))}
        </div>
        <div className="flex flex-wrap items-center gap-3 text-sm text-muted">
          <label className="flex items-center gap-2">
            Version
            <select className="rounded-lg border border-line bg-field px-2 py-2 text-sm text-text" value={version} onChange={(e) => set({ version: e.target.value })}>
              {versions.map((v) => (
                <option key={v} value={v}>
                  {v}
                </option>
              ))}
            </select>
          </label>
          <label className="flex items-center gap-2">
            Check
            <select className="rounded-lg border border-line bg-field px-2 py-2 text-sm text-text" value={check} onChange={(e) => set({ check: e.target.value, case: null })}>
              <option value="all">All checks</option>
              {graderOrder(meta.data?.graders ?? []).map((g) => (
                <option key={g} value={g}>
                  Fails {label(GRADER_LABELS, g).toLowerCase()}
                </option>
              ))}
            </select>
          </label>
        </div>
      </div>

      <LoadState loading={page.loading || meta.loading} error={page.error ?? meta.error} onRetry={page.reload}>
        <div className="grid gap-4 lg:grid-cols-[320px_1fr]">
          <Card as="div" className="self-start p-2">
            {shown.length === 0 ? (
              <p className="p-3 text-sm text-muted">No cases match these filters.</p>
            ) : (
              <ul aria-label="Cases" className="flex max-h-[70vh] flex-col gap-1 overflow-y-auto">
                {shown.map((c) => {
                  const t = c.versions[version];
                  const active = c.id === selected?.id;
                  return (
                    <li key={c.id}>
                      <button
                        type="button"
                        aria-current={active ? "true" : undefined}
                        onClick={() => set({ case: c.id })}
                        className={cx("w-full rounded-lg border p-3 text-left", active ? "border-brand-line bg-brand-soft" : "border-transparent hover:bg-neutral-soft/60")}
                      >
                        <span className="flex items-center justify-between gap-2 text-xs text-muted">
                          <span>
                            {c.id} · {label(CATEGORY_LABELS, c.category)}
                          </span>
                          <Badge tone={t?.status?.passed ? "pass" : "fail"}>{t?.status?.passed ? "Passed" : "Failed"}</Badge>
                        </span>
                        <span className="mt-1 block text-sm">{c.query}</span>
                      </button>
                    </li>
                  );
                })}
              </ul>
            )}
          </Card>
          {selected && runId && run.data && <CaseDetail item={selected} version={version} versions={versions} run={run.data} runId={runId} />}
        </div>
      </LoadState>
    </div>
  );
}

function CaseDetail({ item, version, versions, run, runId }: { item: CaseItem; version: string; versions: string[]; run: RunSummary; runId: string }) {
  const { data: meta } = useMeta();
  const { signedIn } = useAdmin(meta);
  const [copied, setCopied] = useState(false);
  const [labelling, setLabelling] = useState(false);
  const t = item.versions[version] as CaseAnswer;
  const critical = t.status?.critical;
  const later = versions.filter((v) => v > version);
  const compareWith = later[later.length - 1] ?? versions.find((v) => v !== version) ?? version;

  const copy = async () => {
    try {
      await navigator.clipboard.writeText(window.location.href);
      setCopied(true);
      setTimeout(() => setCopied(false), 1500);
    } catch {
      setCopied(false);
    }
  };

  return (
    <Card className="min-w-0 p-6" aria-label={`Case ${item.id}`}>
      <div className="flex items-center justify-between gap-3 text-sm text-muted">
        <span>
          {item.id} · {label(CATEGORY_LABELS, item.category)}
          {critical ? " · critical" : ""}
        </span>
        <Badge tone={t.status?.passed ? "pass" : "fail"}>{t.status?.passed ? "Passed" : "Failed"}</Badge>
      </div>
      <div className="mt-4 text-sm text-muted">Question</div>
      <h2 className="mt-1 text-[19px] font-normal">{item.query}</h2>

      <div className="mt-5 text-sm text-muted">Bot answer</div>
      <div className="mt-1 whitespace-pre-wrap break-words rounded-lg bg-neutral-soft p-4 text-[15px]">{t.answer}</div>
      {t.guardrails.length > 0 && <div className="mt-2 text-xs text-muted">Guardrails applied: {t.guardrails.join(", ")}</div>}

      <div className="mt-5 text-sm text-muted">Checks</div>
      <ul className="mt-2 flex flex-col gap-2">
        {graderOrder(Object.keys(t.grades)).map((g) => {
          const grade = t.grades[g];
          if (!grade) return null;
          return (
            <li key={g} className={cx("grid grid-cols-[18px_190px_1fr] items-start gap-2 text-sm", grade.na && "text-faint")}>
              <span aria-label={grade.na ? "not applicable" : grade.passed ? "passed" : "failed"} className={grade.na ? "" : grade.passed ? "text-pass" : "text-fail"}>
                {grade.na ? "–" : grade.passed ? "✓" : "✕"}
              </span>
              <span className="font-medium" title={g}>
                {label(GRADER_LABELS, g)}
              </span>
              <span className="break-words">{grade.evidence}</span>
            </li>
          );
        })}
      </ul>

      <div className="mt-5 text-sm text-muted">Documents retrieved</div>
      <div className="mt-2 flex flex-wrap gap-2">
        {t.retrieved.length === 0 && <span className="text-sm text-muted">None (answered by a guardrail)</span>}
        {t.retrieved.map((d) => {
          const doc = run.documents[d];
          const untrusted = doc ? UNTRUSTED_SOURCES.has(doc.source) : false;
          return (
            <Chip key={d} mono tone={untrusted ? "warn" : "neutral"}>
              <span title={doc?.title}>
                {d}
                {untrusted ? " (untrusted)" : ""}
              </span>
            </Chip>
          );
        })}
      </div>

      <div className="mt-6 flex flex-wrap gap-2 border-t border-line pt-4">
        {signedIn && (
          <Button onClick={() => setLabelling((l) => !l)} aria-expanded={labelling}>
            Label this answer
          </Button>
        )}
        {compareWith !== version && (
          <ButtonLink href={`/playground/?case=${item.id}&a=${version}&b=${compareWith}`}>Compare with {compareWith}</ButtonLink>
        )}
        <Button onClick={copy}>{copied ? "Copied" : "Copy link"}</Button>
      </div>
      {labelling && <LabelForm item={item} version={version} runId={runId} graders={Object.keys(t.grades).filter((g) => !t.grades[g]?.na)} />}
    </Card>
  );
}

function LabelForm({ item, version, runId, graders }: { item: CaseItem; version: string; runId: string; graders: string[] }) {
  const ordered = graderOrder(graders);
  const [grader, setGrader] = useState(ordered.find((g) => g.startsWith("judge_")) ?? ordered[0] ?? "");
  const [note, setNote] = useState("");
  const [result, setResult] = useState<string | null>(null);

  const save = async (humanPass: boolean) => {
    setResult(null);
    try {
      await apiPost("/api/labels", { run_id: runId, case_id: item.id, version, grader, human_pass: humanPass, note });
      clearApiCache();
      setResult(`Saved: ${grader} ${humanPass ? "pass" : "fail"} for ${item.id} (${version}).`);
    } catch (err) {
      setResult(err instanceof ApiError ? `Not saved: ${err.message}` : String(err));
    }
  };

  return (
    <div className="mt-4 flex flex-col gap-3 rounded-lg bg-neutral-soft/70 p-4 text-sm">
      <p className="text-muted">Your judgement of this answer for one check. Labels calibrate the LLM judges (data/labels.jsonl).</p>
      <label className="flex items-center gap-2">
        Check
        <select className="rounded-lg border border-line bg-field px-2 py-1.5" value={grader} onChange={(e) => setGrader(e.target.value)}>
          {ordered.map((g) => (
            <option key={g} value={g}>
              {g} · {label(GRADER_LABELS, g)}
            </option>
          ))}
        </select>
      </label>
      <input className={INPUT} placeholder="Note (optional)" value={note} maxLength={500} onChange={(e) => setNote(e.target.value)} />
      <div className="flex gap-2">
        <Button variant="primary" onClick={() => save(true)}>
          Should pass
        </Button>
        <Button onClick={() => save(false)}>Should fail</Button>
      </div>
      {result && <p role="status">{result}</p>}
    </div>
  );
}
