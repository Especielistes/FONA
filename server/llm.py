"""Cliente de Ollama con bucle de tool calling."""

import logging

import httpx

import config
import tools

log = logging.getLogger(__name__)


SYSTEM_PROMPT = """Eres el asistente de un videoportero accesible de una vivienda particular. Hablas en castellano natural, educado, neutro y en UNA sola frase corta.

El visitante puede comunicarse hablando, escribiendo o en lengua de signos. Cuando llega de lengua de signos, el mensaje te llegará como secuencia de palabras sueltas sin gramática (ejemplos: "hola visita", "paquete", "visita vecino").

Reglas de interpretación:
- Si dicen 'visita' o 'hola visita' -> Pregunta educadamente a quién viene a ver y quién es.
- Si dicen 'paquete' o 'paquete vecino' -> Pregunta de qué empresa es el paquete y para qué destinatario.
- Si dicen 'abrir' -> Pide su nombre y motivo para consultar al residente.

Reglas estrictas:
- Responde siempre con UNA sola frase corta y clara.
- No uses emojis, ni formato, ni listas. Solo texto plano.
- NUNCA menciones nombres técnicos, código interno ni nombres de herramientas (jamás digas 'herramienta', 'solicitar_apertura' ni 'función').
- Tu objetivo es saber QUIÉN es el visitante y QUÉ quiere.
- Tú NO puedes abrir la puerta directamente. Cuando el visitante esté identificado y pida entrar, invoca directamente la herramienta solicitar_apertura sin anunciar que la vas a invocar.
- Si el residente autoriza la entrada, la respuesta final al visitante debe ser exactamente "Pase."
- Si el residente deniega la entrada, informa brevemente al visitante de que no puede entrar.
- Si es publicidad, despídete educadamente y usa descartar_comercial.
- Si no entiendes lo que dicen, pide que lo repitan una sola vez.
"""


GREETING = "Buenos días. ¿Quién es, por favor?"


async def chat(messages: list[dict]) -> dict:
    """Hace una llamada a Groq API (o a Ollama local como fallback) y devuelve el mensaje."""

    if config.GROQ_API_KEY:
        try:
            url = "https://api.groq.com/openai/v1/chat/completions"
            headers = {
                "Authorization": f"Bearer {config.GROQ_API_KEY}",
                "Content-Type": "application/json",
            }
            payload = {
                "model": config.GROQ_LLM_MODEL,
                "messages": messages,
                "tools": tools.schemas(),
                "temperature": config.LLM_TEMPERATURE,
            }
            async with httpx.AsyncClient(timeout=30.0) as client:
                response = await client.post(url, headers=headers, json=payload)
                response.raise_for_status()
                message = response.json()["choices"][0]["message"]
                log.info("LLM (Groq): %s", message)
                return message
        except Exception as e:
            log.warning("Fallo en Groq LLM, usando fallback Ollama: %s", e)

    # Fallback a Ollama local
    payload = {
        "model": config.LLM_MODEL,
        "messages": messages,
        "tools": tools.schemas(),
        "stream": False,
        "options": {
            "temperature": config.LLM_TEMPERATURE,
        },
    }

    async with httpx.AsyncClient(timeout=120.0) as client:
        response = await client.post(
            f"{config.OLLAMA_URL}/api/chat",
            json=payload,
        )
        response.raise_for_status()

        data = response.json()
        return data["message"]


async def respond(
    messages: list[dict],
    ctx: dict,
) -> tuple[str, bool]:
    """Ejecuta el ciclo modelo -> herramientas -> modelo."""
    end_session = False

    for _round in range(config.LLM_MAX_TOOL_ROUNDS):
        message = await chat(messages)
        messages.append(message)

        tool_calls = message.get("tool_calls") or []

        if not tool_calls:
            content = (message.get("content") or "").strip()
            return content, end_session

        for call in tool_calls:
            function = call.get("function") or {}
            name = function.get("name")
            raw_args = function.get("arguments") or {}

            if isinstance(raw_args, str):
                try:
                    arguments = json.loads(raw_args)
                except Exception:
                    arguments = {}
            else:
                arguments = raw_args

            log.info("Tool call: %s(%s)", name, arguments)

            result, ends = await tools.execute(
                name,
                arguments,
                ctx,
            )

            log.info("Tool result %s: %s", name, result)

            # ========================================================
            # APERTURA DE PUERTA
            #
            # Este flujo NO debe volver al LLM.
            #
            # solicitar_apertura espera a que el residente pulse
            # Abrir o Denegar.
            #
            # Si autoriza:
            #   tools.py pone ctx["open_door"] = True
            #
            # Devolvemos directamente "Pase."
            # ========================================================

            if name == "solicitar_apertura":

                if ctx.get("open_door"):
                    log.info(
                        "Apertura autorizada. Finalizando conversación."
                    )
                    return "Pase.", True

                log.info(
                    "Apertura no autorizada. Finalizando conversación."
                )

                # No dejamos que Ollama vuelva a interpretar la
                # respuesta y pueda entrar en otro ciclo.
                return result, True

            # --------------------------------------------------------
            # Herramientas normales.
            # --------------------------------------------------------

            if ends:
                end_session = True

            messages.append(
                {
                    "role": "tool",
                    "name": name,
                    "content": result,
                }
            )

        # Si hemos llegado aquí, había herramientas normales y el LLM
        # puede continuar para generar la respuesta final.

    # ------------------------------------------------------------
    # El modelo se ha quedado en un ciclo de herramientas.
    # ------------------------------------------------------------

    log.warning(
        "Límite de rondas de tool calling alcanzado"
    )

    return (
        "Disculpe, ha habido un problema. Inténtelo de nuevo más tarde.",
        True,
    )