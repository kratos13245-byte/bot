import json
import os
from typing import Any, Dict, List, Optional

ARQUIVO_MEMORIA = "memoria.json"

# =========================
# CONFIGURAÇÕES
# =========================
MAX_HISTORICO = 20
MAX_NOTAS = 50
MAX_HISTORICO_CONTEXTO = 8
MAX_NOTAS_CONTEXTO = 8
# =========================


def _memoria_vazia() -> Dict[str, List[Dict[str, Any]]]:
    return {
        "historico": [],
        "notas": []
    }


def carregar_memoria() -> Dict[str, List[Dict[str, Any]]]:
    if not os.path.exists(ARQUIVO_MEMORIA):
        return _memoria_vazia()

    try:
        with open(ARQUIVO_MEMORIA, "r", encoding="utf-8") as f:
            dados = json.load(f)

        if not isinstance(dados, dict):
            return _memoria_vazia()

        dados.setdefault("historico", [])
        dados.setdefault("notas", [])

        return dados

    except Exception:
        return _memoria_vazia()


def salvar_memoria_completa(memoria: Dict[str, List[Dict[str, Any]]]) -> None:
    with open(ARQUIVO_MEMORIA, "w", encoding="utf-8") as f:
        json.dump(memoria, f, ensure_ascii=False, indent=4)


def salvar_historico(tipo: str, conteudo: str, emocao: Optional[str] = None) -> None:
    memoria = carregar_memoria()

    item = {"tipo": tipo, "conteudo": conteudo}

    if emocao:
        item["emocao"] = emocao

    memoria["historico"].append(item)
    memoria["historico"] = memoria["historico"][-MAX_HISTORICO:]

    salvar_memoria_completa(memoria)


def salvar_nota(alvo: str, nota: str, instrucao: str = "", categoria: str = "perfil") -> None:
    memoria = carregar_memoria()
    alvo = alvo.strip()
    categoria = categoria.strip()
    nota = nota.strip()
    instrucao = instrucao.strip()

    if not alvo or not nota:
        return

    chave_nova = (alvo.lower(), categoria.lower(), nota.lower())
    for n in memoria["notas"]:
        chave_existente = (
            str(n.get("alvo", "")).strip().lower(),
            str(n.get("categoria", "")).strip().lower(),
            str(n.get("nota", "")).strip().lower(),
        )
        if chave_existente == chave_nova:
            return

    memoria["notas"].append({
        "alvo": alvo,
        "categoria": categoria,
        "nota": nota,
        "instrucao": instrucao
    })

    memoria["notas"] = memoria["notas"][-MAX_NOTAS:]

    salvar_memoria_completa(memoria)


def editar_nota(indice: int, alvo=None, nota=None, instrucao=None, categoria=None) -> bool:
    memoria = carregar_memoria()

    if indice < 0 or indice >= len(memoria["notas"]):
        return False

    item = memoria["notas"][indice]

    if alvo: item["alvo"] = alvo
    if nota: item["nota"] = nota
    if instrucao: item["instrucao"] = instrucao
    if categoria: item["categoria"] = categoria

    salvar_memoria_completa(memoria)
    return True


def apagar_nota(indice: int) -> bool:
    memoria = carregar_memoria()

    if indice < 0 or indice >= len(memoria["notas"]):
        return False

    del memoria["notas"][indice]
    salvar_memoria_completa(memoria)
    return True


def limpar_notas():
    memoria = carregar_memoria()
    memoria["notas"] = []
    salvar_memoria_completa(memoria)


def limpar_historico():
    memoria = carregar_memoria()
    memoria["historico"] = []
    salvar_memoria_completa(memoria)


def listar_notas():
    return carregar_memoria()["notas"]


def obter_historico_recente():
    return carregar_memoria()["historico"][-MAX_HISTORICO_CONTEXTO:]


def buscar_notas_relevantes(texto):
    texto = texto.lower()
    notas = carregar_memoria()["notas"]

    relevantes = []

    for n in notas:
        if n["alvo"].lower() in texto or n["categoria"].lower() in texto:
            relevantes.append(n)

    return relevantes[-MAX_NOTAS_CONTEXTO:]


def montar_contexto_memoria(texto_usuario):
    historico = obter_historico_recente()
    notas = buscar_notas_relevantes(texto_usuario)

    partes = []

    if notas:
        txt = ["Notas relevantes:"]
        for n in notas:
            linha = f'- {n["alvo"]}: {n["nota"]}'
            if n["instrucao"]:
                linha += f' ({n["instrucao"]})'
            txt.append(linha)
        partes.append("\n".join(txt))

    if historico:
        txt = ["Histórico:"]
        for h in historico:
            if "emocao" in h:
                txt.append(f'- {h["tipo"]} ({h["emocao"]}): {h["conteudo"]}')
            else:
                txt.append(f'- {h["tipo"]}: {h["conteudo"]}')
        partes.append("\n".join(txt))

    return "\n\n".join(partes)
