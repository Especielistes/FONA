"""Punto de entrada del servidor.

    uvicorn main:app --host 0.0.0.0 --port 8080
"""

import asyncio
import logging

from fastapi import FastAPI, HTTPException, WebSocket

import config
import notify
import session
import stt
import tools

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s %(levelname)-7s %(name)s: %(message)s",
)
log = logging.getLogger("videoportero")

app = FastAPI(title="Videoportero accesible")

# Una sola conversación a la vez: hay un solo portero y una sola GPU.
_session_lock = asyncio.Lock()


@app.on_event("startup")
async def startup() -> None:
    notify.connect()
    # Precargamos Whisper para que la primera visita no espere 20 segundos.
    await asyncio.to_thread(stt.load)
    log.info("Servidor listo")


@app.websocket("/portero")
async def portero(ws: WebSocket) -> None:
    await ws.accept()

    if _session_lock.locked():
        log.warning("Ya hay una sesión activa; se rechaza la conexión")
        await ws.close(code=1013)  # try again later
        return

    async with _session_lock:
        log.info("Nueva sesión desde %s", ws.client)
        try:
            await asyncio.wait_for(session.run(ws), timeout=config.SESSION_TIMEOUT_S)
        except asyncio.TimeoutError:
            log.info("Sesión cortada por tiempo máximo")
        finally:
            try:
                await ws.close()
            except RuntimeError:
                pass


# ---------------------------------------------------------------------------
# API de confirmación. Integrable con Home Assistant vía REST o MQTT.
# ---------------------------------------------------------------------------

@app.get("/pending")
async def pending() -> list[dict]:
    return [request.to_dict() for request in tools.PENDING.values()]


@app.post("/pending/{request_id}/approve")
async def approve(request_id: str) -> dict:
    return _resolve(request_id, approved=True)


@app.post("/pending/{request_id}/deny")
async def deny(request_id: str) -> dict:
    return _resolve(request_id, approved=False)


def _resolve(request_id: str, approved: bool) -> dict:
    request = tools.PENDING.get(request_id)
    if request is None:
        raise HTTPException(status_code=404, detail="Petición inexistente o caducada")
    request.resolve(approved)
    return {"id": request_id, "approved": approved}