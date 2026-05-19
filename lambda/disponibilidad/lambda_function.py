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
    logger.info(f"Disponibilidad event: {json.dumps(event, default=str)[:1200]}")
    params = extract_params(event)
    logger.info(f"Disponibilidad params: {json.dumps(params, default=str)[:800]}")
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


WEEKDAY_MAP = {
    "lunes": 0, "martes": 1, "miercoles": 2, "miércoles": 2,
    "jueves": 3, "viernes": 4, "sabado": 5, "sábado": 5, "domingo": 6,
}


def _normalize_dia_especifico(raw: str) -> int:
    """Map spanish weekday name (any case/accent) to int 0-6 or -1 for none."""
    if not raw:
        return -1
    key = raw.strip().lower()
    # also accept digits
    if key.isdigit():
        v = int(key)
        return v if 0 <= v <= 6 else -1
    return WEEKDAY_MAP.get(key, -1)


def handle_disponibilidad(params: dict) -> dict:
    center_id = int(params.get("center_id", 1))
    dias_adelante = int(params.get("dias_adelante", 60))
    preferencia_dia = (params.get("preferencia_dia", "cualquiera") or "cualquiera").strip().lower()
    preferencia_horario = (params.get("preferencia_horario", "cualquiera") or "cualquiera").strip().lower()
    dia_especifico = _normalize_dia_especifico(params.get("dia_especifico", ""))  # -1 = no filter
    pagina_raw = params.get("pagina", "0") or "0"  # default "0" si viene vacio o None
    pagina = int(pagina_raw) if pagina_raw.strip().isdigit() else 0

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

    # Usar hora peruana (UTC-5) para determinar "hoy" — evita filtrar slots validos
    # cuando la Lambda corre cerca de medianoche UTC
    peru_tz = timezone(timedelta(hours=-5))
    today = datetime.now(peru_tz).date()
    max_date = today + timedelta(days=dias_adelante)

    # Recolecta TODAS las opciones disponibles primero, luego pagina.
    todas_opciones = []
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
        if dia_especifico >= 0:
            if weekday != dia_especifico:
                continue
        else:
            if preferencia_dia == "semana" and weekday >= 5:
                continue
            if preferencia_dia in ("finde", "sabado") and weekday != 5:
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

        for sch in free_schedules:
            todas_opciones.append({
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

    # Ordena por fecha+hora (la API ya devuelve ordenado pero por si acaso)
    todas_opciones.sort(key=lambda o: (o["fecha"][6:10] + o["fecha"][3:5] + o["fecha"][0:2], o["hora"]))

    # Espacia las opciones para que el caller vea variedad: en lugar de mostrar
    # 13:00 13:10 13:20 (todos del mismo dia y casi misma hora), tomamos slots
    # cada step para abarcar mas dias/horarios cuando hay muchas opciones.
    total_disponibles = len(todas_opciones)
    if total_disponibles > 9:
        # Si hay mas de 9, espacia para que las paginas muestren slots distribuidos
        step = max(1, total_disponibles // 9)
        opciones_espaciadas = todas_opciones[::step][:9]
        # Garantiza que tenemos al menos 9 si era posible
        if len(opciones_espaciadas) < min(9, total_disponibles):
            opciones_espaciadas = todas_opciones[:9]
        opciones_paginables = opciones_espaciadas
    else:
        opciones_paginables = todas_opciones

    logger.info(f"Total opciones disponibles: {total_disponibles}, paginables: {len(opciones_paginables)}")

    # Paginacion: 3 opciones por pagina
    inicio = pagina * 3
    fin = inicio + 3
    opciones = opciones_paginables[inicio:fin]
    hay_mas = fin < len(opciones_paginables)

    if not opciones:
        # Si no hay con preferencia, informar para que el agente pregunte otra fecha
        horario_label = {"manana": "en la manana", "tarde": "en la tarde"}.get(preferencia_horario, "")
        if dia_especifico >= 0:
            dia_nombre = [k for k, v in WEEKDAY_MAP.items() if v == dia_especifico and len(k) <= 9][0]
            motivo = f"no hay horarios disponibles para el {dia_nombre} {horario_label}".strip()
            mensaje_natural = f"Lo siento, no encontre horarios disponibles para el {dia_nombre} {horario_label}. Quiere intentar con otro dia o cambiar el horario?".strip()
        elif preferencia_dia == "sabado":
            motivo = f"no hay horarios disponibles para sabado {horario_label}".strip()
            mensaje_natural = f"Lo siento, no encontre horarios disponibles para sabado {horario_label}. Quiere intentar otro dia o cambiar el horario?".strip()
        else:
            motivo = f"no hay horarios disponibles para esa preferencia"
            mensaje_natural = f"Lo siento, no encontre horarios disponibles para esa preferencia. Quiere intentar con otro dia u otro horario?"
        emit_metric("SinDisponibilidad", 1, dimensions={"sede": str(center_id)})
        return {
            "disponible": False,
            "motivo": motivo,
            "opciones_texto_con_pregunta": mensaje_natural,
            "opciones_texto": mensaje_natural,
        }

    # Texto LARGO con todos los datos (para fallback / tracking)
    opciones_texto_largo = []
    for i, op in enumerate(opciones, 1):
        opciones_texto_largo.append(
            f"Opcion {i}: {op['fecha_display']} a las {op['hora'][:5]} "
            f"con {op['doctor_name']} en {op['center_name']}"
        )
    texto_largo = ". ".join(opciones_texto_largo)

    def _hora_amigable(hora_str: str) -> str:
        h = int(hora_str.split(':')[0])
        m = int(hora_str.split(':')[1])
        if h == 0:
            return "doce de la noche" if m == 0 else f"doce y {m:02d} de la noche"
        if h < 12:
            base = h
            ampm = "de la manana"
        elif h == 12:
            return "doce del mediodia" if m == 0 else f"doce y {m:02d} del mediodia"
        else:
            base = h - 12
            ampm = "de la tarde" if h < 19 else "de la noche"
        return f"{base} {ampm}" if m == 0 else f"{base} y {m:02d} {ampm}"

    def _primer_nombre(full: str) -> str:
        # "Mauricio Alejandro Rodriguez Moscoso" -> "Mauricio Rodriguez"
        parts = full.strip().split()
        if len(parts) >= 2:
            return f"{parts[0]} {parts[-2] if len(parts) >= 3 else parts[-1]}"
        return full

    # Texto natural y conversacional con dia + mes + hora + doctor en cada opcion.
    # NOTA: la SEDE NO se menciona aqui — en la PoC todas las opciones vienen de la
    # misma sede (no hay capacidad de filtrar por sede del usuario porque Multisede
    # no expone la ciudad del afiliado, solo direccion como texto libre).
    # Va al MessageParticipant del flow que lee LITERAL — no depende de Nova Pro.
    opciones_texto_corto = []
    for i, op in enumerate(opciones, 1):
        # fecha_display ej: "jueves 16 de abril de 2026" -> "jueves 16 de abril"
        partes = op['fecha_display'].split(' de ')
        if len(partes) >= 2:
            fecha_natural = f"{partes[0]} de {partes[1]}"  # "jueves 16 de abril"
        else:
            fecha_natural = op['fecha_display']
        hora_str = _hora_amigable(op['hora'][:5])
        doc = _primer_nombre(op['doctor_name'])
        # "opcion uno: jueves 16 de abril a la una de la tarde con el doctor Mauricio Rodriguez"
        ord_palabras = {1: "uno", 2: "dos", 3: "tres"}
        opciones_texto_corto.append(
            f"opcion {ord_palabras.get(i, str(i))}: {fecha_natural} a las {hora_str} con el doctor {doc}"
        )

    texto_opciones = ". ".join(opciones_texto_corto)
    texto_con_pregunta = f"Tengo tres opciones para usted. {texto_opciones}. Cual de estas opciones prefiere?"
    logger.info(f"opciones_texto devuelto (pagina={pagina}): {texto_largo}")
    texto_final = texto_largo  # backward-compat name

    return {
        "disponible": True,
        "cantidad_opciones": len(opciones),
        "opciones_texto": texto_final,
        "opciones_texto_con_pregunta": texto_con_pregunta,
        "opciones": opciones,
        "hay_mas": hay_mas,
        "pagina": pagina,
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
    return f"{days[d.weekday()]} {d.day} de {months[d.month]} de {d.year}"


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
    for key in ["call_id", "sede_referencia"]:
        if key in session and key not in params:
            params[key] = session[key]
    if "center_id" in event and "center_id" not in params:
        params.update(event)
    return params


def _connect_response(result: dict) -> dict:
    """Flatten result to string key-value pairs for Connect.
    Also expands opciones list into individual fields opciones_N_* for the flow.
    """
    flat = {}
    for k, v in result.items():
        if isinstance(v, bool):
            flat[k] = "true" if v else "false"
        elif isinstance(v, (dict, list)):
            flat[k] = json.dumps(v, ensure_ascii=False, default=str)
        else:
            flat[k] = str(v) if v is not None else ""

    # Expand opciones list into individual top-level fields so the flow can
    # save them as contact attributes and pass them to CrearCita later.
    opciones = result.get("opciones", [])
    fields = ["model_id", "doctor_id", "doctor_name", "service_id", "center_id",
              "center_name", "fecha", "hora", "fecha_display"]
    for i in range(3):
        for field in fields:
            key = f"opciones_{i}_{field}"
            if i < len(opciones):
                val = opciones[i].get(field, "")
                flat[key] = str(val) if val is not None else ""
            else:
                flat[key] = ""
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
