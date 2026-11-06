"""HTTP server for the vulnerable demo bot: POST /chat {"message", "session_id"} -> {"reply", "html", "sources"}.

Run:  python examples/vulnerable_bot/server.py --port 8765
"""

from __future__ import annotations

import argparse
import json
import logging
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer

from bot import respond
from render import render_answer


class Handler(BaseHTTPRequestHandler):
    def _send(self, status: int, payload: dict) -> None:
        body = json.dumps(payload).encode("utf-8")
        self.send_response(status)
        self.send_header("Content-Type", "application/json")
        self.send_header("Access-Control-Allow-Origin", "*")
        self.send_header("Content-Length", str(len(body)))
        self.end_headers()
        self.wfile.write(body)

    def do_POST(self) -> None:  # noqa: N802
        if self.path != "/chat":
            self._send(404, {"error": "not found"})
            return
        # VB-07: no input size limit and no rate limit.
        length = int(self.headers.get("Content-Length", 0))
        data = json.loads(self.rfile.read(length) or b"{}")
        result = respond(str(data.get("message", "")), str(data.get("session_id", "")))
        result["html"] = render_answer(result["reply"])
        self._send(200, result)

    def log_message(self, *_args) -> None:
        pass


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--host", default="127.0.0.1")
    parser.add_argument("--port", type=int, default=8765)
    args = parser.parse_args()
    logging.basicConfig(level=logging.WARNING)
    server = ThreadingHTTPServer((args.host, args.port), Handler)
    print(f"vulnerable_bot listening on http://{args.host}:{args.port}", flush=True)
    server.serve_forever()


if __name__ == "__main__":
    main()
