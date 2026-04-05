import time
import random

import numpy as np
import sounddevice as sd
import whisper
import webrtcvad

from state import ia_falando, interromper_usuario
from mood import carregar_humor

# ===== CONFIG =====
TAXA_AMOSTRAGEM = 16000
DURACAO_PADRAO = 5
MODELO_WHISPER = "base"

FRAME_MS = 30
FRAME_SIZE = int(TAXA_AMOSTRAGEM * FRAME_MS / 1000)

VAD_AGRESSIVIDADE = 2
MIN_FRAMES_VOZ_PARA_INICIAR = 3
MAX_FRAMES_SILENCIO_PARA_FINALIZAR = 20
PRE_BUFFER_FRAMES = 10

# quantidade mínima de frames já falados antes da IA poder cortar
MIN_FRAMES_ANTES_DE_INTERRUPPER = 12

# mínimo de amostras de áudio para considerar válido
MIN_AMOSTRAS_AUDIO = 1600  # ~0.1 segundo em 16kHz

print("Carregando Whisper...")
modelo_whisper = whisper.load_model(MODELO_WHISPER)
print("Whisper carregado 👂")

vad = webrtcvad.Vad(VAD_AGRESSIVIDADE)


def obter_chance_interrupcao_por_humor():
    humor = carregar_humor()
    estado = humor.get("estado", "calma")

    mapa = {
        "calma": 0.08,
        "provocadora": 0.25,
        "irritada": 0.45,
        "animada": 0.18,
    }

    return mapa.get(estado, 0.10)


def gravar_audio(duracao=DURACAO_PADRAO, fs=TAXA_AMOSTRAGEM):
    print("🎤 Gravando...")
    audio = sd.rec(int(duracao * fs), samplerate=fs, channels=1, dtype="int16")
    sd.wait()
    print("🛑 Fim da gravação")
    return audio, fs


def transcrever_audio(audio, fs):
    if audio is None:
        print("⚠️ Áudio vazio.")
        return None

    audio = np.asarray(audio)

    if audio.size == 0:
        print("⚠️ Áudio sem conteúdo.")
        return None

    if audio.ndim > 1:
        audio = audio.flatten()

    if audio.dtype != np.float32:
        audio = audio.astype(np.float32) / 32768.0

    try:
        print("🧠 Transcrevendo...")
        resultado = modelo_whisper.transcribe(audio, language="pt")
        texto = resultado["text"].strip()
        return texto
    except Exception as e:
        print(f"Erro na transcrição: {e}")
        return None


def ouvir(duracao=DURACAO_PADRAO):
    if ia_falando.is_set():
        print("🔇 IA ainda está falando. Espera um instante...")
        return None

    try:
        audio, fs = gravar_audio(duracao=duracao)
        texto = transcrever_audio(audio, fs)

        if not texto:
            print("⚠️ Não entendi nada.")
            return None

        print(f"Você disse: {texto}")
        return texto

    except Exception as e:
        print(f"Erro ao ouvir: {e}")
        return None


def frame_tem_voz(frame_int16):
    frame_bytes = frame_int16.tobytes()
    return vad.is_speech(frame_bytes, TAXA_AMOSTRAGEM)


def montar_audio_final(buffer_fala):
    if not buffer_fala:
        return None

    try:
        audio_final = np.concatenate(buffer_fala, axis=0)
    except Exception:
        return None

    if audio_final.size < MIN_AMOSTRAS_AUDIO:
        return None

    return audio_final


def ouvir_live_ate_texto():
    print("👂 Escutando continuamente...")

    pre_buffer = []
    buffer_fala = []

    falando = False
    frames_voz_seguidos = 0
    frames_silencio_seguidos = 0
    frames_falando_total = 0
    ja_sorteou_interrupcao = False
    vai_interromper = False

    interromper_usuario.clear()

    try:
        with sd.InputStream(
            samplerate=TAXA_AMOSTRAGEM,
            channels=1,
            dtype="int16",
            blocksize=FRAME_SIZE
        ) as stream:

            while True:
                if ia_falando.is_set():
                    falando = False
                    frames_voz_seguidos = 0
                    frames_silencio_seguidos = 0
                    frames_falando_total = 0
                    ja_sorteou_interrupcao = False
                    vai_interromper = False
                    pre_buffer.clear()
                    buffer_fala.clear()
                    time.sleep(0.05)
                    continue

                frame, _ = stream.read(FRAME_SIZE)
                frame = frame.flatten()

                tem_voz = frame_tem_voz(frame)

                if not falando:
                    pre_buffer.append(frame)
                    if len(pre_buffer) > PRE_BUFFER_FRAMES:
                        pre_buffer.pop(0)

                    if tem_voz:
                        frames_voz_seguidos += 1
                    else:
                        frames_voz_seguidos = 0

                    if frames_voz_seguidos >= MIN_FRAMES_VOZ_PARA_INICIAR:
                        falando = True
                        buffer_fala = pre_buffer.copy()
                        frames_silencio_seguidos = 0
                        frames_falando_total = 0
                        ja_sorteou_interrupcao = False
                        vai_interromper = False
                        print("🟢 Voz detectada, gravando frase...")

                else:
                    buffer_fala.append(frame)

                    if tem_voz:
                        frames_silencio_seguidos = 0
                        frames_falando_total += 1
                    else:
                        frames_silencio_seguidos += 1

                    if (
                        not ja_sorteou_interrupcao
                        and frames_falando_total >= MIN_FRAMES_ANTES_DE_INTERRUPPER
                    ):
                        chance = obter_chance_interrupcao_por_humor()
                        vai_interromper = random.random() < chance
                        ja_sorteou_interrupcao = True

                    if vai_interromper and tem_voz:
                        print("😈 IA decidiu te interromper.")
                        interromper_usuario.set()

                        audio_final = montar_audio_final(buffer_fala)
                        if audio_final is None:
                            print("⚠️ Áudio insuficiente para transcrição.")
                            return None

                        texto = transcrever_audio(audio_final, TAXA_AMOSTRAGEM)

                        if not texto:
                            print("⚠️ Não entendi nada.")
                            return None

                        return texto

                    if frames_silencio_seguidos >= MAX_FRAMES_SILENCIO_PARA_FINALIZAR:
                        print("🔴 Fim da frase detectado.")

                        audio_final = montar_audio_final(buffer_fala)
                        if audio_final is None:
                            print("⚠️ Áudio insuficiente para transcrição.")
                            return None

                        texto = transcrever_audio(audio_final, TAXA_AMOSTRAGEM)

                        if not texto:
                            print("⚠️ Não entendi nada.")
                            return None

                        return texto

    except Exception as e:
        print(f"Erro no modo live: {e}")
        return None