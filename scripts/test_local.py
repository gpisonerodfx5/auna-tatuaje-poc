"""
Test local del Lambda Agente Acciones.
Simula las invocaciones que haria Bedrock Agent para validar el flujo end-to-end
contra la API de Multisede UAT (sin necesidad de AWS).

Ejecutar: python scripts/test_local.py
"""

import json
import sys
import os

# Agregar el directorio del lambda al path
sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", "lambda", "agente_acciones"))

# Configurar variables de entorno antes de importar el lambda
os.environ.setdefault("MULTISEDE_BASE_URL", "https://17x9fh4a33.execute-api.us-east-1.amazonaws.com/uat")
os.environ.setdefault("MULTISEDE_USERNAME", "ext2700")
os.environ.setdefault("MULTISEDE_PASSWORD", "Auna2026")
os.environ.setdefault("MULTISEDE_SPECIALTY_ID", "64")
os.environ.setdefault("MULTISEDE_FUNDER_ID", "2")
os.environ.setdefault("MULTISEDE_BENEFIT_ID", "289")
os.environ.setdefault("SECRETS_MULTISEDE_ARN", "")  # Sin Secrets Manager en local

from lambda_function import (
    handle_validar_elegibilidad,
    handle_consultar_disponibilidad,
    handle_crear_cita,
    handle_registrar_resultado,
    get_multisede_token,
    lambda_handler,
    build_bedrock_response,
)


def separator(title):
    print(f"\n{'='*60}")
    print(f"  {title}")
    print(f"{'='*60}\n")


def test_token():
    """Test 1: Verificar que podemos obtener token."""
    separator("TEST 1: Autenticacion Multisede")
    try:
        token = get_multisede_token()
        print(f"[OK] Token obtenido: {token[:40]}...")
        return True
    except Exception as e:
        print(f"[FAIL] Error obteniendo token: {e}")
        return False


def test_validar_elegibilidad(dni="73191563"):
    """Test 2: Buscar paciente por DNI."""
    separator(f"TEST 2: Validar elegibilidad (DNI={dni})")
    result = handle_validar_elegibilidad({"dni": dni, "nombre": "Test"})
    print(f"Resultado: {json.dumps(result, indent=2, ensure_ascii=False)}")

    if result.get("elegible"):
        print(f"\n[OK] Paciente encontrado:")
        print(f"  patient_id: {result['patient_id']}")
        print(f"  clinic_history: {result['clinic_history_number']}")
        print(f"  nombre: {result['nombre_completo']}")
    else:
        print(f"\n[INFO] Paciente no encontrado: {result.get('motivo')}")
        print("  Esto es esperado si el DNI no existe en UAT.")

    return result


def test_consultar_disponibilidad(center_id=4):
    """Test 3: Consultar disponibilidad."""
    separator(f"TEST 3: Consultar disponibilidad (centerId={center_id})")
    result = handle_consultar_disponibilidad({"center_id": center_id, "dias_adelante": 14})

    if result.get("disponible"):
        print(f"[OK] {result['cantidad_opciones']} opciones encontradas:")
        print(f"\n{result['opciones_texto']}")
        print(f"\nDatos tecnicos de la primera opcion:")
        if result.get("opciones"):
            op = result["opciones"][0]
            print(json.dumps(op, indent=2, ensure_ascii=False))
    else:
        print(f"[INFO] Sin disponibilidad: {result.get('motivo')}")
        print("  NOTA: Si ves '401 Unauthorized', el endpoint de disponibilidad")
        print("  requiere permisos adicionales. Contactar a Alexia.")

    return result


def test_crear_cita_mock():
    """Test 4: Simular creacion de cita (NO ejecuta realmente)."""
    separator("TEST 4: Crear cita (SIMULACION - datos ficticios)")

    # NO ejecutar realmente contra el API para no crear citas basura
    print("[SKIP] Este test no se ejecuta automaticamente para evitar")
    print("       crear citas de prueba en el sistema UAT.")
    print()
    print("Para probar manualmente, usar estos parametros:")
    params = {
        "patient_id": 12345,
        "clinic_history_number": 67890,
        "model_id": 296688,
        "doctor_id": 2076,
        "service_id": 531,
        "fecha": "28/03/2026",
        "hora": "09:00:00",
        "holder_name": "Juan",
        "holder_last_name": "Perez",
        "holder_mother_last_name": "Garcia",
        "programa": "PROGRAMA ONCOCLASICO PRO",
    }
    print(json.dumps(params, indent=2, ensure_ascii=False))
    return None


def test_registrar_resultado():
    """Test 5: Registrar resultado (solo funciona con DynamoDB activo)."""
    separator("TEST 5: Registrar resultado")

    print("[SKIP] Requiere DynamoDB activo (solo funciona en AWS).")
    print("       Se probara en la prueba end-to-end.")
    return None


def test_bedrock_event_format():
    """Test 6: Verificar que el formato de evento Bedrock funciona."""
    separator("TEST 6: Formato de evento Bedrock Agent")

    # Simular evento como lo envia Bedrock Agent
    event = {
        "actionGroup": "auna-actions",
        "apiPath": "/validar_elegibilidad",
        "httpMethod": "POST",
        "parameters": [],
        "requestBody": {
            "content": {
                "application/json": {
                    "properties": [
                        {"name": "dni", "type": "string", "value": "73191563"},
                        {"name": "nombre", "type": "string", "value": "Test User"},
                    ]
                }
            }
        },
        "sessionAttributes": {
            "call_id": "test-uuid-12345",
            "programa": "PROGRAMA ONCOCLASICO PRO",
        },
        "promptSessionAttributes": {},
    }

    # Llamar al handler como lo haria Bedrock
    try:
        response = lambda_handler(event, None)
        print(f"[OK] Lambda handler respondio correctamente")
        print(f"messageVersion: {response.get('messageVersion')}")
        body = response.get("response", {}).get("responseBody", {}).get("application/json", {}).get("body", "{}")
        parsed = json.loads(body)
        print(f"Resultado: {json.dumps(parsed, indent=2, ensure_ascii=False)}")
    except Exception as e:
        print(f"[FAIL] Error: {e}")

    return response


def main():
    print("=" * 60)
    print("  TEST LOCAL - PoC Tatuaje Auna")
    print("  Agente Acciones Lambda")
    print("=" * 60)

    # Test 1: Token
    if not test_token():
        print("\n[ABORT] No se pudo obtener token. Verificar credenciales.")
        return

    # Test 2: Buscar paciente
    # Probar con varios DNIs
    test_dnis = ["73191563", "76365787", "41792468"]
    patient_result = None
    for dni in test_dnis:
        result = test_validar_elegibilidad(dni)
        if result.get("elegible"):
            patient_result = result
            break

    # Test 3: Disponibilidad
    avail_result = test_consultar_disponibilidad(center_id=4)

    # Test 4: Crear cita (mock)
    test_crear_cita_mock()

    # Test 5: Registrar resultado (skip)
    test_registrar_resultado()

    # Test 6: Formato Bedrock
    test_bedrock_event_format()

    # Resumen
    separator("RESUMEN")
    print(f"  Autenticacion:   [OK]")
    print(f"  Buscar paciente: {'[OK] encontrado' if patient_result and patient_result.get('elegible') else '[WARN] no encontrado en UAT'}")
    print(f"  Disponibilidad:  {'[OK] ' + str(avail_result.get('cantidad_opciones', 0)) + ' opciones' if avail_result and avail_result.get('disponible') else '[WARN] sin disponibilidad o 401'}")
    print(f"  Crear cita:      [SKIP] (manual)")
    print(f"  DynamoDB:        [SKIP] (requiere AWS)")
    print(f"  Formato Bedrock: [OK]")
    print()

    if not (patient_result and patient_result.get("elegible")):
        print("  NOTA: Los DNIs del CSV de prueba no existen en UAT.")
        print("  Solicitar DNIs de prueba a Alexia para validar end-to-end.")

    if not (avail_result and avail_result.get("disponible")):
        print("  NOTA: El endpoint de disponibilidad retorna 401.")
        print("  Solicitar a Alexia que habilite acceso para ext2700.")


if __name__ == "__main__":
    main()
