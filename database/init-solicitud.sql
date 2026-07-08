CREATE TABLE IF NOT EXISTS solicitudes (
    id_solicitud VARCHAR(50) PRIMARY KEY,
    id_domicilio INT NOT NULL,
    potencia_solicitada_kw DECIMAL(5,2) NOT NULL,
    estado VARCHAR(20) NOT NULL DEFAULT 'En evaluación',
    timestamp TIMESTAMP DEFAULT CURRENT_TIMESTAMP
);

CREATE SEQUENCE IF NOT EXISTS solicitudes_seq START 1;