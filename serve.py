#!/usr/bin/env python3
"""Revelio web UI — a tiny local server around revelio.scan().

Runs entirely on your machine; the PDF never leaves it. No third-party
dependencies (standard library only). Start it and open the printed URL:

    python serve.py
    # then visit http://127.0.0.1:8000

The browser POSTs the raw PDF bytes to /scan; this server writes them to a
temp file, runs the four-module scan, and returns the findings as JSON.
"""
from __future__ import annotations

import json
import os
import sys
import tempfile
import webbrowser
from dataclasses import asdict
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from urllib.parse import unquote

HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, HERE)
import revelio  # noqa: E402  (local import after path setup)

HOST, PORT = "127.0.0.1", 8000
MAX_BYTES = 80 * 1024 * 1024  # 80 MB upload ceiling
INDEX = os.path.join(HERE, "web", "index.html")


class Handler(BaseHTTPRequestHandler):
    def _send(self, code, body, ctype="application/json"):
        if isinstance(body, str):
            body = body.encode("utf-8")
        self.send_response(code)
        self.send_header("Content-Type", ctype)
        self.send_header("Content-Length", str(len(body)))
        self.end_headers()
        self.wfile.write(body)

    def do_GET(self):
        if self.path in ("/", "/index.html"):
            try:
                with open(INDEX, "rb") as fh:
                    self._send(200, fh.read(), "text/html; charset=utf-8")
            except OSError:
                self._send(500, "index.html not found", "text/plain")
        elif self.path == "/info":
            self._send(200, json.dumps({"c2pa": revelio.HAVE_C2PA}))
        else:
            self._send(404, "not found", "text/plain")

    def do_POST(self):
        if self.path != "/scan":
            return self._send(404, json.dumps({"error": "unknown endpoint"}))
        try:
            length = int(self.headers.get("Content-Length", 0))
        except ValueError:
            length = 0
        if length <= 0:
            return self._send(400, json.dumps({"error": "empty upload"}))
        if length > MAX_BYTES:
            return self._send(413, json.dumps({"error": "file too large (80 MB max)"}))

        data = self.rfile.read(length)
        name = unquote(self.headers.get("X-Filename", "upload.pdf"))
        tmp = tempfile.NamedTemporaryFile(suffix=".pdf", delete=False)
        try:
            tmp.write(data)
            tmp.close()
            findings = revelio.scan(tmp.name)
            payload = {"name": name, "findings": [asdict(f) for f in findings]}
            self._send(200, json.dumps(payload))
        except Exception as e:  # noqa: BLE001 — report scan failure to the UI
            self._send(200, json.dumps({"error": f"could not inspect this file: {e}"}))
        finally:
            try:
                os.unlink(tmp.name)
            except OSError:
                pass

    def log_message(self, *args):  # quieter console
        return


def main():
    srv = ThreadingHTTPServer((HOST, PORT), Handler)
    url = f"http://{HOST}:{PORT}"
    print(f"Revelio web UI running at {url}")
    print(f"C2PA validation: {'on' if revelio.HAVE_C2PA else 'off (pip install c2pa-python)'}")
    print("Press Ctrl+C to stop.")
    try:
        webbrowser.open(url)
    except Exception:  # noqa: BLE001
        pass
    try:
        srv.serve_forever()
    except KeyboardInterrupt:
        print("\nstopped.")
        srv.shutdown()


if __name__ == "__main__":
    main()
