CREATE TABLE IF NOT EXISTS transformadores (
    id_transformador INT PRIMARY KEY,
    capacidad_total_kw DECIMAL(8,2) NOT NULL,
    capacidad_restante_kw DECIMAL(8,2) NOT NULL
);

INSERT INTO transformadores (id_transformador, capacidad_total_kw, capacidad_restante_kw)
VALUES
    (1, 100.00, 100.00),
    (2, 100.00, 100.00),
    (3, 100.00, 100.00)
ON CONFLICT (id_transformador) DO NOTHING;