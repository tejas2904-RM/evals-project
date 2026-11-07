"use client";

import Link from "next/link";
import { usePathname } from "next/navigation";
import { ButtonLink, cx } from "@/components/ui";
import { useAdmin, useMeta } from "@/lib/hooks";

const LINKS = [
  { href: "/dashboard/", label: "Dashboard" },
  { href: "/audits/", label: "Audits" },
  { href: "/cases/", label: "Cases" },
  { href: "/compare/", label: "Compare" },
  { href: "/calibration/", label: "Calibration" },
  { href: "/playground/", label: "Playground" },
];

const BOT_PAGES = ["/dashboard/", "/cases/", "/compare/", "/calibration/"];

export function Nav() {
  const pathname = usePathname() || "/";
  const path = pathname.endsWith("/") ? pathname : `${pathname}/`;
  const { data: meta } = useMeta();
  const { signedIn } = useAdmin(meta);

  if (path.startsWith("/audits/new/")) {
    return (
      <header className="sticky top-0 z-40 border-b border-line bg-header text-white backdrop-blur-[12px]">
        <div className="mx-auto flex h-16 max-w-[1100px] items-center justify-between px-5">
          <div className="flex items-center gap-6">
            <Link href="/" className="font-display text-lg tracking-[-0.01em]">
              EvalPilot
            </Link>
            <span className="text-sm text-zinc-300">{signedIn ? "Admin · New audit" : "New audit"}</span>
          </div>
          <ButtonLink href="/audits/" variant="onDark">
            Cancel
          </ButtonLink>
        </div>
      </header>
    );
  }

  const isActive = (href: string) => path === href || (href === "/audits/" && path.startsWith("/audits/"));
  const bots = meta?.bots ?? [];

  return (
    <header className="sticky top-0 z-40 border-b border-line bg-header text-white backdrop-blur-[12px]">
      <nav aria-label="Main" className="mx-auto flex h-16 max-w-[1100px] items-center justify-between gap-4 px-5">
        <div className="flex min-w-0 items-center gap-6">
          <Link href="/" className="font-display text-lg tracking-[-0.01em]">
            EvalPilot
          </Link>
          <ul className="hidden items-center gap-1 lg:flex">
            {LINKS.map((l) => (
              <li key={l.href}>
                <Link
                  href={l.href}
                  aria-current={isActive(l.href) ? "page" : undefined}
                  className={cx(
                    "rounded-md px-3 py-1.5 text-sm",
                    isActive(l.href) ? "bg-brand-line/40 text-white ring-1 ring-brand-line" : "text-zinc-300 hover:text-white",
                  )}
                >
                  {l.label}
                </Link>
              </li>
            ))}
          </ul>
        </div>
        <div className="flex items-center gap-3">
          {BOT_PAGES.includes(path) && bots.length > 0 && (
            <label className="hidden items-center text-sm 2xl:flex">
              <span className="sr-only">Bot</span>
              <select className="rounded-md border border-white/25 bg-transparent px-2 py-1.5 text-sm text-white" defaultValue={bots[0]?.run_id}>
                {bots.map((b) => (
                  <option key={b.run_id} value={b.run_id}>
                    {b.name}
                  </option>
                ))}
              </select>
            </label>
          )}
          {path !== "/" && (
            <ButtonLink href="/audits/new/" variant="primary" className="border-brand-line">
              New audit
            </ButtonLink>
          )}
          {signedIn ? (
            <Link href="/admin/" className="rounded-lg border border-brand-line px-3 py-2 text-sm text-white">
              Admin
            </Link>
          ) : (
            <ButtonLink href="/admin/" variant="onDark">
              Admin sign in
            </ButtonLink>
          )}
        </div>
      </nav>
      <ul className="flex gap-1 overflow-x-auto px-3 pb-2 lg:hidden">
        {LINKS.map((l) => (
          <li key={l.href}>
            <Link href={l.href} className={cx("block rounded-md px-3 py-1.5 text-sm whitespace-nowrap", isActive(l.href) ? "bg-brand-line/40 text-white" : "text-zinc-300")}>
              {l.label}
            </Link>
          </li>
        ))}
      </ul>
    </header>
  );
}
