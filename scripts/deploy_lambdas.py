"""
Despliega las 5 Lambdas + Layer compartido en una cuenta AWS.

Pre-requisitos:
  1. Ejecutar antes: python scripts/package_lambdas.py
     (genera dist/*.zip y dist/layer_requests.zip)
  2. Tener creado:
     - IAM role 'auna-tatuaje-poc-lambda-role' con permisos:
       AWSLambdaBasicExecutionRole, acceso a DynamoDB tables PoC,
       acceso a SecretsManager, S3, SQS, Bedrock invocar.
     - DynamoDB tables: auna-tatuaje-poc-interacciones, auna-tatuaje-poc-blacklist
     - SQS queue: auna-tatuaje-poc-llamadas
     - S3 bucket: auna-tatuaje-poc-input-<accountId>
     - Secret en Secrets Manager: auna/multisede/credentials con {username, password}
     (todo lo anterior lo crea scripts/deploy_infra.py)

Uso:
    python scripts/deploy_lambdas.py --profile <perfil-aws> [--region us-east-1]

Hace, para cada Lambda:
  - Crea si no existe, o actualiza el código si ya existe.
  - Configura env vars (incluye SECRETS_MULTISEDE_ARN, DYNAMODB_*, etc).
  - Publica versión nueva.
  - Apunta alias 'live' a esa versión.
  - Asocia el layer compartido auna-tatuaje-poc-deps.
"""

import argparse
import json
import sys
import time
from pathlib import Path

import boto3
from botocore.exceptions import ClientError

ROOT = Path(__file__).resolve().parent.parent
DIST = ROOT / "dist"

LAYER_NAME = "auna-tatuaje-poc-deps"
LAYER_ZIP = DIST / "layer_requests.zip"

LAMBDAS = {
    "parser": {
        "zip": DIST / "parser.zip",
        "function_name": "auna-tatuaje-poc-parser",
        "handler": "lambda_function.lambda_handler",
        "timeout": 60,
        "memory": 256,
        "use_layer": False,  # parser solo usa boto3 (preinstalado)
    },
    "health_check": {
        "zip": DIST / "health_check.zip",
        "function_name": "auna-tatuaje-poc-health-check",
        "handler": "lambda_function.lambda_handler",
        "timeout": 30,
        "memory": 128,
        "use_layer": True,
    },
    "validar_paciente": {
        "zip": DIST / "validar_paciente.zip",
        "function_name": "auna-tatuaje-poc-validar-paciente",
        "handler": "lambda_function.lambda_handler",
        "timeout": 30,
        "memory": 256,
        "use_layer": True,
    },
    "disponibilidad": {
        "zip": DIST / "disponibilidad.zip",
        "function_name": "auna-tatuaje-poc-disponibilidad",
        "handler": "lambda_function.lambda_handler",
        "timeout": 30,
        "memory": 256,
        "use_layer": True,
    },
    "crear_cita": {
        "zip": DIST / "crear_cita.zip",
        "function_name": "auna-tatuaje-poc-crear-cita",
        "handler": "lambda_function.lambda_handler",
        "timeout": 30,
        "memory": 256,
        "use_layer": True,
    },
}

ENV_VARS_COMMON = {
    "MULTISEDE_BASE_URL": "https://17x9fh4a33.execute-api.us-east-1.amazonaws.com/uat",
    "DYNAMODB_TABLE_NAME": "auna-tatuaje-poc-interacciones",
    "DYNAMODB_BLACKLIST_TABLE": "auna-tatuaje-poc-blacklist",
    "CLOUDWATCH_NAMESPACE": "AunaTatuajePoc",
    "MULTISEDE_FUNDER_ID": "2",
    "MULTISEDE_SPECIALTY_ID": "85",
    "MULTISEDE_BENEFIT_ID": "289",
    "MULTISEDE_PROVISION_ID": "5",
    "MULTISEDE_REASON_PRIVATE_ID": "1",
    "MULTISEDE_PAYMENT_METHOD": "3",
    "MULTISEDE_VISIT_TYPE_ID": "PS",
}

TAGS = {"project": "auna-tatuaje-poc", "env": "poc"}


def publish_or_update_layer(lam, region: str) -> str:
    print(f"\n[Layer] Publishing {LAYER_NAME}...")
    if not LAYER_ZIP.exists():
        raise FileNotFoundError(f"Layer ZIP no existe: {LAYER_ZIP}. Corré primero package_lambdas.py.")
    r = lam.publish_layer_version(
        LayerName=LAYER_NAME,
        Description="requests + deps para PoC Tatuaje Auna (py3.12 Linux x86_64)",
        Content={"ZipFile": LAYER_ZIP.read_bytes()},
        CompatibleRuntimes=["python3.12"],
        CompatibleArchitectures=["x86_64"],
    )
    arn = r["LayerVersionArn"]
    print(f"  Layer ARN: {arn}")
    return arn


def lambda_exists(lam, name: str) -> bool:
    try:
        lam.get_function(FunctionName=name)
        return True
    except ClientError as e:
        if e.response["Error"]["Code"] == "ResourceNotFoundException":
            return False
        raise


def deploy_lambda(lam, cfg: dict, role_arn: str, account_id: str, layer_arn: str | None):
    name = cfg["function_name"]
    print(f"\n[Lambda] {name}")

    if not cfg["zip"].exists():
        raise FileNotFoundError(f"{cfg['zip']} no existe. Corré primero package_lambdas.py.")

    secret_arn_placeholder = (
        f"arn:aws:secretsmanager:us-east-1:{account_id}:secret:auna/multisede/credentials"
    )
    env_vars = {
        **ENV_VARS_COMMON,
        "SECRETS_MULTISEDE_ARN": secret_arn_placeholder,
        "AWS_ACCOUNT_ID": account_id,
    }
    if name.endswith("parser"):
        env_vars["SQS_QUEUE_URL"] = (
            f"https://sqs.us-east-1.amazonaws.com/{account_id}/auna-tatuaje-poc-llamadas"
        )

    layers = [layer_arn] if (cfg["use_layer"] and layer_arn) else []

    if lambda_exists(lam, name):
        print("  Updating function code...")
        lam.update_function_code(
            FunctionName=name,
            ZipFile=cfg["zip"].read_bytes(),
        )
        lam.get_waiter("function_updated").wait(FunctionName=name)
        print("  Updating configuration...")
        lam.update_function_configuration(
            FunctionName=name,
            Handler=cfg["handler"],
            Timeout=cfg["timeout"],
            MemorySize=cfg["memory"],
            Environment={"Variables": env_vars},
            Layers=layers,
        )
        lam.get_waiter("function_updated").wait(FunctionName=name)
    else:
        print("  Creating function...")
        lam.create_function(
            FunctionName=name,
            Runtime="python3.12",
            Role=role_arn,
            Handler=cfg["handler"],
            Code={"ZipFile": cfg["zip"].read_bytes()},
            Timeout=cfg["timeout"],
            MemorySize=cfg["memory"],
            Environment={"Variables": env_vars},
            Layers=layers,
            Architectures=["x86_64"],
            Tags=TAGS,
        )
        lam.get_waiter("function_active").wait(FunctionName=name)

    print("  Publishing version...")
    v = lam.publish_version(FunctionName=name)["Version"]
    print(f"  Version: {v}")

    # Alias :live
    try:
        lam.get_alias(FunctionName=name, Name="live")
        lam.update_alias(FunctionName=name, Name="live", FunctionVersion=v)
        print(f"  Alias 'live' -> v{v}")
    except ClientError as e:
        if e.response["Error"]["Code"] == "ResourceNotFoundException":
            lam.create_alias(FunctionName=name, Name="live", FunctionVersion=v)
            print(f"  Alias 'live' creado en v{v}")
        else:
            raise


def main() -> int:
    p = argparse.ArgumentParser(description="Deploy Lambdas + Layer del PoC Tatuaje Auna.")
    p.add_argument("--profile", required=True, help="Perfil AWS local (ej: auna-client)")
    p.add_argument("--region", default="us-east-1")
    p.add_argument(
        "--role-name",
        default="auna-tatuaje-poc-lambda-role",
        help="Nombre del IAM role para las Lambdas",
    )
    args = p.parse_args()

    session = boto3.Session(profile_name=args.profile, region_name=args.region)
    sts = session.client("sts")
    lam = session.client("lambda")
    iam = session.client("iam")

    account_id = sts.get_caller_identity()["Account"]
    print(f"Account: {account_id}  Region: {args.region}  Profile: {args.profile}")

    role = iam.get_role(RoleName=args.role_name)["Role"]
    role_arn = role["Arn"]
    print(f"Role: {role_arn}")

    layer_arn = publish_or_update_layer(lam, args.region)

    for cfg in LAMBDAS.values():
        deploy_lambda(lam, cfg, role_arn, account_id, layer_arn)

    print("\n[OK] Despliegue completo.")
    print("Para asociar las Lambdas a Connect, correr deploy_infra.py.")
    return 0


if __name__ == "__main__":
    sys.exit(main())
