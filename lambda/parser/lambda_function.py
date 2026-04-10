"""
Lambda Parser — PoC Tatuaje Auna v2.1
Responsabilidad unica: Lee CSV de S3, valida, normaliza y publica 1 mensaje
por afiliado en SQS. No hace llamadas ni consulta blacklist.

Trigger: S3 ObjectCreated event en input/*.csv
"""

import boto3
import csv
import io
import json
import logging
import os
import uuid

logger = logging.getLogger()
logger.setLevel(logging.INFO)

s3 = boto3.client("s3")
sqs = boto3.client("sqs", region_name="us-east-1")

SQS_QUEUE_URL = os.environ.get("SQS_QUEUE_URL", "")


def lambda_handler(event, context):
    logger.info(f"Parser invocado: {json.dumps(event, default=str)[:500]}")

    # S3 Event
    if "Records" in event and "s3" in event["Records"][0]:
        record = event["Records"][0]
        bucket = record["s3"]["bucket"]["name"]
        key = record["s3"]["object"]["key"]
    # Step Functions direct invocation
    elif "bucket" in event and "key" in event:
        bucket = event["bucket"]
        key = event["key"]
    else:
        return {"error": "Evento no reconocido"}

    logger.info(f"CSV: s3://{bucket}/{key}")

    obj = s3.get_object(Bucket=bucket, Key=key)
    csv_content = obj["Body"].read().decode("utf-8-sig")

    afiliados = parse_csv(csv_content)
    logger.info(f"Registros validos: {len(afiliados)}")

    if not SQS_QUEUE_URL:
        return {"error": "SQS_QUEUE_URL no configurada", "parsed": len(afiliados)}

    sent = 0
    errors = 0
    for af in afiliados:
        try:
            send_kwargs = {
                "QueueUrl": SQS_QUEUE_URL,
                "MessageBody": json.dumps(af, default=str),
            }
            if ".fifo" in SQS_QUEUE_URL:
                send_kwargs["MessageGroupId"] = "llamadas"
            sqs.send_message(**send_kwargs)
            sent += 1
        except Exception as e:
            logger.error(f"Error SQS: {e}")
            errors += 1

    logger.info(f"SQS: {sent} enviados, {errors} errores")
    return {"sent": sent, "errors": errors, "total_parsed": len(afiliados)}


def parse_csv(csv_content: str) -> list[dict]:
    afiliados = []
    reader = csv.DictReader(io.StringIO(csv_content))

    for i, row in enumerate(reader, start=2):
        dni = str(row.get("numero_documento_afil", "")).strip()
        if not dni or len(dni) not in (8, 9, 12):
            logger.warning(f"Fila {i}: DNI invalido '{dni}'")
            continue

        telefono = row.get("telefono", "").strip()
        if not telefono or not telefono.startswith("+"):
            logger.warning(f"Fila {i}: Telefono invalido | DNI={dni}")
            continue

        nombre = str(row.get("apellidos_nombres_afil", "")).strip().title()
        if not nombre:
            nombre = f"Afiliado {dni}"

        afiliados.append({
            "call_id":         str(uuid.uuid4()),
            "dni":             dni,
            "nombre_completo": nombre,
            "telefono":        telefono,
            "programa":        str(row.get("programa_final", "")).strip(),
            "sede_referencia": str(row.get("sede_referencia", "4")).strip(),
            "cuotas_pagadas":  str(row.get("cantidad_cuotas_pagadas", "")),
            "grupo_cuota":     str(row.get("grupo_cuota_pagada", "")),
            "cod_campana":     str(row.get("cod_campana", "")).strip(),
        })

    return afiliados
