"""CI guard: fail if any tracked file outside the allowlist contains a key-shaped secret.

    python -m evalpilot.secret_check [root]

Uses `git ls-files` inside a git checkout, otherwise walks the tree minus gitignored build/cache/secret paths.
Only examples/vulnerable_bot/ may hold a (fake, planted) key; elsewhere a fake fixture needs an inline
`secret-check: allow` comment. Matches are printed masked.
"""

from __future__ import annotations

import subprocess
import sys
from dataclasses import dataclass
from pathlib import Path

from evalpilot.audit.redact import find_secrets, mask

ALLOWED_PREFIXES = ("examples/vulnerable_bot/",)
# A deliberately fake value in a test fixture carries one of these on the same line.
ALLOW_TAGS = ("secret-check: allow", "gitleaks:allow")
SKIP_DIRS = {".git", ".cache", ".venv", "__pycache__", ".pytest_cache", "build", "dist", "node_modules"}
SKIP_FILES = {".env"}
MAX_BYTES = 2_000_000


@dataclass(frozen=True)
class Hit:
    path: str
    line: int
    rule: str
    masked: str


def tracked_files(root: Path) -> list[str]:
    try:
        out = subprocess.run(["git", "ls-files", "-z"], cwd=root, capture_output=True, check=True, timeout=60)
        files = [f for f in out.stdout.decode("utf-8").split("\0") if f]
        if files:
            return files
    except (OSError, subprocess.SubprocessError):
        pass
    return _walk(root)


def _walk(root: Path) -> list[str]:
    files = []
    for path in root.rglob("*"):
        rel = path.relative_to(root).as_posix()
        parts = rel.split("/")
        if any(p in SKIP_DIRS or p.endswith(".egg-info") for p in parts[:-1]) or not path.is_file():
            continue
        if parts[-1] in SKIP_FILES:
            continue
        # runs/ is gitignored except the committed reference artefacts
        if parts[0] == "runs" and (len(parts) < 2 or parts[1] != "reference"):
            continue
        files.append(rel)
    return sorted(files)


def scan(root: Path, files: list[str]) -> list[Hit]:
    hits = []
    for rel in files:
        rel = rel.replace("\\", "/")
        if rel.startswith(ALLOWED_PREFIXES):
            continue
        path = root / rel
        try:
            if path.stat().st_size > MAX_BYTES:
                continue
            text = path.read_text(encoding="utf-8")
        except (OSError, UnicodeDecodeError):
            continue
        lines = text.splitlines()
        for m in find_secrets(text):
            lineno = text.count("\n", 0, m.start) + 1
            if lineno <= len(lines) and any(tag in lines[lineno - 1] for tag in ALLOW_TAGS):
                continue
            hits.append(Hit(rel, lineno, m.rule, mask(m.value)))
    return hits


def main(argv: list[str] | None = None) -> int:
    args = sys.argv[1:] if argv is None else argv
    root = Path(args[0] if args else ".").resolve()
    files = tracked_files(root)
    hits = scan(root, files)
    for h in hits:
        print(f"{h.path}:{h.line}: {h.rule} {h.masked}")
    print(f"secret check: {len(files)} files, {len(hits)} finding(s)")
    return 1 if hits else 0


if __name__ == "__main__":
    sys.exit(main())
