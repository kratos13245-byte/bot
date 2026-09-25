import threading
import time

_lock = threading.Lock()
_ultimo_resumo = ""
_ultima_atualizacao = 0.0


def atualizar_contexto_minecraft(resumo: str):
    global _ultimo_resumo, _ultima_atualizacao
    resumo = (resumo or "").strip()
    with _lock:
        _ultimo_resumo = resumo
        _ultima_atualizacao = time.time()


def limpar_contexto_minecraft():
    global _ultimo_resumo, _ultima_atualizacao
    with _lock:
        _ultimo_resumo = ""
        _ultima_atualizacao = 0.0


def obter_contexto_minecraft():
    with _lock:
        return {
            "resumo": _ultimo_resumo,
            "timestamp": _ultima_atualizacao,
        }
