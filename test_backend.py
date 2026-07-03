import unittest
import json
from unittest.mock import Mock

# Imaginemos que este es tu método de lógica en el Servicio 2 (Evaluador)
def evaluar_capacidad_logica(potencia_kw):
    if potencia_kw > 40.0:
        return False, "Capacidad de transformador excedida"
    return True, None

class TestCoreBackend(unittest.TestCase):

    def test_servicio2_debe_aprobar_consumo_bajo(self):
        """Verifica que potencias menores o iguales a 40.0 kW sean aprobadas"""
        potencia = 22.5
        aprobado, motivo = evaluar_capacidad_logica(potencia)
        
        self.assertTrue(aprobado)
        self.assertIsNone(motivo)

    def test_servicio2_debe_rechazar_consumo_alto(self):
        """Verifica que potencias mayores a 40.0 kW sean denegadas"""
        potencia = 45.0
        aprobado, motivo = evaluar_capacidad_logica(potencia)
        
        self.assertFalse(aprobado)
        self.assertEqual(motivo, "Capacidad de transformador excedida")

    def test_contrato_json_servicio1(self):
        """Verifica que el payload de salida simule el formato del contrato"""
        payload_simulado = {
            "id_solicitud": "REQ-2026-001",
            "id_domicilio": 1045,
            "potencia_solicitada_kw": 22.5
        }
        
        self.assertIn("id_solicitud", payload_simulado)
        self.assertIsInstance(payload_simulado["id_domicilio"], int)

if __name__ == "__main__":
    unittest.main()