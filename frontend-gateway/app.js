"use strict";

const solicitudForm = document.getElementById("solicitudForm");
const submitButton = document.getElementById("submitButton");
const estadoContainer = document.getElementById("estadoContainer");
const estadoMensaje = document.getElementById("estadoMensaje");
const estadoDetalle = document.getElementById("estadoDetalle");
const detalleServicio = document.getElementById("detalleServicio");
const statusLoader = document.getElementById("statusLoader");
const historialBody = document.getElementById("historialBody");
const historialEstado = document.getElementById("historialEstado");

const HISTORIAL_INTERVALO_MS = 3000;
let idSolicitudActiva = null;

solicitudForm.addEventListener("submit", procesarSolicitud);


/* ----------------------------- Envío de solicitud ------------------------- */

async function procesarSolicitud(event) {
    event.preventDefault();
    limpiarEstado();

    const idDomicilio = Number(document.getElementById("idDomicilio").value);
    const potenciaSolicitadaKw = Number(document.getElementById("potencia").value);

    if (!Number.isInteger(idDomicilio) || idDomicilio <= 0) {
        mostrarError("El ID del domicilio debe ser un número entero válido.");
        return;
    }

    if (!Number.isFinite(potenciaSolicitadaKw) || potenciaSolicitadaKw <= 0) {
        mostrarError("La potencia solicitada debe ser mayor a cero.");
        return;
    }

    const payload = {
        id_domicilio: idDomicilio,
        potencia_solicitada_kw: potenciaSolicitadaKw
    };

    mostrarProcesando(
        "Enviando solicitud",
        "Conectando con el servicio de demanda."
    );
    submitButton.disabled = true;

    try {
        const response = await fetch("/api/solicitud", {
            method: "POST",
            headers: { "Content-Type": "application/json" },
            body: JSON.stringify(payload)
        });

        const responseBody = await leerRespuesta(response);

        if (!response.ok) {
            throw new Error(obtenerMensajeError(responseBody, response.status));
        }

        mostrarSolicitudCreada(responseBody);
        idSolicitudActiva = responseBody.id_solicitud;
        cargarHistorial(); // refresco inmediato: la fila aparece "En evaluación"
    } catch (error) {
        console.error("Error al registrar la solicitud:", error);
        mostrarError(error.message || "No fue posible procesar la solicitud.");
    } finally {
        submitButton.disabled = false;
    }
}


async function leerRespuesta(response) {
    const contentType = response.headers.get("content-type") || "";
    if (contentType.includes("application/json")) {
        return response.json();
    }
    return { detail: await response.text() };
}


function obtenerMensajeError(body, status) {
    if (typeof body?.detail === "string") {
        return body.detail;
    }
    if (Array.isArray(body?.detail)) {
        return body.detail[0]?.msg || "Datos de solicitud inválidos.";
    }
    return `Error HTTP ${status}. No fue posible procesar la solicitud.`;
}


/* ----------------------------- Panel de estado ---------------------------- */

function mostrarProcesando(titulo, detalle) {
    estadoContainer.classList.remove("hidden");
    estadoMensaje.className = "estado-mensaje";
    estadoMensaje.textContent = titulo;
    estadoDetalle.textContent = detalle;
    statusLoader.classList.remove("hidden");
}


function mostrarSolicitudCreada(data) {
    statusLoader.classList.add("hidden");
    estadoMensaje.className = "estado-mensaje success-text";
    estadoMensaje.textContent = "Solicitud registrada";
    estadoDetalle.textContent =
        "La solicitud está EN EVALUACIÓN. El resultado aparecerá en el historial en unos segundos.";

    detalleServicio.innerHTML = `
        <p><strong>ID solicitud:</strong> ${escaparHtml(data.id_solicitud)}</p>
        <p><strong>ID domicilio:</strong> ${escaparHtml(data.id_domicilio)}</p>
        <p><strong>Potencia solicitada:</strong> ${escaparHtml(data.potencia_solicitada_kw)} kW</p>
        <p><strong>Fecha de solicitud:</strong> ${formatearFecha(data.timestamp)}</p>
    `;
}


function mostrarError(mensaje) {
    estadoContainer.classList.remove("hidden");
    statusLoader.classList.add("hidden");
    estadoMensaje.className = "estado-mensaje error-text";
    estadoMensaje.textContent = "Error en la solicitud";
    estadoDetalle.textContent = mensaje;
    detalleServicio.innerHTML = "";
}


function limpiarEstado() {
    detalleServicio.innerHTML = "";
    estadoContainer.classList.add("hidden");
}


/* ------------------- Historial en tiempo real (polling) ------------------- */

function claseDeEstado(estado) {
    const valor = String(estado || "").toLowerCase();
    if (valor === "activo") {
        return "estado-badge estado-activo";
    }
    if (valor === "rechazado") {
        return "estado-badge estado-rechazado";
    }
    return "estado-badge estado-evaluacion";
}

function etiquetaDeEstado(estado) {
    const valor = String(estado || "").toLowerCase();
    if (valor === "activo") {
        return "Servicio activo";
    }
    if (valor === "rechazado") {
        return "Rechazado";
    }
    return "En evaluación";
}


async function cargarHistorial() {
    try {
        const response = await fetch("/api/solicitudes?limit=20");
        if (!response.ok) {
            throw new Error(`HTTP ${response.status}`);
        }
        const solicitudes = await response.json();
        renderizarHistorial(solicitudes);
        if (idSolicitudActiva) {
            const solicitudActualizada = solicitudes.find(s => s.id_solicitud === idSolicitudActiva);
            
            if (solicitudActualizada && solicitudActualizada.estado.toLowerCase() !== "en evaluación") {
                
                statusLoader.classList.add("hidden"); 
                
                if (solicitudActualizada.estado.toLowerCase() === "activo") {
                    estadoMensaje.className = "estado-mensaje success-text";
                    estadoMensaje.textContent = "Solicitud Aprobada";
                    estadoDetalle.textContent = "La red eléctrica ha aceptado la carga de alta potencia para tu domicilio.";
                } else if (solicitudActualizada.estado.toLowerCase() === "rechazado") {
                    estadoMensaje.className = "estado-mensaje error-text";
                    estadoMensaje.textContent = "Solicitud Rechazada";
                    estadoDetalle.textContent = "La capacidad del transformador de tu sector ha sido superada.";
                }
                
                idSolicitudActiva = null; 
            }
        }
        historialEstado.textContent =
            "Actualizado " + new Date().toLocaleTimeString("es-CL");
        historialEstado.classList.remove("historial-error");
    } catch (error) {
        console.error("No fue posible actualizar el historial:", error);
        historialEstado.textContent = "Sin conexión con el sistema";
        historialEstado.classList.add("historial-error");
    }
}


function renderizarHistorial(solicitudes) {
    if (!Array.isArray(solicitudes) || solicitudes.length === 0) {
        historialBody.innerHTML =
            '<tr><td colspan="5" class="historial-vacio">Aún no hay solicitudes registradas.</td></tr>';
        return;
    }

    historialBody.innerHTML = solicitudes
        .map((solicitud) => `
            <tr>
                <td>${escaparHtml(solicitud.id_solicitud)}</td>
                <td>${escaparHtml(solicitud.id_domicilio)}</td>
                <td>${escaparHtml(solicitud.potencia_solicitada_kw)} kW</td>
                <td>
                    <span class="${claseDeEstado(solicitud.estado)}">
                        ${etiquetaDeEstado(solicitud.estado)}
                    </span>
                </td>
                <td>${formatearFecha(solicitud.timestamp)}</td>
            </tr>
        `)
        .join("");
}


/* ------------------------------- Utilidades ------------------------------- */

function formatearFecha(timestamp) {
    const fecha = new Date(timestamp);
    if (Number.isNaN(fecha.getTime())) {
        return escaparHtml(timestamp);
    }
    return fecha.toLocaleString("es-CL");
}


function escaparHtml(valor) {
    const elemento = document.createElement("div");
    elemento.textContent = String(valor ?? "");
    return elemento.innerHTML;
}


/* Arranque: primera carga + refresco periódico */
cargarHistorial();
setInterval(cargarHistorial, HISTORIAL_INTERVALO_MS);
