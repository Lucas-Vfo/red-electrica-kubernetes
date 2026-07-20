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
INPUT_QUEUE = "carga.aprobada"
OUTPUT_QUEUE = "servicio.activo"

DB_HOST = os.getenv("DB_HOST")
DB_NAME = os.getenv("DB_NAME")
DB_USER = os.getenv("DB_USER")
DB_PASS = os.getenv("DB_PASS")

logger = logging.getLogger("service3")
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


def save_service_state(event: dict, db_conn: Optional[object]) -> None:
    record = {
        "id_solicitud": event["id_solicitud"],
        "id_domicilio": event["id_domicilio"],
        "tarifa_por_kw_clp": event["tarifa_por_kw_clp"],
        "estado_servicio": event["estado_servicio"],
        "timestamp_inicio": datetime.utcnow().replace(microsecond=0),
    }
    if not db_conn:
        logger.info("Simulando guardado en BD: %s", record)
        return
    try:
        with db_conn.cursor() as cursor:
            # Tabla/columnas según database/init-tarifador.sql; ON CONFLICT evita
            # duplicados si RabbitMQ re-entrega el mensaje.
            cursor.execute(
                "INSERT INTO facturacion_servicios (id_solicitud, id_domicilio, tarifa_por_kw_clp, estado_servicio, timestamp_inicio)"
                " VALUES (%s, %s, %s, %s, %s)"
                " ON CONFLICT (id_solicitud) DO NOTHING",
                (
                    record["id_solicitud"],
                    record["id_domicilio"],
                    record["tarifa_por_kw_clp"],
                    record["estado_servicio"],
                    record["timestamp_inicio"],
                ),
            )
            logger.info("Facturación registrada en BD")
    except Exception as exc:
        logger.warning("Error guardando estado en BD: %s", exc)


def publish_result(channel: pika.channel.Channel, event: dict) -> None:
    channel.basic_publish(
        exchange="smartgrid.exchange",
        routing_key=OUTPUT_QUEUE,
        body=json.dumps(event, ensure_ascii=False).encode("utf-8"),
        properties=pika.BasicProperties(
            delivery_mode=2,
            content_type="application/json",
        ),
    )


def refresh_db_connection() -> None:
    """Si la conexión a db3 murió (ej. reinicio del Pod de la BD en las pruebas
    de resiliencia), intenta UNA reconexión rápida antes del próximo mensaje."""
    global db_conn
    if not (DB_HOST and DB_NAME and DB_USER and DB_PASS and psycopg2):
        return
    if db_conn is not None and not getattr(db_conn, "closed", 0):
        return
    try:
        db_conn = psycopg2.connect(
            host=DB_HOST, dbname=DB_NAME, user=DB_USER, password=DB_PASS, connect_timeout=5
        )
        db_conn.autocommit = True
        logger.info("Reconexión a PostgreSQL exitosa")
    except Exception as exc:
        db_conn = None
        logger.warning("Reconexión a PostgreSQL fallida: %s", exc)


def callback(ch: pika.channel.Channel, method, properties, body: bytes) -> None:
    try:
        payload = json.loads(body.decode("utf-8"))
        logger.info("Mensaje recibido de %s: %s", INPUT_QUEUE, payload)
        refresh_db_connection()
        potencia = float(payload.get("potencia_solicitada_kw", 0))

        if payload.get("aprobado") is True:
            estado = "activo"
            tarifa_final = potencia * 150 
        else:
            estado = "rechazado"
            tarifa_final = 0

        event = {
            "id_solicitud": payload["id_solicitud"],
            "id_domicilio": int(payload["id_domicilio"]),
            "tarifa_por_kw_clp": tarifa_final,
            "estado_servicio": estado,
            "timestamp_inicio": datetime.utcnow().replace(microsecond=0).isoformat() + "Z",
        }
        
        save_service_state(event, db_conn)
        publish_result(ch, event)
        ch.basic_ack(delivery_tag=method.delivery_tag)
        logger.info("Evento publicado en %s: %s", OUTPUT_QUEUE, event)
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
