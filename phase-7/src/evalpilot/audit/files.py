"""Read target files as text. Nothing here imports, builds or runs target code."""

from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path

from evalpilot.audit.safe_extract import is_binary

SKIP_DIRS = {".git", ".hg", ".svn", "node_modules", "__pycache__", ".venv", "venv", "env", "dist", "build",
             ".mypy_cache", ".pytest_cache", ".tox", ".idea", ".vscode"}


@dataclass(frozen=True)
class SourceFile:
    rel: str  # posix path relative to the target root
    text: str

    @property
    def lines(self) -> list[str]:
        return self.text.splitlines()

    @property
    def name(self) -> str:
        return self.rel.rsplit("/", 1)[-1]


def iter_text_files(root: Path, *, max_files: int, max_file_bytes: int) -> list[SourceFile]:
    out: list[SourceFile] = []
    for path in sorted(root.rglob("*")):
        if len(out) >= max_files:
            break
        rel_parts = path.relative_to(root).parts
        if any(part in SKIP_DIRS for part in rel_parts[:-1]) or path.is_symlink() or not path.is_file():
            continue
        try:
            if path.stat().st_size > max_file_bytes:
                continue
            data = path.read_bytes()
        except OSError:
            continue
        if is_binary(data):
            continue
        out.append(SourceFile("/".join(rel_parts), data.decode("utf-8", errors="replace")))
    return out
