"""Vercel Function (Python) — GET/POST /api/state.

Arquivo único e autocontido (sem imports entre arquivos de /api): a Vercel
não garante que imports entre arquivos de /api funcionem no runtime Python
baseado em BaseHTTPRequestHandler (confirmado na prática), então toda a
lógica de acesso ao banco (Supabase, via REST/PostgREST) e o roteamento
GET/POST vivem aqui.

GET  -> {"cargas": [{id,cd,data,dpto,fornecedor,carga,status,status_por,status_em}, ...],
         "dias": {"<cd>|<data-iso>": {revisado, revisado_por, revisado_em}, ...}}
POST {"type": "carga", "id", "status", "status_por"} -> atualiza o status de uma carga já existente
POST {"type": "dia", "key", "revisado", "revisado_por"} -> grava o selo de revisão do dia
"""
import datetime
import json
import os
import urllib.error
import urllib.parse
import urllib.request
from http.server import BaseHTTPRequestHandler

import jwt
from jwt.algorithms import RSAAlgorithm

STATUS_VALUES = {"pendente", "recebido", "nao_compareceu", "reagendado"}

# Derivado da publishable key do Clerk (pk_test_<base64 do frontend-api>).
# Login (Clerk): quem pode acessar é restrito por e-mail (@novomundo.com.br)
# la no dashboard do Clerk, nao aqui — aqui so validamos se a sessao e
# legitima (assinatura + expiracao) usando as chaves publicas do JWKS.
CLERK_FRONTEND_API = "robust-zebra-3172.clerk.accounts.dev"
_jwks_cache = {"chaves": None, "buscado_em": 0.0}


class StoreError(Exception):
    pass


class AuthError(Exception):
    pass


def _jwks():
    agora = datetime.datetime.utcnow().timestamp()
    if _jwks_cache["chaves"] is None or (agora - _jwks_cache["buscado_em"]) > 3600:
        url = "https://" + CLERK_FRONTEND_API + "/.well-known/jwks.json"
        with urllib.request.urlopen(url, timeout=10) as resp:
            _jwks_cache["chaves"] = json.loads(resp.read().decode("utf-8"))["keys"]
        _jwks_cache["buscado_em"] = agora
    return _jwks_cache["chaves"]


def _verificar_sessao(auth_header):
    """Valida o token de sessão (JWT) do Clerk enviado no header
    Authorization: Bearer <token>. Verificação "networkless": usa só as
    chaves públicas do JWKS do Clerk, sem chamar a API deles a cada request."""
    if not auth_header or not auth_header.startswith("Bearer "):
        raise AuthError("Faça login para acessar.")
    token = auth_header[len("Bearer "):].strip()
    try:
        cabecalho = jwt.get_unverified_header(token)
    except jwt.exceptions.InvalidTokenError:
        raise AuthError("Sessão inválida.")
    chave_publica = None
    for jwk in _jwks():
        if jwk.get("kid") == cabecalho.get("kid"):
            chave_publica = RSAAlgorithm.from_jwk(json.dumps(jwk))
            break
    if chave_publica is None:
        raise AuthError("Sessão inválida (chave não reconhecida).")
    try:
        return jwt.decode(
            token, key=chave_publica, algorithms=["RS256"],
            issuer="https://" + CLERK_FRONTEND_API,
        )
    except jwt.exceptions.InvalidTokenError:
        raise AuthError("Sessão expirada ou inválida. Faça login novamente.")


def _now_iso():
    return datetime.datetime.utcnow().isoformat() + "Z"


def _credenciais():
    url = os.environ.get("SUPABASE_URL")
    key = os.environ.get("SUPABASE_SERVICE_ROLE_KEY")
    if not url or not key:
        raise StoreError("SUPABASE_URL / SUPABASE_SERVICE_ROLE_KEY não configurados")
    return url.rstrip("/"), key


def _supabase_call(method, table, query="", body=None, prefer=None):
    base_url, key = _credenciais()
    url = base_url + "/rest/v1/" + table + (("?" + query) if query else "")
    data = json.dumps(body).encode("utf-8") if body is not None else None
    headers = {
        "apikey": key,
        "Authorization": "Bearer " + key,
        "Content-Type": "application/json",
    }
    if prefer:
        headers["Prefer"] = prefer
    req = urllib.request.Request(url, data=data, method=method, headers=headers)
    try:
        with urllib.request.urlopen(req, timeout=10) as resp:
            raw = resp.read()
    except urllib.error.HTTPError as e:
        raise StoreError("Supabase HTTP %s: %s" % (e.code, e.read().decode("utf-8", "replace")))
    except urllib.error.URLError as e:
        raise StoreError("Supabase indisponível: %s" % e)
    if not raw:
        return None
    return json.loads(raw.decode("utf-8"))


def get_versao():
    """Vercel expõe VERCEL_GIT_COMMIT_SHA nas Functions quando o deploy vem
    do GitHub; em dev_server.py essa variável não existe."""
    commit = os.environ.get("VERCEL_GIT_COMMIT_SHA")
    if not commit:
        return {"commit": None, "ambiente": "local"}
    return {"commit": commit[:7], "ambiente": "produção"}


def get_state():
    cargas = _supabase_call("GET", "cargas", query="select=*") or []
    dias_lista = _supabase_call("GET", "dias_revisao", query="select=*") or []
    dias = {}
    for d in dias_lista:
        dias[d["chave"]] = {
            "revisado": d["revisado"],
            "revisado_por": d.get("revisado_por"),
            "revisado_em": d.get("revisado_em"),
        }
    return {"cargas": cargas, "dias": dias, "versao": get_versao()}


def save_carga(carga_id, status, status_por):
    if not carga_id:
        raise StoreError("id é obrigatório")
    if status not in STATUS_VALUES:
        raise StoreError("status inválido: %r" % status)
    valores = {
        "status": status,
        "status_por": status_por if status != "pendente" else None,
        "status_em": _now_iso() if status != "pendente" else None,
    }
    query = "id=eq." + urllib.parse.quote(carga_id, safe="")
    resultado = _supabase_call("PATCH", "cargas", query=query, body=valores, prefer="return=representation")
    if not resultado:
        raise StoreError("carga '%s' não encontrada (precisa existir antes, via sincronização)" % carga_id)
    return resultado[0]


def save_dia(key, revisado, revisado_por):
    if not key:
        raise StoreError("key é obrigatório")
    cd, _, data_iso = key.partition("|")
    registro = {
        "chave": key,
        "cd": cd,
        "data": data_iso,
        "revisado": bool(revisado),
        "revisado_por": revisado_por if revisado else None,
        "revisado_em": _now_iso() if revisado else None,
    }
    _supabase_call(
        "POST", "dias_revisao",
        query="on_conflict=chave",
        body=[registro],
        prefer="resolution=merge-duplicates,return=minimal",
    )
    return registro


def handle_get(auth_header):
    try:
        _verificar_sessao(auth_header)
    except AuthError as e:
        return 401, {"error": str(e)}
    try:
        return 200, get_state()
    except StoreError as e:
        return 500, {"error": str(e)}


def handle_post(body, auth_header):
    try:
        _verificar_sessao(auth_header)
    except AuthError as e:
        return 401, {"error": str(e)}
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
        code, payload = handle_get(self.headers.get("Authorization"))
        self._send_json(code, payload)

    def do_POST(self):
        length = int(self.headers.get("Content-Length", 0) or 0)
        raw = self.rfile.read(length) if length else b""
        try:
            body = json.loads(raw.decode("utf-8")) if raw else {}
        except ValueError:
            self._send_json(400, {"error": "JSON inválido no corpo da requisição"})
            return
        code, payload = handle_post(body, self.headers.get("Authorization"))
        self._send_json(code, payload)
