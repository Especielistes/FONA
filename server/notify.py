"""Notificaciones hacia el residente.

Por defecto solo escribe en el log. Con MQTT_ENABLED=1 publica en un broker local,
que es la vía recomendada para integrarlo con Home Assistant y recibirlo en el móvil
sin depender de servicios externos.
"""

import asyncio
import json
import logging

import config

log = logging.getLogger(__name__)
_client = None


def connect() -> None:
    global _client
    if not config.MQTT_ENABLED or _client is not None:
        return

    import paho.mqtt.client as mqtt

    _client = mqtt.Client()
    _client.connect(config.MQTT_HOST, config.MQTT_PORT, keepalive=60)
    _client.loop_start()
    log.info("MQTT conectado a %s:%s", config.MQTT_HOST, config.MQTT_PORT)


async def push(title: str, body: str, category: str, request_id: str | None = None) -> None:
    payload = {"title": title, "body": body, "category": category}
    if request_id:
        payload["request_id"] = request_id

    log.info("NOTIFICACIÓN [%s] %s - %s", category, title, body)

    if not config.MQTT_ENABLED or _client is None:
        return

    topic = f"{config.MQTT_TOPIC_PREFIX}/{category}"
    # paho es bloqueante; el publish es rápido pero lo sacamos del loop igualmente.
    await asyncio.to_thread(_client.publish, topic, json.dumps(payload, ensure_ascii=False))