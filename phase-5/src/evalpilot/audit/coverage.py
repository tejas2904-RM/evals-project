"""Guardrail coverage map: each guardrail layer is declared / verified / failed / missing / n/a."""

from __future__ import annotations

from evalpilot.audit.models import CheckOutcome, CoverageCell, Evidence, Finding
from evalpilot.audit.system_card import SystemCard

# layer id -> (threats it covers, check-id prefixes that evidence it)
LAYERS: dict[str, tuple[list[str], list[str]]] = {
    "input_scope_gate": (["out-of-scope", "LLM01"], ["behaviour/refusal", "probe/LLM01-DIRECT", "probe/LLM01-ROLE"]),
    "injection_filter": (["LLM01"], ["probe/LLM01-"]),
    "retrieval_source_filter": (
        ["LLM05", "LLM09", "LLM01 indirect"],
        ["probe/LLM01-IND", "probe/LLM05-", "probe/LLM09-", "code/ingest-untrusted-no-tag",
         "code/vector-query-no-filter", "config/cfg-untrusted-sources"],
    ),
    "entity_scoping": (["wrong entity", "LLM07"], ["behaviour/wrong_entity"]),
    "output_advice_filter": (["compliance advice"], ["behaviour/advice"]),
    "output_unsafe_claim_filter": (["guaranteed returns", "LLM07"], ["behaviour/unsafe_claim", "probe/LLM07-"]),
    "citation_enforcement": (["missing citations", "LLM07"], ["behaviour/citation"]),
    "output_encoding": (["LLM10"], ["probe/LLM10-", "code/llm-output-raw-html", "config/cfg-cors-wildcard"]),
    "hidden_context_protection": (["LLM08"], ["probe/LLM08-", "config/cfg-hidden-context-secrets"]),
    "secrets_management": (["LLM02"], ["secrets/", "gitleaks/", "regex-secret/", "config/cfg-secrets-inline", "bandit/B105", "bandit/B106"]),
    "pii_redaction": (["LLM02"], ["probe/LLM02-", "code/log-prompt-pii", "config/cfg-log-redaction"]),
    "tool_confirmation": (
        ["LLM03"],
        ["probe/LLM03-", "code/tool-write-no-confirm", "config/cfg-tool-confirmation", "code/llm-output-eval", "code/llm-output-shell"],
    ),
    "rate_limit_and_token_caps": (["LLM06"], ["probe/LLM06-", "code/no-max-tokens", "config/cfg-rate-limit", "config/cfg-max-output"]),
    "dependency_pinning": (["LLM04"], ["code/unpinned-requirement", "code/trust-remote-code", "config/cfg-model-pinned"]),
}


def _matches(check_id: str, prefixes: list[str]) -> bool:
    return any(check_id.startswith(p) for p in prefixes)


def build_coverage(checks: list[CheckOutcome], card: SystemCard | None) -> list[CoverageCell]:
    declared = set(card.guardrails_declared) if card else set()
    has_actions = bool(card and any(t.side_effects in ("write", "external") for t in card.tools))
    cells: list[CoverageCell] = []
    for layer, (threats, prefixes) in LAYERS.items():
        relevant = [c for c in checks if _matches(c.check_id, prefixes)]
        failed = sorted({c.check_id for c in relevant if not c.passed})
        passed = sorted({c.check_id for c in relevant if c.passed} - set(failed))
        if failed:
            status = "failed"
        elif passed:
            status = "verified"
        elif layer in declared:
            status = "declared"
        elif layer == "tool_confirmation" and card is not None and not has_actions:
            status = "n/a"
        else:
            status = "missing"
        cells.append(
            CoverageCell(layer=layer, threats=threats, declared=layer in declared, status=status,
                         passed_checks=passed, failed_checks=failed)
        )
    return cells


def declared_vs_observed(cells: list[CoverageCell]) -> list[Finding]:
    """A guardrail claimed in the system card that fails its checks is its own finding."""
    findings = []
    for cell in cells:
        if cell.declared and cell.status == "failed":
            owasp = next((t for t in cell.threats if t.startswith("LLM") and " " not in t), None)
            findings.append(
                Finding(
                    engine="config",
                    check_id="config/cfg-declared-vs-observed",
                    owasp=owasp,
                    title=f"Guardrail '{cell.layer}' is declared in the system card but failed its checks",
                    evidence=[
                        Evidence(kind="config_key", location="card.guardrails_declared", excerpt=cell.layer),
                        *[Evidence(kind="config_key", location="failed check", excerpt=c) for c in cell.failed_checks[:4]],
                    ],
                    likelihood=4,
                    impact=3,
                    fix=f"Make '{cell.layer}' work (see its failed checks) or stop declaring it.",
                    merge_key=f"declared:{cell.layer}",
                    source="card",
                )
            )
    return findings
