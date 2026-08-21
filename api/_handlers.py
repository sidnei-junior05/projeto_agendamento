"""Lógica de roteamento de /api/state, independente do servidor HTTP que a
chama (Vercel Function em api/state.py, ou o dev_server.py local). Retorna
(status_code, payload) — quem chama decide como escrever a resposta.
"""
import _store


def handle_get():
    try:
        return 200, _store.get_state()
    except _store.StoreError as e:
        return 500, {"error": str(e)}


def handle_post(body):
    tipo = body.get("type")
    try:
        if tipo == "carga":
            if not body.get("id"):
                return 400, {"error": "campo 'id' é obrigatório"}
            if body.get("status") not in _store.STATUS_VALUES:
                return 400, {"error": "status inválido: %r" % body.get("status")}
            _store.save_carga(body.get("id"), body.get("status"), body.get("status_por"))
        elif tipo == "dia":
            if not body.get("key"):
                return 400, {"error": "campo 'key' é obrigatório"}
            _store.save_dia(body.get("key"), bool(body.get("revisado")), body.get("revisado_por"))
        else:
            return 400, {"error": "campo 'type' deve ser 'carga' ou 'dia'"}
    except _store.StoreError as e:
        return 500, {"error": str(e)}
    return 200, {"ok": True}
