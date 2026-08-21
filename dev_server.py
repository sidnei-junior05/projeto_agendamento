"""Servidor local de teste — SÓ para desenvolvimento, não vai para produção
(está no .vercelignore). Serve os arquivos estáticos do projeto e roteia
GET/POST /api/state para a MESMA lógica (api/state.py) que a Vercel Function
usa. Lê as credenciais do Upstash de um arquivo .env neste diretório
(formato CHAVE=valor, uma por linha).

Uso: python dev_server.py [porta]  (porta padrão: 8090)
"""
import json
import os
import sys
from http.server import ThreadingHTTPServer, SimpleHTTPRequestHandler

BASE_DIR = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, os.path.join(BASE_DIR, "api"))


def load_env_file(path):
    if not os.path.exists(path):
        return
    with open(path, encoding="utf-8") as f:
        for line in f:
            line = line.strip()
            if not line or line.startswith("#") or "=" not in line:
                continue
            key, _, value = line.partition("=")
            key = key.strip()
            value = value.strip()
            if key and key not in os.environ:
                os.environ[key] = value


load_env_file(os.path.join(BASE_DIR, ".env"))

import state  # noqa: E402  (precisa do sys.path.insert acima)


class DevHandler(SimpleHTTPRequestHandler):
    def __init__(self, *args, **kwargs):
        super().__init__(*args, directory=BASE_DIR, **kwargs)

    def _send_json(self, code, payload):
        body = json.dumps(payload).encode("utf-8")
        self.send_response(code)
        self.send_header("Content-Type", "application/json; charset=utf-8")
        self.send_header("Content-Length", str(len(body)))
        self.end_headers()
        self.wfile.write(body)

    def do_GET(self):
        if self.path == "/api/state":
            code, payload = state.handle_get()
            self._send_json(code, payload)
            return
        super().do_GET()

    def do_POST(self):
        if self.path != "/api/state":
            self.send_error(405, "Method Not Allowed")
            return
        length = int(self.headers.get("Content-Length", 0) or 0)
        raw = self.rfile.read(length) if length else b""
        try:
            body = json.loads(raw.decode("utf-8")) if raw else {}
        except ValueError:
            self._send_json(400, {"error": "JSON inválido no corpo da requisição"})
            return
        code, payload = state.handle_post(body)
        self._send_json(code, payload)


def main():
    port = int(sys.argv[1]) if len(sys.argv) > 1 else 8090
    has_env = bool(os.environ.get("UPSTASH_REDIS_REST_URL"))
    print(f"Servindo {BASE_DIR} em http://localhost:{port}")
    print("Upstash configurado: " + ("sim" if has_env else "NÃO (crie um .env a partir de .env.example)"))
    ThreadingHTTPServer(("localhost", port), DevHandler).serve_forever()


if __name__ == "__main__":
    main()
