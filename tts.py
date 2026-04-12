import io
import numbers
import os
import random
import re
import time
import wave

import numpy as np
import requests

from state import ia_falando

if os.name == "nt":
    _default_xtts_dir = r"~\AppData\Local\tts\tts_models--multilingual--multi-dataset--xtts_v2"
else:
    _default_xtts_dir = "~/.local/share/tts/tts_models--multilingual--multi-dataset--xtts_v2"

MODELO_DIR = os.path.expanduser(os.getenv("XTTS_MODEL_DIR", _default_xtts_dir))
REMOTE_TTS_URL = os.getenv("REMOTE_TTS_URL", "").strip()

ARQUIVO_VOZ = "voz_referencia.wav"
IDIOMA_PADRAO = "pt"

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

# lipsync
MOUTH_GAIN = 2.2
MOUTH_FLOOR = 0.06
MOUTH_ATTACK = 0.55
MOUTH_RELEASE = 0.28
MOUTH_MAX_DELTA = 0.35
MOUTH_HOLD_BOOST = 0.03

# lazy loaded local XTTS
_tts_loaded = False
_tts = None
_torch = None
_cached_speaker_wav = None
_cached_gpt_cond_latent = None
_cached_speaker_embedding = None


def _patch_torch_isin_kwarg(torch_module):
    # compat between torch/transformers versions that expect test_element vs test_elements
    original_isin = torch_module.isin
    try:
        original_isin(elements=torch_module.tensor([1]), test_elements=1)
        return
    except TypeError:
        pass

    def _isin_compat(*args, **kwargs):
        elements = kwargs.get("elements", args[0] if args else None)

        # transformers may call with keyword test_elements in versions where torch expects test_element
        if "test_elements" in kwargs and "test_element" not in kwargs:
            kwargs["test_element"] = kwargs.pop("test_elements")

        test_element = kwargs.get("test_element", None)

        # Some torch versions do not accept Number/Number, but do accept Number/Tensor.
        if isinstance(elements, numbers.Number) and isinstance(test_element, numbers.Number):
            kwargs.pop("test_element", None)
            kwargs["test_elements"] = torch_module.tensor([test_element])

        return original_isin(*args, **kwargs)

    torch_module.isin = _isin_compat


def _resolver_remote_tts_url():
    raw = os.getenv("REMOTE_TTS_URL", REMOTE_TTS_URL).strip()
    if not raw:
        return ""
    raw = raw.rstrip("/")
    if raw.endswith("/tts"):
        return raw
    return raw + "/tts"


def _ensure_tts_loaded():
    global _tts_loaded, _tts, _torch
    if _tts_loaded:
        return

    import torch
    from TTS.tts.configs.xtts_config import XttsConfig
    from TTS.tts.models.xtts import Xtts

    _patch_torch_isin_kwarg(torch)

    device = "cuda" if torch.cuda.is_available() else "cpu"
    print(f"Carregando XTTS streaming em {device}...")

    config_path = os.path.join(MODELO_DIR, "config.json")
    if not os.path.exists(config_path):
        raise FileNotFoundError(
            f"Modelo XTTS nao encontrado em {MODELO_DIR}. "
            "Defina XTTS_MODEL_DIR corretamente ou baixe o modelo xtts_v2 neste caminho."
        )

    config = XttsConfig()
    config.load_json(config_path)

    _tts = Xtts.init_from_config(config)
    _tts.load_checkpoint(config, checkpoint_dir=MODELO_DIR, use_deepspeed=False)
    _tts.to(device)

    _torch = torch
    _tts_loaded = True
    print("XTTS streaming carregado")


def _normalizar_audio_chunk(chunk):
    audio = np.asarray(chunk, dtype=np.float32)
    if audio.ndim == 1:
        audio = audio.reshape(-1, 1)
    return audio


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
        new_value = current + (target - current) * MOUTH_ATTACK
        new_value += MOUTH_HOLD_BOOST
    else:
        new_value = current + (target - current) * MOUTH_RELEASE

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
    if target == 0.0 and current_mouth < 0.08:
        current_mouth = 0.0
    avatar.set_mouth_value(current_mouth)
    return current_mouth


def _play_audio_array(audio: np.ndarray, sample_rate: int, avatar=None):
    import sounddevice as sd

    audio = _normalizar_audio_chunk(audio)
    stream = sd.OutputStream(samplerate=sample_rate, channels=1, dtype="float32")
    stream.start()
    current_mouth = 0.0
    try:
        start = 0
        total = audio.shape[0]
        while start < total:
            end = min(start + MIN_AMOSTRAS_CHUNK, total)
            chunk = audio[start:end]
            stream.write(chunk)
            current_mouth = _enviar_boca_por_audio(avatar, chunk, current_mouth)
            start = end
    finally:
        if avatar:
            for _ in range(3):
                current_mouth = _suavizar_mouth(current_mouth, 0.0)
                if current_mouth < 0.05:
                    current_mouth = 0.0
                avatar.set_mouth_value(current_mouth)
                time.sleep(0.02)
            avatar.set_mouth_value(0.0)
        stream.stop()
        stream.close()


def _wav_bytes_to_audio_array(wav_bytes: bytes):
    with wave.open(io.BytesIO(wav_bytes), "rb") as wf:
        nchannels = wf.getnchannels()
        sample_width = wf.getsampwidth()
        sample_rate = wf.getframerate()
        frames = wf.readframes(wf.getnframes())

    if sample_width == 2:
        data = np.frombuffer(frames, dtype=np.int16).astype(np.float32) / 32768.0
    elif sample_width == 4:
        data = np.frombuffer(frames, dtype=np.int32).astype(np.float32) / 2147483648.0
    elif sample_width == 1:
        data = (np.frombuffer(frames, dtype=np.uint8).astype(np.float32) - 128.0) / 128.0
    else:
        raise ValueError(f"sample width nao suportado: {sample_width}")

    if nchannels > 1:
        data = data.reshape(-1, nchannels).mean(axis=1)

    return data.reshape(-1, 1), sample_rate


def _audio_array_to_wav_bytes(audio: np.ndarray, sample_rate: int):
    audio = np.asarray(audio, dtype=np.float32).reshape(-1)
    audio = np.clip(audio, -1.0, 1.0)
    pcm16 = (audio * 32767.0).astype(np.int16)

    buf = io.BytesIO()
    with wave.open(buf, "wb") as wf:
        wf.setnchannels(1)
        wf.setsampwidth(2)
        wf.setframerate(sample_rate)
        wf.writeframes(pcm16.tobytes())
    return buf.getvalue()


def _dividir_texto_por_pontuacao(texto):
    partes = re.split(r"(?<=[\.\!\?\;\:])\s+", texto.strip())
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
    global _cached_speaker_wav, _cached_gpt_cond_latent, _cached_speaker_embedding

    if (
        _cached_speaker_wav == speaker_wav
        and _cached_gpt_cond_latent is not None
        and _cached_speaker_embedding is not None
    ):
        return _cached_gpt_cond_latent, _cached_speaker_embedding

    _ensure_tts_loaded()
    print("Processando voz de referencia...")
    gpt_cond_latent, speaker_embedding = _tts.get_conditioning_latents(audio_path=speaker_wav)
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
        prefixos = ["aham, ta. ", "nao. ", "claro que nao. ", "senta la. "]
        if len(texto) > 1:
            return random.choice(prefixos) + texto[:1].lower() + texto[1:]
        return random.choice(prefixos) + texto.lower()
    if emocao == "choque":
        if not texto.endswith(("!", "?")):
            texto += "!"
        return texto
    return texto


def gerar_audio_array_local(
    texto,
    speaker_wav=ARQUIVO_VOZ,
    language=IDIOMA_PADRAO,
    emocao="auto",
):
    if not texto:
        return np.zeros((1, 1), dtype=np.float32), SAMPLE_RATE, "normal"

    if not os.path.exists(speaker_wav):
        raise FileNotFoundError(f"Arquivo de voz nao encontrado: {speaker_wav}")

    if emocao == "auto":
        emocao_escolhida = escolher_emocao_automatica() if EMOCAO_AUTOMATICA else "normal"
    else:
        emocao_escolhida = emocao

    texto = aplicar_emocao(texto, emocao_escolhida)
    partes = dividir_texto(texto, max_chars=MAX_CHARS)
    gpt_cond_latent, speaker_embedding = _carregar_condicionamento(speaker_wav)

    pedacos = []
    for i, parte in enumerate(partes):
        chunks = _tts.inference_stream(
            text=parte,
            language=language,
            gpt_cond_latent=gpt_cond_latent,
            speaker_embedding=speaker_embedding,
        )
        for chunk in chunks:
            if isinstance(chunk, _torch.Tensor):
                chunk = chunk.detach().cpu().numpy()
            pedacos.append(_normalizar_audio_chunk(chunk))

        if i < len(partes) - 1:
            pausa = _pausa_para_parte(parte)
            if pausa > 0:
                quantidade = max(1, int(pausa * SAMPLE_RATE))
                pedacos.append(np.zeros((quantidade, 1), dtype=np.float32))

    if not pedacos:
        return np.zeros((1, 1), dtype=np.float32), SAMPLE_RATE, emocao_escolhida

    audio = np.concatenate(pedacos, axis=0)
    return audio, SAMPLE_RATE, emocao_escolhida


def gerar_audio_wav_bytes(
    texto,
    speaker_wav=ARQUIVO_VOZ,
    language=IDIOMA_PADRAO,
    emocao="auto",
):
    audio, sample_rate, emocao_escolhida = gerar_audio_array_local(
        texto=texto,
        speaker_wav=speaker_wav,
        language=language,
        emocao=emocao,
    )
    return _audio_array_to_wav_bytes(audio, sample_rate), emocao_escolhida


def _falar_remoto(texto, language=IDIOMA_PADRAO, emocao="auto", avatar=None):
    url = _resolver_remote_tts_url()
    if not url:
        raise RuntimeError("REMOTE_TTS_URL nao configurado para TTS remoto.")

    payload = {
        "text": texto,
        "texto": texto,
        "language": language,
        "emotion": emocao,
        "emocao": emocao,
    }

    resp = requests.post(url, json=payload, timeout=240)
    resp.raise_for_status()

    audio, sample_rate = _wav_bytes_to_audio_array(resp.content)
    _play_audio_array(audio, sample_rate, avatar=avatar)


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

    try:
        ia_falando.set()
        if on_start:
            on_start()

        remote_url = _resolver_remote_tts_url()
        if remote_url:
            print("Reproduzindo TTS remoto...")
            _falar_remoto(texto=texto, language=language, emocao=emocao, avatar=avatar)
            return

        print("Reproduzindo TTS local...")
        audio, sample_rate, emocao_escolhida = gerar_audio_array_local(
            texto=texto,
            speaker_wav=speaker_wav,
            language=language,
            emocao=emocao,
        )
        print(f"Emocao usada: {emocao_escolhida}")
        _play_audio_array(audio, sample_rate, avatar=avatar)

    except Exception as e:
        print(f"Erro no TTS: {e}")

    finally:
        if avatar:
            avatar.set_mouth_value(0.0)
        if on_end:
            on_end()
        ia_falando.clear()
