"""Registro de herramientas que el LLM puede invocar.

Para añadir una función nueva solo hay que decorarla con @tool. El esquema JSON se
genera a partir de los argumentos que declares aquí; no hay que tocar nada más.
"""

import asyncio
import json
import logging
import os
import time
import uuid
from typing import Awaitable, Callable

import config
import notify

log = logging.getLogger(__name__)

# name -> {"schema": dict, "fn": callable, "ends_session": bool}
REGISTRY: dict[str, dict] = {}


def tool(description: str, params: dict, required: list[str], ends_session: bool = False):
    """Decorador para registrar una herramienta.

    params: {"nombre_arg": {"type": "string", "description": "..."}}
    """

    def decorator(fn: Callable[..., Awaitable[str]]):
        REGISTRY[fn.__name__] = {
            "schema": {
                "type": "function",
                "function": {
                    "name": fn.__name__,
                    "description": description,
                    "parameters": {
                        "type": "object",
                        "properties": params,
                        "required": required,
                    },
                },
            },
            "fn": fn,
            "ends_session": ends_session,
        }
        return fn

    return decorator


def schemas() -> list[dict]:
    return [entry["schema"] for entry in REGISTRY.values()]


async def execute(name: str, arguments: dict | str, ctx: dict) -> tuple[str, bool]:
    """Ejecuta una herramienta. Devuelve (resultado_textual, hay_que_terminar_sesion)."""
    entry = REGISTRY.get(name)
    if entry is None:
        log.warning("El modelo ha pedido una herramienta inexistente: %s", name)
        return f"Error: la herramienta '{name}' no existe.", False

    # 1. Asegurar que los argumentos sean un diccionario Python
    if isinstance(arguments, str):
        try:
            arguments = json.loads(arguments)
        except Exception:
            arguments = {}

    if not isinstance(arguments, dict):
        arguments = {}

    # 2. Si vienen anidados en 'parameters'
    if "parameters" in arguments and isinstance(arguments["parameters"], dict):
        arguments = arguments["parameters"]

    # 3. Invocar la función de forma limpia
    fn = entry["fn"]
    try:
        kwargs = dict(arguments)
        kwargs["ctx"] = ctx
        result = await fn(**kwargs)
    except TypeError:
        try:
            kwargs.pop("ctx", None)
            result = await fn(**kwargs)
        except Exception as exc:
            log.warning("Error de argumentos en %s (%s): %s", name, arguments, exc)
            # Fallback seguro para solicitar_apertura y notificar_residente
            visitante = str(arguments.get("visitante") or arguments.get("name") or "Visitante")
            motivo = str(arguments.get("motivo") or arguments.get("reason") or "Desea entrar")
            try:
                result = await fn(ctx=ctx, visitante=visitante, motivo=motivo)
            except Exception:
                return f"Error de argumentos: {exc}", False
    except Exception as exc:
        log.exception("Error ejecutando %s", name)
        return f"Error interno ejecutando la herramienta: {exc}", False

    return result, entry["ends_session"]


# ---------------------------------------------------------------------------
# Peticiones de apertura pendientes de confirmación humana
# ---------------------------------------------------------------------------

class PendingRequest:
    def __init__(self, motivo: str, visitante: str, image: str | None = None):
        self.id = uuid.uuid4().hex[:8]
        self.motivo = motivo
        self.visitante = visitante
        self.image = image
        self.created_at = time.time()
        self.approved: bool | None = None
        self.event = asyncio.Event()

    def resolve(self, approved: bool) -> None:
        self.approved = approved
        self.event.set()

    def to_dict(self) -> dict:
        return {
            "id": self.id,
            "visitante": self.visitante,
            "motivo": self.motivo,
            "image": self.image,
            "created_at": self.created_at,
            "approved": self.approved,
        }


PENDING: dict[str, PendingRequest] = {}


# ---------------------------------------------------------------------------
# Herramientas
# ---------------------------------------------------------------------------

@tool(
    description=(
        "Notifica al residente de que hay una visita. Úsala cuando el visitante "
        "se haya identificado y hayas entendido el motivo de la visita."
    ),
    params={
        "visitante": {"type": "string", "description": "Nombre o descripción del visitante"},
        "motivo": {"type": "string", "description": "Motivo de la visita, en una frase"},
    },
    required=["visitante", "motivo"],
)
async def notificar_residente(ctx: dict, visitante: str, motivo: str) -> str:
    await notify.push(
        title=f"Visita: {visitante}",
        body=motivo,
        category="visita",
    )
    return "El residente ha sido notificado."


@tool(
    description=(
        "Solicita permiso al residente para abrir la puerta cuando el visitante se ha identificado y pide entrar."
    ),
    params={
        "visitante": {"type": "string", "description": "Nombre o descripción del visitante"},
        "motivo": {"type": "string", "description": "Por qué pide entrar"},
    },
    required=["visitante", "motivo"],
)
async def solicitar_apertura(ctx: dict, visitante: str, motivo: str) -> str:
    import main
    image = main.LATEST_FRAME
    request = PendingRequest(motivo=motivo, visitante=visitante, image=image)
    PENDING[request.id] = request

    await notify.push(
        title=f"¿Abrir la puerta a {visitante}?",
        body=motivo,
        category="apertura",
    )
    
    ws = ctx.get("ws")
    if ws is not None:
        await ws.send_text(json.dumps({
            "type": "transcript",
            "role": "system",
            "content": "Consultando con el residente…",
        }, ensure_ascii=False))
    try:
        await asyncio.wait_for(request.event.wait(), timeout=config.DOOR_CONFIRM_TIMEOUT_S)
    except asyncio.TimeoutError:
        PENDING.pop(request.id, None)
        if ws is not None:
            try:
                await ws.send_text(json.dumps({
                    "type": "transcript",
                    "role": "system",
                    "content": "Sin respuesta del residente.",
                }, ensure_ascii=False))
            except Exception:
                pass
        return "Sin respuesta del residente. La puerta NO se ha abierto."

    PENDING.pop(request.id, None)

    if request.approved:
        ctx["open_door"] = True
        return "Autorizado."
    return "DENEGADO: el residente no ha autorizado la entrada. Informa al visitante de que no puede entrar."


@tool(
    description=(
        "Envía al residente la petición de abrir la puerta y espera su respuesta. "
        "Invócala siempre que el visitante pida entrar. El resultado te dirá si "
        "se ha autorizado o no."
    ),
    params={
        "visitante": {"type": "string", "description": "Quién deja el mensaje"},
        "mensaje": {"type": "string", "description": "Contenido del mensaje"},
    },
    required=["visitante", "mensaje"],
)
async def dejar_mensaje(ctx: dict, visitante: str, mensaje: str) -> str:
    os.makedirs(config.DATA_DIR, exist_ok=True)
    path = os.path.join(config.DATA_DIR, "mensajes.jsonl")
    record = {"ts": time.time(), "visitante": visitante, "mensaje": mensaje}
    with open(path, "a", encoding="utf-8") as handle:
        handle.write(json.dumps(record, ensure_ascii=False) + "\n")

    await notify.push(title=f"Mensaje de {visitante}", body=mensaje, category="mensaje")
    return "Mensaje guardado."


@tool(
    description=(
        "Registra un intento de venta, publicidad o encuesta y cierra la conversación. "
        "No molestes al residente en estos casos."
    ),
    params={
        "empresa": {"type": "string", "description": "Empresa u organización, si se conoce"},
    },
    required=[],
    ends_session=True,
)
async def descartar_comercial(ctx: dict, empresa: str = "desconocida") -> str:
    os.makedirs(config.DATA_DIR, exist_ok=True)
    path = os.path.join(config.DATA_DIR, "comerciales.jsonl")
    with open(path, "a", encoding="utf-8") as handle:
        handle.write(json.dumps({"ts": time.time(), "empresa": empresa}, ensure_ascii=False) + "\n")
    return "Registrado. Despídete educadamente."


@tool(
    description="Cierra la conversación cuando ya no queda nada por hacer.",
    params={
        "resumen": {"type": "string", "description": "Resumen de una frase de lo ocurrido"},
    },
    required=["resumen"],
    ends_session=True,
)
async def finalizar(ctx: dict, resumen: str) -> str:
    log.info("Sesión finalizada: %s", resumen)
    return "Conversación cerrada."