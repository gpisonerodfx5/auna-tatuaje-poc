"""
Lambda Health Check — PoC Tatuaje Auna v2
Valida que la API Multisede esté disponible antes de iniciar llamadas.
Invocada por Step Functions como primer paso del flujo.
"""

import boto3
import json
import logging
import os
import requests
from datetime import datetime, timezone

logger = logging.getLogger()
logger.setLevel(logging.INFO)

MULTISEDE_BASE_URL = os.environ.get(
    "MULTISEDE_BASE_URL",
    "https://17x9fh4a33.execute-api.us-east-1.amazonaws.com/uat",
)
SECRETS_MULTISEDE_ARN = os.environ.get("SECRETS_MULTISEDE_ARN", "")


def lambda_handler(event, context):
    """
    Intenta autenticarse en Multisede.
    Retorna {"api_available": true/false} para que Step Functions decida.
    Connect: retorna flat string dict con campo 'message' para TTS.
    """
    logger.info("Health check iniciado")
    is_connect = "Details" in event

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

        # API not available — raise so Connect routes to error path (no call should proceed)
        msg = f"API Multisede no disponible (HTTP {response.status_code})"
        logger.warning(f"Health check FAILED — {msg}")
        raise RuntimeError(msg)

    except requests.exceptions.Timeout:
        logger.error("Health check TIMEOUT")
        raise RuntimeError("API Multisede no responde (timeout)")

    except RuntimeError:
        raise  # re-raise our own errors

    except Exception as e:
        logger.error(f"Health check ERROR: {e}")
        raise RuntimeError(f"Health check error: {e}") from e


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
        return (
            os.environ.get("MULTISEDE_USERNAME", "ext2700"),
            os.environ.get("MULTISEDE_PASSWORD", "Auna2026"),
        )
    secrets = boto3.client("secretsmanager", region_name="us-east-1")
    secret = secrets.get_secret_value(SecretId=SECRETS_MULTISEDE_ARN)
    creds = json.loads(secret["SecretString"])
    return creds["username"], creds["password"]
