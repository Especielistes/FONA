"""Punto de entrada del servidor.

    uvicorn main:app --host 0.0.0.0 --port 8080
"""

import asyncio
import logging

from fastapi import FastAPI, HTTPException, WebSocket
from fastapi.responses import FileResponse
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

from fastapi.middleware.cors import CORSMiddleware

app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],  # demo local: cap risc real
    allow_methods=["*"],
    allow_headers=["*"],
)

# Gestión de sesión activa (reemplaza sesiones huérfanas al recibir una nueva llamada)
_current_session_task: asyncio.Task | None = None


@app.on_event("startup")
async def startup() -> None:
    notify.connect()
    # Precargamos Whisper para que la primera visita no espere
    await asyncio.to_thread(stt.load)
    log.info("Servidor listo")


@app.websocket("/portero")
async def portero(ws: WebSocket) -> None:
    global _current_session_task
    await ws.accept()

    # Si había una sesión anterior no finalizada (ej: recarga de página o llamada previa), la cancelamos limpiamente
    if _current_session_task and not _current_session_task.done():
        log.info("Cerrando sesión previa huérfana para conectar nueva llamada")
        _current_session_task.cancel()
        try:
            await _current_session_task
        except (asyncio.CancelledError, Exception):
            pass

    task = asyncio.current_task()
    _current_session_task = task

    log.info("Nueva sesión desde %s", ws.client)
    try:
        await asyncio.wait_for(session.run(ws), timeout=config.SESSION_TIMEOUT_S)
    except asyncio.CancelledError:
        log.info("Sesión cancelada por nueva conexión entrante")
    except asyncio.TimeoutError:
        log.info("Sesión cortada por tiempo máximo")
    finally:
        try:
            await ws.close()
        except RuntimeError:
            pass
        if _current_session_task is task:
            _current_session_task = None


# Frame de cámara en vivo para la pantalla de casa
LATEST_FRAME: str | None = None


@app.get("/camera/frame")
async def get_camera_frame():
    return {"image": LATEST_FRAME}


# ---------------------------------------------------------------------------
# API de confirmación. Integrable con Home Assistant vía REST o MQTT.
# ---------------------------------------------------------------------------

@app.get("/")
async def home():
    return FileResponse("../web/index.html")

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