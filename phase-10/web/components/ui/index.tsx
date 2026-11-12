"use client";

import Link from "next/link";
import type { ComponentProps, ReactNode } from "react";
import { useApiStatus } from "@/lib/useApi";

export type Tone = "pass" | "fail" | "warn" | "muted" | "neutral" | "brand";

const TONES: Record<Tone, string> = {
  pass: "bg-pass-soft text-pass",
  fail: "bg-fail-soft text-fail",
  warn: "bg-warn-soft text-warn",
  muted: "bg-neutral-soft text-muted",
  neutral: "bg-neutral-soft text-text",
  brand: "bg-brand-soft text-brand",
};

export function cx(...parts: (string | false | null | undefined)[]): string {
  return parts.filter(Boolean).join(" ");
}

export function Badge({ tone = "neutral", children, className }: { tone?: Tone; children: ReactNode; className?: string }) {
  return (
    <span className={cx("inline-flex items-center rounded-full px-2.5 py-0.5 text-xs font-medium whitespace-nowrap", TONES[tone], className)}>
      {children}
    </span>
  );
}

export function levelTone(level: string): Tone {
  if (level === "critical" || level === "high") return "fail";
  if (level === "medium") return "warn";
  return "muted";
}

export function guardrailTone(state: string): Tone {
  if (state === "present") return "pass";
  if (state === "weak") return "warn";
  if (state === "missing") return "fail";
  return "muted";
}

export function Card({ children, className, as: Tag = "section", ...rest }: { children: ReactNode; className?: string; as?: "section" | "div" | "article" } & Omit<ComponentProps<"section">, "className" | "children" | "ref">) {
  return (
    <Tag className={cx("rounded-[var(--radius-card)] border border-line bg-surface", className)} {...rest}>
      {children}
    </Tag>
  );
}

export function CardTitle({ children, right, className }: { children: ReactNode; right?: ReactNode; className?: string }) {
  return (
    <div className={cx("flex items-center justify-between gap-3", className)}>
      <h2 className="text-[15px] font-normal">{children}</h2>
      {right}
    </div>
  );
}

export function StatCard({ label, value, sub, tone }: { label: string; value: ReactNode; sub?: ReactNode; tone?: "pass" | "fail" }) {
  return (
    <Card className={cx("p-4", tone === "fail" && "border-fail-soft bg-fail-soft", tone === "pass" && "border-pass-soft bg-pass-soft")}>
      <div className={cx("text-sm", tone === "fail" ? "text-fail" : tone === "pass" ? "text-pass" : "text-muted")}>{label}</div>
      <div className={cx("mt-1 font-display text-[28px] font-normal leading-tight tracking-[-0.01em]", tone === "fail" && "text-fail", tone === "pass" && "text-pass")}>
        {value}
      </div>
      {sub && <div className="mt-1 text-xs text-muted">{sub}</div>}
    </Card>
  );
}

type Variant = "primary" | "dark" | "outline" | "ghost" | "onDark";

const VARIANTS: Record<Variant, string> = {
  primary: "bg-brand text-ink hover:bg-brand-hover border border-brand",
  dark: "bg-ink text-white hover:bg-ink-soft border border-ink",
  outline: "bg-transparent text-text border border-line hover:border-faint hover:bg-surface",
  ghost: "text-brand hover:underline",
  onDark: "border border-white/25 text-white hover:border-white/60",
};

const BTN = "inline-flex items-center justify-center gap-2 whitespace-nowrap rounded-lg px-4 py-2 text-sm font-semibold transition-colors disabled:opacity-45";

export function Button({ variant = "outline", className, ...rest }: { variant?: Variant } & ComponentProps<"button">) {
  return <button type="button" className={cx(BTN, VARIANTS[variant], className)} {...rest} />;
}

export function ButtonLink({ variant = "outline", className, href, external, ...rest }: { variant?: Variant; href: string; external?: boolean } & Omit<ComponentProps<"a">, "href">) {
  const cls = cx(BTN, VARIANTS[variant], className);
  if (external) return <a href={href} className={cls} target="_blank" rel="noopener noreferrer" {...rest} />;
  return <Link href={href} className={cls} {...rest} />;
}

export function Tabs({ tabs, active, onChange, label }: { tabs: { id: string; label: string }[]; active: string; onChange: (id: string) => void; label: string }) {
  return (
    <div role="tablist" aria-label={label} className="flex gap-1 border-b border-line">
      {tabs.map((t) => (
        <button
          key={t.id}
          role="tab"
          type="button"
          aria-selected={t.id === active}
          onClick={() => onChange(t.id)}
          className={cx(
            "-mb-px border-b-2 px-3 py-2.5 text-sm",
            t.id === active ? "border-brand font-semibold text-text" : "border-transparent text-muted hover:text-text",
          )}
        >
          {t.label}
        </button>
      ))}
    </div>
  );
}

export function Chip({ children, tone = "neutral", mono, className }: { children: ReactNode; tone?: Tone; mono?: boolean; className?: string }) {
  return (
    <span className={cx("inline-flex items-center rounded-md px-2 py-0.5 text-xs", TONES[tone], mono && "font-mono", className)}>{children}</span>
  );
}

export function FilterChip({ active, children, onClick }: { active: boolean; children: ReactNode; onClick: () => void }) {
  return (
    <button
      type="button"
      aria-pressed={active}
      onClick={onClick}
      className={cx(
        "rounded-full border px-4 py-1.5 text-sm",
        active ? "border-brand-line bg-brand text-ink" : "border-line bg-transparent text-text hover:border-faint",
      )}
    >
      {children}
    </button>
  );
}

/** Two stacked bars: grey for the baseline version, green for the candidate (mockup 2-dashboard.png). */
export function PairedBar({ a, b, labelA, labelB }: { a: number | null; b: number | null; labelA: string; labelB: string }) {
  const bar = (rate: number | null, cls: string, name: string) => (
    <div className="h-2 w-full rounded-full bg-neutral-soft" role="img" aria-label={`${name}: ${rate === null ? "n/a" : `${Math.round(rate * 100)}%`}`}>
      {rate !== null && <div className={cx("h-2 rounded-full", cls)} style={{ width: `${Math.max(rate * 100, rate > 0 ? 1.5 : 0.8)}%` }} />}
    </div>
  );
  return (
    <div className="flex flex-col gap-1">
      {bar(a, "bg-faint", labelA)}
      {bar(b, "bg-brand", labelB)}
    </div>
  );
}

export function Stepper({ steps, current, onSelect }: { steps: { id: number; title: string; sub: string }[]; current: number; onSelect?: (id: number) => void }) {
  return (
    <ol className="flex flex-col gap-1" aria-label="Steps">
      {steps.map((s) => {
        const done = s.id < current;
        const active = s.id === current;
        return (
          <li key={s.id}>
            <button
              type="button"
              disabled={!done || !onSelect}
              onClick={() => onSelect?.(s.id)}
              aria-current={active ? "step" : undefined}
              className={cx(
                "flex w-full items-start gap-3 rounded-lg border px-3 py-2.5 text-left disabled:cursor-default",
                active ? "border-line bg-surface" : "border-transparent",
              )}
            >
              <span
                className={cx(
                  "mt-0.5 flex h-6 w-6 shrink-0 items-center justify-center rounded-full text-xs font-semibold",
                  active ? "bg-brand text-white" : done ? "text-pass" : "text-muted",
                )}
              >
                {done ? "✓" : s.id}
              </span>
              <span>
                <span className={cx("block text-sm font-semibold", !active && !done && "text-muted")}>{s.title}</span>
                <span className="block text-xs text-muted">{s.sub}</span>
              </span>
            </button>
          </li>
        );
      })}
    </ol>
  );
}

export function Field({ label, children, hint, htmlFor }: { label: string; children: ReactNode; hint?: ReactNode; htmlFor?: string }) {
  return (
    <div className="flex flex-col gap-1.5">
      <label htmlFor={htmlFor} className="text-sm font-medium">
        {label}
      </label>
      {children}
      {hint && <div className="text-xs text-muted">{hint}</div>}
    </div>
  );
}

export const INPUT =
  "w-full rounded-lg border border-line bg-field px-3 py-2.5 text-sm placeholder:text-faint focus:border-brand-line focus:outline-none disabled:bg-neutral-soft disabled:text-muted";

export function Skeleton({ className }: { className?: string }) {
  return <div className={cx("animate-pulse rounded-lg bg-neutral-soft", className)} aria-hidden="true" />;
}

export function LoadState({ loading, error, onRetry, children }: { loading: boolean; error: string | null; onRetry?: () => void; children: ReactNode }) {
  if (error) {
    return (
      <Card className="p-6" role="alert">
        <div className="font-semibold">Couldn&apos;t load this page</div>
        <p className="mt-1 text-sm text-muted">{error}</p>
        {onRetry && (
          <Button className="mt-3" onClick={onRetry}>
            Try again
          </Button>
        )}
      </Card>
    );
  }
  if (loading) {
    return (
      <div className="flex flex-col gap-4" aria-busy="true" aria-label="Loading">
        <Skeleton className="h-10 w-2/3" />
        <Skeleton className="h-32" />
        <Skeleton className="h-64" />
      </div>
    );
  }
  return <>{children}</>;
}

export function ApiStatusBar() {
  const status = useApiStatus();
  if (status === "ok") return null;
  return (
    <div role="status" className={cx("px-5 py-2 text-center text-sm", status === "waking" ? "bg-warn-soft text-warn" : "bg-neutral-soft text-muted")}>
      {status === "waking"
        ? "Waking the API (the free server sleeps when idle). Showing the saved snapshot meanwhile."
        : "Showing the saved snapshot of the reference results: the API is not reachable right now."}
    </div>
  );
}

export function SourceBadge({ source }: { source: string | null }) {
  if (source !== "snapshot") return null;
  return <Badge tone="warn">snapshot</Badge>;
}

export function PageHeader({ eyebrow, title, right }: { eyebrow?: ReactNode; title: ReactNode; right?: ReactNode }) {
  return (
    <div className="flex flex-wrap items-end justify-between gap-4">
      <div>
        {eyebrow && <div className="text-sm text-muted">{eyebrow}</div>}
        <h1 className="mt-1 text-[28px] font-normal leading-tight tracking-[-0.01em]">{title}</h1>
      </div>
      {right && <div className="flex flex-wrap gap-2">{right}</div>}
    </div>
  );
}
