import Link from "next/link";

export default function NotFound() {
  return (
    <div className="mx-auto max-w-md py-16 text-center">
      <h1 className="text-[28px] font-semibold">Page not found</h1>
      <p className="mt-2 text-sm text-muted">
        Try the <Link href="/dashboard/" className="text-brand underline">dashboard</Link> or the{" "}
        <Link href="/audits/" className="text-brand underline">audit list</Link>.
      </p>
    </div>
  );
}
