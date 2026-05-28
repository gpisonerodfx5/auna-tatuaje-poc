"""
Auditor de tags para todos los recursos del PoC Tatuaje Auna.

Busca recursos taggeados con `project=auna-tatuaje-poc` y verifica que
TODOS lleven el tag `aws-apn-id=pc:55xvhbzjwkkzw9hupxc9n3m2l` (categoría
CX del AWS Partner Network). Si encuentra recursos sin el tag, los lista
y opcionalmente los corrige.

Uso:
    # Solo audita (no modifica nada) — recomendado primero
    python scripts/retag_resources.py --profile <perfil>

    # Audita y corrige los faltantes
    python scripts/retag_resources.py --profile <perfil> --apply

    # Usado como Lambda (handler retag_handler), corre en modo --apply
    # automáticamente y publica el resumen a un topic SNS si encuentra
    # recursos que faltaban.

Diseñado para correr:
  - Manualmente cuando alguien crea recursos desde la consola sin tags.
  - Como Lambda + EventBridge Schedule semanal (ver scripts/deploy_retagger_lambda.py).
"""

import argparse
import json
import logging
import os
import sys
from typing import Iterable

import boto3
from botocore.exceptions import ClientError

# Configuración estándar — debe coincidir con TAGS de los scripts de deploy
PROJECT_TAG_KEY = "project"
PROJECT_TAG_VALUE = "auna-tatuaje-poc"
APN_TAG_KEY = "aws-apn-id"
APN_TAG_VALUE = "pc:55xvhbzjwkkzw9hupxc9n3m2l"  # categoría CX
ENV_TAG_KEY = "env"
ENV_TAG_VALUE_DEFAULT = "poc"

REQUIRED_TAGS = {
    PROJECT_TAG_KEY: PROJECT_TAG_VALUE,
    APN_TAG_KEY: APN_TAG_VALUE,
}

logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(message)s")
log = logging.getLogger("retagger")


def list_project_resources(session: boto3.Session) -> list[dict]:
    """Devuelve todos los recursos con tag project=auna-tatuaje-poc."""
    api = session.client("resourcegroupstaggingapi")
    resources: list[dict] = []
    paginator = api.get_paginator("get_resources")
    for page in paginator.paginate(TagFilters=[{"Key": PROJECT_TAG_KEY, "Values": [PROJECT_TAG_VALUE]}]):
        resources.extend(page.get("ResourceTagMappingList", []))
    return resources


def resources_missing_tag(resources: list[dict], tag_key: str, tag_value: str) -> list[dict]:
    """Filtra recursos que NO tienen el tag (key + value)."""
    missing = []
    for r in resources:
        tags = {t["Key"]: t["Value"] for t in r.get("Tags", [])}
        if tags.get(tag_key) != tag_value:
            missing.append(r)
    return missing


def apply_tags(session: boto3.Session, arns: Iterable[str], tags: dict) -> dict:
    """Aplica tags a una lista de ARNs en lotes de 20 (límite AWS)."""
    api = session.client("resourcegroupstaggingapi")
    arns = list(arns)
    failed: dict = {}
    for i in range(0, len(arns), 20):
        batch = arns[i : i + 20]
        try:
            r = api.tag_resources(ResourceARNList=batch, Tags=tags)
            failed.update(r.get("FailedResourcesMap", {}))
        except ClientError as e:
            for arn in batch:
                failed[arn] = {"ErrorMessage": str(e)}
    return failed


def audit_and_fix(session: boto3.Session, apply: bool) -> dict:
    """Devuelve un resumen del estado del tagging."""
    log.info(f"Listando recursos con tag {PROJECT_TAG_KEY}={PROJECT_TAG_VALUE}...")
    resources = list_project_resources(session)
    total = len(resources)
    log.info(f"Total recursos del proyecto: {total}")

    missing = resources_missing_tag(resources, APN_TAG_KEY, APN_TAG_VALUE)
    log.info(f"Recursos sin tag {APN_TAG_KEY}={APN_TAG_VALUE}: {len(missing)}")

    summary = {
        "total_resources": total,
        "missing_apn_tag": [r["ResourceARN"] for r in missing],
        "applied": False,
        "failed": {},
    }

    if not missing:
        return summary

    for r in missing:
        log.warning(f"  FALTA tag {APN_TAG_KEY}: {r['ResourceARN']}")

    if apply:
        log.info(f"Aplicando tag {APN_TAG_KEY}={APN_TAG_VALUE} a {len(missing)} recursos...")
        failed = apply_tags(session, [r["ResourceARN"] for r in missing], {APN_TAG_KEY: APN_TAG_VALUE})
        summary["applied"] = True
        summary["failed"] = failed
        if failed:
            for arn, err in failed.items():
                log.error(f"  FALLO: {arn} -> {err}")
        else:
            log.info(f"OK: todos los recursos tagueados")
    else:
        log.info(f"DRY-RUN: usar --apply para corregir los {len(missing)} recursos faltantes")

    return summary


# --- CLI -------------------------------------------------------------------

def main() -> int:
    p = argparse.ArgumentParser(description=__doc__)
    p.add_argument("--profile", required=True, help="Perfil AWS local")
    p.add_argument("--region", default="us-east-1")
    p.add_argument("--apply", action="store_true",
                   help="Aplicar el tag faltante (sin esta flag, solo audita)")
    args = p.parse_args()

    session = boto3.Session(profile_name=args.profile, region_name=args.region)
    summary = audit_and_fix(session, apply=args.apply)
    print()
    print(json.dumps({
        "total_resources": summary["total_resources"],
        "missing": len(summary["missing_apn_tag"]),
        "applied": summary["applied"],
        "failed": len(summary["failed"]),
    }, indent=2))
    return 1 if summary["missing_apn_tag"] and not args.apply else 0


# --- Lambda handler --------------------------------------------------------

def retag_handler(event, context):
    """
    Handler para correr como Lambda programada por EventBridge.
    Modo --apply siempre. Notifica via SNS si encuentra recursos sin tag.

    Env vars:
      AWS_REGION             — región a auditar (default us-east-1)
      SNS_NOTIFY_TOPIC_ARN   — opcional: topic donde publicar el resumen
                               si encontró recursos sin tag al iniciar
    """
    region = os.environ.get("AWS_REGION", "us-east-1")
    sns_topic = os.environ.get("SNS_NOTIFY_TOPIC_ARN", "")

    session = boto3.Session(region_name=region)
    summary = audit_and_fix(session, apply=True)

    # Notificar solo si tuvo que corregir algo o si quedaron fallos
    found_missing = len(summary["missing_apn_tag"])
    failed = len(summary["failed"])

    if sns_topic and (found_missing or failed):
        msg = (
            f"[Retagger PoC Tatuaje] Auditoría completada.\n\n"
            f"Total recursos del proyecto: {summary['total_resources']}\n"
            f"Recursos sin tag aws-apn-id: {found_missing}\n"
            f"Recursos corregidos automáticamente: {found_missing - failed}\n"
            f"Fallos al aplicar tag: {failed}\n\n"
            f"Lista de recursos faltantes:\n"
            + "\n".join(f"  - {arn}" for arn in summary["missing_apn_tag"])
        )
        if failed:
            msg += "\n\nFallos:\n" + json.dumps(summary["failed"], indent=2)
        sns = session.client("sns")
        sns.publish(
            TopicArn=sns_topic,
            Subject=f"PoC Tatuaje: {found_missing} recursos sin aws-apn-id",
            Message=msg,
        )
        log.info(f"Notificación SNS enviada a {sns_topic}")

    return {
        "statusCode": 200,
        "body": json.dumps({
            "total_resources": summary["total_resources"],
            "missing_at_start": found_missing,
            "fixed": found_missing - failed,
            "failed": failed,
        }),
    }


if __name__ == "__main__":
    sys.exit(main())
