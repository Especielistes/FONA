"""Segmentación del audio entrante en enunciados.

Detección de voz por energía del señal (RMS) con umbral adaptativo. Se eligió
esta vía en lugar de webrtcvad para no depender de una extensión en C, que
requiere compilador en Windows y no tiene ruedas para las versiones más
recientes de Python.

Es menos robusta que webrtcvad con ruido de fondo constante, pero suficiente
para un micrófono cercano en un entorno controlado.
"""

import numpy as np

import config

FRAME_SAMPLES = int(config.SAMPLE_RATE * config.FRAME_MS / 1000)
FRAME_BYTES = FRAME_SAMPLES * 2  # 16 bits mono
PREBUFFER_FRAMES = 10  # ~200 ms antes del inicio de la voz, para no cortar sílabas

# --- Parámetros de detección ---
# Si el asistente se dispara con el ruido de fondo, sube MIN_RMS.
# Si no detecta que hablas, bájalo. Los valores son sobre muestras int16.
MIN_RMS = 300.0            # suelo absoluto: por debajo nunca es voz
NOISE_MULTIPLIER = 3.0     # cuántas veces el ruido de fondo para considerar voz
HYSTERESIS = 0.6           # el final se detecta a un umbral más bajo que el inicio
NOISE_ADAPT_RATE = 0.05    # velocidad a la que se recalibra el ruido de fondo


def frame_rms(frame: bytes) -> float:
    samples = np.frombuffer(frame, dtype=np.int16).astype(np.float32)
    if samples.size == 0:
        return 0.0
    return float(np.sqrt(np.mean(samples * samples)))


class UtteranceDetector:
    """Acumula PCM y devuelve el enunciado completo cuando detecta el final.

    Uso:
        det = UtteranceDetector()
        for chunk in stream:
            utt = det.push(chunk)
            if utt is not None:
                transcribir(utt)
    """

    def __init__(self, min_rms: float = MIN_RMS):
        self.min_rms = min_rms
        self.noise_rms = min_rms  # se recalibra sola con el silencio real
        self.reset()

    def reset(self) -> None:
        self._leftover = b""
        self._prebuffer: list[bytes] = []
        self._voiced: list[bytes] = []
        self._silence_ms = 0
        self._speech_ms = 0
        self._in_speech = False

    def _thresholds(self) -> tuple[float, float]:
        """Umbral de entrada y de salida. El de salida es más bajo (histéresis)
        para que una pausa breve dentro de una frase no la corte."""
        enter = max(self.min_rms, self.noise_rms * NOISE_MULTIPLIER)
        return enter, enter * HYSTERESIS

    def push(self, chunk: bytes) -> bytes | None:
        """Devuelve los bytes del enunciado si ha terminado, o None si sigue hablando."""
        data = self._leftover + chunk
        offset = 0

        while offset + FRAME_BYTES <= len(data):
            frame = data[offset:offset + FRAME_BYTES]
            offset += FRAME_BYTES

            rms = frame_rms(frame)
            enter_threshold, exit_threshold = self._thresholds()

            if not self._in_speech:
                # Recalibramos el ruido de fondo solo cuando no hay voz.
                self.noise_rms += NOISE_ADAPT_RATE * (rms - self.noise_rms)

                # Ventana deslizante para no perder el arranque de la primera sílaba.
                self._prebuffer.append(frame)
                if len(self._prebuffer) > PREBUFFER_FRAMES:
                    self._prebuffer.pop(0)

                if rms > enter_threshold:
                    self._in_speech = True
                    self._voiced = list(self._prebuffer)
                    self._voiced.append(frame)
                    self._speech_ms = config.FRAME_MS
                    self._silence_ms = 0
                continue

            # Ya estamos dentro de un enunciado.
            self._voiced.append(frame)
            if rms > exit_threshold:
                self._speech_ms += config.FRAME_MS
                self._silence_ms = 0
            else:
                self._silence_ms += config.FRAME_MS

            total_ms = len(self._voiced) * config.FRAME_MS
            finished = (
                self._silence_ms >= config.UTTERANCE_SILENCE_MS
                or total_ms >= config.UTTERANCE_MAX_MS
            )

            if finished:
                utterance = b"".join(self._voiced)
                enough_speech = self._speech_ms >= config.UTTERANCE_MIN_SPEECH_MS
                noise_estimate = self.noise_rms
                self._leftover = data[offset:]
                self.reset()
                self.noise_rms = noise_estimate  # la calibración se conserva
                # Descartamos ruidos cortos (una puerta, un coche) sin molestar al LLM.
                return utterance if enough_speech else None

        self._leftover = data[offset:]
        return None