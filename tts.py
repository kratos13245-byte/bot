import os
import re
import queue
import threading
import random
import time

import numpy as np
import sounddevice as sd
import torch

from TTS.tts.configs.xtts_config import XttsConfig
from TTS.tts.models.xtts import Xtts
from state import ia_falando

MODELO_DIR = os.path.expanduser(
    r"~\AppData\Local\tts\tts_models--multilingual--multi-dataset--xtts_v2"
)

ARQUIVO_VOZ = "voz_referencia.wav"
IDIOMA_PADRAO = "pt"

BUFFER_MIN = 5
MAX_CHARS = 180
SAMPLE_RATE = 24000
MIN_AMOSTRAS_CHUNK = 2048

PAUSA_ENTRE_PARTES = 0.05
PAUSA_FIM_FRASE = 0.12
USAR_PAUSAS_NATURAIS = True

EMOCAO_AUTOMATICA = True

EMOCOES_DISPONIVEIS = [
    "normal",
    "amor",
    "choro",
    "irritada",
    "animada",
    "negar",
    "choque",
]

# =========================
# LIPSYNC
# =========================
MOUTH_GAIN = 2.2
MOUTH_FLOOR = 0.06
MOUTH_ATTACK = 0.55      # sobe rápido
MOUTH_RELEASE = 0.28     # desce relativamente rápido
MOUTH_MAX_DELTA = 0.35   # limita salto brusco
MOUTH_HOLD_BOOST = 0.03  # segura um tiquinho quando abre
# =========================

device = "cuda" if torch.cuda.is_available() else "cpu"

print(f"Carregando XTTS streaming em {device}...")

config = XttsConfig()
config.load_json(os.path.join(MODELO_DIR, "config.json"))

tts = Xtts.init_from_config(config)
tts.load_checkpoint(config, checkpoint_dir=MODELO_DIR, use_deepspeed=False)
tts.to(device)

print("XTTS streaming carregado 🔊")

_cached_speaker_wav = None
_cached_gpt_cond_latent = None
_cached_speaker_embedding = None


def _normalizar_audio_chunk(chunk):
    audio = np.asarray(chunk, dtype=np.float32)

    if audio.ndim == 1:
        audio = audio.reshape(-1, 1)

    return audio


def _criar_silencio(segundos, sample_rate):
    quantidade = max(1, int(segundos * sample_rate))
    return np.zeros((quantidade, 1), dtype=np.float32)


def _calcular_mouth_target(audio: np.ndarray) -> float:
    if audio.size == 0:
        return 0.0

    mono = audio.flatten()
    rms = float(np.sqrt(np.mean(np.square(mono))))

    value = rms * MOUTH_GAIN
    value = value / (value + 0.45)

    if value < MOUTH_FLOOR:
        return 0.0

    return max(0.0, min(1.0, value))


def _suavizar_mouth(current: float, target: float) -> float:
    if target > current:
        # ataque rápido
        new_value = current + (target - current) * MOUTH_ATTACK
        new_value += MOUTH_HOLD_BOOST
    else:
        # release mais firme
        new_value = current + (target - current) * MOUTH_RELEASE

    # limita saltos muito grandes
    delta = new_value - current
    if delta > MOUTH_MAX_DELTA:
        new_value = current + MOUTH_MAX_DELTA
    elif delta < -MOUTH_MAX_DELTA:
        new_value = current - MOUTH_MAX_DELTA

    return max(0.0, min(1.0, new_value))


def _enviar_boca_por_audio(avatar, audio, current_mouth):
    if not avatar:
        return current_mouth

    target = _calcular_mouth_target(audio)
    current_mouth = _suavizar_mouth(current_mouth, target)

    # se o target zerou, força fechamento mais convincente
    if target == 0.0 and current_mouth < 0.08:
        current_mouth = 0.0

    avatar.set_mouth_value(current_mouth)
    return current_mouth


def _play_audio_worker(audio_queue, sample_rate, avatar=None):
    stream = sd.OutputStream(
        samplerate=sample_rate,
        channels=1,
        dtype="float32"
    )
    stream.start()

    buffer_inicial = []
    acumulador = []
    current_mouth = 0.0

    try:
        while True:
            item = audio_queue.get()

            if item is None:
                break

            audio = _normalizar_audio_chunk(item)

            if len(buffer_inicial) < BUFFER_MIN:
                buffer_inicial.append(audio)
                continue

            if buffer_inicial:
                for buffered_chunk in buffer_inicial:
                    stream.write(buffered_chunk)
                    current_mouth = _enviar_boca_por_audio(avatar, buffered_chunk, current_mouth)
                buffer_inicial.clear()

            acumulador.append(audio)
            total_amostras = sum(chunk.shape[0] for chunk in acumulador)

            if total_amostras >= MIN_AMOSTRAS_CHUNK:
                audio_final = np.concatenate(acumulador, axis=0)
                stream.write(audio_final)
                current_mouth = _enviar_boca_por_audio(avatar, audio_final, current_mouth)
                acumulador.clear()

        if buffer_inicial:
            for buffered_chunk in buffer_inicial:
                stream.write(buffered_chunk)
                current_mouth = _enviar_boca_por_audio(avatar, buffered_chunk, current_mouth)

        if acumulador:
            audio_final = np.concatenate(acumulador, axis=0)
            stream.write(audio_final)
            current_mouth = _enviar_boca_por_audio(avatar, audio_final, current_mouth)

    finally:
        if avatar:
            # fechamento suave rápido no final
            for _ in range(3):
                current_mouth = _suavizar_mouth(current_mouth, 0.0)
                if current_mouth < 0.05:
                    current_mouth = 0.0
                avatar.set_mouth_value(current_mouth)
                time.sleep(0.02)
            avatar.set_mouth_value(0.0)

        stream.stop()
        stream.close()


def _dividir_texto_por_pontuacao(texto):
    partes = re.split(r'(?<=[\.\!\?\;\:])\s+', texto.strip())
    return [p.strip() for p in partes if p.strip()]


def _quebrar_parte_longa(texto, max_chars=MAX_CHARS):
    palavras = texto.split()
    partes = []
    atual = ""

    for palavra in palavras:
        if len(atual) + len(palavra) + 1 <= max_chars:
            atual += (" " if atual else "") + palavra
        else:
            if atual:
                partes.append(atual)
            atual = palavra

    if atual:
        partes.append(atual)

    return partes


def dividir_texto(texto, max_chars=MAX_CHARS):
    partes_finais = []

    for parte in _dividir_texto_por_pontuacao(texto):
        if len(parte) <= max_chars:
            partes_finais.append(parte)
        else:
            partes_finais.extend(_quebrar_parte_longa(parte, max_chars=max_chars))

    return partes_finais


def _carregar_condicionamento(speaker_wav):
    global _cached_speaker_wav
    global _cached_gpt_cond_latent
    global _cached_speaker_embedding

    if (
        _cached_speaker_wav == speaker_wav
        and _cached_gpt_cond_latent is not None
        and _cached_speaker_embedding is not None
    ):
        return _cached_gpt_cond_latent, _cached_speaker_embedding

    print("🧠 Processando voz de referência...")

    gpt_cond_latent, speaker_embedding = tts.get_conditioning_latents(
        audio_path=speaker_wav
    )

    _cached_speaker_wav = speaker_wav
    _cached_gpt_cond_latent = gpt_cond_latent
    _cached_speaker_embedding = speaker_embedding

    return gpt_cond_latent, speaker_embedding


def _pausa_para_parte(parte):
    if not USAR_PAUSAS_NATURAIS:
        return 0.0

    parte = parte.strip()

    if not parte:
        return 0.0

    if parte.endswith((".", "!", "?")):
        return PAUSA_FIM_FRASE

    return PAUSA_ENTRE_PARTES


def escolher_emocao_automatica():
    return random.choice(EMOCOES_DISPONIVEIS)


def aplicar_emocao(texto, emocao="normal"):
    texto = texto.strip()

    if not texto:
        return texto

    if emocao == "normal":
        return texto

    if emocao == "amor":
        if not texto.endswith(("...", "!", "?")):
            texto += "..."
        return texto

    if emocao == "choro":
        texto = "..." + texto
        if not texto.endswith(("...", "!", "?")):
            texto += "..."
        return texto

    if emocao == "irritada":
        texto = texto.replace(" por favor", "")
        texto = texto.replace("se quiser", "")
        if texto.endswith("..."):
            texto = texto[:-3]
        if not texto.endswith(("!", "?")):
            texto += "."
        return texto

    if emocao == "animada":
        if not texto.endswith(("!", "?")):
            texto += "!"
        return texto

    if emocao == "negar":
        prefixos = [
            "aham, tá. ",
            "não. ",
            "claro que não. ",
            "senta lá. ",
        ]
        return random.choice(prefixos) + texto[:1].lower() + texto[1:] if len(texto) > 1 else random.choice(prefixos) + texto.lower()

    if emocao == "choque":
        if not texto.endswith(("!", "?")):
            texto += "!"
        return texto

    return texto


def falar(
    texto,
    speaker_wav=ARQUIVO_VOZ,
    language=IDIOMA_PADRAO,
    emocao="auto",
    on_start=None,
    on_end=None,
    avatar=None,
):
    if not texto:
        return

    if not os.path.exists(speaker_wav):
        print(f"Arquivo de voz não encontrado: {speaker_wav}")
        return

    try:
        ia_falando.set()

        if on_start:
            on_start()

        if emocao == "auto":
            emocao_escolhida = escolher_emocao_automatica() if EMOCAO_AUTOMATICA else "normal"
        else:
            emocao_escolhida = emocao

        texto = aplicar_emocao(texto, emocao_escolhida)
        print(f"🎭 Emoção usada: {emocao_escolhida}")

        partes = dividir_texto(texto, max_chars=MAX_CHARS)

        if not partes:
            return

        gpt_cond_latent, speaker_embedding = _carregar_condicionamento(speaker_wav)

        audio_queue = queue.Queue()
        player = threading.Thread(
            target=_play_audio_worker,
            args=(audio_queue, SAMPLE_RATE, avatar),
            daemon=True
        )
        player.start()

        print("🔊 Gerando fala em streaming...")

        for i, parte in enumerate(partes):
            chunks = tts.inference_stream(
                text=parte,
                language=language,
                gpt_cond_latent=gpt_cond_latent,
                speaker_embedding=speaker_embedding,
            )

            for chunk in chunks:
                if isinstance(chunk, torch.Tensor):
                    chunk = chunk.detach().cpu().numpy()

                audio_queue.put(chunk)

            if i < len(partes) - 1:
                pausa = _pausa_para_parte(parte)
                if pausa > 0:
                    audio_queue.put(_criar_silencio(pausa, SAMPLE_RATE))

        audio_queue.put(None)
        player.join()

    except Exception as e:
        print(f"Erro no TTS streaming: {e}")

    finally:
        if avatar:
            avatar.set_mouth_value(0.0)
        if on_end:
            on_end()
        ia_falando.clear()