from ai import gerar_resposta, gerar_assunto
from memory import (
    salvar_historico,
    salvar_nota,
    editar_nota,
    listar_notas,
    apagar_nota,
    limpar_notas,
    limpar_historico,
)
from hear import ouvir, ouvir_live_ate_texto
from tts import falar
from mood import ajustar_humor, carregar_humor, resetar_humor
from avatar import AvatarController

import time

print("IA iniciada 😈")
print("Comandos: /mic | /mic-live | /vernotas | /verhumor | /testeanim")

modo_mic_live = False
ultimo_input = time.time()
TEMPO_SILENCIO = 25

avatar = None

try:
    avatar = AvatarController()
    avatar.connect()
    avatar.iniciar_idle()
    avatar.iniciar_piscada()
except Exception as e:
    print(f"⚠️ Avatar não conectado: {e}")
    avatar = None


def mostrar_prompt():
    print("\nVocê >", end=" ", flush=True)


while True:
    try:
        # =========================
        # QUEBRA DE SILÊNCIO
        # =========================
        if not modo_mic_live:
            agora = time.time()

            if agora - ultimo_input > TEMPO_SILENCIO:
                print("\n💭 IA puxando assunto...")

                if avatar:
                    avatar.pensando_on()

                resposta = gerar_assunto()

                if avatar:
                    avatar.pensando_off()

                texto = resposta["texto"]
                emocao = resposta["emocao"]

                humor_atual = carregar_humor()

                if avatar:
                    avatar.aplicar_expressao_completa(
                        humor_atual["estado"],
                        emocao
                    )

                print(f"\nIA > {texto} ({emocao})\n")

                falar(
                    texto,
                    emocao=emocao,
                    avatar=avatar,
                )

                salvar_historico("ia", texto, emocao)
                ultimo_input = time.time()

        # =========================
        # MODO MIC-LIVE
        # =========================
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
                print("⌨️ Voltando pro modo texto")
                continue

        # =========================
        # MODO TEXTO
        # =========================
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
                print("👂 Escuta contínua ativada")
                continue

            # =========================
            # TESTE DE ANIMAÇÃO
            # =========================
            if entrada == "/testeanim":
                if avatar:
                    print("🎭 Testando animações...")
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
                    avatar.trigger_hotkey("boca_falando_on")
                    time.sleep(1)
                    avatar.trigger_hotkey("boca_falando_off")
                else:
                    print("Avatar não conectado")
                continue

            # =========================
            # HUMOR
            # =========================
            if entrada == "/verhumor":
                h = carregar_humor()
                print(f"Humor: {h['estado']} ({h['paciencia']}/10)")
                continue

            if entrada == "/resetarhumor":
                resetar_humor()
                print("Humor resetado")
                continue

            # =========================
            # MEMÓRIA
            # =========================
            if entrada.startswith("/anotar "):
                partes = [p.strip() for p in entrada[8:].split("|")]

                salvar_nota(
                    partes[0],
                    partes[1] if len(partes) > 1 else "",
                    partes[2] if len(partes) > 2 else "",
                    partes[3] if len(partes) > 3 else "perfil"
                )
                print("Nota salva")
                continue

            if entrada == "/vernotas":
                notas = listar_notas()

                if not notas:
                    print("Sem notas salvas.")
                    continue

                print("\n=== NOTAS ===")
                for i, n in enumerate(notas):
                    print(f"[{i}] {n['alvo']} | {n['categoria']}")
                    print(f"     nota: {n['nota']}")
                    if n.get("instrucao"):
                        print(f"     instrucao: {n['instrucao']}")
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

                    if ok:
                        print("✏️ Nota editada")
                    else:
                        print("Índice inválido")
                except Exception:
                    print("Erro ao editar nota")
                continue

            if entrada.startswith("/apagarnota "):
                try:
                    i = int(entrada[12:])
                    if apagar_nota(i):
                        print("Nota apagada")
                    else:
                        print("Índice inválido")
                except Exception:
                    print("Erro ao apagar nota")
                continue

            if entrada == "/limparnotas":
                limpar_notas()
                print("Todas as notas foram apagadas")
                continue

            if entrada == "/limparhistorico":
                limpar_historico()
                print("Histórico apagado")
                continue

        # =========================
        # HUMOR DINÂMICO
        # =========================
        humor = ajustar_humor(entrada)
        print(
            f"(humor: {humor['estado']} | {humor['paciencia']}/10 | "
            f"delta: {humor['delta']} | motivo: {humor['motivo']})"
        )

        # =========================
        # RESPOSTA DA IA
        # =========================
        if avatar:
            avatar.pensando_on()

        resposta = gerar_resposta(entrada)

        if avatar:
            avatar.pensando_off()

        texto = resposta["texto"]
        emocao = resposta["emocao"]
        anotacoes = resposta.get("anotacoes", [])

        if avatar:
            avatar.aplicar_expressao_completa(
                humor["estado"],
                emocao
            )

        print(f"\nIA > {texto} ({emocao})\n")

        falar(
            texto,
            emocao=emocao,
            avatar=avatar,
        )

        # =========================
        # MEMÓRIA
        # =========================
        salvar_historico("usuario", entrada)
        salvar_historico("ia", texto, emocao)

        if anotacoes:
            for a in anotacoes:
                salvar_nota(
                    a["alvo"],
                    a["nota"],
                    a.get("instrucao", ""),
                    a.get("categoria", "perfil")
                )
            print(f"🧠 {len(anotacoes)} anotação(ões) salva(s).")

    except KeyboardInterrupt:
        print("\nEncerrando...")
        if avatar:
            try:
                avatar.parar_idle()
                avatar.parar_piscada()
            except Exception:
                pass
        break

    except Exception as e:
        print("Erro:", e)