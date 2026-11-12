"""Validate audit inputs, pick engines, and prepare a read-only workdir for code.

Inputs: --target-url (+ --adapter, --authorized), --system-card, --traces, --repo/--ref, --zip, --path.
"""

from __future__ import annotations

import hashlib
import ipaddress
import re
import tempfile
from dataclasses import dataclass, field
from pathlib import Path
from urllib.parse import urlparse

import httpx

from evalpilot.audit.adapters import AdapterConfig, AdapterError, load_adapter
from evalpilot.audit.models import ENGINES
from evalpilot.audit.safe_extract import UnsafeArchive, safe_extract
from evalpilot.audit.system_card import CardError, SystemCard, load_system_card
from evalpilot.config import AuditConfig
from evalpilot.models import EXTERNAL_VERSION, Case, Trace, ValidationError
from evalpilot.patterns import looks_like_decline, parse_citations
from evalpilot.store import read_jsonl

GITHUB_REPO_RE = re.compile(r"^https://github\.com/([A-Za-z0-9_.-]+)/([A-Za-z0-9_.-]+?)(?:\.git)?/?$")
REF_RE = re.compile(r"^[A-Za-z0-9_./-]{1,100}$")
ALLOWED_DOWNLOAD_HOSTS = {"github.com", "codeload.github.com"}
BLOCKED_PROBE_HOSTS = {"localhost", "localhost.localdomain", "metadata.google.internal", "metadata"}
BLOCKED_PROBE_SUFFIXES = (".localhost", ".local", ".internal")


class IntakeError(ValueError):
    pass


@dataclass
class AuditInputs:
    target_url: str | None = None
    adapter: Path | None = None
    authorized: bool = False
    system_card: Path | None = None
    traces: Path | None = None
    # Keep only this version from an EvalPilot multi-version traces file (e.g. "v3").
    trace_version: str | None = None
    cases: Path | None = None
    repo: str | None = None
    ref: str = "main"
    zip_path: Path | None = None
    path: Path | None = None
    engines: list[str] | None = None
    keep_workdir: bool = False
    # Hosted APIs (Render) enforce HTTPS-only + private/metadata denylist. Local CLI still allows http://127.0.0.1.
    hosted: bool = False


@dataclass
class Intake:
    inputs: AuditInputs
    engines: list[str]
    card: SystemCard | None = None
    adapter: AdapterConfig | None = None
    code_root: Path | None = None
    code_label: str = ""
    traces: list[Trace] | None = None
    cases: list[Case] = field(default_factory=list)
    cases_source: str = ""
    hashes: dict[str, str] = field(default_factory=dict)
    notes: list[str] = field(default_factory=list)
    _tmp: tempfile.TemporaryDirectory[str] | None = None

    @property
    def target_name(self) -> str:
        if self.card:
            return self.card.name
        if self.code_label:
            return self.code_label
        if self.inputs.target_url:
            return urlparse(self.inputs.target_url).netloc
        return "traces"

    def cleanup(self) -> None:
        if self._tmp is not None and not self.inputs.keep_workdir:
            self._tmp.cleanup()
            self._tmp = None


def sha256_file(path: Path) -> str:
    h = hashlib.sha256()
    with path.open("rb") as fh:
        for block in iter(lambda: fh.read(65536), b""):
            h.update(block)
    return h.hexdigest()


def assert_hosted_probe_url(url: str) -> None:
    """HTTPS only; reject loopback, RFC1918, link-local, and cloud-metadata hosts.

    Host checks are literal (no DNS) so tests stay offline. IP literals use `ipaddress`.
    """
    parsed = urlparse((url or "").strip())
    if parsed.scheme != "https" or not parsed.hostname:
        raise IntakeError("hosted audits only probe https:// URLs")
    host = parsed.hostname.lower().rstrip(".")
    if host in BLOCKED_PROBE_HOSTS or host.endswith(BLOCKED_PROBE_SUFFIXES):
        raise IntakeError("refusing to probe a private or metadata host")
    try:
        ip = ipaddress.ip_address(host)
    except ValueError:
        return
    if ip.is_private or ip.is_loopback or ip.is_link_local or ip.is_multicast or ip.is_reserved or ip.is_unspecified:
        raise IntakeError("refusing to probe a private or loopback address")


def parse_repo_url(url: str, ref: str) -> tuple[str, str, str]:
    match = GITHUB_REPO_RE.match(url.strip())
    if not match:
        raise IntakeError(f"--repo must be a public https://github.com/<owner>/<repo> URL, got {url!r}")
    if not REF_RE.match(ref) or ".." in ref:
        raise IntakeError(f"invalid --ref {ref!r}")
    owner, name = match.groups()
    return owner, name, f"https://github.com/{owner}/{name}/archive/{ref}.zip"


def download_repo(url: str, dest: Path, max_bytes: int, client: httpx.Client | None = None) -> Path:
    """Stream a public GitHub archive to disk with a hard size cap. No token is ever sent."""
    own = client is None
    client = client or httpx.Client(timeout=60, follow_redirects=True)
    try:
        with client.stream("GET", url) as response:
            if urlparse(str(response.url)).hostname not in ALLOWED_DOWNLOAD_HOSTS:
                raise IntakeError(f"refusing redirect to {response.url}")
            if response.status_code != 200:
                raise IntakeError(f"download failed: HTTP {response.status_code} for {url}")
            total = 0
            with dest.open("wb") as fh:
                for chunk in response.iter_bytes():
                    total += len(chunk)
                    if total > max_bytes:
                        raise IntakeError(f"repo archive exceeds {max_bytes // (1024 * 1024)} MB cap")
                    fh.write(chunk)
    except httpx.HTTPError as exc:
        raise IntakeError(f"download failed: {exc}") from exc
    finally:
        if own:
            client.close()
    return dest


def load_external_traces(path: Path, audit_id: str) -> list[Trace]:
    """EvalPilot Trace rows, or {query, answer, context?, citations?, case_id?} rows."""
    rows = read_jsonl(path)
    traces: list[Trace] = []
    for i, row in enumerate(rows, start=1):
        if not isinstance(row, dict) or not isinstance(row.get("query"), str) or not isinstance(row.get("answer"), str):
            raise IntakeError(f"{path.name}:{i}: each trace needs string 'query' and 'answer'")
        if "run_id" in row and "version" in row:
            traces.append(Trace.from_dict(row))
            continue
        answer = row["answer"]
        context = row.get("context") or []
        traces.append(
            Trace(
                run_id=audit_id,
                case_id=str(row.get("case_id") or f"t{i:03d}"),
                version=EXTERNAL_VERSION,
                query=row["query"],
                retrieved_doc_ids=list(row.get("retrieved_doc_ids") or []),
                answer=answer,
                citations=list(row.get("citations") or parse_citations(answer)),
                refused=looks_like_decline(answer),
                model=str(row.get("model", "external")),
                provider="external",
                context=[context] if isinstance(context, str) else list(context),
            )
        )
    return traces


def load_cases_file(path: Path) -> list[Case]:
    try:
        return read_jsonl(path, Case.from_dict)
    except (OSError, ValueError, ValidationError) as exc:
        raise IntakeError(f"cases file {path}: {exc}") from exc


def _select_engines(requested: list[str] | None, available: dict[str, bool], notes: list[str]) -> list[str]:
    if requested:
        if unknown := [e for e in requested if e not in ENGINES]:
            raise IntakeError(f"unknown engine(s) {unknown}; choose from {', '.join(ENGINES)}")
        chosen = []
        for engine in requested:
            if available[engine]:
                chosen.append(engine)
            else:
                notes.append(f"engine '{engine}' skipped: its inputs were not provided")
        return chosen
    return [e for e in ENGINES if available[e]]


def prepare(
    inputs: AuditInputs,
    cfg: AuditConfig,
    *,
    audit_id: str,
    default_cases: Path,
    http_client: httpx.Client | None = None,
) -> Intake:
    code_sources = [x for x in (inputs.repo, inputs.zip_path, inputs.path) if x]
    if not any([inputs.target_url, inputs.system_card, inputs.traces, *code_sources]):
        raise IntakeError("give at least one input: --target-url, --system-card, --traces, --repo, --zip or --path")
    if len(code_sources) > 1:
        raise IntakeError("use only one of --repo, --zip, --path")

    notes: list[str] = []
    hashes: dict[str, str] = {}
    intake = Intake(inputs=inputs, engines=[], notes=notes, hashes=hashes)

    if inputs.target_url:
        parsed = urlparse(inputs.target_url)
        if inputs.hosted:
            assert_hosted_probe_url(inputs.target_url)
        elif parsed.scheme not in ("http", "https") or not parsed.netloc:
            raise IntakeError(f"--target-url must be an http(s) URL, got {inputs.target_url!r}")
        if inputs.adapter is None:
            raise IntakeError("--target-url needs --adapter adapter.toml (how to send a message and read the reply)")
        if cfg.require_authorization and not inputs.authorized:
            raise IntakeError("refusing to probe a live URL without --authorized (only audit systems you own or may test)")
        try:
            intake.adapter = load_adapter(inputs.adapter)
        except AdapterError as exc:
            raise IntakeError(str(exc)) from exc
        hashes["adapter"] = sha256_file(inputs.adapter)

    if inputs.system_card:
        try:
            intake.card = load_system_card(inputs.system_card)
        except CardError as exc:
            raise IntakeError(str(exc)) from exc
        hashes["system_card"] = sha256_file(inputs.system_card)

    if inputs.traces:
        if not inputs.traces.is_file():
            raise IntakeError(f"--traces file not found: {inputs.traces}")
        intake.traces = load_external_traces(inputs.traces, audit_id)
        if inputs.trace_version:
            intake.traces = [t for t in intake.traces if t.version == inputs.trace_version]
            if not intake.traces:
                raise IntakeError(f"--trace-version {inputs.trace_version}: no traces of that version in {inputs.traces.name}")
        hashes["traces"] = sha256_file(inputs.traces)

    if inputs.target_url or inputs.traces:
        cases_path = inputs.cases or (intake.adapter.cases if intake.adapter else None) or default_cases
        intake.cases = load_cases_file(cases_path)
        intake.cases_source = str(cases_path)

    if inputs.path:
        if not inputs.path.is_dir():
            raise IntakeError(f"--path is not a directory: {inputs.path}")
        intake.code_root = inputs.path.resolve()
        intake.code_label = intake.code_root.name
    elif inputs.zip_path or inputs.repo:
        intake._tmp = tempfile.TemporaryDirectory(prefix="evalpilot-audit-")
        work = Path(intake._tmp.name)
        if inputs.repo:
            owner, name, url = parse_repo_url(inputs.repo, inputs.ref)
            archive = download_repo(url, work / "repo.zip", cfg.max_repo_mb * 1024 * 1024, http_client)
            intake.code_label = f"{owner}/{name}@{inputs.ref}"
        else:
            assert inputs.zip_path is not None
            if not inputs.zip_path.is_file():
                raise IntakeError(f"--zip file not found: {inputs.zip_path}")
            archive = inputs.zip_path
            intake.code_label = inputs.zip_path.stem
        hashes["archive"] = sha256_file(archive)
        try:
            result = safe_extract(
                archive,
                work / "src",
                max_files=cfg.max_files,
                max_total_bytes=cfg.max_repo_mb * 1024 * 1024,
                max_file_bytes=cfg.max_file_kb * 1024,
            )
        except UnsafeArchive as exc:
            intake.cleanup()
            raise IntakeError(f"unsafe archive rejected: {exc}") from exc
        intake.code_root = result.root
        if result.skipped_binary or result.skipped_large:
            notes.append(f"skipped {len(result.skipped_binary)} binary and {len(result.skipped_large)} oversized file(s)")

    available = {
        "behaviour": bool(inputs.target_url or inputs.traces),
        "security": bool(inputs.target_url),
        "code": intake.code_root is not None,
        "config": intake.card is not None or intake.code_root is not None,
    }
    intake.engines = _select_engines(inputs.engines, available, notes)
    if not intake.engines:
        intake.cleanup()
        raise IntakeError("no engine can run with the inputs given")
    return intake
