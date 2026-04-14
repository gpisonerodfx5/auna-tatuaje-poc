"""
Lambda ValidarPaciente — PoC Tatuaje Auna v2.1
Responsabilidad unica: Buscar paciente por DNI en Multisede (search-patient)
y enriquecer con datos de poliza (insurance-client).
Emite metricas a CloudWatch.

Invocada por Nova Sonic 2 (tool call) durante la llamada activa.
"""

import boto3
import json
import logging
import os
import requests
import time
from datetime import datetime, timezone

logger = logging.getLogger()
logger.setLevel(logging.INFO)

MULTISEDE_BASE_URL = os.environ.get(
    "MULTISEDE_BASE_URL",
    "https://17x9fh4a33.execute-api.us-east-1.amazonaws.com/uat",
)
SECRETS_MULTISEDE_ARN = os.environ.get("SECRETS_MULTISEDE_ARN", "")
FUNDER_ID = int(os.environ.get("MULTISEDE_FUNDER_ID", "2"))
CW_NAMESPACE = os.environ.get("CLOUDWATCH_NAMESPACE", "AunaTatuajePoc")

cloudwatch = boto3.client("cloudwatch", region_name="us-east-1")
secrets_client = boto3.client("secretsmanager", region_name="us-east-1")

_token_cache = {"token": None, "expires": 0}


def lambda_handler(event, context):
    logger.info(f"ValidarPaciente: {json.dumps(event, default=str)}")
    is_connect = "Details" in event
    params = extract_params(event)
    try:
        result = handle_validar(params)
    except Exception as e:
        logger.error(f"Error: {e}", exc_info=True)
        emit_metric("ErroresMultisede", 1)
        # Raise so Connect routes to error path (silent-disconnect before greeting)
        if is_connect:
            raise
        return {"elegible": False, "motivo": str(e)}

    if not result.get("elegible"):
        motivo = result.get("motivo", "no elegible")
        logger.info(f"Paciente no elegible: {motivo}")
        emit_metric("NoElegibles", 1)
        # Raise so Connect routes to error path (silent-disconnect before greeting)
        if is_connect:
            raise RuntimeError(motivo)
        return result

    # Elegible — return result (Connect goes to greeting)
    return build_response(event, result)


def handle_validar(params: dict) -> dict:
    dni = str(params.get("dni", "")).strip()
    if not dni:
        return {"elegible": False, "motivo": "DNI no proporcionado"}

    token = get_multisede_token()
    headers = _build_headers(token)

    response = requests.post(
        f"{MULTISEDE_BASE_URL}/maintainers/v1/search-patient/pe",
        headers=headers,
        json={"document_number": dni, "pagination": {"number": 1, "size": 5}},
        timeout=5,
    )

    if response.status_code == 404 or (response.status_code == 200 and not response.json().get("results")):
        emit_metric("NoElegibles", 1)
        return {"elegible": False, "motivo": "Paciente no encontrado en el sistema"}

    if response.status_code != 200:
        emit_metric("ErroresMultisede", 1)
        return {"elegible": False, "motivo": f"Error buscando paciente ({response.status_code})"}

    patient = response.json()["results"][0]
    fields = patient.get("fields", {})
    patient_id = patient.get("id")
    clinic_history = fields.get("medical_record_number")
    first_name = fields.get("first_name", "")
    last_name = fields.get("last_name", "")
    mother_last_name = fields.get("mother_last_name", "")

    logger.info(f"Paciente encontrado: id={patient_id} | {first_name} {last_name}")

    # Enriquecer con datos de poliza
    try:
        policy_data = _get_insurance_policy(dni, token)
    except Exception as e:
        logger.warning(f"Skipping policy enrichment: {e}")
        policy_data = None

    if policy_data:
        mother_last_name = policy_data.get("holderMotherLastName", mother_last_name)
        holder_last = policy_data.get("holderLastName", "")
        if holder_last:
            last_name = holder_last
        first_name = policy_data.get("holderName", first_name)

    return {
        "elegible": True,
        "patient_id": patient_id,
        "clinic_history_number": clinic_history,
        "holder_name": first_name,
        "holder_last_name": last_name,
        "holder_mother_last_name": mother_last_name,
        "nombre_completo": f"{first_name} {last_name} {mother_last_name}".strip(),
        "affiliate_policy_number": policy_data.get("affiliatePolicyNumber", "") if policy_data else "",
        "start_date_policy": _format_policy_date(policy_data.get("startDatePolicy", "")) if policy_data else "01/01/2025",
    }


# — Helpers —

def _build_headers(token: str) -> dict:
    return {
        "Authorization": f"Bearer {token}",
        "Content-Type": "application/json",
        "aws-x-authorization": token,
        "aws-x-source": "app-000",
    }


def _get_insurance_policy(document: str, token: str) -> dict | None:
    """Enriquece con datos de poliza. Timeout agresivo para no exceder 8s de Connect."""
    headers = _build_headers(token)
    # Solo intentamos docType=1 (DNI) con timeout corto para mantenernos bajo 8s total
    try:
        response = requests.get(
            f"{MULTISEDE_BASE_URL}/insurance-client/v4/pe/policies",
            headers=headers,
            params={"centerId": 4, "document": document, "documentTypeId": 1, "funderId": FUNDER_ID},
            timeout=2,
        )
        if response.status_code == 200:
            results = response.json().get("results", [])
            if results:
                return results[0]
    except Exception as e:
        logger.warning(f"Error poliza: {e}")
    return None


def _format_policy_date(iso_date: str) -> str:
    if not iso_date:
        return "01/01/2025"
    try:
        dt = datetime.fromisoformat(iso_date.replace("Z", "+00:00"))
        return dt.strftime("%d/%m/%Y")
    except (ValueError, TypeError):
        return "01/01/2025"


def get_multisede_token() -> str:
    now = time.time()
    if _token_cache["token"] and now < _token_cache["expires"]:
        return _token_cache["token"]

    username, password = get_credentials()
    response = requests.post(
        f"{MULTISEDE_BASE_URL}/authentication/v1/login",
        json={"username": username, "password": password},
        timeout=15,
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


def emit_metric(name: str, value: float, unit: str = "Count"):
    try:
        cloudwatch.put_metric_data(
            Namespace=CW_NAMESPACE,
            MetricData=[{"MetricName": name, "Value": value, "Unit": unit,
                         "Timestamp": datetime.now(timezone.utc)}],
        )
    except Exception as e:
        logger.warning(f"Error emitiendo metrica {name}: {e}")


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
        content = body.get("content", {})
        json_body = content.get("application/json", {})
        for prop in json_body.get("properties", []):
            params[prop["name"]] = prop.get("value", "")
    session = event.get("sessionAttributes", {})
    for key in ["call_id", "programa", "afiliado_dni", "sede_referencia"]:
        if key in session and key not in params:
            params[key] = session[key]
    # Direct invocation (Step Functions / test)
    if "dni" in event and "dni" not in params:
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
    # If invoked directly (not via Bedrock), return raw result
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
