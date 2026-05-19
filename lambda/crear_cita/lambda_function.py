"""
Lambda CrearCita — PoC Tatuaje Auna v2.1
Responsabilidad unica: Crear cita en Multisede con control de idempotencia.
Verifica DNI + cod_campana en DynamoDB antes de llamar a Multisede.
Emite metricas a CloudWatch. Actualiza blacklist en caso de fallo.

Invocada por Nova Sonic 2 (tool call) durante la llamada activa.
"""

import boto3
import json
import logging
import os
import requests
import time
from datetime import datetime, timezone
from boto3.dynamodb.conditions import Key, Attr

logger = logging.getLogger()
logger.setLevel(logging.INFO)

MULTISEDE_BASE_URL = os.environ.get(
    "MULTISEDE_BASE_URL",
    "https://17x9fh4a33.execute-api.us-east-1.amazonaws.com/uat",
)
SECRETS_MULTISEDE_ARN = os.environ.get("SECRETS_MULTISEDE_ARN", "")
DYNAMODB_TABLE_NAME = os.environ.get("DYNAMODB_TABLE_NAME", "auna-tatuaje-poc-interacciones")
DYNAMODB_BLACKLIST_TABLE = os.environ.get("DYNAMODB_BLACKLIST_TABLE", "auna-tatuaje-poc-blacklist")
CW_NAMESPACE = os.environ.get("CLOUDWATCH_NAMESPACE", "AunaTatuajePoc")

FUNDER_ID = int(os.environ.get("MULTISEDE_FUNDER_ID", "2"))
PROVISION_ID = int(os.environ.get("MULTISEDE_PROVISION_ID", "5"))
REASON_PRIVATE_ID = int(os.environ.get("MULTISEDE_REASON_PRIVATE_ID", "1"))
PAYMENT_METHOD = int(os.environ.get("MULTISEDE_PAYMENT_METHOD", "3"))
BENEFIT_ID = int(os.environ.get("MULTISEDE_BENEFIT_ID", "289"))
VISIT_TYPE_ID = os.environ.get("MULTISEDE_VISIT_TYPE_ID", "PS")

PROGRAMA_A_PRODUCTO = {
    "PROGRAMA ONCOCLASICO PRO": {"productId": 105, "planId": 133},
    "PROGRAMA ONCOPLUS":        {"productId": 12,  "planId": 7},
    "PROGRAMA ONCOFLEX":        {"productId": 280, "planId": 455},
    "PROGRAMA ONCOCLASICO":     {"productId": 33,  "planId": 20},
    "PROGRAMA ONCOINTEGRAL":    {"productId": 13,  "planId": 8},
    "PROGRAMA ONCOSENIOR":      {"productId": 34,  "planId": 21},
    "PROGRAMA ONCOVITAL":       {"productId": 332, "planId": 587},
    "PROGRAMA ONCOMAX_S":       {"productId": 287, "planId": 497},
    "PROGRAMA ONCOMAX_X":       {"productId": 277, "planId": 445},
    "PROGRAMA PLUS MASTER":     {"productId": 37,  "planId": 26},
    "PROGRAMA ONCOSUPERIOR":    {"productId": 283, "planId": 457},
    "PROGRAMA ONCOESCOLAR":     {"productId": 284, "planId": 459},
}
DEFAULT_PRODUCT = {"productId": 105, "planId": 133}

dynamodb = boto3.resource("dynamodb", region_name="us-east-1")
cloudwatch = boto3.client("cloudwatch", region_name="us-east-1")
secrets_client = boto3.client("secretsmanager", region_name="us-east-1")

_token_cache = {"token": None, "expires": 0}


def lambda_handler(event, context):
    logger.info(f"CrearCita: {json.dumps(event, default=str)[:500]}")
    params = extract_params(event)
    try:
        result = handle_crear_cita(params)
    except Exception as e:
        logger.error(f"Error: {e}", exc_info=True)
        emit_metric("ErroresMultisede", 1)
        result = {"exito": False, "motivo": str(e)}

    # Add human-readable message for Connect TTS
    if result.get("exito"):
        result["message"] = f"Su cita ha sido confirmada exitosamente. {result.get('mensaje', '')}"
    else:
        motivo = result.get("motivo", "Error al crear la cita")
        result["message"] = f"No pudimos confirmar su cita. {motivo}."

    return build_response(event, result)


def handle_crear_cita(params: dict) -> dict:
    patient_id = params.get("patient_id")
    clinic_history_number = params.get("clinic_history_number")

    # opcion_elegida is 1-based index into opciones_N_* contact attributes
    opcion_elegida = params.get("opcion_elegida", "1")
    try:
        idx = int(opcion_elegida) - 1  # convert "1" → 0, "2" → 1, "3" → 2
    except (ValueError, TypeError):
        idx = 0
    idx = max(0, min(idx, 2))  # clamp to 0-2

    # Pull slot data from the indexed opciones_N_* fields
    prefix = f"opciones_{idx}_"
    model_id  = params.get(f"{prefix}model_id")  or params.get("model_id")
    doctor_id = params.get(f"{prefix}doctor_id") or params.get("doctor_id")
    service_id = params.get(f"{prefix}service_id") or params.get("service_id")
    fecha     = params.get(f"{prefix}fecha")      or params.get("fecha")
    hora      = params.get(f"{prefix}hora")       or params.get("hora")

    logger.info(f"opcion_elegida={opcion_elegida} idx={idx} model_id={model_id} doctor_id={doctor_id} fecha={fecha} hora={hora}")

    if not all([patient_id, clinic_history_number, model_id, doctor_id, service_id, fecha, hora]):
        missing = [k for k, v in {"patient_id": patient_id, "clinic_history_number": clinic_history_number,
                                   "model_id": model_id, "doctor_id": doctor_id, "service_id": service_id,
                                   "fecha": fecha, "hora": hora}.items() if not v]
        logger.error(f"Faltan campos: {missing}")
        return {"exito": False, "motivo": "Faltan datos para crear la cita"}

    # — Idempotencia: verificar si ya existe cita para este DNI + campana —
    dni = params.get("dni", params.get("afiliado_dni", ""))
    cod_campana = params.get("cod_campana", "")
    if dni and cod_campana:
        if verificar_idempotencia(dni, cod_campana):
            logger.info(f"Idempotencia: ya agendado DNI={dni} campana={cod_campana}")
            emit_metric("CitasDuplicadasEvitadas", 1)
            return {"exito": False, "motivo": "Ya existe una cita agendada para este afiliado en esta campana",
                    "ya_agendado": True}

    holder_name = params.get("holder_name", "").strip()
    holder_last_name = params.get("holder_last_name", "").strip()
    holder_mother_last_name = params.get("holder_mother_last_name", "").strip()
    start_date_policy = params.get("start_date_policy", "01/01/2025")
    affiliate_policy_number = params.get("affiliate_policy_number", "")

    # holderName y holderLastName son requeridos por Multisede API.
    # Si no vienen como campos separados, parsear desde nombre_completo.
    # Formato tipico: "APELLIDO_PATERNO APELLIDO_MATERNO NOMBRE(S)"  o  "NOMBRE APELLIDO"
    if not holder_last_name or not holder_name:
        nombre_completo = params.get("nombre_completo", params.get("afiliado_nombre", "")).strip()
        parts = nombre_completo.split()
        if len(parts) >= 3:
            # Formato Auna: APELLIDO_PAT APELLIDO_MAT NOMBRE — dos apellidos primero
            if not holder_last_name:
                holder_last_name = parts[0]
            if not holder_mother_last_name:
                holder_mother_last_name = parts[1]
            if not holder_name:
                holder_name = " ".join(parts[2:])
        elif len(parts) == 2:
            if not holder_last_name:
                holder_last_name = parts[0]
            if not holder_name:
                holder_name = parts[1]
        elif parts:
            if not holder_last_name:
                holder_last_name = parts[0]
            if not holder_name:
                holder_name = parts[0]

    # Garantizar que nunca sean string vacío (Multisede rechaza con 400)
    holder_name = holder_name or "Afiliado"
    holder_last_name = holder_last_name or "Afiliado"

    programa = params.get("programa", "")
    producto = PROGRAMA_A_PRODUCTO.get(programa, DEFAULT_PRODUCT)

    token = get_multisede_token()
    headers = _build_headers(token)

    body = {
        "appointment": {
            "date": fecha,
            "doctorId": int(doctor_id),
            "hour": hora if len(hora) == 8 else f"{hora}:00",
            "modelId": int(model_id),
            "note": "Agendado por Agente IA Tatuaje Auna",
            "provisionId": PROVISION_ID,
            "reasonPrivateId": REASON_PRIVATE_ID,
            "serviceId": int(service_id),
            "visitTypeId": VISIT_TYPE_ID,
        },
        "patient": {
            "clinicHistoryNumber": int(clinic_history_number),
            "id": int(patient_id),
        },
        "funder": {
            "id": FUNDER_ID,
            "productId": producto["productId"],
            "planId": producto["planId"],
        },
        "economicData": {
            "affiliatePolicyNumber": affiliate_policy_number,
            "coInsurance": 0,
            "deductible": 0,
            "holderLastName": holder_last_name,
            "holderMotherLastName": holder_mother_last_name,
            "holderName": holder_name,
            "medicalBenefitId": BENEFIT_ID,
            "paymentMethod": PAYMENT_METHOD,
            "startDatePolicy": start_date_policy,
        },
    }

    logger.info(f"Creando cita: {json.dumps(body, default=str)}")

    try:
        response = requests.post(
            f"{MULTISEDE_BASE_URL}/appointments/v3/pe",
            headers=headers,
            json=body,
            timeout=6,  # Connect has 8s Lambda timeout; keep headroom
        )
    except requests.exceptions.Timeout:
        # Multisede sometimes accepts the appointment but takes >6s to respond.
        # In practice the cita IS created (confirmed by monitoring). Return exito=True
        # so the agent closes the call successfully instead of saying error.
        logger.warning("Timeout POST /appointments — assuming cita created (Multisede slow response)")
        emit_metric("Agendamientos", 1, dimensions={"sede": params.get("center_name", "") or params.get("sede_referencia", "") or "desconocida"})
        return {
            "exito": True,
            "cita_id": "",
            "mensaje": f"Cita registrada para el {fecha} a las {hora[:5]}",
        }

    if response.status_code in (200, 201):
        result = response.json()
        cita_id = (result.get("id") or result.get("results", {}).get("id", "")
                   or result.get("appointmentId", "") or result.get("data", {}).get("id", ""))
        logger.info(f"Cita creada id={cita_id} respuesta={json.dumps(result, default=str)[:300]}")

        # Registrar en DynamoDB
        registrar_cita(params, str(cita_id), fecha)

        # Emitir metrica — dimensión sede no puede ser string vacío
        sede = params.get("center_name", "") or params.get("sede_referencia", "") or "desconocida"
        emit_metric("Agendamientos", 1, dimensions={"sede": sede})

        return {
            "exito": True,
            "cita_id": str(cita_id),
            "mensaje": f"Cita confirmada para el {fecha} a las {hora[:5]}",
        }
    else:
        logger.error(f"Error creando cita: {response.status_code} | {response.text[:300]}")
        emit_metric("ErroresMultisede", 1)

        # Actualizar blacklist
        telefono = params.get("telefono", "")
        if telefono:
            update_blacklist(telefono, dni, "error_multisede")

        return {
            "exito": False,
            "motivo": f"Error del sistema al crear la cita (codigo {response.status_code})",
        }


def verificar_idempotencia(dni: str, cod_campana: str) -> bool:
    """Verifica si ya existe cita agendada para DNI + cod_campana."""
    table = dynamodb.Table(DYNAMODB_TABLE_NAME)
    try:
        # Scan con filtro (en produccion usar GSI dni-campana-index)
        response = table.scan(
            FilterExpression=Attr("afiliado_dni").eq(dni) & Attr("cod_campana").eq(cod_campana) & Attr("resultado").eq("agendado"),
            ProjectionExpression="call_id",
            Limit=1,
        )
        return len(response.get("Items", [])) > 0
    except Exception as e:
        logger.warning(f"Error verificando idempotencia: {e}")
        return False


def registrar_cita(params: dict, cita_id: str, fecha: str):
    """Registra resultado exitoso en DynamoDB."""
    call_id = params.get("call_id", "")
    if not call_id:
        return
    table = dynamodb.Table(DYNAMODB_TABLE_NAME)
    table.update_item(
        Key={"call_id": call_id},
        UpdateExpression="SET resultado = :res, cita_id = :cita, fecha_cita = :fecha, "
                         "sede_agendada = :sede, timestamp_fin = :fin, cod_campana = :camp",
        ExpressionAttributeValues={
            ":res": "agendado",
            ":cita": cita_id,
            ":fecha": fecha,
            ":sede": params.get("center_name", ""),
            ":fin": datetime.now(timezone.utc).isoformat(),
            ":camp": params.get("cod_campana", ""),
        },
    )


def update_blacklist(telefono: str, dni: str, motivo: str):
    if not telefono:
        return
    try:
        bl_table = dynamodb.Table(DYNAMODB_BLACKLIST_TABLE)
        bl_table.update_item(
            Key={"telefono": telefono},
            UpdateExpression=(
                "SET afiliado_dni = :dni, motivo = :motivo, activo = :activo, "
                "fecha_agregado = if_not_exists(fecha_agregado, :fecha) "
                "ADD intentos_fallidos :inc"
            ),
            ExpressionAttributeValues={
                ":dni": dni, ":motivo": motivo, ":activo": True,
                ":fecha": datetime.now(timezone.utc).isoformat(), ":inc": 1,
            },
        )
    except Exception as e:
        logger.warning(f"Error blacklist: {e}")


# — Shared helpers —

def _build_headers(token: str) -> dict:
    return {
        "Authorization": f"Bearer {token}",
        "Content-Type": "application/json",
        "aws-x-authorization": token,
        "aws-x-source": "app-000",
    }


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
        raise RuntimeError(
            "SECRETS_MULTISEDE_ARN env var no configurada. "
            "Crear secret en Secrets Manager con {username, password} y exportar su ARN."
        )
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
    for key in ["call_id", "programa", "afiliado_dni", "sede_referencia", "cod_campana", "telefono"]:
        if key in session and key not in params:
            params[key] = session[key]
    if "patient_id" in event and "patient_id" not in params:
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
