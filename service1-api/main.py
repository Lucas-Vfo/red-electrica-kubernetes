import os
import json
import logging
import itertools
import time
from datetime import datetime
from typing import Optional

import pika
from fastapi import FastAPI, HTTPException
from pydantic import BaseModel, Field

RABBITMQ_HOST = os.getenv("RABBITMQ_HOST", "localhost")
RABBITMQ_PORT = int(os.getenv("RABBITMQ_PORT", "5672"))
RABBITMQ_USER = os.getenv("RABBITMQ_USER", "guest")
RABBITMQ_PASS = os.getenv("RABBITMQ_PASS", "guest")
RABBITMQ_RETRY_DELAY = int(os.getenv("RABBITMQ_RETRY_DELAY", "5"))
RABBITMQ_MAX_RETRIES = int(os.getenv("RABBITMQ_MAX_RETRIES", "10"))
QUEUE_NAME = "solicitud.creada"

logger = logging.getLogger("service1")
logging.basicConfig(level=logging.INFO, format="%(asctime)s [%(levelname)s] %(message)s")
app = FastAPI(title="Smart Grid - Receptor de Solicitudes")

id_counter = itertools.count(1)


class SolicitudRequest(BaseModel):
    id_domicilio: int
    potencia_solicitada_kw: float = Field(..., gt=0)


def build_rabbitmq_parameters() -> pika.ConnectionParameters:
    credentials = pika.PlainCredentials(RABBITMQ_USER, RABBITMQ_PASS)
    return pika.ConnectionParameters(
        host=RABBITMQ_HOST,
        port=RABBITMQ_PORT,
        credentials=credentials,
        heartbeat=30,
        blocked_connection_timeout=30,
    )


def connect_rabbitmq() -> pika.BlockingConnection:
    last_error: Optional[Exception] = None
    for attempt in range(1, RABBITMQ_MAX_RETRIES + 1):
        try:
            logger.info("Conectando a RabbitMQ (intento %d/%d)", attempt, RABBITMQ_MAX_RETRIES)
            connection = pika.BlockingConnection(build_rabbitmq_parameters())
            return connection
        except Exception as exc:
            last_error = exc
            logger.warning("Error de conexión a RabbitMQ: %s", exc)
            time.sleep(RABBITMQ_RETRY_DELAY)
    logger.error("No se pudo conectar a RabbitMQ tras %d intentos", RABBITMQ_MAX_RETRIES)
    raise last_error


def ensure_rabbitmq_channel() -> pika.channel.Channel:
    if not hasattr(app.state, "rabbitmq_connection") or app.state.rabbitmq_connection.is_closed:
        app.state.rabbitmq_connection = connect_rabbitmq()
        app.state.rabbitmq_channel = app.state.rabbitmq_connection.channel()
        app.state.rabbitmq_channel.queue_declare(queue=QUEUE_NAME, durable=True)
    elif app.state.rabbitmq_channel.is_closed:
        app.state.rabbitmq_channel = app.state.rabbitmq_connection.channel()
        app.state.rabbitmq_channel.queue_declare(queue=QUEUE_NAME, durable=True)
    return app.state.rabbitmq_channel


@app.on_event("startup")
def on_startup() -> None:
    try:
        ensure_rabbitmq_channel()
        logger.info("Servicio API iniciado y conectado a RabbitMQ")
    except Exception as exc:
        logger.error("Startup error: %s", exc)


@app.on_event("shutdown")
def on_shutdown() -> None:
    connection = getattr(app.state, "rabbitmq_connection", None)
    if connection and not connection.is_closed:
        connection.close()
        logger.info("Conexión RabbitMQ cerrada")


@app.post("/solicitud")
def crear_solicitud(payload: SolicitudRequest):
    try:
        channel = ensure_rabbitmq_channel()
        next_id = next(id_counter)
        event = {
            "id_solicitud": f"REQ-2026-{next_id:03d}",
            "id_domicilio": payload.id_domicilio,
            "potencia_solicitada_kw": payload.potencia_solicitada_kw,
            "timestamp": datetime.utcnow().replace(microsecond=0).isoformat() + "Z",
        }
        channel.basic_publish(
            exchange="smartgrid.exchange",
            routing_key=QUEUE_NAME,
            body=json.dumps(event, ensure_ascii=False).encode("utf-8"),
            properties=pika.BasicProperties(
                delivery_mode=2,
                content_type="application/json",
            ),
        )
        logger.info("Solicitud publicada: %s", event)
        return event
    except Exception as exc:
        logger.exception("Error al publicar solicitud en RabbitMQ")
        raise HTTPException(status_code=503, detail="No se pudo procesar la solicitud en este momento")
