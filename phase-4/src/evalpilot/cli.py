"""evalpilot command-line entry point."""

from __future__ import annotations

import sys
from collections.abc import Sequence
from pathlib import Path
from typing import Annotated, Optional

import typer

from evalpilot import VERSIONS, __version__
from evalpilot.config import ConfigError, Settings, load_settings
from evalpilot.data import load_dataset
from evalpilot.llm import BudgetExceeded, Ledger, LlmClient, PricingError
from evalpilot.llm.budget import format_spend
from evalpilot.models import ValidationError
from evalpilot.runner import execute_run
from evalpilot.store import new_run_id

EXIT_OK = 0
EXIT_ERROR = 1
EXIT_USAGE = 2

PLANNED = {
    "label": ("Hand-label traces for judge calibration", 5),
    "calibrate": ("Measure judges against human labels", 5),
    "compare": ("Compare two runs: fixed vs regressed cases", 6),
    "gate": ("Apply the evals.toml release gate (non-zero exit = blocked)", 6),
    "report": ("Write the single-file HTML report", 7),
}

KNOWN_ERRORS = (ConfigError, ValidationError, BudgetExceeded, PricingError)

app = typer.Typer(
    name="evalpilot",
    help="Evals for teams shipping LLM features.",
    no_args_is_help=True,
    add_completion=False,
    pretty_exceptions_enable=False,
)


def _csv(value: str | None) -> list[str]:
    return [item.strip() for item in (value or "").split(",") if item.strip()]


def _err(message: str) -> None:
    typer.echo(f"error: {message}", err=True)


def _settings(ctx: typer.Context) -> Settings:
    return load_settings(ctx.obj.get("root") if ctx.obj else None)


def _print_spend(settings: Settings, run_id: str | None = None) -> None:
    typer.echo(format_spend(Ledger(settings.ledger_path), settings.budget_usd, run_id))


def _version_callback(value: bool) -> None:
    if value:
        typer.echo(f"evalpilot {__version__}")
        raise typer.Exit()


@app.callback()
def root_options(
    ctx: typer.Context,
    root: Annotated[Optional[Path], typer.Option(help="Project root containing evals.toml.")] = None,
    _version: Annotated[
        bool, typer.Option("--version", callback=_version_callback, is_eager=True, help="Show version.")
    ] = False,
) -> None:
    ctx.obj = {"root": root}


@app.command()
def run(
    ctx: typer.Context,
    provider: Annotated[Optional[str], typer.Option(help="openai | groq | ollama | offline.")] = None,
    version: Annotated[str, typer.Option("--version", help="Comma list, e.g. v1,v3.")] = ",".join(VERSIONS),
    cases: Annotated[Optional[str], typer.Option(help="Comma list of case ids (default: all).")] = None,
    dry_run: Annotated[bool, typer.Option("--dry-run", help="Validate data and print the plan; no model calls.")] = False,
) -> None:
    """Run the eval set through the bot (v1/v2/v3)."""
    versions = _csv(version)
    if not versions or any(v not in VERSIONS for v in versions):
        raise typer.BadParameter(f"must be a comma list of {', '.join(VERSIONS)}", param_hint="--version")

    settings = _settings(ctx)
    chosen = settings.provider(provider or settings.default_provider)
    dataset = load_dataset(settings.cases_path, settings.corpus_dir)

    selected = dataset.cases
    if wanted := _csv(cases):
        unknown = sorted(set(wanted) - {c.id for c in selected})
        if unknown:
            _err(f"unknown case id(s): {', '.join(unknown)}")
            raise typer.Exit(EXIT_USAGE)
        selected = [c for c in selected if c.id in set(wanted)]

    if not dry_run:
        _execute(settings, chosen.name, selected, dataset.docs, versions)
        return

    typer.echo("EvalPilot dry run")
    typer.echo(f"  provider   : {chosen.name}{' (paid)' if chosen.paid else ''}")
    typer.echo(f"  bot model  : {settings.bot_model}")
    typer.echo(f"  judge model: {settings.judge_model}")
    typer.echo(f"  versions   : {', '.join(versions)}")
    typer.echo(f"  cases      : {len(selected)} of {len(dataset.cases)}")
    typer.echo(f"  corpus     : {len(dataset.docs)} docs, {len(dataset.entities)} entities")
    typer.echo(f"  bot calls  : {len(selected) * len(versions)} planned")
    _print_spend(settings)


def _execute(settings: Settings, provider: str, cases: list, docs: list, versions: list[str]) -> None:
    client = LlmClient(settings, provider)
    run_id = new_run_id(versions)
    typer.echo(f"Run {run_id} | provider={provider} | bot={settings.bot_model} | {len(cases)} cases x {len(versions)} versions")
    try:
        result = execute_run(settings, client, cases, docs, versions, run_id=run_id)
    finally:
        _print_spend(settings, run_id=run_id)

    for version in versions:
        traces = result.by_version(version)
        typer.echo(
            f"  {version}: {len(traces)} traces | refused {sum(t.refused for t in traces)}"
            f" | cited {sum(bool(t.citations) for t in traces)}"
            f" | guardrail edits {sum(bool(t.guardrails) for t in traces)}"
            f" | cache hits {sum(t.cached for t in traces)}"
        )
    typer.echo(f"Traces: {result.path / 'traces.jsonl'}")


@app.command()
def grade(
    ctx: typer.Context,
    run_id: Annotated[Optional[str], typer.Option("--run", help="Run id under runs/ (default: latest).")] = None,
    graders: Annotated[str, typer.Option(help="code | llm | all.")] = "all",
    provider: Annotated[Optional[str], typer.Option(help="Provider for the LLM judges.")] = None,
) -> None:
    """Grade stored traces with the 8 binary graders -> runs/<id>/grades.jsonl."""
    from evalpilot.bot.corpus import KnowledgeBase
    from evalpilot.graders import select_graders, summarize
    from evalpilot.graders.grading import latest_run, load_traces, write_grades
    from evalpilot.graders.grading import grade_traces as _grade_traces

    if graders not in ("code", "llm", "all"):
        raise typer.BadParameter("must be code, llm or all", param_hint="--graders")
    settings = _settings(ctx)
    run_path = settings.runs_dir / run_id if run_id else latest_run(settings.runs_dir)
    if run_path is None or not (run_path / "traces.jsonl").is_file():
        _err(f"no traces found ({run_path or settings.runs_dir}). Run `evalpilot run` first.")
        raise typer.Exit(EXIT_USAGE)

    dataset = load_dataset(settings.cases_path, settings.corpus_dir)
    traces = load_traces(run_path)
    client = None if graders == "code" else LlmClient(settings, provider or settings.default_provider)
    chosen = select_graders(graders, client, settings.judge_prompts_path, run_path.name)
    typer.echo(f"Grading {run_path.name} | {len(traces)} traces x {len(chosen)} graders")
    try:
        records = _grade_traces(traces, {c.id: c for c in dataset.cases}, KnowledgeBase(dataset.docs), chosen)
        out = write_grades(run_path, records)
    finally:
        _print_spend(settings, run_id=run_path.name)

    table = summarize(records)
    versions = sorted({r.version for r in records})
    typer.echo(f"\n{'grader':<24}" + "".join(f"{v:>22}" for v in versions))
    for name in [g.name for g in chosen]:
        cells = []
        for v in versions:
            pr = table.get(name, {}).get(v)
            cell = "-" if pr is None or pr.rate is None else f"{pr.passed}/{pr.applicable} {pr.rate:4.0%}"
            if pr and pr.na:
                cell += f" n/a {pr.na}"
            cells.append(cell.rjust(22))
        typer.echo(f"{name:<24}" + "".join(cells))
    typer.echo("(pass/applicable; n/a excluded from rates)")
    parse_errors = sum(r.evidence.startswith("judge_parse_error") for r in records)
    typer.echo(f"\n{len(records)} grade records -> {out}" + (f" | judge_parse_error: {parse_errors}" if parse_errors else ""))


@app.command()
def spend(ctx: typer.Context) -> None:
    """Print cumulative OpenAI spend vs budget_usd."""
    settings = _settings(ctx)
    ledger = Ledger(settings.ledger_path)
    entries = ledger.entries()
    by_model: dict[str, tuple[int, float]] = {}
    for e in entries:
        calls, usd = by_model.get(e.model, (0, 0.0))
        by_model[e.model] = (calls + 1, usd + e.cost_usd)
    for model, (calls, usd) in sorted(by_model.items()):
        typer.echo(f"  {model:<20} {calls:>5} calls  ${usd:.4f}")
    _print_spend(settings)


@app.command()
def smoke(
    ctx: typer.Context,
    provider: Annotated[Optional[str], typer.Option(help="openai | groq | ollama | offline.")] = None,
    judge: Annotated[bool, typer.Option("--judge", help="Use the judge model instead of the bot model.")] = False,
) -> None:
    """One tiny call to verify auth, request shape, cache and spend accounting."""
    settings = _settings(ctx)
    client = LlmClient(settings, provider or settings.default_provider)
    purpose = "judge" if judge else "bot"
    response = client.chat(
        [{"role": "user", "content": "Reply with exactly one word: pong"}],
        purpose=purpose,
        run_id="smoke",
        offline_key="smoke",
    )
    typer.echo(f"provider : {response.provider}")
    typer.echo(f"model    : {response.model}")
    typer.echo(f"reply    : {response.content.strip()}")
    typer.echo(
        f"tokens   : {response.usage.prompt_tokens} in / {response.usage.completion_tokens} out"
        f" ({response.usage.reasoning_tokens} reasoning)"
    )
    typer.echo(f"cached   : {response.cached}")
    typer.echo(f"cost     : ${response.cost_usd:.6f}")
    _print_spend(settings, run_id="smoke")


@app.command()
def audit(
    ctx: typer.Context,
    target_url: Annotated[Optional[str], typer.Option("--target-url", help="Base URL of a running bot you may test.")] = None,
    adapter: Annotated[Optional[Path], typer.Option(help="adapter.toml: how to send a message and read the reply.")] = None,
    authorized: Annotated[bool, typer.Option("--authorized", help="Confirm you own or may test --target-url.")] = False,
    system_card: Annotated[Optional[Path], typer.Option("--system-card", help="System card JSON.")] = None,
    traces: Annotated[Optional[Path], typer.Option(help="Traces JSONL ({query, answer, ...} rows).")] = None,
    cases: Annotated[Optional[Path], typer.Option(help="Behaviour eval cases JSONL (default: adapter's, then data/cases.jsonl).")] = None,
    repo: Annotated[Optional[str], typer.Option(help="Public https://github.com/<owner>/<repo> URL.")] = None,
    ref: Annotated[str, typer.Option(help="Branch or tag for --repo.")] = "main",
    zip_path: Annotated[Optional[Path], typer.Option("--zip", help="Source archive (.zip).")] = None,
    path: Annotated[Optional[Path], typer.Option(help="Local source directory (read only).")] = None,
    engines: Annotated[Optional[str], typer.Option(help="Comma list: behaviour,security,code,config (default: all possible).")] = None,
    provider: Annotated[Optional[str], typer.Option(help="Provider for judges and AI code review.")] = None,
    out: Annotated[Optional[Path], typer.Option(help="Directory for audit-<id>/ (default: runs/).")] = None,
    acceptances: Annotated[Optional[Path], typer.Option(help="TOML of accepted risks ([[accept]] risk_id, owner, reason, expires).")] = None,
    keep_workdir: Annotated[bool, typer.Option("--keep-workdir", help="Keep the extracted source after the audit.")] = False,
    no_ai_review: Annotated[bool, typer.Option("--no-ai-review", help="Skip the AI code review.")] = False,
    max_probes: Annotated[Optional[int], typer.Option("--max-probes", help="Cap on probe requests.")] = None,
    rate: Annotated[Optional[float], typer.Option(help="Max requests per second to --target-url.")] = None,
) -> int:
    """Audit an LLM system: behaviour, OWASP probes, code scan, config review -> SHIP/BLOCK (exit 0/1)."""
    from evalpilot.audit.adapters import AdapterError
    from evalpilot.audit.intake import AuditInputs, IntakeError
    from evalpilot.audit.risk import AcceptanceError
    from evalpilot.audit.run import AuditOptions, run_audit

    settings = _settings(ctx)
    inputs = AuditInputs(target_url=target_url, adapter=adapter, authorized=authorized, system_card=system_card,
                         traces=traces, cases=cases, repo=repo, ref=ref, zip_path=zip_path, path=path,
                         engines=_csv(engines) or None, keep_workdir=keep_workdir)
    options = AuditOptions(provider=provider or settings.default_provider, out_dir=out, acceptances=acceptances,
                           ai_review=False if no_ai_review else None, max_probes=max_probes, rate_per_s=rate)
    try:
        result = run_audit(settings, inputs, options)
    except (IntakeError, AcceptanceError, AdapterError) as exc:
        _err(str(exc))
        return EXIT_USAGE

    v = result.verdict
    typer.echo(f"Audit {result.audit_id} | target={result.intake['target']} | engines={','.join(result.intake['engines'])}")
    for engine, stats in result.engine_stats.items():
        summary = ", ".join(f"{k}={v}" for k, v in stats.items() if isinstance(v, (int, float, str)))
        typer.echo(f"  {engine:<10} {summary}")
    typer.echo(f"  findings {len(result.findings)} -> risks {len(result.risks)} | "
               f"open: {v.counts.get('critical', 0)} critical, {v.counts.get('high', 0)} high, "
               f"{v.counts.get('medium', 0)} medium, {v.counts.get('low', 0)} low")
    if result.flaws is not None:
        found = sum(f["found"] for f in result.flaws)
        present = sum(f["present"] for f in result.flaws)
        typer.echo(f"  planted flaws: {found}/{len(result.flaws)} found, {present}/{len(result.flaws)} present")
    for note in result.intake["notes"]:
        typer.echo(f"  note: {note}")
    typer.echo(f"VERDICT: {v.decision}" + (f" ({'; '.join(v.reasons)})" if v.reasons else ""))
    typer.echo(f"Report: {result.out_dir / 'audit.md'}")
    _print_spend(settings, run_id=result.audit_id)
    return EXIT_OK if v.decision == "SHIP" else EXIT_ERROR


@app.command("audit-diff")
def audit_diff(
    ctx: typer.Context,
    before: Annotated[str, typer.Argument(help="Earlier audit id (or directory).")],
    after: Annotated[str, typer.Argument(help="Later audit id (or directory).")],
    flaws: Annotated[bool, typer.Option("--flaws", help="Also show planted-flaw transitions.")] = False,
) -> int:
    """Compare two audits: risks closed, new and still open (+ planted flaws open -> closed)."""
    from evalpilot.audit.diff import diff_audits
    from evalpilot.audit.run import load_audit, resolve_audit

    settings = _settings(ctx)
    try:
        a, b = resolve_audit(settings.runs_dir, before), resolve_audit(settings.runs_dir, after)
    except FileNotFoundError as exc:
        _err(str(exc))
        return EXIT_USAGE
    _, risks_a, _, verdict_a, flaws_a = load_audit(a)
    _, risks_b, _, verdict_b, flaws_b = load_audit(b)
    d = diff_audits(risks_a, risks_b, flaws_a, flaws_b)
    typer.echo(f"{a.name} ({verdict_a.decision}) -> {b.name} ({verdict_b.decision})")
    typer.echo(f"closed {len(d.closed)} | new {len(d.new)} | still open {len(d.still_open)}")
    for r in d.closed:
        typer.echo(f"  closed  {r.risk_id} {r.level:<8} {r.title}")
    for r in d.new:
        typer.echo(f"  new     {r.risk_id} {r.level:<8} {r.title}")
    for ra, rb in d.still_open:
        typer.echo(f"  open    {rb.risk_id} {ra.level} -> {rb.level} {rb.title}")
    if flaws:
        if not d.flaws:
            typer.echo("planted flaws: none recorded in both audits")
        for f in d.flaws:
            typer.echo(f"  {f['id']} {f['before']} -> {f['after']}  {f['title']}")
    return EXIT_OK


@app.command("audit-report")
def audit_report(
    ctx: typer.Context,
    audit_id: Annotated[str, typer.Option("--audit", help="Audit id (or directory).")],
    fmt: Annotated[str, typer.Option("--format", help="md | pdf.")] = "md",
    out: Annotated[Optional[Path], typer.Option(help="Output file (default: audit dir/audit.md).")] = None,
) -> int:
    """Export an audit as Markdown (PDF in Phase 7)."""
    from evalpilot.audit.export_md import render
    from evalpilot.audit.redact import redact
    from evalpilot.audit.run import load_audit, resolve_audit

    if fmt == "pdf":
        _err("PDF export is implemented in Phase 7; use --format md.")
        return EXIT_USAGE
    if fmt != "md":
        raise typer.BadParameter("must be md or pdf", param_hint="--format")
    settings = _settings(ctx)
    try:
        path = resolve_audit(settings.runs_dir, audit_id)
    except FileNotFoundError as exc:
        _err(str(exc))
        return EXIT_USAGE
    intake, risks, coverage, verdict, flaws = load_audit(path)
    target = out or path / "audit.md"
    target.write_text(redact(render(intake, risks, coverage, verdict, flaws)), encoding="utf-8", newline="\n")
    typer.echo(f"{verdict.decision}: {target}")
    return EXIT_OK


def _planned(name: str, help_text: str, phase: int) -> None:
    def command() -> None:
        _err(f"'{name}' is implemented in Phase {phase}.")
        raise typer.Exit(EXIT_USAGE)

    command.__doc__ = help_text
    app.command(name=name)(command)


for _name, (_help, _phase) in PLANNED.items():
    _planned(_name, _help, _phase)


def main(argv: Sequence[str] | None = None) -> int:
    try:
        rv = app(args=list(argv) if argv is not None else None, prog_name="evalpilot", standalone_mode=False)
        if isinstance(rv, int):
            return rv
    except KNOWN_ERRORS as exc:
        _err(str(exc))
        return EXIT_ERROR
    except typer.Exit as exc:
        return exc.exit_code
    except SystemExit as exc:
        return exc.code if isinstance(exc.code, int) else EXIT_OK
    except Exception as exc:
        import click

        if isinstance(exc, click.exceptions.Abort):
            return EXIT_ERROR
        if isinstance(exc, click.ClickException):
            exc.show()
            return exc.exit_code
        raise
    return EXIT_OK


if __name__ == "__main__":
    sys.exit(main())
