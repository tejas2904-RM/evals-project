// After `next build`: hash every inline <script> in out/**/*.html and put a per-page CSP <meta> first in <head>.
// Inline scripts are Next's bootstrap/RSC payload; hashing them keeps `script-src` free of 'unsafe-inline'.
// vercel.json can't carry these hashes (Vercel reads it before the build), so it only sets the static headers.

import { createHash } from "node:crypto";
import { readdirSync, readFileSync, statSync, writeFileSync } from "node:fs";
import { join, relative, resolve } from "node:path";
import { URL, fileURLToPath } from "node:url";

const MARK = 'http-equiv="Content-Security-Policy"';
const INLINE_SCRIPT = /<script(?![^>]*\bsrc=)[^>]*>([\s\S]*?)<\/script>/gi;

export function apiOrigin(base = process.env.NEXT_PUBLIC_API_BASE_URL || "http://127.0.0.1:8000") {
  return new URL(base).origin;
}

export function policy(hashes, api) {
  const scripts = ["'self'", ...[...hashes].sort().map((h) => `'${h}'`)].join(" ");
  return [
    "default-src 'self'",
    `script-src ${scripts}`,
    "style-src 'self' 'unsafe-inline'",
    "img-src 'self' data:",
    "font-src 'self'",
    `connect-src 'self' ${api}`,
    "object-src 'none'",
    "base-uri 'self'",
    "form-action 'self'",
  ].join("; ");
}

export function inlineHashes(html) {
  const hashes = new Set();
  for (const m of html.matchAll(INLINE_SCRIPT)) {
    hashes.add(`sha256-${createHash("sha256").update(m[1], "utf8").digest("base64")}`);
  }
  return hashes;
}

export function addCsp(html, api) {
  if (html.includes(MARK)) throw new Error("page already has a CSP meta tag");
  const meta = `<meta ${MARK} content="${policy(inlineHashes(html), api)}"/>`;
  if (!/<head[^>]*>/i.test(html)) throw new Error("no <head> in page");
  return html.replace(/<head[^>]*>/i, (head) => `${head}${meta}`);
}

function htmlFiles(dir) {
  return readdirSync(dir).flatMap((name) => {
    const path = join(dir, name);
    if (statSync(path).isDirectory()) return htmlFiles(path);
    return name.endsWith(".html") ? [path] : [];
  });
}

if (process.argv[1] && resolve(process.argv[1]) === fileURLToPath(import.meta.url)) {
  const OUT = fileURLToPath(new URL("../out", import.meta.url));
  const api = apiOrigin();
  if (!process.env.NEXT_PUBLIC_API_BASE_URL) console.warn("csp: NEXT_PUBLIC_API_BASE_URL is not set; connect-src allows", api);
  let pages = 0;
  for (const file of htmlFiles(OUT)) {
    writeFileSync(file, addCsp(readFileSync(file, "utf8"), api));
    pages += 1;
    console.log(`csp: ${relative(OUT, file)} (${inlineHashes(readFileSync(file, "utf8")).size} inline scripts)`);
  }
  console.log(`csp: ${pages} pages, connect-src ${api}`);
}
