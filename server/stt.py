"""STT local con faster-whisper. El modelo se carga una sola vez."""

import logging

import numpy as np
from faster_whisper import WhisperModel

import config

log = logging.getLogger(__name__)
_model: WhisperModel | None = None


def load() -> None:
    """Carga el modelo. Llamarlo al arrancar para no pagarlo en la primera visita."""
    global _model
    if _model is None:
        log.info("Cargando Whisper %s (%s)...", config.STT_MODEL, config.STT_DEVICE)
        _model = WhisperModel(
            config.STT_MODEL,
            device=config.STT_DEVICE,
            compute_type=config.STT_COMPUTE,
        )


def transcribe(pcm: bytes) -> str:
    """Transcribe PCM de 16 bits mono a la frecuencia de config.SAMPLE_RATE."""
    load()
    audio = np.frombuffer(pcm, dtype=np.int16).astype(np.float32) / 32768.0

    segments, _info = _model.transcribe(
        audio,
        language=config.LANGUAGE,
        beam_size=1,  # greedy: priorizamos latencia sobre precisión
        vad_filter=False,  # ya hemos segmentado nosotros con webrtcvad
        condition_on_previous_text=False,  # evita bucles de alucinación
    )

    parts = []
    for segment in segments:
        text = segment.text.strip()
        if text:
            parts.append(text)

    return " ".join(parts).strip()