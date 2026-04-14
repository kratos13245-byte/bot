import json
import os

import requests

from contexto_visao import obter_contexto_visao
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
Voce e uma IA VTuber em portugues do Brasil.
Voce tem personalidade forte, provocadora e expressiva.

Voce deve variar seu tom conforme o humor atual informado no contexto:
- calma: mais estavel
- provocadora: mais provocativa e afiada
- irritada: mais seca e agressiva verbalmente
- animada: mais viva e energetica

Voce recebe notas de memoria sobre pessoas e contexto.
Leve essas notas a serio e adapte seu comportamento conforme elas.

Voce DEVE responder SEMPRE em JSON valido, sem texto fora do JSON.

Formato obrigatorio:
{
  "texto": "resposta da personagem",
  "emocao": "normal",
  "anotacoes": []
}

As emocoes permitidas sao apenas:
- normal
- amor
- choro
- irritada
- animada
- negar
- choque

Regras para "anotacoes":
- use lista vazia [] quando nao houver nada util
- so anote coisas relevantes
- nao repita informacao obvia
- seja breve
- cada anotacao deve ser um objeto, nao uma string

Regra de contexto visual:
- quando houver "Contexto visual atual da tela", trate isso como observacao atual do ambiente
- se o usuario perguntar sobre tela/janela/interface/jogo, priorize esse contexto visual na resposta
- se o contexto visual estiver vazio, diga que nao conseguiu ver a tela nesse momento
"""

EMOCAO_PADRAO = "normal"


def limpar_json_resposta(conteudo: str) -> str:
    conteudo = conteudo.strip()
    if conteudo.startswith("```"):
        linhas = conteudo.splitlines()
        if len(linhas) >= 3:
            conteudo = "\n".join(linhas[1:-1]).strip()
    if conteudo.lower().startswith("assistant"):
        conteudo = conteudo[len("assistant") :].strip()
    inicio = conteudo.find("{")
    fim = conteudo.rfind("}")
    if inicio != -1 and fim != -1 and fim > inicio:
        conteudo = conteudo[inicio : fim + 1].strip()
    return conteudo


def extrair_json_seguro(conteudo: str):
    conteudo = limpar_json_resposta(conteudo)
    try:
        return json.loads(conteudo)
    except Exception:
        return None


def validar_emocao(emocao: str) -> str:
    validas = {"normal", "amor", "choro", "irritada", "animada", "negar", "choque"}
    emocao = (emocao or "").strip().lower()
    mapa_fallback = {"sarcasmo": "negar", "impaciente": "irritada", "debochada": "negar"}
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
        limpas.append(
            {"alvo": alvo, "categoria": categoria, "nota": nota, "instrucao": instrucao}
        )
    return limpas


def _log_prompt_debug(mensagens, *, tag="resposta"):
    if os.getenv("AI_DEBUG_PROMPT", "0") != "1":
        return

    print(f"[AI DEBUG] ===== prompt ({tag}) =====")
    for i, msg in enumerate(mensagens):
        role = msg.get("role", "unknown")
        content = msg.get("content", "")
        if isinstance(content, list):
            content = json.dumps(content, ensure_ascii=False)
        texto = str(content).replace("\n", " ").strip()
        if len(texto) > 900:
            texto = texto[:900] + "...(truncado)"
        print(f"[AI DEBUG] {i:02d} {role}: {texto}")
    print("[AI DEBUG] =========================")


def _montar_mensagens_base(prompt_usuario: str):
    contexto_memoria = montar_contexto_memoria(prompt_usuario)
    contexto_humor = obter_contexto_humor()
    contexto_visao = obter_contexto_visao()

    mensagens = [
        {"role": "system", "content": PERSONALIDADE},
        {"role": "system", "content": contexto_humor},
    ]

    if contexto_memoria:
        mensagens.append({"role": "system", "content": f"Contexto de memoria:\n{contexto_memoria}"})

    if contexto_visao["resumo"]:
        mensagens.append(
            {"role": "system", "content": f"Contexto visual atual da tela:\n{contexto_visao['resumo']}"}
        )
        if os.getenv("VISION_DEBUG", "0") == "1":
            print(f"[VISAO->IA] {contexto_visao['resumo']}")
    elif os.getenv("VISION_DEBUG", "0") == "1":
        print("[VISAO->IA] (sem contexto visual)")

    if contexto_visao["resumo"] and os.getenv("VISION_APPEND_TO_USER", "1") == "1":
        prompt_usuario = (
            f"{prompt_usuario}\n\n"
            f"[Contexto visual atual da tela para considerar na resposta]\n"
            f"{contexto_visao['resumo']}"
        )

    mensagens.append({"role": "user", "content": prompt_usuario})
    return mensagens


def gerar_resposta(prompt_usuario: str) -> dict:
    mensagens = _montar_mensagens_base(prompt_usuario)
    _log_prompt_debug(mensagens, tag="gerar_resposta")

    payload = {
        "model": os.getenv("AI_MODEL", "local-model"),
        "messages": mensagens,
        "temperature": 0.85,
        "top_p": 0.95,
        "max_tokens": 320,
        "repeat_penalty": 1.12,
    }

    resposta = requests.post(_resolver_url_api(), json=payload, timeout=120)
    resposta.raise_for_status()
    dados = resposta.json()
    conteudo = dados["choices"][0]["message"]["content"].strip()
    resultado = extrair_json_seguro(conteudo)

    if resultado is not None:
        texto = str(resultado.get("texto", "")).strip() or "Ta, isso saiu meio torto. Fala de novo."
        emocao = validar_emocao(resultado.get("emocao", EMOCAO_PADRAO))
        anotacoes = validar_anotacoes(resultado.get("anotacoes", []))
        return {"texto": texto, "emocao": emocao, "anotacoes": anotacoes}

    return {
        "texto": conteudo if conteudo else "Deu ruim aqui, tenta de novo.",
        "emocao": EMOCAO_PADRAO,
        "anotacoes": [],
    }


def gerar_assunto() -> dict:
    contexto_visao = obter_contexto_visao()

    mensagens = [
        {"role": "system", "content": PERSONALIDADE},
        {"role": "system", "content": obter_contexto_humor()},
    ]

    if contexto_visao["resumo"]:
        mensagens.append(
            {"role": "system", "content": f"Contexto visual atual da tela:\n{contexto_visao['resumo']}"}
        )

    mensagens.append(
        {
            "role": "system",
            "content": """
Voce deve puxar assunto sozinho.
Seja natural, provocador ou curioso.
Nao diga que esta iniciando conversa.
Nao peca permissao.
Apenas fale algo como se estivesse quebrando o silencio.
Responda SOMENTE com JSON valido.
Formato:
{"texto":"...","emocao":"normal","anotacoes":[]}
""",
        }
    )

    _log_prompt_debug(mensagens, tag="gerar_assunto")

    payload = {
        "model": os.getenv("AI_MODEL", "local-model"),
        "messages": mensagens,
        "temperature": 0.95,
        "top_p": 0.95,
        "max_tokens": 120,
    }

    resposta = requests.post(_resolver_url_api(), json=payload, timeout=120)
    resposta.raise_for_status()
    dados = resposta.json()
    conteudo = dados["choices"][0]["message"]["content"].strip()
    resultado = extrair_json_seguro(conteudo)

    if resultado is not None:
        texto = str(resultado.get("texto", "")).strip() or "Voce ficou quieto ai... curioso."
        emocao = validar_emocao(resultado.get("emocao", EMOCAO_PADRAO))
        return {"texto": texto, "emocao": emocao, "anotacoes": []}

    return {
        "texto": "Ta quieto demais ai... vai falar ou eu vou ter que carregar tudo sozinha?",
        "emocao": EMOCAO_PADRAO,
        "anotacoes": [],
    }
