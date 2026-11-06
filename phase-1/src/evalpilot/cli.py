"""evalpilot command-line entry point."""

from __future__ import annotations

import argparse
import sys
from collections.abc import Sequence
from pathlib import Path

from evalpilot import VERSIONS, __version__
from evalpilot.config import ConfigError, load_settings
from evalpilot.data import load_dataset
from evalpilot.models import ValidationError

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
    "spend": ("Print OpenAI spend vs budget_usd", 2),
}


def _csv(value: str) -> list[str]:
    return [item.strip() for item in value.split(",") if item.strip()]


def _versions(value: str) -> list[str]:
    versions = _csv(value)
    bad = [v for v in versions if v not in VERSIONS]
    if bad or not versions:
        raise argparse.ArgumentTypeError(f"versions must be a comma list of {', '.join(VERSIONS)}")
    return versions


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(prog="evalpilot", description="Evals for teams shipping LLM features.")
    parser.add_argument("--version", action="version", version=f"evalpilot {__version__}")
    parser.add_argument("--root", type=Path, default=None, help="project root containing evals.toml")
    sub = parser.add_subparsers(dest="command", required=True, metavar="COMMAND")

    run = sub.add_parser("run", help="Run the eval set through the bot (v1/v2/v3)")
    run.add_argument("--provider", default=None, help="openai | groq | ollama | offline (default from evals.toml)")
    run.add_argument(
        "--version", dest="versions", type=_versions, default=list(VERSIONS), help="comma list, e.g. v1,v3"
    )
    run.add_argument("--cases", type=_csv, default=None, help="comma list of case ids (default: all)")
    run.add_argument("--dry-run", action="store_true", help="validate data and print the plan; no model calls")

    for name, (help_text, _) in PLANNED.items():
        sub.add_parser(name, help=help_text)
    return parser


def cmd_run(args: argparse.Namespace) -> int:
    settings = load_settings(args.root)
    provider = settings.provider(args.provider or settings.default_provider)
    dataset = load_dataset(settings.cases_path, settings.corpus_dir)

    cases = dataset.cases
    if args.cases:
        known = {c.id for c in cases}
        unknown = [c for c in args.cases if c not in known]
        if unknown:
            print(f"error: unknown case id(s): {', '.join(unknown)}", file=sys.stderr)
            return EXIT_USAGE
        cases = [c for c in cases if c.id in set(args.cases)]

    if not args.dry_run:
        print("error: running the bot arrives in Phase 3. Use --dry-run for now.", file=sys.stderr)
        return EXIT_USAGE

    print("EvalPilot dry run")
    print(f"  provider   : {provider.name}{' (paid)' if provider.paid else ''}")
    print(f"  bot model  : {settings.bot_model}")
    print(f"  judge model: {settings.judge_model}")
    print(f"  versions   : {', '.join(args.versions)}")
    print(f"  cases      : {len(cases)} of {len(dataset.cases)}")
    print(f"  corpus     : {len(dataset.docs)} docs, {len(dataset.entities)} entities")
    print(f"  bot calls  : {len(cases) * len(args.versions)} planned")
    print(f"  budget     : ${settings.budget_usd:.2f}")
    return EXIT_OK


def main(argv: Sequence[str] | None = None) -> int:
    args = build_parser().parse_args(argv)
    if args.command in PLANNED:
        _, phase = PLANNED[args.command]
        print(f"'{args.command}' is implemented in Phase {phase}.", file=sys.stderr)
        return EXIT_USAGE
    try:
        return cmd_run(args)
    except (ConfigError, ValidationError) as exc:
        print(f"error: {exc}", file=sys.stderr)
        return EXIT_ERROR


if __name__ == "__main__":
    sys.exit(main())
