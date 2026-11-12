import { createHash } from "node:crypto";
import { readFileSync } from "node:fs";
import { resolve } from "node:path";
import { addCsp, apiOrigin, inlineHashes, policy } from "../scripts/csp-hashes.mjs";

const sha = (s: string) => `sha256-${createHash("sha256").update(s, "utf8").digest("base64")}`;
const PAGE =
  '<!DOCTYPE html><html><head><meta charSet="utf-8"/><script src="/_next/a.js" async=""></script></head>' +
  '<body><script>self.__next_f=[]</script><script id="x">self.__next_f.push([1,"a"])</script></body></html>';

describe("CSP build step", () => {
  it("hashes inline scripts only", () => {
    expect(inlineHashes(PAGE)).toEqual(new Set([sha("self.__next_f=[]"), sha('self.__next_f.push([1,"a"])')]));
  });

  it("puts the policy first in <head>, before any script", () => {
    const out = addCsp(PAGE, "https://api.example.com");
    expect(out).toMatch(/^<!DOCTYPE html><html><head><meta http-equiv="Content-Security-Policy" content="/);
    expect(out.indexOf("Content-Security-Policy")).toBeLessThan(out.indexOf("<script"));
    expect(() => addCsp(out, "https://api.example.com")).toThrow(/already/);
  });

  it("never allows inline or eval'd scripts, and only talks to the API", () => {
    const p = policy([sha("x")], "https://api.example.com");
    const script = p.split("; ").find((d) => d.startsWith("script-src")) ?? "";
    expect(script).toBe(`script-src 'self' '${sha("x")}'`);
    expect(script).not.toMatch(/unsafe-inline|unsafe-eval/);
    expect(p).toContain("connect-src 'self' https://api.example.com");
    expect(p).toContain("object-src 'none'");
  });

  it("uses the origin of the API base URL", () => {
    expect(apiOrigin("https://evalpilot-api.onrender.com/")).toBe("https://evalpilot-api.onrender.com");
    expect(apiOrigin("http://127.0.0.1:8000")).toBe("http://127.0.0.1:8000");
  });

  it("vercel.json forbids framing and sniffing on every path", () => {
    const config = JSON.parse(readFileSync(resolve(process.cwd(), "vercel.json"), "utf8")) as {
      headers: { source: string; headers: { key: string; value: string }[] }[];
    };
    const all = config.headers.find((h) => h.source === "/(.*)");
    const get = (k: string) => all?.headers.find((h) => h.key === k)?.value;
    expect(get("Content-Security-Policy")).toContain("frame-ancestors 'none'");
    expect(get("X-Content-Type-Options")).toBe("nosniff");
    expect(get("X-Frame-Options")).toBe("DENY");
  });
});
