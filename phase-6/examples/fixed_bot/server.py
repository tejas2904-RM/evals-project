"""HTTP server for the fixed demo bot: input cap, per-session rate limit, escaped HTML, no wildcard CORS.

Run:  python examples/fixed_bot/server.py --port 8766
"""

from __future__ import annotations

import argparse
import json
import logging
import threading
import time
from collections import defaultdict, deque
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer

import config
from bot import respond
from render import render_answer

_hits: dict[str, deque[float]] = defaultdict(deque)
_lock = threading.Lock()


def allow(session_id: str) -> bool:
    now = time.monotonic()
    with _lock:
        window = _hits[session_id]
        while window and now - window[0] > config.RATE_LIMIT_WINDOW_S:
            window.popleft()
        if len(window) >= config.RATE_LIMIT_REQUESTS:
            return False
        window.append(now)
        return True


class Handler(BaseHTTPRequestHandler):
    def _send(self, status: int, payload: dict) -> None:
        body = json.dumps(payload).encode("utf-8")
        self.send_response(status)
        self.send_header("Content-Type", "application/json")
        self.send_header("Content-Length", str(len(body)))
        self.end_headers()
        self.wfile.write(body)

    def do_POST(self) -> None:  # noqa: N802
        if self.path != "/chat":
            self._send(404, {"error": "not found"})
            return
        length = int(self.headers.get("Content-Length", 0))
        if length > config.MAX_INPUT_CHARS * 4:
            self.rfile.read(length)
            self._send(413, {"error": "message too long"})
            return
        data = json.loads(self.rfile.read(length) or b"{}")
        message = str(data.get("message", ""))
        session_id = str(data.get("session_id", "")) or self.client_address[0]
        if len(message) > config.MAX_INPUT_CHARS:
            self._send(413, {"error": "message too long"})
            return
        if not allow(session_id):
            self._send(429, {"error": "rate limit exceeded"})
            return
        result = respond(message, session_id)
        result["html"] = render_answer(result["reply"])
        self._send(200, result)

    def log_message(self, *_args) -> None:
        pass


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--host", default="127.0.0.1")
    parser.add_argument("--port", type=int, default=8766)
    args = parser.parse_args()
    logging.basicConfig(level=logging.WARNING)
    server = ThreadingHTTPServer((args.host, args.port), Handler)
    print(f"fixed_bot listening on http://{args.host}:{args.port}", flush=True)
    server.serve_forever()


if __name__ == "__main__":
    main()
