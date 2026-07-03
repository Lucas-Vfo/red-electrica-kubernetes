import os
import json
import logging
import time
from datetime import datetime
from typing import Optional

import pika

try:
    import psycopg2
except ImportError:
    psycopg2 = None

RABBITMQ_HOST = os.getenv("RABBITMQ_HOST", "localhost")
RABBITMQ_PORT = int(os.getenv("RABBITMQ_PORT", "5672"))
RABBITMQ_USER = os.getenv("RABBITMQ_USER", "guest")
RABBITMQ_PASS = os.getenv("RABBITMQ_PASS", "guest")
RABBITMQ_RETRY_DELAY = int(os.getenv("RABBITMQ_RETRY_DELAY", "5"))
RABBITMQ_MAX_RETRIES = int(os.getenv("RABBITMQ_MAX_RETRIES", "10"))
INPUT_QUEUE = "solicitud.creada"
OUTPUT_QUEUE = "carga.aprobada"

DB_HOST = os.getenv("DB_HOST")
DB_NAME = os.getenv("DB_NAME")
DB_USER = os.getenv("DB_USER")
DB_PASS = os.getenv("DB_PASS")

logger = logging.getLogger("service2")
logging.basicConfig(level=logging.INFO, format="%(asctime)s [%(levelname)s] %(message)s")


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
            return pika.BlockingConnection(build_rabbitmq_parameters())
        except Exception as exc:
            last_error = exc
            logger.warning("Error de conexión a RabbitMQ: %s", exc)
            time.sleep(RABBITMQ_RETRY_DELAY)
    logger.error("No se pudo conectar a RabbitMQ tras %d intentos", RABBITMQ_MAX_RETRIES)
    raise last_error


def connect_db() -> Optional[object]:
    if not (DB_HOST and DB_NAME and DB_USER and DB_PASS and psycopg2):
        logger.info("No se encontró configuración completa de BD o psycopg2 no está instalado; usando simulación")
        return None
    for attempt in range(1, RABBITMQ_MAX_RETRIES + 1):
        try:
            logger.info("Conectando a PostgreSQL (intento %d/%d)", attempt, RABBITMQ_MAX_RETRIES)
            conn = psycopg2.connect(
                host=DB_HOST,
                dbname=DB_NAME,
                user=DB_USER,
                password=DB_PASS,
                connect_timeout=10,
            )
            conn.autocommit = True
            return conn
        except Exception as exc:
            logger.warning("Error de conexión a PostgreSQL: %s", exc)
            time.sleep(RABBITMQ_RETRY_DELAY)
    logger.error("No se pudo conectar a PostgreSQL tras %d intentos", RABBITMQ_MAX_RETRIES)
    return None


def resolve_capacity(id_domicilio: int, potencia: float, db_conn: Optional[object]) -> tuple[bool, Optional[str]]:
    capacity_threshold = 40.0
    if db_conn:
        try:
            with db_conn.cursor() as cursor:
                cursor.execute(
                    "SELECT capacidad_kw FROM transformadores WHERE id_domicilio = %s LIMIT 1",
                    (id_domicilio,),
                )
                row = cursor.fetchone()
                if row and row[0] is not None:
                    capacity_threshold = float(row[0])
                    logger.info("Capacidad real encontrada para domicilio %d: %s kW", id_domicilio, capacity_threshold)
                else:
                    logger.info("No se encontró transformador para domicilio %d; usando valor simulado", id_domicilio)
        except Exception as exc:
            logger.warning("Error al consultar capacidad en la BD: %s; usando valor simulado", exc)
    aprobado = potencia <= capacity_threshold
    motivo_rechazo = None if aprobado else "Saturación del transformador: la demanda supera la capacidad disponible"
    return aprobado, motivo_rechazo


def publish_result(channel: pika.channel.Channel, event: dict) -> None:
    channel.basic_publish(
        exchange="",
        routing_key=OUTPUT_QUEUE,
        body=json.dumps(event, ensure_ascii=False).encode("utf-8"),
        properties=pika.BasicProperties(
            delivery_mode=2,
            content_type="application/json",
        ),
    )


def callback(ch: pika.channel.Channel, method, properties, body: bytes) -> None:
    try:
        payload = json.loads(body.decode("utf-8"))
        logger.info("Mensaje recibido de %s: %s", INPUT_QUEUE, payload)
        aprobado, motivo = resolve_capacity(
            int(payload["id_domicilio"]),
            float(payload["potencia_solicitada_kw"]),
            db_conn,
        )
        result_event = {
            "id_solicitud": payload["id_solicitud"],
            "id_domicilio": int(payload["id_domicilio"]),
            "potencia_solicitada_kw": float(payload["potencia_solicitada_kw"]),
            "aprobado": aprobado,
            "motivo_rechazo": motivo,
            "timestamp_evaluacion": datetime.utcnow().replace(microsecond=0).isoformat() + "Z",
        }
        publish_result(ch, result_event)
        ch.basic_ack(delivery_tag=method.delivery_tag)
        logger.info("Evento publicado en %s: %s", OUTPUT_QUEUE, result_event)
    except Exception as exc:
        logger.exception("Error procesando mensaje; reintentando")
        ch.basic_nack(delivery_tag=method.delivery_tag, requeue=True)


def main() -> None:
    global db_conn
    connection = connect_rabbitmq()
    channel = connection.channel()
    channel.queue_declare(queue=INPUT_QUEUE, durable=True)
    channel.queue_declare(queue=OUTPUT_QUEUE, durable=True)
    channel.basic_qos(prefetch_count=1)
    db_conn = connect_db()
    logger.info("Esperando mensajes en %s", INPUT_QUEUE)
    channel.basic_consume(queue=INPUT_QUEUE, on_message_callback=callback)
    try:
        channel.start_consuming()
    except KeyboardInterrupt:
        logger.info("Worker detenido por teclado")
    finally:
        if connection and not connection.is_closed:
            connection.close()


if __name__ == "__main__":
    db_conn = None
    main()
