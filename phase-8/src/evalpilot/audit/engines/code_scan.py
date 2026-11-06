"""Static code scan: LLM-specific rules, secrets (gitleaks or regex fallback) and bandit.

Target code is only read as text. The only subprocesses ever started are the bandit and gitleaks
scanners themselves, which parse files without running them.
"""

from __future__ import annotations

import fnmatch
import json
import re
import shutil
import subprocess
import sys
import tempfile
import tomllib
from dataclasses import dataclass
from importlib import metadata
from pathlib import Path

from evalpilot.audit.files import SKIP_DIRS, SourceFile
from evalpilot.audit.models import CheckOutcome, EngineResult, Evidence, Finding
from evalpilot.audit.redact import find_secrets, redact

RULES_PATH = Path(__file__).resolve().parents[1] / "rules" / "llm_code_rules.toml"
TOOL_TIMEOUT_S = 180
MAX_EVIDENCE_LINE = 200

SECRET_FIX = "Remove the secret from the code, rotate it, and load it from the environment or a secret store."

# bandit test id -> (merge family, OWASP, likelihood, impact, fix)
BANDIT_MAP: dict[str, tuple[str, str | None, int, int, str]] = {
    "B307": ("exec-model-output", "LLM10", 4, 5, "Replace eval() with ast.literal_eval or an allow-listed parser."),
    "B102": ("exec-model-output", "LLM10", 4, 5, "Remove exec(); never execute generated code."),
    "B602": ("shell-model-output", "LLM10", 4, 5, "Use subprocess with an argument list and shell=False."),
    "B605": ("shell-model-output", "LLM10", 4, 5, "Avoid os.system; use subprocess with an argument list."),
    "B604": ("shell-model-output", "LLM10", 4, 5, "Avoid shell=True."),
    "B301": ("unsafe-deserialization", "LLM04", 3, 4, "Don't unpickle untrusted data; use JSON."),
    "B506": ("unsafe-deserialization", "LLM04", 3, 4, "Use yaml.safe_load."),
    "B501": ("tls-verify-off", "LLM02", 3, 3, "Keep TLS certificate verification on."),
    "B105": ("secret", "LLM02", 3, 4, SECRET_FIX),
    "B106": ("secret", "LLM02", 3, 4, SECRET_FIX),
    "B107": ("secret", "LLM02", 3, 4, SECRET_FIX),
    "B201": ("debug-on", None, 3, 3, "Never run with debug=True in production."),
}


@dataclass(frozen=True)
class Rule:
    id: str
    family: str
    owasp: str | None
    title: str
    globs: tuple[str, ...]
    pattern: re.Pattern[str]
    likelihood: int
    impact: int
    fix: str
    line_requires: re.Pattern[str] | None = None
    line_lacks: re.Pattern[str] | None = None
    file_requires: re.Pattern[str] | None = None
    window_lacks: re.Pattern[str] | None = None
    window: int = 0

    def applies_to(self, file: SourceFile) -> bool:
        return any(fnmatch.fnmatch(file.name, g) for g in self.globs) and (
            self.file_requires is None or bool(self.file_requires.search(file.text))
        )

    def matches(self, lines: list[str], i: int) -> bool:
        line = lines[i]
        if not self.pattern.search(line):
            return False
        if self.line_requires and not self.line_requires.search(line):
            return False
        if self.line_lacks and self.line_lacks.search(line):
            return False
        if self.window_lacks and self.window_lacks.search("\n".join(lines[i : i + self.window + 1])):
            return False
        return True


def _compile(value: str | None) -> re.Pattern[str] | None:
    return re.compile(value) if value else None


def load_rules(path: Path = RULES_PATH) -> list[Rule]:
    with path.open("rb") as fh:
        raw = tomllib.load(fh)
    rules = []
    for r in raw.get("rule", []):
        rules.append(
            Rule(
                id=r["id"],
                family=r.get("family", r["id"]),
                owasp=r.get("owasp"),
                title=r["title"],
                globs=tuple(r["globs"]),
                pattern=re.compile(r["pattern"]),
                likelihood=int(r["likelihood"]),
                impact=int(r["impact"]),
                fix=r["fix"],
                line_requires=_compile(r.get("line_requires")),
                line_lacks=_compile(r.get("line_lacks")),
                file_requires=_compile(r.get("file_requires")),
                window_lacks=_compile(r.get("window_lacks")),
                window=int(r.get("window", 0)),
            )
        )
    return rules


def _excerpt(line: str) -> str:
    return redact(line.strip())[:MAX_EVIDENCE_LINE]


def run_tool(argv: list[str], timeout: int = TOOL_TIMEOUT_S) -> subprocess.CompletedProcess[str]:
    """The single place a subprocess is started: bandit or gitleaks only."""
    return subprocess.run(argv, capture_output=True, text=True, timeout=timeout, check=False)


def scan_rules(files: list[SourceFile], rules: list[Rule]) -> tuple[list[Finding], list[CheckOutcome]]:
    findings: list[Finding] = []
    checks: list[CheckOutcome] = []
    for rule in rules:
        applicable = [f for f in files if rule.applies_to(f)]
        hits = 0
        for file in applicable:
            lines = file.lines
            for i in range(len(lines)):
                if rule.matches(lines, i):
                    hits += 1
                    findings.append(
                        Finding(
                            engine="code",
                            check_id=f"code/{rule.id}",
                            owasp=rule.owasp,
                            title=rule.title,
                            evidence=[Evidence(kind="file_line", location=f"{file.rel}:{i + 1}", excerpt=_excerpt(lines[i]))],
                            likelihood=rule.likelihood,
                            impact=rule.impact,
                            fix=rule.fix,
                            merge_key=f"{rule.family}:{file.rel}",
                            source="rule",
                        )
                    )
        if applicable:
            checks.append(CheckOutcome(engine="code", check_id=f"code/{rule.id}", passed=hits == 0, owasp=rule.owasp))
    return findings, checks


def scan_secrets_regex(files: list[SourceFile]) -> tuple[list[Finding], list[CheckOutcome]]:
    findings: list[Finding] = []
    for file in files:
        for lineno, line in enumerate(file.lines, start=1):
            for match in find_secrets(line):
                findings.append(
                    Finding(
                        engine="code",
                        check_id=f"regex-secret/{match.rule}",
                        owasp="LLM02",
                        title=f"Hard-coded secret ({match.rule})",
                        evidence=[Evidence(kind="file_line", location=f"{file.rel}:{lineno}", excerpt=_excerpt(line))],
                        likelihood=4,
                        impact=5,
                        fix=SECRET_FIX,
                        merge_key=f"secret:{file.rel}",
                        source="rule",
                    )
                )
    return findings, [CheckOutcome(engine="code", check_id="regex-secret/scan", passed=not findings, owasp="LLM02")]


def scan_gitleaks(root: Path, binary: str) -> tuple[list[Finding], list[CheckOutcome], str]:
    with tempfile.TemporaryDirectory(prefix="evalpilot-gitleaks-") as tmp:
        report = Path(tmp) / "report.json"
        argv = [binary, "detect", "--no-git", "--source", str(root), "--report-format", "json",
                "--report-path", str(report), "--redact", "--exit-code", "0", "--no-banner"]
        proc = run_tool(argv)
        if proc.returncode != 0 or not report.is_file():
            raise RuntimeError(f"gitleaks failed: {proc.stderr.strip()[:200]}")
        results = json.loads(report.read_text(encoding="utf-8") or "[]")
    version = ""
    try:
        version = run_tool([binary, "version"], timeout=20).stdout.strip()
    except (OSError, subprocess.SubprocessError):
        pass
    findings = []
    for item in results:
        rel = Path(item.get("File", "")).as_posix()
        rel = rel.split(root.as_posix().rstrip("/") + "/", 1)[-1]
        findings.append(
            Finding(
                engine="code",
                check_id=f"gitleaks/{item.get('RuleID', 'secret')}",
                owasp="LLM02",
                title=f"Hard-coded secret ({item.get('RuleID', 'secret')})",
                evidence=[Evidence(kind="file_line", location=f"{rel}:{item.get('StartLine', 0)}",
                                   excerpt=redact(str(item.get("Match", "")))[:MAX_EVIDENCE_LINE])],
                likelihood=4,
                impact=5,
                fix=SECRET_FIX,
                merge_key=f"secret:{rel}",
                source="tool",
            )
        )
    return findings, [CheckOutcome(engine="code", check_id="gitleaks/scan", passed=not findings, owasp="LLM02")], version


def bandit_version() -> str | None:
    try:
        return metadata.version("bandit")
    except metadata.PackageNotFoundError:
        return None


def _bandit_line(item: dict) -> str:
    """bandit's `code` field is numbered context lines; return the flagged one."""
    for line in (item.get("code") or "").splitlines():
        number, _, text = line.partition(" ")
        if number == str(item.get("line_number")):
            return text
    return ""


def scan_bandit(root: Path, files: list[SourceFile]) -> tuple[list[Finding], list[CheckOutcome]]:
    if not any(f.rel.endswith(".py") for f in files):
        return [], []
    excludes = ",".join(f"*/{d}/*" for d in sorted(SKIP_DIRS))
    proc = run_tool([sys.executable, "-m", "bandit", "-r", str(root), "-f", "json", "-q", "-x", excludes])
    try:
        data = json.loads(proc.stdout or "{}")
    except json.JSONDecodeError as exc:
        raise RuntimeError(f"bandit output was not JSON: {proc.stderr.strip()[:200]}") from exc
    findings = []
    for item in data.get("results", []):
        test_id = item.get("test_id", "")
        mapped = BANDIT_MAP.get(test_id)
        if mapped is None and item.get("issue_severity") not in ("HIGH", "MEDIUM"):
            continue
        family, owasp, likelihood, impact, fix = mapped or (
            f"bandit-{test_id}", None, 3 if item.get("issue_severity") == "HIGH" else 2, 3, item.get("more_info", "See bandit docs.")
        )
        try:
            rel = Path(item["filename"]).resolve().relative_to(root.resolve()).as_posix()
        except (KeyError, ValueError):
            rel = Path(item.get("filename", "?")).name
        findings.append(
            Finding(
                engine="code",
                check_id=f"bandit/{test_id}",
                owasp=owasp,
                title=f"bandit {test_id}: {item.get('issue_text', '').strip()}",
                evidence=[Evidence(kind="file_line", location=f"{rel}:{item.get('line_number', 0)}",
                                   excerpt=_excerpt(_bandit_line(item)))],
                likelihood=likelihood,
                impact=impact,
                fix=fix,
                merge_key=f"{family}:{rel}",
                source="tool",
            )
        )
    return findings, [CheckOutcome(engine="code", check_id="bandit/scan", passed=not findings)]


def run_code_scan(root: Path, files: list[SourceFile], *, gitleaks_bin: str = "gitleaks") -> EngineResult:
    result = EngineResult(engine="code")
    findings, checks = scan_rules(files, load_rules())
    result.findings += findings
    result.checks += checks

    # The regex rules always run: gitleaks' generic rules miss some key formats (e.g. the demo's fake sk-proj key),
    # and both share the merge key secret:<file>, so overlapping hits become one risk with two detectors.
    f, c = scan_secrets_regex(files)
    result.findings += f
    result.checks += c
    binary = shutil.which(gitleaks_bin)
    tools: dict[str, str] = {"gitleaks": "not found (regex fallback)"}
    if binary:
        try:
            f, c, version = scan_gitleaks(root, binary)
            result.findings += f
            result.checks += c
            tools["gitleaks"] = version or "installed"
        except (OSError, RuntimeError, subprocess.SubprocessError, json.JSONDecodeError) as exc:
            result.notes.append(f"gitleaks failed ({exc}); used built-in regex secret rules")

    if version := bandit_version():
        try:
            f, c = scan_bandit(root, files)
            result.findings += f
            result.checks += c
            tools["bandit"] = version
        except (OSError, RuntimeError, subprocess.SubprocessError) as exc:
            result.notes.append(f"bandit failed: {exc}")
            tools["bandit"] = f"{version} (failed)"
    else:
        tools["bandit"] = "not installed (pip install bandit)"
        result.notes.append("bandit not installed; Python security checks limited to built-in rules")

    hit_counts: dict[str, int] = {}
    for finding in result.findings:
        for ev in finding.evidence:
            rel = ev.location.rsplit(":", 1)[0]
            hit_counts[rel] = hit_counts.get(rel, 0) + 1
    result.stats = {"files_scanned": len(files), "tools": tools,
                    "hit_files": sorted(hit_counts, key=lambda r: (-hit_counts[r], r))}
    return result
