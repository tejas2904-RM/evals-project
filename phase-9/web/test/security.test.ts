// Source rules that would otherwise need a linter: bot answers, evidence and uploaded text are rendered as text only.
import { readdirSync, readFileSync, statSync } from "node:fs";
import { join, relative } from "node:path";
import { URL, fileURLToPath } from "node:url";

const ROOT = process.cwd();

function sources(dir: string): string[] {
  return readdirSync(dir).flatMap((name) => {
    const path = join(dir, name);
    if (statSync(path).isDirectory()) return sources(path);
    return /\.(ts|tsx|mjs)$/.test(name) ? [path] : [];
  });
}

const files = ["app", "components", "lib", "scripts"].flatMap((d) => sources(join(ROOT, d)));

const BANNED: [string, RegExp][] = [
  ["dangerouslySetInnerHTML", /dangerouslySetInnerHTML/],
  ["innerHTML / outerHTML", /\.(inner|outer)HTML\s*=/],
  ["insertAdjacentHTML", /insertAdjacentHTML/],
  ["document.write", /document\.write/],
  ["eval", /\beval\s*\(/],
  ["new Function", /new\s+Function\s*\(/],
  ["javascript: URL", /["'`]javascript:/i],
];

describe("frontend source rules", () => {
  it("scans the app", () => {
    expect(files.length).toBeGreaterThan(15);
  });

  it.each(BANNED)("never uses %s", (_name, pattern) => {
    const hits = files.filter((f) => pattern.test(readFileSync(f, "utf8"))).map((f) => relative(ROOT, f));
    expect(hits).toEqual([]);
  });

  it("only reads public NEXT_PUBLIC_ settings, never a key", () => {
    for (const f of files) {
      const text = readFileSync(f, "utf8");
      expect(text, relative(ROOT, f)).not.toMatch(/OPENAI_API_KEY/);
      expect(text, relative(ROOT, f)).not.toMatch(/process\.env\.(?!NEXT_PUBLIC_)[A-Z0-9_]+/);
    }
  });

  it("opens external links without an opener", () => {
    for (const f of files) {
      const text = readFileSync(f, "utf8");
      for (const tag of text.match(/<a\b[^>]*target="_blank"[^>]*>/g) ?? []) expect(tag, relative(ROOT, f)).toMatch(/rel="noopener noreferrer"/);
    }
  });
});
