import asyncio
import threading
import time
from contextlib import suppress

from ai import gerar_assunto, gerar_resposta
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


TEMPO_SILENCIO = 25
process_lock = threading.Lock()
modo_mic_live = False
ultimo_input = time.time()


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
    if not avatar:
        return

    with suppress(Exception):
        avatar.parar_idle()
    with suppress(Exception):
        avatar.parar_piscada()


print("IA iniciada")
print("Comandos: /mic | /mic-live | /vernotas | /verhumor | /testeanim | /sair")

twitch_thread = iniciar_twitch_em_background()
print("[TWITCH] Integracao com chat iniciada em background.")


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

            if "ativar modo texto" in entrada.lower():
                modo_mic_live = False
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

        ultimo_input = time.time()
        responder_personagem(entrada, origem="usuario", autor="voce")

    except KeyboardInterrupt:
        print("\nEncerrando...")
        encerrar_avatar()
        break
    except Exception as e:
        print("Erro:", e)


encerrar_avatar()
