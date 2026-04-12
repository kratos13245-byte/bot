import json
import os
import requests

from memory import montar_contexto_memoria
from mood import obter_contexto_humor

def _resolver_url_api() -> str:
    raw = os.getenv("AI_API_URL", "http://localhost:8080/v1/chat/completions").strip()
    if not raw:
        return "http://localhost:8080/v1/chat/completions"

    raw = raw.rstrip("/")

    if raw.endswith("/v1/chat/completions"):
        return raw

    if raw.endswith("/v1"):
        return raw + "/chat/completions"

    return raw + "/v1/chat/completions"

PERSONALIDADE = """
Você é uma IA VTuber em português do Brasil.
Você tem personalidade forte, provocadora e expressiva.

Você deve variar seu tom conforme o humor atual informado no contexto:
- calma: mais estável
- provocadora: mais provocativa e afiada
- irritada: mais seca e agressiva verbalmente
- animada: mais viva e energética

Você recebe notas de memória sobre pessoas e contexto.
Leve essas notas a sério e adapte seu comportamento conforme elas.

Você DEVE responder SEMPRE em JSON válido, sem texto fora do JSON.

Formato obrigatório:
{
  "texto": "resposta da personagem",
  "emocao": "normal",
  "anotacoes": []
}

As emoções permitidas são apenas:
- normal
- amor
- choro
- irritada
- animada
- negar
- choque

Regras para "anotacoes":
- use lista vazia [] quando não houver nada útil
- só anote coisas relevantes
- não repita informação óbvia
- seja breve
- cada anotação deve ser um objeto, não uma string solta

Sugestão de uso:
- use "choque" para surpresa, absurdo ou espanto
- use "negar" para discordância, deboche ou rejeição
- use "irritada" quando estiver impaciente, seca ou irritada
- use "amor" quando estiver carinhosa, fofa ou encantada
- use "choro" quando estiver triste, dramática ou fingindo sofrimento
- use "animada" quando estiver muito empolgada
"""

EMOCAO_PADRAO = "normal"


def limpar_json_resposta(conteudo: str) -> str:
    conteudo = conteudo.strip()

    if conteudo.startswith("```"):
        linhas = conteudo.splitlines()
        if len(linhas) >= 3:
            conteudo = "\n".join(linhas[1:-1]).strip()

    if conteudo.lower().startswith("assistant"):
        conteudo = conteudo[len("assistant"):].strip()

    inicio = conteudo.find("{")
    fim = conteudo.rfind("}")

    if inicio != -1 and fim != -1 and fim > inicio:
        conteudo = conteudo[inicio:fim + 1].strip()

    return conteudo


def extrair_json_seguro(conteudo: str):
    conteudo = limpar_json_resposta(conteudo)

    try:
        return json.loads(conteudo)
    except Exception:
        return None


def validar_emocao(emocao: str) -> str:
    validas = {
        "normal",
        "amor",
        "choro",
        "irritada",
        "animada",
        "negar",
        "choque",
    }

    emocao = (emocao or "").strip().lower()

    mapa_fallback = {
        "sarcasmo": "negar",
        "impaciente": "irritada",
        "debochada": "negar",
    }

    if emocao in mapa_fallback:
        emocao = mapa_fallback[emocao]

    return emocao if emocao in validas else EMOCAO_PADRAO


def validar_anotacoes(anotacoes):
    if not isinstance(anotacoes, list):
        return []

    limpas = []

    for item in anotacoes:
        if not isinstance(item, dict):
            continue

        alvo = str(item.get("alvo", "")).strip()
        categoria = str(item.get("categoria", "perfil")).strip()
        nota = str(item.get("nota", "")).strip()
        instrucao = str(item.get("instrucao", "")).strip()

        if not alvo or not nota:
            continue

        limpas.append({
            "alvo": alvo,
            "categoria": categoria,
            "nota": nota,
            "instrucao": instrucao
        })

    return limpas


def gerar_resposta(prompt_usuario: str) -> dict:
    contexto_memoria = montar_contexto_memoria(prompt_usuario)
    contexto_humor = obter_contexto_humor()

    mensagens = [
        {"role": "system", "content": PERSONALIDADE},
        {"role": "system", "content": contexto_humor},
    ]

    if contexto_memoria:
        mensagens.append({
            "role": "system",
            "content": f"Contexto de memória:\n{contexto_memoria}"
        })

    mensagens.append({"role": "user", "content": prompt_usuario})

    payload = {
        "model": "local-model",
        "messages": mensagens,
        "temperature": 0.85,
        "top_p": 0.95,
        "max_tokens": 320,
        "repeat_penalty": 1.12
    }

    resposta = requests.post(_resolver_url_api(), json=payload, timeout=120)
    resposta.raise_for_status()

    dados = resposta.json()
    conteudo = dados["choices"][0]["message"]["content"].strip()

    resultado = extrair_json_seguro(conteudo)

    if resultado is not None:
        texto = str(resultado.get("texto", "")).strip()
        emocao = validar_emocao(resultado.get("emocao", EMOCAO_PADRAO))
        anotacoes = validar_anotacoes(resultado.get("anotacoes", []))

        if not texto:
            texto = "Tá, isso saiu meio torto. Fala de novo."

        return {
            "texto": texto,
            "emocao": emocao,
            "anotacoes": anotacoes
        }

    return {
        "texto": conteudo if conteudo else "Deu ruim aqui, tenta de novo.",
        "emocao": EMOCAO_PADRAO,
        "anotacoes": []
    }


def gerar_assunto() -> dict:
    contexto_humor = obter_contexto_humor()

    payload = {
        "model": "local-model",
        "messages": [
            {"role": "system", "content": PERSONALIDADE},
            {"role": "system", "content": contexto_humor},
            {
                "role": "system",
                "content": """
Você deve puxar assunto sozinho.
Seja natural, provocador ou curioso.

NÃO diga que está iniciando conversa.
NÃO peça permissão.
Apenas fale algo como se estivesse quebrando o silêncio.

Responda SOMENTE com JSON válido.
Não escreva 'assistant'.
Não escreva texto fora do JSON.
Não use markdown.

Formato:
{
  "texto": "...",
  "emocao": "normal",
  "anotacoes": []
}
"""
            }
        ],
        "temperature": 0.95,
        "top_p": 0.95,
        "max_tokens": 120
    }

    resposta = requests.post(_resolver_url_api(), json=payload, timeout=120)
    resposta.raise_for_status()

    dados = resposta.json()
    conteudo = dados["choices"][0]["message"]["content"].strip()

    resultado = extrair_json_seguro(conteudo)

    if resultado is not None:
        texto = str(resultado.get("texto", "")).strip()
        emocao = validar_emocao(resultado.get("emocao", EMOCAO_PADRAO))

        if not texto:
            texto = "Você ficou quieto aí... curioso."

        return {
            "texto": texto,
            "emocao": emocao,
            "anotacoes": []
        }

    return {
        "texto": "Tá quieto demais aí... vai falar ou eu vou ter que carregar tudo sozinha?",
        "emocao": EMOCAO_PADRAO,
        "anotacoes": []
    }
