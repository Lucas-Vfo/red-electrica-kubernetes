"use strict";

const solicitudForm =
    document.getElementById("solicitudForm");

const submitButton =
    document.getElementById("submitButton");

const estadoContainer =
    document.getElementById("estadoContainer");

const estadoMensaje =
    document.getElementById("estadoMensaje");

const estadoDetalle =
    document.getElementById("estadoDetalle");

const detalleServicio =
    document.getElementById("detalleServicio");

const statusLoader =
    document.getElementById("statusLoader");


solicitudForm.addEventListener(
    "submit",
    procesarSolicitud
);


async function procesarSolicitud(event) {

    event.preventDefault();

    limpiarEstado();

    const idDomicilio = Number(
        document.getElementById("idDomicilio").value
    );

    const potenciaSolicitadaKw = Number(
        document.getElementById("potencia").value
    );


    if (
        !Number.isInteger(idDomicilio) ||
        idDomicilio <= 0
    ) {

        mostrarError(
            "El ID del domicilio debe ser un número entero válido."
        );

        return;
    }


    if (
        !Number.isFinite(potenciaSolicitadaKw) ||
        potenciaSolicitadaKw <= 0
    ) {

        mostrarError(
            "La potencia solicitada debe ser mayor a cero."
        );

        return;
    }


    const payload = {

        id_domicilio: idDomicilio,

        potencia_solicitada_kw:
            potenciaSolicitadaKw

    };


    mostrarProcesando(
        "Enviando solicitud",
        "Conectando con el servicio de demanda."
    );


    submitButton.disabled = true;


    try {

        const response = await fetch(
            "/api/solicitud",
            {

                method: "POST",

                headers: {

                    "Content-Type":
                        "application/json"

                },

                body: JSON.stringify(payload)

            }
        );


        const responseBody =
            await leerRespuesta(response);


        if (!response.ok) {

            throw new Error(
                obtenerMensajeError(
                    responseBody,
                    response.status
                )
            );

        }


        mostrarSolicitudCreada(
            responseBody
        );


    } catch (error) {

        console.error(
            "Error al registrar la solicitud:",
            error
        );


        mostrarError(
            error.message ||
            "No fue posible procesar la solicitud."
        );


    } finally {

        submitButton.disabled = false;

    }

}


async function leerRespuesta(response) {

    const contentType =
        response.headers.get("content-type") || "";


    if (
        contentType.includes(
            "application/json"
        )
    ) {

        return response.json();

    }


    return {

        detail: await response.text()

    };

}


function obtenerMensajeError(
    body,
    status
) {

    if (
        typeof body?.detail === "string"
    ) {

        return body.detail;

    }


    if (Array.isArray(body?.detail)) {

        return (
            body.detail[0]?.msg ||
            "Datos de solicitud inválidos."
        );

    }


    return (
        `Error HTTP ${status}. ` +
        "No fue posible procesar la solicitud."
    );

}


function mostrarProcesando(
    titulo,
    detalle
) {

    estadoContainer.classList.remove(
        "hidden"
    );


    estadoMensaje.className =
        "estado-mensaje";


    estadoMensaje.textContent =
        titulo;


    estadoDetalle.textContent =
        detalle;


    statusLoader.classList.remove(
        "hidden"
    );

}


function mostrarSolicitudCreada(data) {

    statusLoader.classList.add(
        "hidden"
    );


    estadoMensaje.className =
        "estado-mensaje success-text";


    estadoMensaje.textContent =
        "Solicitud registrada";


    estadoDetalle.textContent =
        "La solicitud fue enviada al sistema de evaluación de capacidad.";


    detalleServicio.innerHTML = `

        <p>
            <strong>ID solicitud:</strong>
            ${escaparHtml(data.id_solicitud)}
        </p>

        <p>
            <strong>ID domicilio:</strong>
            ${escaparHtml(data.id_domicilio)}
        </p>

        <p>
            <strong>Potencia solicitada:</strong>
            ${escaparHtml(
                data.potencia_solicitada_kw
            )} kW
        </p>

        <p>
            <strong>Fecha de solicitud:</strong>
            ${formatearFecha(data.timestamp)}
        </p>

    `;

}


function mostrarError(mensaje) {

    estadoContainer.classList.remove(
        "hidden"
    );


    statusLoader.classList.add(
        "hidden"
    );


    estadoMensaje.className =
        "estado-mensaje error-text";


    estadoMensaje.textContent =
        "Error en la solicitud";


    estadoDetalle.textContent =
        mensaje;


    detalleServicio.innerHTML = "";

}


function limpiarEstado() {

    detalleServicio.innerHTML = "";


    estadoContainer.classList.add(
        "hidden"
    );

}


function formatearFecha(timestamp) {

    const fecha = new Date(timestamp);


    if (
        Number.isNaN(fecha.getTime())
    ) {

        return escaparHtml(timestamp);

    }


    return fecha.toLocaleString(
        "es-CL"
    );

}


function escaparHtml(valor) {

    const elemento =
        document.createElement("div");


    elemento.textContent =
        String(valor ?? "");


    return elemento.innerHTML;

}