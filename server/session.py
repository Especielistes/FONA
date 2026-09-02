"""Orquestación de una conversación completa con un visitante.

Protocolo WebSocket (cliente <-> servidor):

  cliente -> servidor
    binario : PCM 16 bits mono, 16 kHz
    texto   : {"type": "text", "content": "..."}   -- teclado o signos reconocidos
    texto   : {"type": "hangup"}                   -- el visitante ha colgado

  servidor -> cliente
    texto   : {"type": "state", "value": "listening" | "speaking"}
    texto   : {"type": "transcript", "role": "visitor"|"assistant", "content": "..."}
    binario : PCM 16 bits mono, 16 kHz para reproducir
    texto   : {"type": "open_door"}
    texto   : {"type": "bye"}

Los mensajes "transcript" son los que alimentan la pantalla: todo lo que se dice
aparece siempre en texto, sea cual sea la modalidad de entrada.
"""

import asyncio
import json
import logging

from fastapi import WebSocket, WebSocketDisconnect

import config
import llm
import stt
import tts
from audio import UtteranceDetector

log = logging.getLogger(__name__)

CHUNK_BYTES = 3200  # 100 ms por trama de envío


async def _send(ws: WebSocket, payload: dict) -> None:
    await ws.send_text(json.dumps(payload, ensure_ascii=False))


async def _speak(ws: WebSocket, text: str) -> None:
    """Envía el texto a pantalla y, si hay TTS, también el audio."""
    if not text:
        return

    log.info("ASISTENTE: %s", text)
    await _send(ws, {"type": "transcript", "role": "assistant", "content": text})

    pcm = await asyncio.to_thread(tts.synthesize, text)
    if not pcm:
        return

    await _send(ws, {"type": "state", "value": "speaking"})
    for offset in range(0, len(pcm), CHUNK_BYTES):
        await ws.send_bytes(pcm[offset:offset + CHUNK_BYTES])
    await _send(ws, {"type": "state", "value": "listening"})


async def _receive_input(ws: WebSocket, detector: UtteranceDetector) -> str | None:
    """Espera una entrada del visitante en cualquier modalidad.

    Devuelve el texto ya normalizado, o None si cuelga o se agota el tiempo.
    """
    while True:
        try:
            message = await asyncio.wait_for(ws.receive(), timeout=30.0)
        except asyncio.TimeoutError:
            log.info("Sin actividad durante 30 s")
            return None

        if message["type"] == "websocket.disconnect":
            return None

        # --- voz ---
        if message.get("bytes") is not None:
            utterance = detector.push(message["bytes"])
            if utterance is None:
                continue
            text = await asyncio.to_thread(stt.transcribe, utterance)
            if text:
                return text
            continue

        # --- texto o signos ---
        if message.get("text"):
            try:
                payload = json.loads(message["text"])
            except json.JSONDecodeError:
                continue

            if isinstance(payload, dict) and payload.get("image"):
                ctx["image"] = payload["image"]
                import main
                main.LATEST_FRAME = payload["image"]

            kind = payload.get("type") if isinstance(payload, dict) else None
            if kind == "hangup":
                return None
            
            if kind == "text":
                content = (payload.get("content") or "").strip()
                if not content:
                    continue
                # El texto que se muestra en pantalla es el del visitante; al
                # modelo le añadimos el contexto de la modalidad para que sepa
                # con qué puede contar el visitante para responderle.
                if payload.get("source") == "signs":
                    vocabulary = ", ".join(payload.get("vocabulary") or [])
                    annotated = (
                        f"{content}\n\n[Mensaje en lengua de signos. "
                        f"Vocabulario disponible: {vocabulary}]"
                    )
                else:
                    annotated = content

                return {"display": content, "model": annotated}


async def run(ws: WebSocket) -> None:
    """Gestiona una conversación de principio a fin."""
    detector = UtteranceDetector()
    messages: list[dict] = [{"role": "system", "content": llm.SYSTEM_PROMPT}]
    ctx: dict = {"open_door": False, "ws": ws}

    await _speak(ws, llm.GREETING)
    messages.append({"role": "assistant", "content": llm.GREETING})

    try:
        while True:
            entry = await _receive_input(ws, detector)
            if entry is None:
                break

            log.info("VISITANTE: %s", text)
            await _send(ws, {"type": "transcript", "role": "visitor", "content": text})
            messages.append({"role": "user", "content": text})

            reply, end_session = await llm.respond(messages, ctx)

            # ================================================================
            # APERTURA AUTORIZADA
            # ================================================================
            # La autorización del residente tiene prioridad absoluta sobre
            # cualquier respuesta que haya generado el LLM.
            #
            # No volvemos a consultar al LLM.
            # No usamos su respuesta.
            # Enviamos directamente la señal de apertura y "Pase."
            # ================================================================

            if ctx.get("open_door"):
                log.info("APERTURA AUTORIZADA: enviando orden al cliente")

                ctx["open_door"] = False

                # Primero avisamos al frontend para que abra visualmente
                # la puerta.
                await _send(ws, {"type": "open_door"})

                # Después decimos exactamente "Pase."
                await _speak(ws, "Pase.")

                # Cerramos la conversación.
                await _send(ws, {"type": "bye"})
                break

            # ================================================================
            # RESPUESTA NORMAL
            # ================================================================

            await _speak(ws, reply)

            if end_session:
                break

        await _send(ws, {"type": "bye"})

    except WebSocketDisconnect:
        log.info("El cliente se ha desconectado")
    except Exception:
        log.exception("Error durante la sesión")