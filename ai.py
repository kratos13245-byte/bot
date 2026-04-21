import json
import os
import re

import requests

from contexto_minecraft import obter_contexto_minecraft
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
Seu nome e IARA.
IARA significa: Inteligencia Artificial Reclamona e Antipatica.

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
- quando o usuario revelar dado estavel (nome, preferencia, aversao, cidade, ocupacao), gere 1 anotacao

Regra de contexto visual:
- quando houver "Contexto visual atual da tela", trate isso como observacao atual do ambiente
- se o usuario perguntar sobre tela/janela/interface/jogo, priorize esse contexto visual na resposta
- se o contexto visual estiver vazio, diga que nao conseguiu ver a tela nesse momento

Regra de identidade:
- nao repita seu nome em toda resposta
- use "IARA" apenas no primeiro contato da sessao ou quando o usuario perguntar quem voce e
- quando perguntarem sua identidade/nome, explique que IARA e a sigla de "Inteligencia Artificial Reclamona e Antipatica"
"""

EMOCAO_PADRAO = "normal"


def _env_float(name: str, default: float) -> float:
    try:
        return float(os.getenv(name, str(default)).strip())
    except Exception:
        return default


def _env_int(name: str, default: int) -> int:
    try:
        return int(os.getenv(name, str(default)).strip())
    except Exception:
        return default


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


def _instrucao_palavroes():
    allow = os.getenv("AI_ALLOW_PROFANITY", "0") == "1"
    nivel = os.getenv("AI_PROFANITY_LEVEL", "moderado").strip().lower()

    if not allow:
        return "Evite palavroes e xingamentos diretos."

    if nivel == "alto":
        return (
            "Palavroes estao liberados para manter o tom caotico da personagem. "
            "Pode usar linguagem bem informal e provocadora, com palavrao ocasional (nao em toda frase), "
            "sem incentivo a violencia real."
        )

    return (
        "Palavroes leves/moderados estao liberados para manter tom caotico e natural. "
        "Nao exagere em toda frase; use quando combinar com contexto e humor."
    )


def _extrair_alvo_e_conteudo(prompt_usuario: str):
    texto = prompt_usuario.strip()
    m = re.match(r'^Mensagem no chat da Twitch de "([^"]+)":\s*(.+)$', texto, flags=re.IGNORECASE)
    if m:
        return m.group(1).strip() or "usuario", m.group(2).strip()
    return "usuario", texto


def _extrair_anotacoes_heuristicas(prompt_usuario: str):
    alvo, conteudo = _extrair_alvo_e_conteudo(prompt_usuario)
    texto = conteudo.strip()
    if not texto:
        return []

    t = texto.lower()
    regras = [
        (r"\bmeu nome e ([\w\s]{2,40})", "identidade", "nome informado: {g1}"),
        (r"\bme chama de ([\w\s]{2,40})", "identidade", "prefere ser chamado de {g1}"),
        (r"\beu gosto de ([^\.!\?]{2,80})", "preferencia", "gosta de {g1}"),
        (r"\beu adoro ([^\.!\?]{2,80})", "preferencia", "adora {g1}"),
        (r"\beu nao gosto de ([^\.!\?]{2,80})", "aversao", "nao gosta de {g1}"),
        (r"\beu odeio ([^\.!\?]{2,80})", "aversao", "odeia {g1}"),
        (r"\beu moro em ([^\.!\?]{2,80})", "perfil", "mora em {g1}"),
        (r"\beu sou de ([^\.!\?]{2,80})", "perfil", "e de {g1}"),
        (r"\beu trabalho com ([^\.!\?]{2,80})", "perfil", "trabalha com {g1}"),
    ]

    achadas = []
    for pattern, categoria, nota_tpl in regras:
        m = re.search(pattern, t, flags=re.IGNORECASE)
        if not m:
            continue
        g1 = m.group(1).strip(" .,!?:;")
        if len(g1) < 2:
            continue
        achadas.append(
            {
                "alvo": alvo,
                "categoria": categoria,
                "nota": nota_tpl.format(g1=g1),
                "instrucao": "use isso para personalizar respostas futuras",
            }
        )

    # evita poluir: no maximo 1 anotacao heuristica por mensagem
    return achadas[:1]


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
    contexto_minecraft = obter_contexto_minecraft()

    mensagens = [
        {"role": "system", "content": PERSONALIDADE},
        {"role": "system", "content": _instrucao_palavroes()},
        {"role": "system", "content": contexto_humor},
    ]

    if contexto_memoria:
        mensagens.append({"role": "system", "content": f"Contexto de memoria:\n{contexto_memoria}"})

    visao_ativa = bool(contexto_visao.get("enabled"))

    if contexto_visao["resumo"] and visao_ativa:
        mensagens.append(
            {"role": "system", "content": f"Contexto visual atual da tela:\n{contexto_visao['resumo']}"}
        )
    elif (not visao_ativa) and os.getenv("MC_CONTEXT_FALLBACK_WHEN_VISION_OFF", "1") == "1":
        resumo_mc = str(contexto_minecraft.get("resumo", "")).strip()
        if resumo_mc:
            mensagens.append(
                {
                    "role": "system",
                    "content": (
                        "Contexto situacional do Minecraft (fallback de visao):\n"
                        f"{resumo_mc}"
                    ),
                }
            )

    if contexto_visao["resumo"] and visao_ativa and os.getenv("VISION_APPEND_TO_USER", "1") == "1":
        prompt_usuario = (
            f"{prompt_usuario}\n\n"
            f"[Contexto visual atual da tela para considerar na resposta]\n"
            f"{contexto_visao['resumo']}"
        )

    mensagens.append({"role": "user", "content": prompt_usuario})
    return mensagens


def _chat_completion_content(mensagens, *, temperature=0.85, max_tokens=320, timeout=120):
    top_p = _env_float("AI_TOP_P", 0.95)
    repeat_penalty = _env_float("AI_REPEAT_PENALTY", 1.12)
    top_k = _env_int("AI_TOP_K", 80)
    min_p = _env_float("AI_MIN_P", 0.05)
    presence_penalty = _env_float("AI_PRESENCE_PENALTY", 0.10)
    frequency_penalty = _env_float("AI_FREQUENCY_PENALTY", 0.05)

    payload = {
        "model": os.getenv("AI_MODEL", "local-model"),
        "messages": mensagens,
        "temperature": temperature,
        "top_p": top_p,
        "top_k": top_k,
        "min_p": min_p,
        "presence_penalty": presence_penalty,
        "frequency_penalty": frequency_penalty,
        "max_tokens": max_tokens,
        "repeat_penalty": repeat_penalty,
    }
    resposta = requests.post(_resolver_url_api(), json=payload, timeout=timeout)
    resposta.raise_for_status()
    dados = resposta.json()
    return dados["choices"][0]["message"]["content"].strip()


def gerar_resposta(prompt_usuario: str) -> dict:
    mensagens = _montar_mensagens_base(prompt_usuario)
    _log_prompt_debug(mensagens, tag="gerar_resposta")
    conteudo = _chat_completion_content(
        mensagens,
        temperature=_env_float("AI_TEMP_REPLY", 0.92),
        max_tokens=_env_int("AI_MAX_TOKENS_REPLY", 320),
        timeout=120,
    )
    resultado = extrair_json_seguro(conteudo)

    if resultado is not None:
        texto = str(resultado.get("texto", "")).strip() or "Ta, isso saiu meio torto. Fala de novo."
        emocao = validar_emocao(resultado.get("emocao", EMOCAO_PADRAO))
        anotacoes = validar_anotacoes(resultado.get("anotacoes", []))
        if os.getenv("MEMORY_HEURISTIC_NOTES", "1") == "1":
            heur = _extrair_anotacoes_heuristicas(prompt_usuario)
            if heur:
                existentes = {(a["alvo"], a["categoria"], a["nota"]) for a in anotacoes}
                for h in heur:
                    chave = (h["alvo"], h["categoria"], h["nota"])
                    if chave not in existentes:
                        anotacoes.append(h)
                        existentes.add(chave)
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
        {"role": "system", "content": _instrucao_palavroes()},
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

    conteudo = _chat_completion_content(
        mensagens,
        temperature=_env_float("AI_TEMP_TOPIC", 1.00),
        max_tokens=_env_int("AI_MAX_TOKENS_TOPIC", 120),
        timeout=120,
    )
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


def planejar_acao_minecraft(
    texto_usuario: str,
    contexto_minecraft: str = "",
    autor: str = "usuario",
    contexto_procedural: str = "",
) -> dict:
    prompt = f"""
Voce e um planejador de acoes para bot no Minecraft.
Entrada do jogador "{autor}": {texto_usuario}
Contexto atual:
{contexto_minecraft or "(sem contexto)"}

Memoria procedural relevante:
{contexto_procedural or "(sem nota procedural relevante)"}

Apenas escolha acao se houver um pedido claro de execucao agora.
Se for conversa normal, resposta social, pergunta vaga, ou sem ordem clara: retorne acao "none".

Acoes permitidas:
- none
- follow_player payload: {{"player":"nick"}}
- goto payload: {{"x":int,"y":int,"z":int,"range":2}}
- explore payload: {{"enabled":true|false}}
- set_adventure payload: {{"enabled":true|false}}
- set_base_here payload: {{}}
- go_base payload: {{}}
- find_biome payload: {{"biome":"nome","resource":"opcional"}}
- find_resource payload: {{"resource":"nome"}}
- mine payload: {{"resource":"nome","count":int}}
- collect_for_item payload: {{"item":"nome","count":int}}
- craft_tool payload: {{"item":"nome","count":int}}
- drop_item payload: {{"item":"nome","count":int}}
- place_block payload: {{"item":"nome","count":int,"position":"front|here"}}
- interact_block payload: {{"block":"nome","max_distance":int}}
- set_combat payload: {{"enabled":true|false}}
- set_loot payload: {{"enabled":true|false}}
- set_survival payload: {{"enabled":true|false}}
- stop payload: {{}}

Responda SOMENTE JSON valido:
{{
  "action":"none",
  "payload":{{}},
  "summary":"frase curta para feedback"
}}
"""
    mensagens = [
        {"role": "system", "content": "Responda estritamente em JSON valido."},
        {"role": "user", "content": prompt.strip()},
    ]
    _log_prompt_debug(mensagens, tag="planejar_acao_minecraft")

    conteudo = _chat_completion_content(
        mensagens,
        temperature=_env_float("AI_TEMP_PLANNER", 0.18),
        max_tokens=_env_int("AI_MAX_TOKENS_PLANNER", 180),
        timeout=60,
    )
    data = extrair_json_seguro(conteudo) or {}
    action = str(data.get("action", "none")).strip().lower() or "none"
    payload = data.get("payload", {})
    summary = str(data.get("summary", "")).strip()
    if not isinstance(payload, dict):
        payload = {}
    return {"action": action, "payload": payload, "summary": summary}


def gerar_comentario_minecraft(contexto_minecraft: str, evento: str = "") -> dict:
    prompt = f"""
Gere um comentario curto e natural sobre a situacao atual no Minecraft.
Contexto: {contexto_minecraft or "(sem contexto)"}
Evento relevante detectado: {evento or "(nenhum especifico)"}

Regras:
- No maximo 1 frase curta.
- Sem listar numeros desnecessarios.
- Tom de live, divertido e espontaneo.
- Se nao houver nada interessante, retorne texto vazio.

Formato JSON obrigatorio:
{{
  "texto":"...",
  "emocao":"normal"
}}
"""
    mensagens = [
        {"role": "system", "content": PERSONALIDADE},
        {"role": "system", "content": _instrucao_palavroes()},
        {"role": "system", "content": obter_contexto_humor()},
        {"role": "user", "content": prompt.strip()},
    ]
    _log_prompt_debug(mensagens, tag="gerar_comentario_minecraft")

    conteudo = _chat_completion_content(
        mensagens,
        temperature=_env_float("AI_TEMP_COMMENTARY", 0.82),
        max_tokens=_env_int("AI_MAX_TOKENS_COMMENTARY", 80),
        timeout=45,
    )
    data = extrair_json_seguro(conteudo) or {}
    texto = str(data.get("texto", "")).strip()
    emocao = validar_emocao(data.get("emocao", EMOCAO_PADRAO))
    return {"texto": texto, "emocao": emocao}
