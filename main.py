#nada
import asyncio
import os
import threading
import time
from contextlib import suppress


def _load_local_env(env_path=".env"):
    if not os.path.exists(env_path):
        return

    with open(env_path, "r", encoding="utf-8") as f:
        for raw in f:
            line = raw.strip()
            if not line or line.startswith("#") or "=" not in line:
                continue
            key, value = line.split("=", 1)
            key = key.strip()
            value = value.strip().strip('"').strip("'")
            if key and key not in os.environ:
                os.environ[key] = value


_load_local_env()

from ai import (
    gerar_assunto,
    gerar_comentario_minecraft,
    gerar_resposta,
    planejar_acao_minecraft,
)
from avatar import AvatarController
from hear import ouvir, ouvir_live_ate_texto
from memory import (
    apagar_nota,
    editar_nota,
    limpar_historico,
    limpar_notas,
    listar_notas,
    salvar_historico,
    salvar_nota,
)
from mood import ajustar_humor, carregar_humor, resetar_humor
from tts import falar
from twitch_bot import TWITCH_TRIGGER_MODE, TwitchChatBridge
from vision_local import VisionWatcher
from minecraft_bridge import MinecraftBridge


TEMPO_SILENCIO = 25
COOLDOWN_MIC_LIVE_SEC = int(os.getenv("MIC_LIVE_COOLDOWN_SEC", "10"))
process_lock = threading.Lock()
modo_mic_live = False
modo_mic_pausado = False
ultimo_input = time.time()
proxima_fala_mic_live = 0.0
COMANDO_DORMIR = "dormir"
COMANDO_ACORDAR = "acordar"
ALIASES_DORMIR = ["cala a boca iara"]
ALIASES_ACORDAR = ["escuta aqui iara"]
MC_AI_ACTION_PLANNER = os.getenv("MC_AI_ACTION_PLANNER", "1") == "1"
MC_NARRATION_ENABLED_DEFAULT = os.getenv("MC_NARRATION_ENABLED", "1") == "1"
MC_NARRATION_INTERVAL_SEC = float(os.getenv("MC_NARRATION_INTERVAL_SEC", "5"))
MC_NARRATION_COOLDOWN_SEC = float(os.getenv("MC_NARRATION_COOLDOWN_SEC", "28"))
MC_NARRATION_TO_CHAT = os.getenv("MC_NARRATION_TO_CHAT", "1") == "1"
MC_NARRATION_TO_TTS = os.getenv("MC_NARRATION_TO_TTS", "0") == "1"
ALLOWED_MC_ACTIONS = {
    "none",
    "follow_player",
    "goto",
    "explore",
    "set_adventure",
    "set_base_here",
    "go_base",
    "find_biome",
    "find_resource",
    "mine",
    "craft_tool",
    "set_combat",
    "set_loot",
    "set_survival",
    "stop",
}


def inicializar_avatar():
    try:
        avatar = AvatarController()
        avatar.connect()
        avatar.iniciar_idle()
        avatar.iniciar_piscada()
        return avatar
    except Exception as e:
        print(f"Aviso: avatar nao conectado: {e}")
        return None


avatar = inicializar_avatar()
vision = VisionWatcher()
mc = MinecraftBridge()
mc_narracao_ativa = MC_NARRATION_ENABLED_DEFAULT
mc_narracao_stop = threading.Event()
mc_narracao_thread = None


def mostrar_prompt():
    print("\nVoce >", end=" ", flush=True)


def salvar_anotacoes(anotacoes):
    if not anotacoes:
        return

    for anotacao in anotacoes:
        salvar_nota(
            anotacao["alvo"],
            anotacao["nota"],
            anotacao.get("instrucao", ""),
            anotacao.get("categoria", "perfil"),
        )

    print(f"[MEMORIA] {len(anotacoes)} anotacao(oes) salva(s).")


def _extrair_evento_minecraft(ctx: dict):
    data = ctx.get("data", {}) if isinstance(ctx, dict) else {}
    health = data.get("health")
    food = data.get("food")
    mobs = data.get("mobs_near") or []
    players = data.get("players_near") or []
    mode = ((data.get("state") or {}).get("mode") or "").strip()

    if isinstance(health, (int, float)) and health <= 7:
        return "vida baixa"
    if isinstance(food, (int, float)) and food <= 10:
        return "fome baixa"
    if mobs:
        nome = str(mobs[0].get("kind") or mobs[0].get("name") or "mob")
        return f"mob por perto ({nome})"
    if players:
        nome = str(players[0].get("name") or "jogador")
        return f"jogador por perto ({nome})"
    if mode in {"mine", "find_resource", "find_biome", "adventure", "explore"}:
        return f"atividade atual: {mode}"
    return ""


def _tentar_acao_planejada_minecraft(autor: str, entrada: str, enviar_chat=None):
    if not mc.enabled or not MC_AI_ACTION_PLANNER:
        return None

    try:
        ctx = mc.get_context()
        contexto_resumo = str(ctx.get("summary", "")).strip()
    except Exception:
        ctx = {}
        contexto_resumo = ""

    try:
        plano = planejar_acao_minecraft(entrada, contexto_minecraft=contexto_resumo, autor=autor)
    except Exception as e:
        print(f"[MINECRAFT] Planner IA falhou: {e}")
        return None

    action = str(plano.get("action", "none")).strip().lower()
    payload = plano.get("payload", {}) or {}
    summary = str(plano.get("summary", "")).strip()

    if action == "none":
        return None
    if action not in ALLOWED_MC_ACTIONS:
        print(f"[MINECRAFT] Planner sugeriu acao invalida: {action}")
        return None

    try:
        out = mc.send_action(action, payload)
    except Exception as e:
        print(f"[MINECRAFT] Falha ao executar acao planejada ({action}): {e}")
        return None

    feedback = summary or f"Acao executada: {action}."
    if out.get("ok") and action == "craft_tool":
        item = out.get("item")
        crafted = out.get("crafted", out.get("requested", 1))
        feedback = summary or f"Craft concluido: {item} x{crafted}."

    print(f"[MINECRAFT PLANNER] {feedback} | action={action} payload={payload}")
    if enviar_chat:
        with suppress(Exception):
            enviar_chat(feedback)

    return {
        "texto": feedback,
        "emocao": "normal",
        "humor": {"estado": "calma", "paciencia": 6, "delta": 0, "motivo": "planner"},
    }


def iniciar_narracao_minecraft():
    def runner():
        last_context_key = ""
        last_comment_ts = 0.0
        while not mc_narracao_stop.is_set():
            if not mc_narracao_ativa or not mc.enabled:
                mc_narracao_stop.wait(MC_NARRATION_INTERVAL_SEC)
                continue

            try:
                ctx = mc.get_context()
                resumo = str(ctx.get("summary", "")).strip()
                evento = _extrair_evento_minecraft(ctx)
            except Exception:
                mc_narracao_stop.wait(MC_NARRATION_INTERVAL_SEC)
                continue

            if not resumo:
                mc_narracao_stop.wait(MC_NARRATION_INTERVAL_SEC)
                continue

            key = f"{evento}|{resumo[:220]}"
            now = time.time()
            changed = key != last_context_key
            ready = (now - last_comment_ts) >= MC_NARRATION_COOLDOWN_SEC

            if changed and ready:
                with process_lock:
                    try:
                        comentario = gerar_comentario_minecraft(resumo, evento=evento)
                        texto = str(comentario.get("texto", "")).strip()
                        emocao = comentario.get("emocao", "normal")
                    except Exception as e:
                        print(f"[MC NARRACAO] Falha na geracao: {e}")
                        texto = ""
                        emocao = "normal"

                    if texto:
                        print(f"[MC NARRACAO] {texto}")
                        if MC_NARRATION_TO_CHAT:
                            with suppress(Exception):
                                mc.send_chat(texto)
                        if MC_NARRATION_TO_TTS:
                            with suppress(Exception):
                                falar(texto, emocao=emocao, avatar=avatar)
                        last_comment_ts = now
                        last_context_key = key

            mc_narracao_stop.wait(MC_NARRATION_INTERVAL_SEC)

    thread = threading.Thread(target=runner, daemon=True, name="mc-narracao-thread")
    thread.start()
    return thread


def responder_personagem(entrada: str, *, origem: str = "usuario", autor: str = "voce", enviar_chat=None):
    entrada = entrada.strip()
    if not entrada:
        return None

    with process_lock:
        humor = ajustar_humor(entrada)
        print(
            f"(humor: {humor['estado']} | {humor['paciencia']}/10 | "
            f"delta: {humor['delta']} | motivo: {humor['motivo']})"
        )

        prompt_ia = entrada
        historico_usuario = entrada

        if origem == "twitch":
            prompt_ia = f'Mensagem no chat da Twitch de "{autor}": {entrada}'
            historico_usuario = f"{autor}: {entrada}"
            print(f"\n[TWITCH] {autor} > {entrada}")
        elif origem == "minecraft":
            try:
                cmd_result = mc.try_handle_natural_command(autor, entrada)
            except Exception as e:
                cmd_result = {"handled": False}
                print(f"[MINECRAFT] Falha ao interpretar comando: {e}")

            if cmd_result.get("handled"):
                resumo = str(cmd_result.get("summary", "Comando executado.")).strip()
                print(f"[MINECRAFT ACTION] {resumo}")
                if enviar_chat:
                    try:
                        enviar_chat(resumo)
                    except Exception as e:
                        print(f"[MINECRAFT] Falha ao enviar feedback de acao: {e}")

                if os.getenv("MC_SKIP_AI_ON_COMMAND", "1") == "1":
                    return {
                        "texto": resumo,
                        "emocao": "normal",
                        "humor": {"estado": "calma", "paciencia": 6, "delta": 0, "motivo": "comando"},
                    }
            else:
                planned = _tentar_acao_planejada_minecraft(autor, entrada, enviar_chat=enviar_chat)
                if planned and os.getenv("MC_SKIP_AI_ON_COMMAND", "1") == "1":
                    return planned

            prompt_ia = f'Mensagem no chat do Minecraft de "{autor}": {entrada}'
            historico_usuario = f"{autor}: {entrada}"
            print(f"\n[MINECRAFT] {autor} > {entrada}")

        if avatar:
            avatar.pensando_on()

        try:
            resposta = gerar_resposta(prompt_ia)
        finally:
            if avatar:
                avatar.pensando_off()

        texto = resposta["texto"]
        emocao = resposta["emocao"]
        anotacoes = resposta.get("anotacoes", [])

        if avatar:
            avatar.aplicar_expressao_completa(humor["estado"], emocao)

        if origem == "twitch":
            print(f"[IA->TWITCH] {texto} ({emocao})")
        elif origem == "minecraft":
            print(f"[IA->MINECRAFT] {texto} ({emocao})")
        else:
            print(f"\nIA > {texto} ({emocao})\n")

        salvar_historico("usuario", historico_usuario)
        salvar_historico("ia", texto, emocao)
        salvar_anotacoes(anotacoes)

        if enviar_chat:
            try:
                enviar_chat(texto)
            except Exception as e:
                print(f"[TWITCH] Falha ao enfileirar resposta no chat: {e}")

        falar(
            texto,
            emocao=emocao,
            avatar=avatar,
        )

        return {
            "texto": texto,
            "emocao": emocao,
            "humor": humor,
        }


def puxar_assunto_sozinha():
    global ultimo_input

    with process_lock:
        print("\n[IA] Puxando assunto...")

        if avatar:
            avatar.pensando_on()

        try:
            resposta = gerar_assunto()
        finally:
            if avatar:
                avatar.pensando_off()

        texto = resposta["texto"]
        emocao = resposta["emocao"]
        humor_atual = carregar_humor()

        if avatar:
            avatar.aplicar_expressao_completa(humor_atual["estado"], emocao)

        print(f"\nIA > {texto} ({emocao})\n")

        falar(
            texto,
            emocao=emocao,
            avatar=avatar,
        )

        salvar_historico("ia", texto, emocao)
        ultimo_input = time.time()


def iniciar_twitch_em_background():
    def runner():
        async def processar_chat(incoming_queue: asyncio.Queue, outgoing_queue: asyncio.Queue):
            loop = asyncio.get_running_loop()

            def enviar_chat_threadsafe(texto: str):
                future = asyncio.run_coroutine_threadsafe(
                    outgoing_queue.put({"text": texto}),
                    loop,
                )
                future.result()

            while True:
                msg = await incoming_queue.get()
                try:
                    user = str(msg.get("user", "desconhecido")).strip() or "desconhecido"
                    text = str(msg.get("text", "")).strip()

                    if not text:
                        continue

                    await asyncio.to_thread(
                        responder_personagem,
                        text,
                        origem="twitch",
                        autor=user,
                        enviar_chat=enviar_chat_threadsafe,
                    )
                except Exception as e:
                    print(f"[TWITCH] Erro processando mensagem: {e}")
                finally:
                    incoming_queue.task_done()

        async def bot_runner():
            incoming_queue = asyncio.Queue()
            outgoing_queue = asyncio.Queue()
            bot = TwitchChatBridge(incoming_queue, outgoing_queue)

            consumer_task = asyncio.create_task(processar_chat(incoming_queue, outgoing_queue))
            start_options = {
                "load_tokens": False,
                "with_adapter": False,
            }

            bot_task = asyncio.create_task(bot.start(**start_options))

            try:
                await asyncio.gather(bot_task, consumer_task)
            finally:
                consumer_task.cancel()
                await bot.close()
                await asyncio.gather(consumer_task, return_exceptions=True)

        try:
            asyncio.run(bot_runner())
        except Exception as e:
            print(f"[TWITCH] Integracao encerrada com erro: {e}")

    thread = threading.Thread(target=runner, daemon=True, name="twitch-chat-thread")
    thread.start()
    return thread


def encerrar_avatar():
    global mc_narracao_thread
    mc_narracao_stop.set()
    if mc_narracao_thread and mc_narracao_thread.is_alive():
        with suppress(Exception):
            mc_narracao_thread.join(timeout=2)

    with suppress(Exception):
        mc.stop()

    with suppress(Exception):
        vision.stop()

    if not avatar:
        return

    with suppress(Exception):
        avatar.parar_idle()
    with suppress(Exception):
        avatar.parar_piscada()


print("IA iniciada")
print("Comandos: /mic | /mic-live | /vernotas | /verhumor | /visao on | /visao off | /visao status | /visao agora | /mc status | /mc cmd <comando> | /mc ai <ordem> | /mc narracao on|off | /testeanim | /sair")
print(f"No /mic-live: diga '{COMANDO_DORMIR}' para pausar e '{COMANDO_ACORDAR}' para voltar.")
print("Atalhos de voz: 'cala a boca iara' (pausa) e 'escuta aqui iara' (retoma).")

twitch_thread = iniciar_twitch_em_background()
print("[TWITCH] Integracao com chat iniciada em background.")

if mc.enabled:
    def _on_minecraft_chat(user: str, text: str):
        try:
            responder_personagem(
                text,
                origem="minecraft",
                autor=user,
                enviar_chat=mc.send_chat,
            )
        except Exception as e:
            print(f"[MINECRAFT] Erro processando mensagem: {e}")

    try:
        status = mc.health()
        print(f"[MINECRAFT] Bridge online: connected={status.get('connected')}")
        mc.start_polling(_on_minecraft_chat)
        print("[MINECRAFT] Integracao com chat iniciada em background.")
        mc_narracao_thread = iniciar_narracao_minecraft()
        print(f"[MINECRAFT] Narracao automatica: {'on' if mc_narracao_ativa else 'off'}")
    except Exception as e:
        print(f"[MINECRAFT] Bridge indisponivel: {e}")

if os.getenv("VISION_AUTO_START", "0") == "1":
    if vision.start():
        print("[VISAO] Captura visual iniciada automaticamente.")


while True:
    try:
        if not modo_mic_live:
            agora = time.time()
            if agora - ultimo_input > TEMPO_SILENCIO:
                puxar_assunto_sozinha()

        if modo_mic_live:
            if avatar:
                avatar.escutando_on()

            entrada = ouvir_live_ate_texto()

            if avatar:
                avatar.escutando_off()

            if not entrada:
                continue

            entrada_lower = entrada.lower()

            if COMANDO_DORMIR in entrada_lower or any(alias in entrada_lower for alias in ALIASES_DORMIR):
                modo_mic_pausado = True
                print("Escuta em pausa. Diga 'acordar' para voltar.")
                continue

            if COMANDO_ACORDAR in entrada_lower or any(alias in entrada_lower for alias in ALIASES_ACORDAR):
                modo_mic_pausado = False
                print("Escuta reativada.")
                continue

            if modo_mic_pausado:
                continue

            if "ativar modo texto" in entrada.lower():
                modo_mic_live = False
                modo_mic_pausado = False
                proxima_fala_mic_live = 0.0
                print("Voltando pro modo texto")
                continue
        else:
            mostrar_prompt()
            entrada = input().strip()

            if not entrada:
                continue

            ultimo_input = time.time()

            if entrada == "/sair":
                print("Encerrando...")
                break

            if entrada == "/mic":
                if avatar:
                    avatar.escutando_on()

                entrada = ouvir()

                if avatar:
                    avatar.escutando_off()

                if not entrada:
                    continue

            if entrada == "/mic-live":
                modo_mic_live = True
                modo_mic_pausado = False
                proxima_fala_mic_live = 0.0
                print("Escuta continua ativada")
                continue

            if entrada == "/testeanim":
                if avatar:
                    print("Testando animacoes...")
                    avatar.resetar_estado_visual()

                    avatar.trigger_hotkey("exp_irritada")
                    time.sleep(1)
                    avatar.trigger_hotkey("emo_choque")
                    time.sleep(1)
                    avatar.trigger_hotkey("exp_animada")
                    time.sleep(1)
                    avatar.trigger_hotkey("emo_amor")
                    time.sleep(1)
                    avatar.set_idle_values(eye_x=0.8, eye_y=0.0, head_x=0.2, head_y=0.1)
                    time.sleep(1)
                    avatar.set_idle_values(eye_x=-0.8, eye_y=0.0, head_x=-0.2, head_y=0.0)
                    time.sleep(1)
                    avatar.set_idle_values(eye_x=0.0, eye_y=0.6, head_x=0.0, head_y=0.1)
                    time.sleep(1)
                    avatar.set_idle_values(eye_x=0.0, eye_y=-0.6, head_x=0.0, head_y=-0.1)
                    time.sleep(1)
                    avatar.piscar()
                    time.sleep(1)
                    avatar.set_idle_values(eye_x=0.0, eye_y=0.0, head_x=0.0, head_y=0.0)
                    avatar.set_blink_values(0.0, 0.0)
                else:
                    print("Avatar nao conectado")
                continue

            if entrada == "/visao on":
                if vision.start():
                    print("[VISAO] Captura visual ativada.")
                else:
                    print("[VISAO] Ja estava ativa.")
                continue

            if entrada == "/mc status":
                try:
                    status = mc.health()
                    print(
                        f"[MINECRAFT] bridge_ok={status.get('ok')} "
                        f"connected={status.get('connected')} "
                        f"user={status.get('username')}"
                    )
                except Exception as e:
                    print(f"[MINECRAFT] Falha no status: {e}")
                continue

            if entrada.startswith("/mc cmd "):
                try:
                    cmd = entrada[len("/mc cmd "):].strip()
                    mc.send_command(cmd)
                    print(f"[MINECRAFT] Comando enviado: {cmd}")
                except Exception as e:
                    print(f"[MINECRAFT] Falha ao enviar comando: {e}")
                continue

            if entrada.startswith("/mc ai "):
                ordem = entrada[len("/mc ai "):].strip()
                if not ordem:
                    print("[MINECRAFT] Informe uma ordem apos /mc ai.")
                    continue
                resultado = _tentar_acao_planejada_minecraft("voce", ordem, enviar_chat=mc.send_chat)
                if resultado:
                    print(f"[MINECRAFT] {resultado['texto']}")
                else:
                    print("[MINECRAFT] Planner nao identificou acao clara.")
                continue

            if entrada in {"/mc narracao on", "/mc narracao off"}:
                mc_narracao_ativa = entrada.endswith("on")
                print(f"[MINECRAFT] Narracao {'ativada' if mc_narracao_ativa else 'desativada'}.")
                continue

            if entrada == "/visao off":
                if vision.stop():
                    print("[VISAO] Captura visual desativada.")
                else:
                    print("[VISAO] Ja estava desativada.")
                continue

            if entrada == "/visao status":
                s = vision.status()
                print(f"[VISAO] ativa={s['enabled']} | intervalo={s['intervalo']}s")
                if s["ultimo_erro"]:
                    print(f"[VISAO] ultimo erro: {s['ultimo_erro']}")
                if s["resumo"]:
                    print(f"[VISAO] ultimo resumo: {s['resumo']}")
                else:
                    print("[VISAO] sem resumo ainda.")
                continue

            if entrada == "/visao agora":
                try:
                    resumo = vision.force_once()
                    print(f"[VISAO] resumo atualizado: {resumo}")
                except Exception as e:
                    print(f"[VISAO] falha ao capturar agora: {e}")
                continue

            if entrada == "/verhumor":
                h = carregar_humor()
                print(f"Humor: {h['estado']} ({h['paciencia']}/10)")
                continue

            if entrada == "/resetarhumor":
                resetar_humor()
                print("Humor resetado")
                continue

            if entrada.startswith("/anotar "):
                partes = [p.strip() for p in entrada[8:].split("|")]
                salvar_nota(
                    partes[0],
                    partes[1] if len(partes) > 1 else "",
                    partes[2] if len(partes) > 2 else "",
                    partes[3] if len(partes) > 3 else "perfil",
                )
                print("Nota salva")
                continue

            if entrada == "/vernotas":
                notas = listar_notas()

                if not notas:
                    print("Sem notas salvas.")
                    continue

                print("\n=== NOTAS ===")
                for i, nota in enumerate(notas):
                    print(f"[{i}] {nota['alvo']} | {nota['categoria']}")
                    print(f"     nota: {nota['nota']}")
                    if nota.get("instrucao"):
                        print(f"     instrucao: {nota['instrucao']}")
                print("=============\n")
                continue

            if entrada.startswith("/editarnota "):
                try:
                    partes = [p.strip() for p in entrada[12:].split("|")]
                    indice = int(partes[0])

                    ok = editar_nota(
                        indice,
                        alvo=partes[1] if len(partes) > 1 else None,
                        nota=partes[2] if len(partes) > 2 else None,
                        instrucao=partes[3] if len(partes) > 3 else None,
                        categoria=partes[4] if len(partes) > 4 else None,
                    )

                    print("Nota editada" if ok else "Indice invalido")
                except Exception:
                    print("Erro ao editar nota")
                continue

            if entrada.startswith("/apagarnota "):
                try:
                    indice = int(entrada[12:])
                    print("Nota apagada" if apagar_nota(indice) else "Indice invalido")
                except Exception:
                    print("Erro ao apagar nota")
                continue

            if entrada == "/limparnotas":
                limpar_notas()
                print("Todas as notas foram apagadas")
                continue

            if entrada == "/limparhistorico":
                limpar_historico()
                print("Historico apagado")
                continue

        if modo_mic_live:
            agora = time.time()
            if agora < proxima_fala_mic_live:
                restante = int(proxima_fala_mic_live - agora + 0.999)
                print(f"Aguarde {restante}s para a proxima resposta no /mic-live.")
                continue

            ultimo_input = agora
            responder_personagem(entrada, origem="usuario", autor="voce")
            proxima_fala_mic_live = time.time() + COOLDOWN_MIC_LIVE_SEC
            continue

        ultimo_input = time.time()
        responder_personagem(entrada, origem="usuario", autor="voce")

    except KeyboardInterrupt:
        print("\nEncerrando...")
        encerrar_avatar()
        break
    except Exception as e:
        print("Erro:", e)


encerrar_avatar()
