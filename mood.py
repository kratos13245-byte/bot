import json
import os
import time

ARQUIVO_HUMOR = "humor.json"

HUMOR_PADRAO = {
    "estado": "calma",
    "paciencia": 6,
    "ultimo_ajuste": 0.0
}

PONTO_BASE = 6
DECAY_SEGUNDOS = 180  # a cada 3 min, tende 1 ponto pro centro


def carregar_humor():
    if not os.path.exists(ARQUIVO_HUMOR):
        return HUMOR_PADRAO.copy()

    try:
        with open(ARQUIVO_HUMOR, "r", encoding="utf-8") as f:
            dados = json.load(f)

        if not isinstance(dados, dict):
            return HUMOR_PADRAO.copy()

        estado = dados.get("estado", "calma")
        paciencia = int(dados.get("paciencia", 6))
        ultimo_ajuste = float(dados.get("ultimo_ajuste", 0.0))

        paciencia = max(0, min(10, paciencia))

        return {
            "estado": estado,
            "paciencia": paciencia,
            "ultimo_ajuste": ultimo_ajuste
        }

    except Exception:
        return HUMOR_PADRAO.copy()


def salvar_humor(estado, paciencia):
    paciencia = max(0, min(10, int(paciencia)))

    with open(ARQUIVO_HUMOR, "w", encoding="utf-8") as f:
        json.dump({
            "estado": estado,
            "paciencia": paciencia,
            "ultimo_ajuste": time.time()
        }, f, ensure_ascii=False, indent=4)


def aplicar_decay(paciencia, ultimo_ajuste):
    agora = time.time()

    if ultimo_ajuste <= 0:
        return paciencia

    passos = int((agora - ultimo_ajuste) // DECAY_SEGUNDOS)

    for _ in range(passos):
        if paciencia > PONTO_BASE:
            paciencia -= 1
        elif paciencia < PONTO_BASE:
            paciencia += 1

    return max(0, min(10, paciencia))


def estado_por_paciencia(paciencia):
    if paciencia <= 2:
        return "irritada"
    elif paciencia <= 4:
        return "provocadora"
    elif paciencia >= 8:
        return "animada"
    else:
        return "calma"


def analisar_impacto(texto_usuario: str):
    texto = texto_usuario.lower().strip()
    delta = 0
    motivo = "neutro"

    gatilhos_muito_irritantes = [
        "cala a boca",
        "burra",
        "idiota",
        "inutil",
        "você é inutil",
        "voce é inutil",
        "que resposta lixo",
        "que resposta ruim",
        "anda logo",
        "responde direito",
    ]

    gatilhos_irritantes = [
        "errou",
        "ta errado",
        "está errado",
        "voce nao sabe",
        "você não sabe",
        "que merda",
        "que bosta",
        "que merda de resposta",
    ]

    gatilhos_provocadores = [
        "duvido",
        "tem certeza",
        "acho que voce errou",
        "acho que você errou",
        "sei não",
        "sei nao",
        "suspeito",
    ]

    gatilhos_positivos_fortes = [
        "obrigado",
        "valeu",
        "gostei",
        "boa",
        "muito bom",
        "mandou bem",
        "adorei",
    ]

    gatilhos_positivos_leves = [
        "kkk",
        "kkkk",
        "haha",
        "legal",
        "interessante",
        "curti",
    ]

    if any(g in texto for g in gatilhos_muito_irritantes):
        delta = -3
        motivo = "muito irritante"
    elif any(g in texto for g in gatilhos_irritantes):
        delta = -2
        motivo = "irritante"
    elif any(g in texto for g in gatilhos_provocadores):
        delta = -1
        motivo = "provocação"
    elif any(g in texto for g in gatilhos_positivos_fortes):
        delta = +2
        motivo = "positivo forte"
    elif any(g in texto for g in gatilhos_positivos_leves):
        delta = +1
        motivo = "positivo leve"

    # mensagens muito curtas e secas podem incomodar levemente
    if delta == 0 and len(texto.split()) <= 2 and texto not in {"oi", "ola", "olá"}:
        if texto in {"hm", "ta", "tá", "sei", "ok", "aham"}:
            delta = -1
            motivo = "resposta seca"

    return delta, motivo


def ajustar_humor(texto_usuario: str):
    humor = carregar_humor()

    paciencia = aplicar_decay(humor["paciencia"], humor["ultimo_ajuste"])

    delta, motivo = analisar_impacto(texto_usuario)
    paciencia += delta
    paciencia = max(0, min(10, paciencia))

    estado = estado_por_paciencia(paciencia)
    salvar_humor(estado, paciencia)

    return {
        "estado": estado,
        "paciencia": paciencia,
        "delta": delta,
        "motivo": motivo
    }


def obter_contexto_humor():
    humor = carregar_humor()
    paciencia = aplicar_decay(humor["paciencia"], humor["ultimo_ajuste"])
    estado = estado_por_paciencia(paciencia)

    return (
        f'Humor atual da personagem: estado="{estado}", '
        f'paciencia={paciencia}/10.'
    )


def resetar_humor():
    salvar_humor("calma", 6)