import io
import logging
import wave
import httpx
import numpy as np
from faster_whisper import WhisperModel

import config

log = logging.getLogger(__name__)
_model: WhisperModel | None = None


def load() -> None:
    """Carga el modelo local en caso de no disponer de GROQ_API_KEY."""
    global _model
    if not config.GROQ_API_KEY and _model is None:
        log.info("Cargando Whisper local %s (%s)...", config.STT_MODEL, config.STT_DEVICE)
        _model = WhisperModel(
            config.STT_MODEL,
            device=config.STT_DEVICE,
            compute_type=config.STT_COMPUTE,
        )


def transcribe(pcm: bytes) -> str:
    """Transcribe PCM de 16 bits mono a la frecuencia de config.SAMPLE_RATE."""
    if not pcm or len(pcm) < 320:
        return ""

    # 1. Intentar usar Groq STT (ultra-rápido en nube, ~100ms)
    if config.GROQ_API_KEY:
        try:
            wav_io = io.BytesIO()
            with wave.open(wav_io, "wb") as wf:
                wf.setnchannels(1)
                wf.setsampwidth(2)
                wf.setframerate(config.SAMPLE_RATE)
                wf.writeframes(pcm)
            wav_bytes = wav_io.getvalue()

            headers = {"Authorization": f"Bearer {config.GROQ_API_KEY}"}
            files = {"file": ("audio.wav", wav_bytes, "audio/wav")}
            data = {"model": config.GROQ_STT_MODEL, "language": config.LANGUAGE}

            response = httpx.post(
                "https://api.groq.com/openai/v1/audio/transcriptions",
                headers=headers,
                files=files,
                data=data,
                timeout=10.0,
            )
            if response.status_code == 200:
                text = (response.json().get("text") or "").strip()
                log.info("STT (Groq): %s", text)
                return text
        except Exception as e:
            log.warning("Fallo en Groq STT, usando fallback local: %s", e)

    # 2. Fallback local (faster-whisper)
    load()
    if _model is None:
        return ""

    audio = np.frombuffer(pcm, dtype=np.int16).astype(np.float32) / 32768.0

    segments, _info = _model.transcribe(
        audio,
        language=config.LANGUAGE,
        beam_size=1,
        vad_filter=False,
        condition_on_previous_text=False,
    )

    parts = []
    for segment in segments:
        text = segment.text.strip()
        if text:
            parts.append(text)

    return " ".join(parts).strip()