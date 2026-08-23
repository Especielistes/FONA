"""Configuración central. Todo en un único sitio para no tener que buscar constantes."""

import os

# --- Red ---
HOST = "0.0.0.0"
PORT = 8080

# --- Audio ---
# Frecuencia única en todo el sistema: micrófono, STT y salida hacia el altavoz.
# Piper genera a otra frecuencia y se remuestrea en el servidor.
SAMPLE_RATE = 16000
FRAME_MS = 20  # webrtcvad solo acepta 10, 20 o 30 ms

# --- STT (faster-whisper) ---
STT_MODEL = os.getenv("STT_MODEL", "medium")  # "small" pierde nombres propios con ruido
STT_DEVICE = os.getenv("STT_DEVICE", "cuda")  # "cpu" si no hay GPU
STT_COMPUTE = os.getenv("STT_COMPUTE", "float16")  # "int8" en CPU
LANGUAGE = "es"

# --- TTS (Piper) ---
PIPER_BIN = os.getenv("PIPER_BIN", "piper")
PIPER_MODEL = os.getenv("PIPER_MODEL", "./voices/es_ES-davefx-medium.onnx")
PIPER_SAMPLE_RATE = 22050  # depende del modelo: comprobar en el .onnx.json

# --- LLM (Ollama) ---
OLLAMA_URL = os.getenv("OLLAMA_URL", "http://localhost:11434")
LLM_MODEL = os.getenv("LLM_MODEL", "qwen2.5:7b-instruct")
LLM_TEMPERATURE = 0.3
LLM_MAX_TOOL_ROUNDS = 4  # cortafuegos contra bucles de tool calling

# --- Sesión ---
UTTERANCE_SILENCE_MS = 800  # silencio que marca el final del turno del visitante
UTTERANCE_MAX_MS = 15000  # corte duro por si el VAD no detecta el final
UTTERANCE_MIN_SPEECH_MS = 300  # para descartar ruidos cortos
SESSION_TIMEOUT_S = 90  # duración máxima de una conversación
DOOR_CONFIRM_TIMEOUT_S = 45  # tiempo que esperamos la confirmación del residente

# --- Notificaciones ---
MQTT_ENABLED = os.getenv("MQTT_ENABLED", "0") == "1"
MQTT_HOST = os.getenv("MQTT_HOST", "localhost")
MQTT_PORT = int(os.getenv("MQTT_PORT", "1883"))
MQTT_TOPIC_PREFIX = "videoportero"

# --- Almacenamiento ---
DATA_DIR = os.getenv("DATA_DIR", "./data")