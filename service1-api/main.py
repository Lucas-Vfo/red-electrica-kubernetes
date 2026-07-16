import os
import json
import logging
import itertools
import threading
import time
from datetime import datetime
from typing import Optional

import pika
import psycopg2
from fastapi import FastAPI, HTTPException
from pydantic import BaseModel, Field

RABBITMQ_HOST = os.getenv("RABBITMQ_HOST", "localhost")
RABBITMQ_PORT = int(os.getenv("RABBITMQ_PORT", "5672"))
RABBITMQ_USER = os.getenv("RABBITMQ_USER", "guest")
RABBITMQ_PASS = os.getenv("RABBITMQ_PASS", "guest")
RABBITMQ_RETRY_DELAY = int(os.getenv("RABBITMQ_RETRY_DELAY", "5"))
RABBITMQ_MAX_RETRIES = int(os.getenv("RABBITMQ_MAX_RETRIES", "10"))
QUEUE_NAME = "solicitud.creada"
QUEUE_ESTADO = "servicio.activo"   # estado final que emite el Servicio 3

# db1: historial de solicitudes (aislada; solo este servicio la consulta)
DB_HOST = os.getenv("DB_HOST", "localhost")
DB_PORT = int(os.getenv("DB_PORT", "5432"))
DB_NAME = os.getenv("DB_NAME", "solicitudes")
DB_USER = os.getenv("DB_USER", "smartgrid")
DB_PASS = os.getenv("DB_PASS", "smartgrid")

logger = logging.getLogger("service1")
logging.basicConfig(level=logging.INFO, format="%(asctime)s [%(levelname)s] %(message)s")
app = FastAPI(title="Smart Grid - Receptor de Solicitudes")

id_counter = itertools.count(1)   # respaldo si db1 no está disponible

db_conn: Optional[object] = None


def get_db_connection() -> Optional[object]:
    """Conexión perezosa a db1 con reconexión simple: si murió (ej. reinicio
    del Pod de la BD), intenta UNA reconexión rápida y si falla devuelve None
    (el flujo de eventos continúa; solo se pierde el historial persistente)."""
    global db_conn
    if db_conn is not None and not getattr(db_conn, "closed", 0):
        return db_conn
    try:
        db_conn = psycopg2.connect(
            host=DB_HOST,
            port=DB_PORT,
            dbname=DB_NAME,
            user=DB_USER,
            password=DB_PASS,
            connect_timeout=5,
        )
        db_conn.autocommit = True
        logger.info("Conectado a PostgreSQL (db1)")
    except Exception as exc:
        db_conn = None
        logger.warning("db1 no disponible: %s", exc)
    return db_conn


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
    # Hilo que escucha `servicio.activo` y refleja el estado final en db1
    threading.Thread(target=consumir_estados, name="consumidor-servicio-activo", daemon=True).start()


@app.on_event("shutdown")
def on_shutdown() -> None:
    connection = getattr(app.state, "rabbitmq_connection", None)
    if connection and not connection.is_closed:
        connection.close()
        logger.info("Conexión RabbitMQ cerrada")


@app.post("/solicitud")
def crear_solicitud(payload: SolicitudRequest):
    timestamp = datetime.utcnow().replace(microsecond=0)

    # 1) Registrar en db1 con estado "En evaluación" (historial del frontend).
    #    El ID sale de la SEQUENCE de db1 (no se repite entre workers ni
    #    reinicios); si la BD no está disponible se usa el contador en memoria
    #    y el flujo de eventos continúa igual.
    id_solicitud = None
    conn = get_db_connection()
    if conn is not None:
        try:
            with conn.cursor() as cursor:
                cursor.execute("SELECT nextval('solicitudes_seq')")
                id_solicitud = f"REQ-{timestamp.year}-{int(cursor.fetchone()[0]):03d}"
                cursor.execute(
                    "INSERT INTO solicitudes (id_solicitud, id_domicilio, potencia_solicitada_kw, estado, timestamp)"
                    " VALUES (%s, %s, %s, %s, %s)",
                    (id_solicitud, payload.id_domicilio, payload.potencia_solicitada_kw, "En evaluación", timestamp),
                )
        except Exception:
            logger.exception("No se pudo registrar la solicitud en db1; se continúa sin persistencia")
            id_solicitud = None
    if id_solicitud is None:
        id_solicitud = f"REQ-{timestamp.year}-{next(id_counter):03d}"

    # 2) Publicar el evento para que el Servicio 2 evalúe la capacidad.
    try:
        channel = ensure_rabbitmq_channel()
        event = {
            "id_solicitud": id_solicitud,
            "id_domicilio": payload.id_domicilio,
            "potencia_solicitada_kw": payload.potencia_solicitada_kw,
            "timestamp": timestamp.isoformat() + "Z",
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
        return {**event, "estado": "En evaluación"}
    except Exception as exc:
        logger.exception("Error al publicar solicitud en RabbitMQ")
        raise HTTPException(status_code=503, detail="No se pudo procesar la solicitud en este momento")


@app.get("/solicitudes")
def listar_solicitudes(limit: int = 50):
    """Historial para el frontend (más recientes primero). El frontend lo
    consulta cada pocos segundos: así ve el estado en tiempo real."""
    conn = get_db_connection()
    if conn is None:
        raise HTTPException(status_code=503, detail="Base de datos de solicitudes no disponible")
    try:
        with conn.cursor() as cursor:
            cursor.execute(
                "SELECT id_solicitud, id_domicilio, potencia_solicitada_kw, estado, timestamp"
                " FROM solicitudes ORDER BY timestamp DESC, id_solicitud DESC LIMIT %s",
                (max(1, min(int(limit), 200)),),
            )
            filas = cursor.fetchall()
    except Exception:
        logger.exception("Error consultando el historial en db1")
        raise HTTPException(status_code=503, detail="Base de datos de solicitudes no disponible")
    return [
        {
            "id_solicitud": fila[0],
            "id_domicilio": fila[1],
            "potencia_solicitada_kw": float(fila[2]),
            "estado": fila[3],
            "timestamp": fila[4].isoformat() + "Z",
        }
        for fila in filas
    ]


@app.get("/healthz")
def healthz():
    """Probe de Kubernetes: reporta el estado de las dependencias (siempre 200;
    la recuperación la manejan los reintentos internos)."""
    db_ok = False
    conn = get_db_connection()
    if conn is not None:
        try:
            with conn.cursor() as cursor:
                cursor.execute("SELECT 1")
            db_ok = True
        except Exception:
            db_ok = False
    rabbit = getattr(app.state, "rabbitmq_connection", None)
    return {
        "status": "ok",
        "servicio": "service1-api",
        "db": db_ok,
        "rabbitmq": bool(rabbit) and not rabbit.is_closed,
    }


def aplicar_estado_final(ch, method, properties, body: bytes) -> None:
    """Consume `servicio.activo` (Servicio 3) y actualiza el estado en db1:
    'En evaluación' -> 'activo' | 'rechazado'."""
    try:
        evento = json.loads(body.decode("utf-8"))
        conn = get_db_connection()
        if conn is None:
            raise RuntimeError("db1 no disponible")
        with conn.cursor() as cursor:
            cursor.execute(
                "UPDATE solicitudes SET estado = %s WHERE id_solicitud = %s",
                (str(evento.get("estado_servicio", "desconocido")), evento["id_solicitud"]),
            )
        logger.info("Estado final aplicado: %s -> %s", evento["id_solicitud"], evento.get("estado_servicio"))
        ch.basic_ack(delivery_tag=method.delivery_tag)
    except Exception:
        logger.exception("Error aplicando estado final; se reintentará")
        time.sleep(2)  # evita un bucle caliente de re-entregas
        ch.basic_nack(delivery_tag=method.delivery_tag, requeue=True)


def consumir_estados() -> None:
    """Hilo en segundo plano. La cola y su binding al exchange los crea el Job
    de topología de infraestructura (k8s/*/12-topology-job.yaml); aquí solo se
    declara la cola (idempotente) y se consume."""
    while True:
        try:
            connection = pika.BlockingConnection(build_rabbitmq_parameters())
            channel = connection.channel()
            channel.queue_declare(queue=QUEUE_ESTADO, durable=True)
            channel.basic_qos(prefetch_count=1)
            channel.basic_consume(queue=QUEUE_ESTADO, on_message_callback=aplicar_estado_final)
            logger.info("Consumidor de %s iniciado", QUEUE_ESTADO)
            channel.start_consuming()
        except Exception as exc:
            logger.warning("Consumidor de estados caído (%s); reintento en 5s", exc)
            time.sleep(5)