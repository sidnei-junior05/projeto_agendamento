"""Vercel Function (Python) — GET/POST /api/state.

GET  -> {"cargas": {id: {status, status_por, status_em}}, "dias": {key: {revisado, revisado_por, revisado_em}}}
POST {"type": "carga", "id", "status", "status_por"} -> grava status da carga
POST {"type": "dia", "key", "revisado", "revisado_por"} -> grava selo de revisão do dia
"""
import json
from http.server import BaseHTTPRequestHandler

import _handlers


class handler(BaseHTTPRequestHandler):
    def _send_json(self, code, payload):
        body = json.dumps(payload).encode("utf-8")
        self.send_response(code)
        self.send_header("Content-Type", "application/json; charset=utf-8")
        self.send_header("Content-Length", str(len(body)))
        self.end_headers()
        self.wfile.write(body)

    def do_GET(self):
        code, payload = _handlers.handle_get()
        self._send_json(code, payload)

    def do_POST(self):
        length = int(self.headers.get("Content-Length", 0) or 0)
        raw = self.rfile.read(length) if length else b""
        try:
            body = json.loads(raw.decode("utf-8")) if raw else {}
        except ValueError:
            self._send_json(400, {"error": "JSON inválido no corpo da requisição"})
            return
        code, payload = _handlers.handle_post(body)
        self._send_json(code, payload)
