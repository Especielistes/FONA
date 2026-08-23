"""TTS local con Piper.

Piper se invoca como subproceso y escribe PCM crudo en stdout. Se remuestrea a la
frecuencia del sistema para que el cliente tenga una única configuración de audio.
"""

import logging
import subprocess

import numpy as np
import soxr

import config

log = logging.getLogger(__name__)


def synthesize(text: str) -> bytes:
    """Devuelve PCM de 16 bits mono a config.SAMPLE_RATE. Bloqueante: llamar en un hilo."""
    if not text.strip():
        return b""

    result = subprocess.run(
        [config.PIPER_BIN, "--model", config.PIPER_MODEL, "--output_raw"],
        input=text.encode("utf-8"),
        capture_output=True,
        check=True,
    )

    pcm = np.frombuffer(result.stdout, dtype=np.int16)
    if len(pcm) == 0:
        log.warning("Piper no ha generado audio para: %r", text)
        return b""

    if config.PIPER_SAMPLE_RATE != config.SAMPLE_RATE:
        resampled = soxr.resample(
            pcm.astype(np.float32),
            config.PIPER_SAMPLE_RATE,
            config.SAMPLE_RATE,
        )
        pcm = np.clip(resampled, -32768, 32767).astype(np.int16)

    return pcm.tobytes()