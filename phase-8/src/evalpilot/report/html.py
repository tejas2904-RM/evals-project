"""Single-file HTML report: inline CSS and JS, no remote assets.

All data is escaped server-side; the inline script only sorts and filters existing elements,
so bot answers (which can contain <script> payloads from the vulnerable demo) are never parsed as HTML.
"""

from __future__ import annotations

from html import escape
from typing import Any

from evalpilot.audit.redact import redact

LEVEL_ORDER = {"critical": 4, "high": 3, "medium": 2, "low": 1}

CSS = """
:root{--ok:#1a7f37;--bad:#cf222e;--warn:#9a6700;--mute:#57606a;--line:#d0d7de;--bg:#f6f8fa}
*{box-sizing:border-box}body{font:14px/1.5 -apple-system,Segoe UI,Helvetica,Arial,sans-serif;margin:0;color:#1f2328}
header{background:#0d1117;color:#fff;padding:24px 32px}header h1{margin:0 0 4px;font-size:22px}
header .sub{color:#9da7b3;font-size:13px}main{max-width:1200px;margin:0 auto;padding:16px 32px 64px}
nav{position:sticky;top:0;background:#fff;border-bottom:1px solid var(--line);padding:8px 32px;z-index:2;font-size:13px}
nav a{margin-right:14px;color:#0969da;text-decoration:none}
h2{margin:36px 0 10px;padding-bottom:6px;border-bottom:1px solid var(--line);font-size:19px}
h3{margin:22px 0 8px;font-size:16px}
table{border-collapse:collapse;width:100%;margin:8px 0 14px;font-size:13px}
th,td{border:1px solid var(--line);padding:5px 8px;text-align:left;vertical-align:top;overflow-wrap:break-word}
summary,pre,.ids{overflow-wrap:anywhere}details,.card{overflow-x:auto}td code{white-space:nowrap}
th{background:var(--bg)}table.sortable th{cursor:pointer}table.sortable th:after{content:" \\2195";color:var(--mute)}
td.num{text-align:right;font-variant-numeric:tabular-nums}
.badge{display:inline-block;padding:2px 10px;border-radius:12px;font-weight:600;font-size:12px;color:#fff}
.SHIP,.PASS,.pass,.verified{background:var(--ok)}.BLOCK,.BLOCKED,.fail,.failed,.critical{background:var(--bad)}
.pending,.explained,.medium,.declared{background:var(--warn)}.high{background:#bc4c00}.low,.missing,.na{background:var(--mute)}
.banner{border-radius:8px;padding:16px 20px;margin:18px 0;color:#fff}.banner h2{border:0;margin:0 0 6px;color:#fff}
.banner.SHIP{background:var(--ok)}.banner.BLOCK{background:var(--bad)}.banner ul{margin:6px 0 0}
.cell-ok{background:#dafbe1}.cell-mid{background:#fff8c5}.cell-bad{background:#ffebe9}.cell-na{color:var(--mute)}
.ids{font-family:ui-monospace,Consolas,monospace;font-size:12px;color:#444}
pre{white-space:pre-wrap;background:var(--bg);border:1px solid var(--line);padding:8px;border-radius:6px;font-size:12px;margin:4px 0}
details{border:1px solid var(--line);border-radius:6px;margin:6px 0;padding:6px 10px}summary{cursor:pointer}
.case-v{border-left:3px solid var(--line);padding-left:10px;margin:8px 0}.bits span{margin-right:4px}
.filters{display:flex;gap:12px;flex-wrap:wrap;margin:8px 0;align-items:center}.filters select,.filters input{padding:4px}
.muted{color:var(--mute)}.warn{color:var(--warn)}.grid{display:grid;grid-template-columns:repeat(auto-fit,minmax(320px,1fr));gap:14px}
.card{border:1px solid var(--line);border-radius:8px;padding:12px 14px}
"""

JS = """
document.querySelectorAll('table.sortable').forEach(function(t){
  t.querySelectorAll('th').forEach(function(th,i){
    th.addEventListener('click',function(){
      var body=t.tBodies[0],rows=Array.prototype.slice.call(body.rows);
      var dir=th.dataset.dir==='desc'?'asc':'desc';th.dataset.dir=dir;
      rows.sort(function(a,b){
        var x=a.cells[i].dataset.sort||a.cells[i].textContent,y=b.cells[i].dataset.sort||b.cells[i].textContent;
        var nx=parseFloat(x),ny=parseFloat(y),c=(!isNaN(nx)&&!isNaN(ny))?nx-ny:x.localeCompare(y);
        return dir==='asc'?c:-c;});
      rows.forEach(function(r){body.appendChild(r);});});});});
(function(){
  var cat=document.getElementById('f-cat'),ver=document.getElementById('f-ver'),gr=document.getElementById('f-grader'),
      q=document.getElementById('f-q'),count=document.getElementById('f-count');
  if(!cat)return;
  function apply(){
    var shown=0;
    document.querySelectorAll('details.case').forEach(function(d){
      var ok=(!cat.value||d.dataset.category===cat.value)&&(!q.value||d.textContent.toLowerCase().indexOf(q.value.toLowerCase())>=0);
      var anyV=false;
      d.querySelectorAll('.case-v').forEach(function(v){
        var vOk=(!ver.value||v.dataset.version===ver.value)&&(!gr.value||(' '+v.dataset.failing+' ').indexOf(' '+gr.value+' ')>=0);
        v.style.display=vOk?'':'none';if(vOk)anyV=true;});
      var vis=ok&&anyV;d.style.display=vis?'':'none';if(vis)shown++;});
    count.textContent=shown+' case(s)';}
  [cat,ver,gr,q].forEach(function(e){e.addEventListener('input',apply);});apply();
})();
"""


def e(value: Any) -> str:
    return escape("" if value is None else str(value))


def badge(text: str, cls: str | None = None) -> str:
    return f'<span class="badge {e(cls or text)}">{e(text)}</span>'


def pct(value: float | None) -> str:
    return "-" if value is None else f"{value:.0%}"


def _rate_cell(stats: dict[str, Any], threshold: float | None) -> str:
    if stats["rate"] is None:
        return f'<td class="num cell-na">n/a {stats["na"]}</td>'
    cls = "cell-ok" if threshold is None or stats["rate"] >= threshold else ("cell-mid" if stats["rate"] >= threshold - 0.15 else "cell-bad")
    na = f' <span class="muted">n/a {stats["na"]}</span>' if stats["na"] else ""
    return f'<td class="num {cls}">{stats["passed"]}/{stats["applicable"]} ({pct(stats["rate"])}){na}</td>'


def _ids(ids: list[str]) -> str:
    return f'<span class="ids">{e(", ".join(ids)) or "-"}</span>'


def section_final(ctx: dict[str, Any]) -> str:
    f = ctx["final"]
    items = "".join(f"<li>{e(r)}</li>" for r in f["reasons"])
    rules = "".join(f"<li><code>{e(r)}</code></li>" for r in f["deciding_rules"])
    risks = ", ".join(f["deciding_risks"])
    out = [f'<div class="banner {e(f["decision"])}" id="verdict"><h2>Final verdict for {e(f["version"])}: {e(f["decision"])}</h2>',
           "<div>SHIP only when the release gate passes <b>and</b> the audit of this version says SHIP.</div>",
           f"<ul>{items}</ul>"]
    if rules:
        out.append(f"<div>Deciding gate rules:</div><ul>{rules}</ul>")
    if risks:
        out.append(f"<div>Deciding audit risks: {e(risks)}</div>")
    if f["conditions"]:
        out.append("<div>Conditions:</div><ul>" + "".join(f"<li>{e(c)}</li>" for c in f["conditions"]) + "</ul>")
    out.append("</div>")
    return "".join(out)


def section_spend(ctx: dict[str, Any]) -> str:
    s = ctx["spend"]
    rows = "".join(f'<tr><td>{e(m)}</td><td class="num">{int(v["calls"])}</td><td class="num">${v["cost_usd"]:.4f}</td></tr>'
                   for m, v in s["by_model"].items())
    prows = "".join(f'<tr><td>{e(p)}</td><td class="num">{int(v["calls"])}</td><td class="num">${v["cost_usd"]:.4f}</td></tr>'
                    for p, v in s["by_purpose"].items())
    return (f'<h2 id="spend">Spend</h2><p><b>${s["total_usd"]:.4f}</b> of the ${s["budget_usd"]:.2f} budget guard '
            f'(hard ceiling ${s["hard_ceiling_usd"]:.2f}) over {s["calls"]} paid calls. OpenAI is the only paid item; '
            "re-runs of unchanged cases hit the cache.</p>"
            '<div class="grid"><table><thead><tr><th>Model</th><th>Calls</th><th>USD</th></tr></thead>'
            f"<tbody>{rows}</tbody></table><table><thead><tr><th>Purpose</th><th>Calls</th><th>USD</th></tr></thead>"
            f"<tbody>{prows}</tbody></table></div>")


def section_gate(ctx: dict[str, Any]) -> str:
    out = ['<h2 id="gate">Release gate</h2><p>Thresholds from <code>evals.toml [gate]</code>: minimum pass rates, '
           "zero regressions against the previous version, required improvements (a perfect baseline counts as "
           '"no regression").</p><div class="grid">']
    for v, g in ctx["gates"].items():
        out.append(f'<div class="card"><h3>{e(v)} {badge(g["verdict"])} <span class="muted">baseline {e(g["baseline"] or "none")}</span></h3>')
        if g["violations"]:
            out.append("<table><thead><tr><th>Grader</th><th>Rule</th><th>Threshold</th><th>Observed</th><th>Cases</th></tr></thead><tbody>")
            for viol in g["violations"]:
                out.append(f'<tr><td>{e(viol["grader"])}</td><td>{e(viol["rule"])}</td><td>{e(viol["threshold"])}</td>'
                           f'<td>{e(viol["observed"])}</td><td>{_ids(viol["case_ids"])}</td></tr>')
            out.append("</tbody></table>")
        else:
            out.append("<p>No violations.</p>")
        for w in g["warnings"]:
            out.append(f'<div class="warn">warning: {e(w)}</div>')
        out.append("</div>")
    out.append("</div>")
    return "".join(out)


def section_matrix(ctx: dict[str, Any], thresholds: dict[str, float]) -> str:
    head = "".join(f"<th>{e(v)}</th>" for v in ctx["versions"])
    rows = []
    for g in ctx["graders"]:
        t = thresholds.get(g)
        cells = "".join(_rate_cell(ctx["matrix"][g][v], t) for v in ctx["versions"])
        rows.append(f'<tr><td>{e(g)}</td><td class="num">{pct(t)}</td>{cells}</tr>')
    return (f'<h2 id="matrix">Pass rates: {len(ctx["graders"])} graders x {len(ctx["versions"])} versions</h2>'
            "<p>Binary graders, one failure mode each. <code>n/a</code> cases are excluded from the rate.</p>"
            f"<table><thead><tr><th>Grader</th><th>Gate min</th>{head}</tr></thead><tbody>{''.join(rows)}</tbody></table>")


def section_compare(ctx: dict[str, Any]) -> str:
    out = ['<h2 id="compare">Compare: fixed and regressed cases</h2>']
    for c in ctx["compares"]:
        out.append(f'<h3>{e(c["baseline"])} &rarr; {e(c["candidate"])}</h3><table><thead><tr><th>Grader</th><th>Fixed</th>'
                   "<th>Regressed</th><th>Still pass</th><th>Still fail</th><th>n/a</th><th>Fixed cases</th><th>Regressed cases</th></tr></thead><tbody>")
        for name, d in c["graders"].items():
            k = d["counts"]
            reg = f' class="cell-bad"' if d["regressed"] else ""
            out.append(f'<tr><td>{e(name)}</td><td class="num">{k["fixed"]}</td><td class="num"{reg}>{k["regressed"]}</td>'
                       f'<td class="num">{k["still_pass"]}</td><td class="num">{k["still_fail"]}</td><td class="num">{k["not_comparable"]}</td>'
                       f'<td>{_ids(d["fixed"])}</td><td>{_ids(d["regressed"])}</td></tr>')
        out.append("</tbody></table>")
    return "".join(out)


def section_calibration(ctx: dict[str, Any]) -> str:
    cal = ctx["calibration"]
    t = cal["targets"]
    status = badge("PASS" if cal["enough_labels"] else "pending", "pass" if cal["enough_labels"] else "pending")
    out = [f'<h2 id="calibration">Judge calibration {status}</h2>',
           f"<p>Human labels are ground truth; positive class = pass. Targets: TPR &ge; {t['tpr']:.2f}, TNR &ge; {t['tnr']:.2f}, "
           f"&kappa; &ge; {t['kappa']:.2f}; at least {cal['min_labels']} judge labels.</p>"]
    for p in cal["problems"]:
        out.append(f'<div class="warn">{e(p)}</div>')
    out.append("<table><thead><tr><th>Grader</th><th>Labels</th><th>TP</th><th>FP</th><th>TN</th><th>FN</th><th>TPR</th>"
               "<th>TNR</th><th>Accuracy</th><th>&kappa;</th><th>Status</th></tr></thead><tbody>")
    for name, g in cal["graders"].items():
        c = g["confusion"]
        st = "need labels" if not g["enough_labels"] else ("meets targets" if g["meets_targets"] else "below target")
        kappa = "-" if g["kappa"] is None else f"{g['kappa']:.2f}"
        out.append(f'<tr><td>{e(name)}</td><td class="num">{g["n_labels"]}/{g["min_labels"]}</td><td class="num">{c["tp"]}</td>'
                   f'<td class="num">{c["fp"]}</td><td class="num">{c["tn"]}</td><td class="num">{c["fn"]}</td>'
                   f'<td class="num">{pct(g["tpr"])}</td><td class="num">{pct(g["tnr"])}</td><td class="num">{pct(g["accuracy"])}</td>'
                   f'<td class="num">{kappa}</td><td>{e(st)}</td></tr>')
    out.append("</tbody></table>")
    return "".join(out)


def section_cases(ctx: dict[str, Any]) -> str:
    cats = sorted({c["category"] for c in ctx["cases"]})
    opt = lambda values: "".join(f'<option value="{e(v)}">{e(v)}</option>' for v in values)  # noqa: E731
    out = ['<h2 id="cases">Case explorer</h2><p>Query &rarr; retrieved documents &rarr; answer &rarr; 8 binary grades with evidence.</p>',
           '<div class="filters"><label>Category <select id="f-cat"><option value="">all</option>' + opt(cats) + "</select></label>"
           '<label>Version <select id="f-ver"><option value="">all</option>' + opt(ctx["versions"]) + "</select></label>"
           '<label>Failing grader <select id="f-grader"><option value="">any</option>' + opt(ctx["graders"]) + "</select></label>"
           '<label>Search <input id="f-q" type="search"></label><span id="f-count" class="muted"></span></div>']
    for c in ctx["cases"]:
        fails = sum(1 for v in c["versions"].values() for g in v["grades"].values() if not g["passed"])
        out.append(f'<details class="case" data-category="{e(c["category"])}"><summary><b>{e(c["id"])}</b> '
                   f'<span class="muted">{e(c["category"])}</span> {e(c["query"])} '
                   f'<span class="muted">({fails} failing grade(s))</span></summary>'
                   f'<div class="muted">in_scope={e(c["in_scope"])} should_refuse={e(c["should_refuse"])}</div>')
        for v, t in c["versions"].items():
            failing = " ".join(g for g, r in t["grades"].items() if not r["passed"])
            bits = "".join(
                f'<span class="badge {"na" if r["na"] else ("pass" if r["passed"] else "fail")}" title="{e(r["evidence"])}">{e(g)}</span>'
                for g, r in t["grades"].items())
            evid = "".join(f"<li><b>{e(g)}</b>: {e(r['evidence'])}</li>" for g, r in t["grades"].items() if not r["passed"] or r["na"])
            out.append(f'<div class="case-v" data-version="{e(v)}" data-failing="{e(failing)}"><b>{e(v)}</b> '
                       f'<span class="muted">retrieved: {e(", ".join(t["retrieved"])) or "-"} | refused={e(t["refused"])} | '
                       f'guardrails: {e(", ".join(t["guardrails"])) or "-"}{" | cached" if t["cached"] else ""}</span>'
                       f'<pre>{e(t["answer"])}</pre><div class="bits">{bits}</div>'
                       + (f"<ul>{evid}</ul>" if evid else "") + "</div>")
        out.append("</details>")
    return "".join(out)


def _coverage_table(cells: list[dict[str, Any]]) -> str:
    rows = "".join(
        f'<tr><td>{e(c["layer"])}</td><td>{e(", ".join(c["threats"]))}</td><td>{"yes" if c["declared"] else "no"}</td>'
        f'<td>{badge(c["status"], c["status"].replace("/", ""))}</td><td>{_ids(c["failed_checks"][:6])}</td>'
        f'<td class="num">{len(c["passed_checks"])}</td></tr>' for c in cells)
    return ("<table><thead><tr><th>Guardrail layer</th><th>Threats</th><th>Declared</th><th>Status</th>"
            f"<th>Failed checks</th><th>Passed</th></tr></thead><tbody>{rows}</tbody></table>")


def _risk_table(risks: list[dict[str, Any]]) -> str:
    rows = []
    for r in sorted(risks, key=lambda r: -r["severity"]):
        level = r["level"] + (f" (AI-only, capped from {r['capped_from']})" if r.get("capped_from") else "")
        rows.append(f'<tr><td><code>{e(r["risk_id"])}</code></td><td data-sort="{LEVEL_ORDER.get(r["level"], 0)}">{badge(level, r["level"])}</td>'
                    f'<td class="num" data-sort="{r["severity"]}">{r["severity"]} ({r["likelihood"]}x{r["impact"]})</td>'
                    f'<td>{e(r.get("owasp") or "-")}</td><td>{e(r["title"])}</td><td>{e(r["status"])}</td><td>{e(r["fix"])}</td></tr>')
    return ('<table class="sortable"><thead><tr><th>Risk</th><th>Level</th><th>Severity (L x I)</th><th>OWASP</th><th>Title</th>'
            f"<th>Status</th><th>Fix</th></tr></thead><tbody>{''.join(rows)}</tbody></table>")


def _evidence(risks: list[dict[str, Any]]) -> str:
    out = []
    for r in sorted(risks, key=lambda r: -r["severity"]):
        evs = "".join(f'<div><b>{e(ev["kind"])}</b> <code>{e(ev["location"])}</code>'
                      + (f"<pre>{e(chr(10).join(ev.get('excerpt', '').splitlines()[:8]))}</pre>" if ev.get("excerpt") else "")
                      + "</div>" for ev in r["evidence"][:6])
        more = f'<div class="muted">+{len(r["evidence"]) - 6} more</div>' if len(r["evidence"]) > 6 else ""
        out.append(f'<details><summary><code>{e(r["risk_id"])}</code> {badge(r["level"])} {e(r["title"])}</summary>'
                   f'<div class="muted">checks: {e(", ".join(r["check_ids"]))}</div>{evs}{more}<div>Fix: {e(r["fix"])}</div></details>')
    return "".join(out)


ROLE_TITLES = {"bot": "EvalPilot's own bot", "vulnerable": "Example: vulnerable_bot", "fixed": "Example: fixed_bot", "other": "Audit"}


def section_audits(ctx: dict[str, Any]) -> str:
    out = ['<h2 id="audit">Audit</h2><p>Behaviour evals, OWASP LLM Top 10 (2026) probes, code scan (rules, secrets, bandit, '
           "AI review with verified file:line evidence; target code never executed) and config review, merged into a risk "
           "register (severity = likelihood x impact), a guardrail coverage map and a SHIP/BLOCK verdict.</p>"]
    if not ctx["audits"]:
        out.append("<p>No audits included.</p>")
    for a in ctx["audits"]:
        v = a["verdict"]
        k = v["counts"]
        out.append(f'<h3>{e(ROLE_TITLES.get(a["role"], "Audit"))}: {e(a["target"])} {badge(v["decision"])}</h3>'
                   f'<div class="muted">{e(a["audit_id"])} | provider {e(a["provider"])} | engines {e(", ".join(a["engines"]))} | '
                   f'spend ${a["spend_usd"]:.4f} | exports {e(", ".join(a["exports"]) or "-")}</div>'
                   f'<p>Open risks: {k.get("critical", 0)} critical, {k.get("high", 0)} high, {k.get("medium", 0)} medium, '
                   f'{k.get("low", 0)} low; {k.get("accepted", 0)} accepted. {e("; ".join(v["reasons"]))}</p>')
        if v["conditions"]:
            out.append("<details><summary>Ship conditions (" + str(len(v["conditions"])) + ")</summary><ul>"
                       + "".join(f"<li>{e(c)}</li>" for c in v["conditions"]) + "</ul></details>")
        if a["flaws"]:
            found = sum(f["found"] for f in a["flaws"])
            present = sum(f["present"] for f in a["flaws"])
            frows = "".join(f'<tr><td>{e(f["id"])}</td><td>{e(f["owasp"])}</td><td>{e(f["title"])}</td>'
                            f'<td>{badge("yes" if f["found"] else "no", "pass" if f["found"] else "na")}</td>'
                            f'<td>{badge("yes" if f["present"] else "no", "fail" if f["present"] else "pass")}</td>'
                            f'<td>{_ids(f["matched_checks"])}</td></tr>' for f in a["flaws"])
            out.append(f"<details><summary>Planted flaws: {found}/{len(a['flaws'])} found, {present}/{len(a['flaws'])} present</summary>"
                       "<table><thead><tr><th>Flaw</th><th>OWASP</th><th>Title</th><th>Found</th><th>Present</th><th>Matched checks</th>"
                       f"</tr></thead><tbody>{frows}</tbody></table></details>")
        out.append(f"<details open><summary>Risk register ({len(a['risks'])}, click a header to sort)</summary>{_risk_table(a['risks'])}</details>")
        out.append(f"<details><summary>Guardrail coverage map</summary>{_coverage_table(a['coverage'])}</details>")
        if a["risks"]:
            out.append(f"<details><summary>Evidence drill-down</summary>{_evidence(a['risks'])}</details>")
    return "".join(out)


def section_dod(ctx: dict[str, Any]) -> str:
    rows = "".join(f'<tr><td>{e(d["item"])}</td><td>{badge(d["status"])}</td><td>{e(d["evidence"])}</td></tr>' for d in ctx["dod"])
    return ('<h2 id="dod">Definition of done</h2><table><thead><tr><th>Item</th><th>Status</th><th>Evidence</th></tr></thead>'
            f"<tbody>{rows}</tbody></table><p class=\"muted\">Also by design and tests: target code is never executed, URL "
            "probing needs --authorized, CI runs offline with no key, and pytest + the gate run in CI.</p>")


def section_legend(ctx: dict[str, Any]) -> str:
    lg = ctx["legend"]
    ratio = lg["cache_hits"] / lg["traces"] if lg["traces"] else 0
    return ('<h2 id="legend">Legend</h2><ul>'
            "<li><b>n/a</b>: the grader doesn't apply to this case (e.g. citation on a refusal); excluded from pass rates.</li>"
            f"<li><b>judge_parse_error</b>: a judge reply that wasn't valid {{pass, reason}} JSON, recorded as a fail "
            f"({lg['judge_parse_errors']} in this run).</li>"
            f"<li><b>Cache hits</b>: {lg['cache_hits']}/{lg['traces']} bot traces ({ratio:.0%}) came from the response cache at $0.</li>"
            "<li><b>AI-only, capped</b>: a risk backed only by the AI reviewer, with no rule/tool/probe agreeing, is capped at medium.</li>"
            "</ul>")


def render_html(ctx: dict[str, Any], thresholds: dict[str, float]) -> str:
    m = ctx["meta"]
    nav = "".join(f'<a href="#{a}">{t}</a>' for a, t in (
        ("verdict", "Verdict"), ("spend", "Spend"), ("gate", "Gate"), ("matrix", "Pass rates"), ("compare", "Compare"),
        ("calibration", "Calibration"), ("cases", "Cases"), ("audit", "Audit"), ("dod", "Done"), ("legend", "Legend")))
    body = "".join([
        section_final(ctx), section_spend(ctx), section_gate(ctx), section_matrix(ctx, thresholds), section_compare(ctx),
        section_calibration(ctx), section_cases(ctx), section_audits(ctx), section_dod(ctx), section_legend(ctx),
    ])
    page = (
        '<!doctype html><html lang="en"><head><meta charset="utf-8">'
        '<meta name="viewport" content="width=device-width,initial-scale=1">'
        "<title>EvalPilot report</title>"
        f"<style>{CSS}</style></head><body>"
        f'<header><h1>EvalPilot: Asterion FAQ bot evals + AI system audit</h1><div class="sub">run {e(m["run_id"])} | '
        f'provider {e(m["provider"])} | bot {e(m["bot_model"])} | judge {e(m["judge_model"])} | {m["n_cases"]} cases | '
        f'data as of {e(m["as_of"])} | evalpilot {e(m["evalpilot_version"])}</div></header>'
        f"<nav>{nav}</nav><main>{body}</main>"
        f"<script>{JS}</script></body></html>\n"
    )
    return redact(page)
