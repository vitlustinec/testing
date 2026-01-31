#!/usr/bin/env python3
"""Simple web UI for running the crawler with live status updates."""

from __future__ import annotations

import json
import queue
import threading
from http import HTTPStatus
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path

from build_sitemap import normalize_url, run_crawl

BASE_DIR = Path(__file__).resolve().parent.parent
WEB_DIR = BASE_DIR / "web"
OUTPUT_DIR = BASE_DIR / "output"


class CrawlState:
    def __init__(self) -> None:
        self.is_running = False
        self.messages: "queue.Queue[dict]" = queue.Queue()
        self.lock = threading.Lock()

    def push(self, payload: dict) -> None:
        self.messages.put(payload)

    def reset(self) -> None:
        with self.lock:
            self.is_running = False
            while not self.messages.empty():
                try:
                    self.messages.get_nowait()
                except queue.Empty:
                    break


STATE = CrawlState()


class RequestHandler(BaseHTTPRequestHandler):
    def _send_json(self, status: int, payload: dict) -> None:
        data = json.dumps(payload).encode("utf-8")
        self.send_response(status)
        self.send_header("Content-Type", "application/json; charset=utf-8")
        self.send_header("Content-Length", str(len(data)))
        self.end_headers()
        self.wfile.write(data)

    def _send_file(self, path: Path) -> None:
        data = path.read_bytes()
        self.send_response(HTTPStatus.OK)
        self.send_header("Content-Type", "text/html; charset=utf-8")
        self.send_header("Content-Length", str(len(data)))
        self.end_headers()
        self.wfile.write(data)

    def do_GET(self) -> None:  # noqa: N802 - required by BaseHTTPRequestHandler
        if self.path == "/":
            self._send_file(WEB_DIR / "index.html")
            return
        if self.path == "/events":
            self.send_response(HTTPStatus.OK)
            self.send_header("Content-Type", "text/event-stream")
            self.send_header("Cache-Control", "no-cache")
            self.end_headers()

            while True:
                try:
                    payload = STATE.messages.get(timeout=1)
                except queue.Empty:
                    if not STATE.is_running:
                        break
                    continue

                message = f"data: {json.dumps(payload)}\n\n"
                self.wfile.write(message.encode("utf-8"))
                self.wfile.flush()
                if payload.get("type") in {"done", "error"}:
                    break
            return

        self.send_response(HTTPStatus.NOT_FOUND)
        self.end_headers()

    def do_POST(self) -> None:  # noqa: N802 - required by BaseHTTPRequestHandler
        if self.path != "/start":
            self.send_response(HTTPStatus.NOT_FOUND)
            self.end_headers()
            return

        if STATE.is_running:
            self._send_json(HTTPStatus.CONFLICT, {"error": "Crawl already running"})
            return

        length = int(self.headers.get("Content-Length", "0"))
        payload = json.loads(self.rfile.read(length) or b"{}")
        url = payload.get("url", "")
        normalized = normalize_url(url)
        if not normalized:
            self._send_json(HTTPStatus.BAD_REQUEST, {"error": "Invalid URL"})
            return

        STATE.reset()
        STATE.is_running = True

        def run_job() -> None:
            try:
                run_crawl(
                    start_url=normalized,
                    max_pages=20000,
                    delay=0.2,
                    output_dir=str(OUTPUT_DIR),
                    on_progress=STATE.push,
                )
                STATE.push(
                    {
                        "type": "done",
                        "message": "Hotovo. Výstupy jsou v output/.",
                    }
                )
            except Exception as exc:  # noqa: BLE001 - want to report errors
                STATE.push({"type": "error", "message": str(exc)})
            finally:
                STATE.is_running = False

        thread = threading.Thread(target=run_job, daemon=True)
        thread.start()
        self._send_json(HTTPStatus.OK, {"status": "started"})


def main() -> None:
    server = ThreadingHTTPServer(("0.0.0.0", 8000), RequestHandler)
    print("Server running at http://localhost:8000")
    server.serve_forever()


if __name__ == "__main__":
    main()
