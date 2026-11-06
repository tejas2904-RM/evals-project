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
    "grade": ("Grade traces with the 8 binary graders", 4),
    "label": ("Hand-label traces for judge calibration", 5),
    "calibrate": ("Measure judges against human labels", 5),
    "compare": ("Compare two runs: fixed vs regressed cases", 6),
    "gate": ("Apply the evals.toml release gate (non-zero exit = blocked)", 6),
    "report": ("Write the single-file HTML report", 7),
    "audit": ("Audit an LLM system: behaviour, OWASP probes, code scan, config review", 4),
    "audit-diff": ("Compare two audits: risks opened vs closed", 4),
    "audit-report": ("Export an audit as Markdown (PDF in Phase 7)", 4),
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
