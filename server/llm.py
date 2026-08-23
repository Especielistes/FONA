"""Cliente de Ollama con bucle de tool calling."""

import logging

import httpx

import config
import tools

log = logging.getLogger(__name__)

SYSTEM_PROMPT = """El visitante puede comunicarse hablando, escribiendo o en lengua de signos. Los
mensajes en lengua de signos llegan como palabras sueltas sin gramática (por
ejemplo: "paquete vecino gracias"). Interprétalos y reformúlalos en una frase
natural; no le pidas al visitante que se exprese mejor.

En lengua de signos el visitante solo dispone del vocabulario cerrado que se te
indica en cada mensaje. Formula únicamente preguntas de sí o no, o preguntas que
pueda responder con ese vocabulario. Si necesitas un dato que no está en él (un
nombre, una empresa, un número de piso), NO lo preguntes en abierto: dile que lo
escriba con el teclado de la pantalla."""

GREETING = "Buenos días. ¿Quién es, por favor?"


async def chat(messages: list[dict]) -> dict:
    """Una llamada a Ollama. Devuelve el mensaje del asistente."""
    payload = {
        "model": config.LLM_MODEL,
        "messages": messages,
        "tools": tools.schemas(),
        "stream": False,
        "options": {"temperature": config.LLM_TEMPERATURE},
    }

    async with httpx.AsyncClient(timeout=120.0) as client:
        response = await client.post(f"{config.OLLAMA_URL}/api/chat", json=payload)
        response.raise_for_status()
        return response.json()["message"]


async def respond(messages: list[dict], ctx: dict) -> tuple[str, bool]:
    """Ejecuta el ciclo modelo -> herramientas -> modelo hasta obtener texto que decir.

    Muta `messages` con todo el historial. Devuelve (texto_a_decir, terminar_sesion).
    """
    end_session = False

    for _round in range(config.LLM_MAX_TOOL_ROUNDS):
        message = await chat(messages)
        messages.append(message)

        tool_calls = message.get("tool_calls") or []
        if not tool_calls:
            return message.get("content", "").strip(), end_session

        for call in tool_calls:
            name = call["function"]["name"]
            arguments = call["function"].get("arguments") or {}
            log.info("Tool call: %s(%s)", name, arguments)

            result, ends = await tools.execute(name, arguments, ctx)
            if ends:
                end_session = True

            messages.append({"role": "tool", "name": name, "content": result})

    # Si llegamos aquí, el modelo se ha quedado en bucle de herramientas.
    log.warning("Límite de rondas de tool calling alcanzado")
    return "Disculpe, ha habido un problema. Inténtelo de nuevo más tarde.", True