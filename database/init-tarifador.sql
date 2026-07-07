CREATE TABLE IF NOT EXISTS facturacion_servicios (
    id_solicitud VARCHAR(50) PRIMARY KEY,
    id_domicilio INT NOT NULL,
    tarifa_por_kw_clp DECIMAL(10,2) NOT NULL,
    estado_servicio VARCHAR(20) NOT NULL,
    timestamp_inicio TIMESTAMP DEFAULT CURRENT_TIMESTAMP
);