# FONA
# Videoportero accesible

Prototipo de videoportero que permite comunicarse en tres modalidades —voz, texto
y lengua de signos— sin que el visitante ni el residente tengan que adaptarse a
una sola. Todo lo que se dice aparece siempre en pantalla como texto.

```
entrada: voz | signos | teclado  →  TEXTO  →  salida: texto siempre + voz si procede
```

## Estado del proyecto

Prueba de concepto. El reconocimiento de signos funciona con un **vocabulario
cerrado de signos estáticos**, no con lengua de signos continua. No incluye
signos con movimiento ni expresión facial, que son parte de la gramática de la
lengua de signos española.

## Estructura

```
server/                  backend Python
  config.py              configuración central
  audio.py               segmentación de voz (VAD)
  stt.py                 transcripción con faster-whisper
  tts.py                 síntesis con Piper
  llm.py                 cliente de Ollama y tool calling
  tools.py               acciones que el modelo puede solicitar
  notify.py              avisos al residente (log o MQTT)
  session.py             orquestación de la conversación
  main.py                servidor FastAPI
tools/
  gesture_trainer.html   grabación de muestras y validación del clasificador
client_pc.py             cliente de consola para probar el backend
firmware/                opcional, solo si se monta el dispositivo físico
```

## Reconocimiento de signos

MediaPipe Hands extrae 21 puntos por mano. Cada muestra se normaliza (origen en
la muñeca, escala invariante a la distancia) y se concatena en un vector de 128
dimensiones. La clasificación es un **k-NN con k=5** sobre las muestras grabadas:
sin entrenamiento, sin dependencias de ML y suficiente para signos estáticos.

Para grabar el vocabulario:

```bash
cd tools
python -m http.server 8000
# abrir http://localhost:8000/gesture_trainer.html
```

La cámara no funciona abriendo el archivo con doble clic: Chrome bloquea
`getUserMedia` en `file://`. Hay que servirlo por HTTP.

## Backend

```bash
cd server
python -m venv .venv && .venv\Scripts\activate
pip install -r requirements.txt
```

Modelo de lenguaje:

```bash
ollama pull qwen2.5:7b-instruct
```

Voz de Piper (castellano):

```bash
mkdir voices
# descargar es_ES-davefx-medium.onnx y su .onnx.json del repositorio de voces de Piper
```

Comprobar la frecuencia real de la voz en el `.onnx.json` (`audio.sample_rate`) y
ajustar `PIPER_SAMPLE_RATE` en `config.py`.

Arranque:

```bash
uvicorn main:app --host 0.0.0.0 --port 8080
```

Sin GPU:

```bash
set STT_DEVICE=cpu && set STT_COMPUTE=int8 && set STT_MODEL=small
uvicorn main:app --host 0.0.0.0 --port 8080
```

## Apertura de la puerta

El modelo **no puede abrir la puerta**. Cuando invoca `solicitar_apertura`, la
petición queda pendiente y el servidor espera hasta 45 segundos una confirmación
humana:

```bash
curl http://localhost:8080/pending
curl -X POST http://localhost:8080/pending/<id>/approve
```

Esta separación es deliberada: un modelo de lenguaje que conversa con
desconocidos es vulnerable a instrucciones maliciosas habladas, y la decisión de
franquear el acceso a una vivienda no debe depender de él.

## Añadir acciones nuevas

En `tools.py`, decorar una función asíncrona:

```python
@tool(
    description="Qué hace y cuándo debe usarse",
    params={"arg": {"type": "string", "description": "..."}},
    required=["arg"],
)
async def mi_funcion(ctx: dict, arg: str) -> str:
    return "Resultado que verá el modelo"
```

El esquema JSON y el registro se generan solos. Con `ends_session=True` la
conversación termina tras ejecutarla.

## Latencia

| Etapa | GPU | CPU |
|---|---|---|
| Whisper, 4 s de audio | ~0,4 s (medium) | ~3 s (small) |
| LLM 7B, 40 tokens | ~0,7 s | ~6 s |
| Piper | ~0,2 s | ~0,4 s |
| **Total por turno** | **~1,3 s** | **~10 s** |