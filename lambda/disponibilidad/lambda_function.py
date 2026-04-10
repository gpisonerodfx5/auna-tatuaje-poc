"""
Lambda ConsultarDisponibilidad — PoC Tatuaje Auna v2.1
Responsabilidad unica: Consultar disponibilidad en Multisede,
filtrar por centerId localmente, retornar opciones formateadas.
Emite metricas a CloudWatch.

Invocada por Nova Sonic 2 (tool call) durante la llamada activa.
"""

import boto3
import json
import logging
import os
import requests
import time
from datetime import datetime, timezone, timedelta

logger = logging.getLogger()
logger.setLevel(logging.INFO)

MULTISEDE_BASE_URL = os.environ.get(
    "MULTISEDE_BASE_URL",
    "https://17x9fh4a33.execute-api.us-east-1.amazonaws.com/uat",
)
SECRETS_MULTISEDE_ARN = os.environ.get("SECRETS_MULTISEDE_ARN", "")
SPECIALTY_ID = int(os.environ.get("MULTISEDE_SPECIALTY_ID", "85"))
VISIT_TYPE_ID = os.environ.get("MULTISEDE_VISIT_TYPE_ID", "PS")
CW_NAMESPACE = os.environ.get("CLOUDWATCH_NAMESPACE", "AunaTatuajePoc")

cloudwatch = boto3.client("cloudwatch", region_name="us-east-1")
secrets_client = boto3.client("secretsmanager", region_name="us-east-1")

_token_cache = {"token": None, "expires": 0}


def lambda_handler(event, context):
    logger.info(f"Disponibilidad: {json.dumps(event, default=str)[:500]}")
    params = extract_params(event)
    try:
        result = handle_disponibilidad(params)
    except Exception as e:
        logger.error(f"Error: {e}", exc_info=True)
        emit_metric("ErroresMultisede", 1)
        result = {"disponible": False, "motivo": str(e)}

    # Add human-readable message for Connect TTS
    if result.get("disponible"):
        result["message"] = f"Tenemos disponibilidad para su chequeo. {result.get('opciones_texto', '')}"
    else:
        motivo = result.get("motivo", "No hay horarios disponibles")
        result["message"] = f"Lamentablemente, {motivo.lower()}."

    return build_response(event, result)


def handle_disponibilidad(params: dict) -> dict:
    center_id = int(params.get("center_id", 1))
    dias_adelante = int(params.get("dias_adelante", 14))
    preferencia_dia = params.get("preferencia_dia", "cualquiera")      # "semana" | "finde" | "cualquiera"
    preferencia_horario = params.get("preferencia_horario", "cualquiera")  # "manana" | "tarde" | "cualquiera"

    token = get_multisede_token()
    headers = _build_headers(token)

    response = requests.get(
        f"{MULTISEDE_BASE_URL}/availability/v2/pe",
        headers=headers,
        params={
            "specialtyId": SPECIALTY_ID,
            "visitTypeIds": VISIT_TYPE_ID,
            "count": 1500,
            "offset": 0,
        },
        timeout=30,
    )

    if response.status_code != 200:
        emit_metric("ErroresMultisede", 1)
        return {"disponible": False, "motivo": "el servicio de agenda no esta disponible en este momento"}

    all_slots = response.json().get("results", [])
    logger.info(f"Total slots API: {len(all_slots)}")

    filtered = [s for s in all_slots if s.get("centerId") == center_id]
    logger.info(f"Slots centerId={center_id}: {len(filtered)}")

    if not filtered:
        emit_metric("SinDisponibilidad", 1, dimensions={"sede": str(center_id)})
        return {"disponible": False, "motivo": "No hay horarios disponibles en su sede"}

    today = datetime.now(timezone.utc).date()
    max_date = today + timedelta(days=dias_adelante)

    opciones = []
    for slot in filtered:
        slot_date_str = slot.get("date", "")[:10]
        try:
            slot_date = datetime.strptime(slot_date_str, "%Y-%m-%d").date()
        except ValueError:
            continue
        if slot_date < today or slot_date > max_date:
            continue

        # Filtro por preferencia de dia
        weekday = slot_date.weekday()  # 0=lunes ... 5=sabado, 6=domingo
        if preferencia_dia == "semana" and weekday >= 5:
            continue
        if preferencia_dia == "finde" and weekday != 5:  # solo sabado (no domingo)
            continue

        schedules = slot.get("schedules", [])
        free_schedules = [s for s in schedules if s.get("status") == "LI"]

        # Filtro por preferencia de horario
        if preferencia_horario == "manana":
            free_schedules = [s for s in free_schedules if s.get("time", "13:00") < "13:00"]
        elif preferencia_horario == "tarde":
            free_schedules = [s for s in free_schedules if s.get("time", "00:00") >= "13:00"]

        if not free_schedules:
            continue

        doctor_name = slot.get("professionalName", "Doctor")
        center_name = slot.get("centerName", "Sede")

        for sch in free_schedules[:2]:
            opciones.append({
                "model_id": sch.get("modelId"),
                "doctor_id": slot.get("professionalId"),
                "doctor_name": doctor_name,
                "service_id": slot.get("subSpecialtyId"),
                "center_name": center_name,
                "center_id": center_id,
                "fecha": slot_date.strftime("%d/%m/%Y"),
                "hora": sch.get("time", ""),
                "fecha_display": format_date_spanish(slot_date),
            })
            if len(opciones) >= 3:  # max 3 opciones para no abrumar
                break
        if len(opciones) >= 3:
            break

    if not opciones:
        # Si no hay con preferencia, informar para que el agente pregunte otra fecha
        motivo = f"no hay horarios disponibles para su preferencia en los proximos {dias_adelante} dias"
        emit_metric("SinDisponibilidad", 1, dimensions={"sede": str(center_id)})
        return {"disponible": False, "motivo": motivo}

    opciones_texto = []
    for i, op in enumerate(opciones, 1):
        opciones_texto.append(
            f"Opcion {i}: {op['fecha_display']} a las {op['hora'][:5]} "
            f"con el doctor {op['doctor_name'].split()[-1]} en {op['center_name']}"
        )

    return {
        "disponible": True,
        "cantidad_opciones": len(opciones),
        "opciones_texto": ". ".join(opciones_texto),
        "opciones": opciones,
    }


# — Helpers —

def _build_headers(token: str) -> dict:
    return {
        "Authorization": f"Bearer {token}",
        "Content-Type": "application/json",
        "aws-x-authorization": token,
        "aws-x-source": "app-000",
    }


def format_date_spanish(d) -> str:
    days = ["lunes", "martes", "miercoles", "jueves", "viernes", "sabado", "domingo"]
    months = ["", "enero", "febrero", "marzo", "abril", "mayo", "junio",
              "julio", "agosto", "septiembre", "octubre", "noviembre", "diciembre"]
    return f"{days[d.weekday()]} {d.day} de {months[d.month]}"


def get_multisede_token() -> str:
    now = time.time()
    if _token_cache["token"] and now < _token_cache["expires"]:
        return _token_cache["token"]
    username, password = get_credentials()
    response = requests.post(
        f"{MULTISEDE_BASE_URL}/authentication/v1/login",
        json={"username": username, "password": password}, timeout=15,
    )
    response.raise_for_status()
    data = response.json()
    token = data.get("accessToken") or data.get("results", {}).get("accessToken")
    _token_cache["token"] = token
    _token_cache["expires"] = now + (18 * 3600)
    return token


def get_credentials() -> tuple:
    if not SECRETS_MULTISEDE_ARN:
        return (os.environ.get("MULTISEDE_USERNAME", "ext2700"),
                os.environ.get("MULTISEDE_PASSWORD", "Auna2026"))
    secret = secrets_client.get_secret_value(SecretId=SECRETS_MULTISEDE_ARN)
    creds = json.loads(secret["SecretString"])
    return creds["username"], creds["password"]


def emit_metric(name: str, value: float, unit: str = "Count", dimensions: dict = None):
    try:
        metric = {"MetricName": name, "Value": value, "Unit": unit,
                  "Timestamp": datetime.now(timezone.utc)}
        if dimensions:
            metric["Dimensions"] = [{"Name": k, "Value": v} for k, v in dimensions.items()]
        cloudwatch.put_metric_data(Namespace=CW_NAMESPACE, MetricData=[metric])
    except Exception as e:
        logger.warning(f"Error metrica {name}: {e}")


def extract_params(event: dict) -> dict:
    # Connect event format
    if "Details" in event:
        params = {}
        params.update(event.get("Details", {}).get("ContactData", {}).get("Attributes", {}))
        params.update(event.get("Details", {}).get("Parameters", {}))
        return params

    # Bedrock Agent event format
    params = {}
    for p in event.get("parameters", []):
        params[p["name"]] = p.get("value", "")
    body = event.get("requestBody", {})
    if body:
        for prop in body.get("content", {}).get("application/json", {}).get("properties", []):
            params[prop["name"]] = prop.get("value", "")
    session = event.get("sessionAttributes", {})
    for key in ["call_id", "sede_referencia"]:
        if key in session and key not in params:
            params[key] = session[key]
    if "center_id" in event and "center_id" not in params:
        params.update(event)
    return params


def _connect_response(result: dict) -> dict:
    """Flatten result to string key-value pairs for Connect."""
    flat = {}
    for k, v in result.items():
        if isinstance(v, bool):
            flat[k] = "true" if v else "false"
        elif isinstance(v, (dict, list)):
            flat[k] = json.dumps(v, ensure_ascii=False, default=str)
        else:
            flat[k] = str(v) if v is not None else ""
    return flat


def build_response(event: dict, result: dict) -> dict:
    # Connect: return flat string dict
    if "Details" in event:
        return _connect_response(result)
    if "actionGroup" not in event and "apiPath" not in event:
        return result
    return {
        "messageVersion": "1.0",
        "response": {
            "actionGroup": event.get("actionGroup", "auna-actions"),
            "apiPath": event.get("apiPath", ""),
            "httpMethod": event.get("httpMethod", "POST"),
            "httpStatusCode": 200,
            "responseBody": {"application/json": {"body": json.dumps(result, ensure_ascii=False, default=str)}},
        },
        "sessionAttributes": event.get("sessionAttributes", {}),
        "promptSessionAttributes": event.get("promptSessionAttributes", {}),
    }
