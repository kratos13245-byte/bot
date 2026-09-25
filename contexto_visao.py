import threading
import time

_lock = threading.Lock()
_ultimo_resumo = ""
_ultima_atualizacao = 0.0
_visao_ativa = False


def atualizar_contexto_visao(resumo: str):
    global _ultimo_resumo, _ultima_atualizacao
    resumo = (resumo or "").strip()
    with _lock:
        _ultimo_resumo = resumo
        _ultima_atualizacao = time.time()


def definir_visao_ativa(ativa: bool):
    global _visao_ativa
    with _lock:
        _visao_ativa = bool(ativa)


def limpar_contexto_visao():
    global _ultimo_resumo, _ultima_atualizacao
    with _lock:
        _ultimo_resumo = ""
        _ultima_atualizacao = 0.0


def obter_contexto_visao():
    with _lock:
        return {
            "resumo": _ultimo_resumo,
            "timestamp": _ultima_atualizacao,
            "enabled": _visao_ativa,
        }
