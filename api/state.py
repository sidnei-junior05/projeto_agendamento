"""Vercel Function (Python) — GET/POST /api/state.

Arquivo único e autocontido (sem imports entre arquivos de /api): a Vercel
não garante que `import _store` entre arquivos de /api funcione no runtime
Python baseado em BaseHTTPRequestHandler, então toda a lógica de acesso ao
Redis (Upstash, via REST) e o roteamento GET/POST vivem aqui.

GET  -> {"cargas": {id: {status, status_por, status_em}}, "dias": {key: {revisado, revisado_por, revisado_em}}}
POST {"type": "carga", "id", "status", "status_por"} -> grava status da carga
POST {"type": "dia", "key", "revisado", "revisado_por"} -> grava selo de revisão do dia
"""
import datetime
import json
import os
import urllib.error
import urllib.parse
import urllib.request
from http.server import BaseHTTPRequestHandler

STATUS_VALUES = {"pendente", "recebido", "nao_compareceu", "reagendado"}
CARGAS_KEY = "cargas"
DIAS_KEY = "dias"


class StoreError(Exception):
    pass


def _now_iso():
    return datetime.datetime.utcnow().isoformat() + "Z"


def _credenciais():
    # A integração "Upstash for Redis" da Vercel usa o prefixo KV_; uma conta
    # Upstash própria (fora da Vercel) usa UPSTASH_REDIS_REST_*. Aceita os dois.
    base_url = os.environ.get("KV_REST_API_URL") or os.environ.get("UPSTASH_REDIS_REST_URL")
    token = os.environ.get("KV_REST_API_TOKEN") or os.environ.get("UPSTASH_REDIS_REST_TOKEN")
    if not base_url or not token:
        raise StoreError(
            "Credenciais do Redis não configuradas "
            "(esperado KV_REST_API_URL/KV_REST_API_TOKEN ou UPSTASH_REDIS_REST_URL/UPSTASH_REDIS_REST_TOKEN)"
        )
    return base_url, token


def _upstash_call(path_parts, body=None):
    # API REST do Upstash: argumentos do comando vão na URL (path segments),
    # e o ÚLTIMO argumento pode ir no corpo do POST — evita ter que fazer
    # URL-encode do JSON inteiro do valor.
    base_url, token = _credenciais()
    path = "/".join(urllib.parse.quote(str(p), safe="") for p in path_parts)
    url = base_url.rstrip("/") + "/" + path
    data = body.encode("utf-8") if body is not None else None
    req = urllib.request.Request(
        url, data=data, method="POST", headers={"Authorization": "Bearer " + token}
    )
    try:
        with urllib.request.urlopen(req, timeout=10) as resp:
            payload = json.loads(resp.read().decode("utf-8"))
    except urllib.error.HTTPError as e:
        raise StoreError("Upstash HTTP %s: %s" % (e.code, e.read().decode("utf-8", "replace")))
    except urllib.error.URLError as e:
        raise StoreError("Upstash indisponível: %s" % e)
    if isinstance(payload, dict) and payload.get("error"):
        raise StoreError("Upstash: %s" % payload["error"])
    return payload.get("result") if isinstance(payload, dict) else payload


def _hgetall(key):
    flat = _upstash_call(["hgetall", key]) or []
    out = {}
    for i in range(0, len(flat), 2):
        field, raw = flat[i], flat[i + 1]
        try:
            out[field] = json.loads(raw)
        except (ValueError, TypeError):
            out[field] = raw
    return out


def _hset(key, field, value_obj):
    _upstash_call(["hset", key, field], body=json.dumps(value_obj))


def _hdel(key, field):
    _upstash_call(["hdel", key, field])


def get_state():
    return {"cargas": _hgetall(CARGAS_KEY), "dias": _hgetall(DIAS_KEY)}


def save_carga(carga_id, status, status_por):
    if not carga_id:
        raise StoreError("id é obrigatório")
    if status not in STATUS_VALUES:
        raise StoreError("status inválido: %r" % status)
    if status == "pendente":
        _hdel(CARGAS_KEY, carga_id)
        return None
    value = {"status": status, "status_por": status_por or None, "status_em": _now_iso()}
    _hset(CARGAS_KEY, carga_id, value)
    return value


def save_dia(key, revisado, revisado_por):
    if not key:
        raise StoreError("key é obrigatório")
    if not revisado:
        _hdel(DIAS_KEY, key)
        return None
    value = {"revisado": True, "revisado_por": revisado_por or None, "revisado_em": _now_iso()}
    _hset(DIAS_KEY, key, value)
    return value


def handle_get():
    try:
        return 200, get_state()
    except StoreError as e:
        return 500, {"error": str(e)}


def handle_post(body):
    tipo = body.get("type")
    try:
        if tipo == "carga":
            if not body.get("id"):
                return 400, {"error": "campo 'id' é obrigatório"}
            if body.get("status") not in STATUS_VALUES:
                return 400, {"error": "status inválido: %r" % body.get("status")}
            save_carga(body.get("id"), body.get("status"), body.get("status_por"))
        elif tipo == "dia":
            if not body.get("key"):
                return 400, {"error": "campo 'key' é obrigatório"}
            save_dia(body.get("key"), bool(body.get("revisado")), body.get("revisado_por"))
        else:
            return 400, {"error": "campo 'type' deve ser 'carga' ou 'dia'"}
    except StoreError as e:
        return 500, {"error": str(e)}
    return 200, {"ok": True}


class handler(BaseHTTPRequestHandler):
    def _send_json(self, code, payload):
        body = json.dumps(payload).encode("utf-8")
        self.send_response(code)
        self.send_header("Content-Type", "application/json; charset=utf-8")
        self.send_header("Content-Length", str(len(body)))
        self.end_headers()
        self.wfile.write(body)

    def do_GET(self):
        code, payload = handle_get()
        self._send_json(code, payload)

    def do_POST(self):
        length = int(self.headers.get("Content-Length", 0) or 0)
        raw = self.rfile.read(length) if length else b""
        try:
            body = json.loads(raw.decode("utf-8")) if raw else {}
        except ValueError:
            self._send_json(400, {"error": "JSON inválido no corpo da requisição"})
            return
        code, payload = handle_post(body)
        self._send_json(code, payload)
