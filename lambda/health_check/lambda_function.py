"""
Lambda Health Check — PoC Tatuaje Auna v2
Valida que la API Multisede esté disponible antes de iniciar llamadas.
Tambien soporta action="check_hours" para validar horario laboral Peru.
Invocada por Step Functions como primer paso del flujo.
"""

import boto3
import json
import logging
import os
import requests
from datetime import datetime, timezone, timedelta

logger = logging.getLogger()
logger.setLevel(logging.INFO)

MULTISEDE_BASE_URL = os.environ.get(
    "MULTISEDE_BASE_URL",
    "https://17x9fh4a33.execute-api.us-east-1.amazonaws.com/uat",
)
SECRETS_MULTISEDE_ARN = os.environ.get("SECRETS_MULTISEDE_ARN", "")

# Horario laboral Peru: L-V 9:00-19:00, S 9:00-13:00 (hora Peru, UTC-5)
PERU_TZ = timezone(timedelta(hours=-5))


def _in_working_hours() -> bool:
    now_peru = datetime.now(PERU_TZ)
    weekday = now_peru.weekday()  # 0=lunes ... 6=domingo
    hour = now_peru.hour
    if weekday <= 4:  # Lunes a Viernes
        return 9 <= hour < 19
    if weekday == 5:  # Sabado
        return 9 <= hour < 13
    return False  # Domingo


def lambda_handler(event, context):
    """
    Si event.action == "check_hours": retorna {"in_working_hours": true/false}.
    En otro caso: intenta autenticarse en Multisede y retorna {"api_available": true/false}.
    Connect: retorna flat string dict con campo 'message' para TTS.
    """
    is_connect = "Details" in event
    action = event.get("action", "") if isinstance(event, dict) else ""

    # Action: check_hours (llamado desde Step Functions antes de la llamada)
    if action == "check_hours":
        in_hours = _in_working_hours()
        logger.info(f"check_hours: in_working_hours={in_hours}")
        return {"in_working_hours": in_hours, "timestamp": datetime.now(timezone.utc).isoformat()}

    # Default action: API Multisede health check
    logger.info("Health check iniciado")
    try:
        username, password = get_credentials()

        response = requests.post(
            f"{MULTISEDE_BASE_URL}/authentication/v1/login",
            json={"username": username, "password": password},
            timeout=15,
        )

        if response.status_code in (200, 201):
            data = response.json()
            token = data.get("accessToken") or data.get("results", {}).get("accessToken")
            if token:
                logger.info("Health check OK — API Multisede disponible")
                result = {
                    "api_available": True,
                    "timestamp": datetime.now(timezone.utc).isoformat(),
                }
                return _connect_response(result) if is_connect else result

        # API not available — return available=false so Step Functions routes to fallback
        msg = f"API Multisede no disponible (HTTP {response.status_code})"
        logger.warning(f"Health check FAILED — {msg}")
        if is_connect:
            raise RuntimeError(msg)
        return {"api_available": False, "error": msg}

    except requests.exceptions.Timeout:
        logger.error("Health check TIMEOUT")
        if is_connect:
            raise RuntimeError("API Multisede no responde (timeout)")
        return {"api_available": False, "error": "timeout"}

    except RuntimeError:
        raise  # re-raise for Connect path

    except Exception as e:
        logger.error(f"Health check ERROR: {e}")
        if is_connect:
            raise RuntimeError(f"Health check error: {e}") from e
        return {"api_available": False, "error": str(e)}


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


def get_credentials() -> tuple:
    if not SECRETS_MULTISEDE_ARN:
        raise RuntimeError(
            "SECRETS_MULTISEDE_ARN env var no configurada. "
            "Crear secret en Secrets Manager con {username, password} y exportar su ARN."
        )
    secrets = boto3.client("secretsmanager", region_name="us-east-1")
    secret = secrets.get_secret_value(SecretId=SECRETS_MULTISEDE_ARN)
    creds = json.loads(secret["SecretString"])
    return creds["username"], creds["password"]
