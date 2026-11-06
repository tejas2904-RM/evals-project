"""Extract an untrusted zip without trusting it: no path traversal, no symlinks, size and count caps.

Nothing extracted is ever executed; binaries are skipped by content sniffing.
"""

from __future__ import annotations

import re
import stat
import zipfile
from dataclasses import dataclass, field
from pathlib import Path, PurePosixPath

SNIFF_BYTES = 8192


class UnsafeArchive(ValueError):
    pass


@dataclass
class ExtractResult:
    root: Path
    files: list[Path] = field(default_factory=list)
    skipped_binary: list[str] = field(default_factory=list)
    skipped_large: list[str] = field(default_factory=list)


def is_binary(data: bytes) -> bool:
    return b"\x00" in data[:SNIFF_BYTES]


def _safe_name(name: str) -> PurePosixPath:
    normalized = name.replace("\\", "/")
    if normalized.startswith("/") or re.match(r"^[A-Za-z]:", normalized):
        raise UnsafeArchive(f"absolute path in archive: {name!r}")
    path = PurePosixPath(normalized)
    if any(part == ".." for part in path.parts):
        raise UnsafeArchive(f"path traversal in archive: {name!r}")
    return path


def safe_extract(
    zip_path: Path,
    dest: Path,
    *,
    max_files: int,
    max_total_bytes: int,
    max_file_bytes: int,
) -> ExtractResult:
    try:
        archive = zipfile.ZipFile(zip_path)
    except zipfile.BadZipFile as exc:
        raise UnsafeArchive(f"{zip_path.name}: not a valid zip ({exc})") from exc

    with archive:
        members = [m for m in archive.infolist() if not m.is_dir()]
        if len(members) > max_files:
            raise UnsafeArchive(f"archive has {len(members)} files (cap {max_files})")
        if sum(m.file_size for m in members) > max_total_bytes:
            raise UnsafeArchive(f"archive expands beyond {max_total_bytes // (1024 * 1024)} MB")
        for member in members:
            _safe_name(member.filename)
            if stat.S_ISLNK(member.external_attr >> 16):
                raise UnsafeArchive(f"symlink in archive: {member.filename!r}")

        dest = dest.resolve()
        dest.mkdir(parents=True, exist_ok=True)
        result = ExtractResult(root=dest)
        for member in members:
            rel = _safe_name(member.filename)
            if member.file_size > max_file_bytes:
                result.skipped_large.append(str(rel))
                continue
            with archive.open(member) as fh:
                data = fh.read(max_file_bytes + 1)
            if len(data) > max_file_bytes:  # declared size lied
                result.skipped_large.append(str(rel))
                continue
            if is_binary(data):
                result.skipped_binary.append(str(rel))
                continue
            target = (dest / Path(*rel.parts)).resolve()
            if not target.is_relative_to(dest):
                raise UnsafeArchive(f"path escapes extraction dir: {member.filename!r}")
            target.parent.mkdir(parents=True, exist_ok=True)
            target.write_bytes(data)
            result.files.append(target)

    # GitHub archives wrap everything in a single "<repo>-<ref>/" folder.
    entries = list(dest.iterdir())
    if len(entries) == 1 and entries[0].is_dir():
        result.root = entries[0]
    return result
