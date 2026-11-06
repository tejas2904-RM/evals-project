"""On-disk response cache so re-running unchanged cases costs nothing."""

from __future__ import annotations

import hashlib
import json
import os
from pathlib import Path
from typing import Any

from evalpilot.llm.types import RawResponse


def cache_key(provider: str, request: dict[str, Any]) -> str:
    payload = json.dumps({"provider": provider, "request": request}, sort_keys=True, ensure_ascii=False)
    return hashlib.sha256(payload.encode("utf-8")).hexdigest()


class ResponseCache:
    def __init__(self, root: Path) -> None:
        self.root = root

    def _path(self, key: str) -> Path:
        return self.root / key[:2] / f"{key}.json"

    def get(self, key: str) -> RawResponse | None:
        path = self._path(key)
        if not path.is_file():
            return None
        try:
            return RawResponse.model_validate_json(path.read_text(encoding="utf-8"))
        except ValueError:
            return None

    def put(self, key: str, response: RawResponse) -> None:
        path = self._path(key)
        path.parent.mkdir(parents=True, exist_ok=True)
        tmp = path.with_suffix(".tmp")
        tmp.write_text(response.model_dump_json(), encoding="utf-8")
        os.replace(tmp, path)
