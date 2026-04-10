#!/usr/bin/env python3
"""
Setup completo de infraestructura para PoC Tatuaje Auna v2.1
Ejecutar: python scripts/setup_infra.py

Crea:
  - S3 bucket de input
  - DynamoDB table interacciones
  - DynamoDB table blacklist
  - SQS queue
  - Secrets Manager secret
  - IAM Role para Lambda (con CloudWatch put_metric_data)
  - IAM Role para Step Functions (con DynamoDB directo)
  - Lambda Parser (lee CSV, publica SQS)
  - Lambda Health Check (ping Multisede)
  - Lambda ValidarPaciente (search-patient + insurance)
  - Lambda Disponibilidad (availability)
  - Lambda CrearCita (create appointment + idempotencia)
  - Step Functions State Machine (flujo completo v2.1)
  - S3 Event Notification -> Parser
"""

import boto3
import json
import os
import sys
import zipfile
import io
import time

# -- Configuracion ------------------------------------------------------------
REGION       = "us-east-1"
ACCOUNT_ID   = ""  # Se detecta automaticamente

# Nombres de recursos
BUCKET_NAME          = ""  # Se asigna con account_id
TABLE_NAME           = "auna-tatuaje-poc-interacciones"
BLACKLIST_TABLE_NAME = "auna-tatuaje-poc-blacklist"
SQS_QUEUE_NAME       = "auna-tatuaje-poc-llamadas"
SECRET_NAME          = "auna/multisede/credentials"
ROLE_NAME            = "auna-tatuaje-poc-lambda-role"
SF_ROLE_NAME         = "auna-tatuaje-poc-stepfunctions-role"

# Lambdas v2.1
LAMBDA_PARSER_NAME       = "auna-tatuaje-poc-parser"
LAMBDA_HC_NAME           = "auna-tatuaje-poc-health-check"
LAMBDA_VALIDAR_NAME      = "auna-tatuaje-poc-validar-paciente"
LAMBDA_DISPONIBILIDAD_NAME = "auna-tatuaje-poc-disponibilidad"
LAMBDA_CREAR_CITA_NAME   = "auna-tatuaje-poc-crear-cita"
STATE_MACHINE_NAME       = "auna-tatuaje-poc-flow"

# Lambdas v2 (a eliminar si existen)
OLD_LAMBDA_ORQ_NAME  = "auna-tatuaje-poc-orquestador"
OLD_LAMBDA_ACC_NAME  = "auna-tatuaje-poc-agente-acciones"

# Credenciales Multisede UAT
MULTISEDE_USERNAME = "ext2700"
MULTISEDE_PASSWORD = "Auna2026"
MULTISEDE_BASE_URL = "https://17x9fh4a33.execute-api.us-east-1.amazonaws.com/uat"

# Connect (ya existente en sandbox)
CONNECT_INSTANCE_ID    = "4830896a-ec8c-4ee7-9499-de31587fbb36"
CONNECT_CONTACT_FLOW_ID = "42846822-1c43-4d8a-a1b6-1d730e5512f7"
CONNECT_SOURCE_PHONE   = "+18584776876"

# Tags para todos los recursos
TAGS = {
    "Project": "PoC Tatuaje",
    "Environment": "production",
    "Team": "dfx5",
    "ManagedBy": "setup_infra.py",
}
# Tags en formato lista para servicios que lo requieren
TAGS_LIST = [{"Key": k, "Value": v} for k, v in TAGS.items()]
# Step Functions uses lowercase key/value
TAGS_LIST_SF = [{"key": k, "value": v} for k, v in TAGS.items()]

# IDs de Multisede
MULTISEDE_IDS = {
    "SPECIALTY_ID":       "85",
    "FUNDER_ID":          "2",
    "PRODUCT_ID":         "105",
    "PLAN_ID":            "133",
    "BENEFIT_ID":         "289",
    "PROVISION_ID":       "5",
    "REASON_PRIVATE_ID":  "1",
    "PAYMENT_METHOD":     "3",
    "VISIT_TYPE_ID":      "PS",
}

# -- Clientes ----------------------------------------------------------------
session    = boto3.Session(region_name=REGION, profile_name="auna-sandbox")
sts        = session.client("sts")
s3         = session.client("s3")
dynamodb   = session.client("dynamodb")
secrets    = session.client("secretsmanager")
iam        = session.client("iam")
lambda_cli = session.client("lambda")
sqs_cli    = session.client("sqs")
sf_cli     = session.client("stepfunctions")


def main():
    global ACCOUNT_ID, BUCKET_NAME

    print("Iniciando setup v2.1 de infraestructura PoC Tatuaje Auna\n")

    identity = sts.get_caller_identity()
    ACCOUNT_ID = identity["Account"]
    BUCKET_NAME = f"auna-tatuaje-poc-input-{ACCOUNT_ID}"
    print(f"Cuenta AWS: {ACCOUNT_ID}")
    print(f"Region: {REGION}")

    # 0. Cleanup old v2 Lambdas
    cleanup_old_lambdas()

    # 1. S3 Bucket
    create_s3_bucket()

    # 2. DynamoDB Tables
    create_dynamodb_table(TABLE_NAME, "call_id")
    create_dynamodb_table(BLACKLIST_TABLE_NAME, "telefono")

    # 3. SQS Queue
    sqs_url = create_sqs_queue()

    # 4. Secrets Manager
    secret_arn = create_secret()

    # 5. IAM Role Lambda (con CloudWatch)
    role_arn = create_iam_role(ACCOUNT_ID)

    # 6. IAM Role Step Functions (con DynamoDB directo)
    sf_role_arn = create_step_functions_role(ACCOUNT_ID)

    print("Esperando propagacion del rol IAM (10s)...")
    time.sleep(10)

    # Env vars compartidas para Lambdas de accion
    action_env = {
        "MULTISEDE_BASE_URL":          MULTISEDE_BASE_URL,
        "SECRETS_MULTISEDE_ARN":       secret_arn,
        "DYNAMODB_TABLE_NAME":         TABLE_NAME,
        "DYNAMODB_BLACKLIST_TABLE":    BLACKLIST_TABLE_NAME,
        "CLOUDWATCH_NAMESPACE":        "AunaTatuajePoc",
        "MULTISEDE_FUNDER_ID":         MULTISEDE_IDS["FUNDER_ID"],
        "MULTISEDE_SPECIALTY_ID":      MULTISEDE_IDS["SPECIALTY_ID"],
        "MULTISEDE_PROVISION_ID":      MULTISEDE_IDS["PROVISION_ID"],
        "MULTISEDE_REASON_PRIVATE_ID": MULTISEDE_IDS["REASON_PRIVATE_ID"],
        "MULTISEDE_PAYMENT_METHOD":    MULTISEDE_IDS["PAYMENT_METHOD"],
        "MULTISEDE_VISIT_TYPE_ID":     MULTISEDE_IDS["VISIT_TYPE_ID"],
        "MULTISEDE_BENEFIT_ID":        MULTISEDE_IDS["BENEFIT_ID"],
    }

    # 7. Lambda Health Check
    lambda_hc_arn = create_lambda(
        LAMBDA_HC_NAME,
        "lambda/health_check/lambda_function.py",
        role_arn,
        timeout=30,
        memory=256,
        env_vars={
            "MULTISEDE_BASE_URL": MULTISEDE_BASE_URL,
            "SECRETS_MULTISEDE_ARN": secret_arn,
        },
        description="PoC Tatuaje v2.1 - Health Check API Multisede",
        dist_zip="health_check.zip",
    )

    # 8. Lambda Parser (reemplaza orquestador)
    lambda_parser_arn = create_lambda(
        LAMBDA_PARSER_NAME,
        "lambda/parser/lambda_function.py",
        role_arn,
        timeout=300,
        memory=512,
        env_vars={
            "SQS_QUEUE_URL":           sqs_url,
            "DYNAMODB_TABLE_NAME":     TABLE_NAME,
        },
        description="PoC Tatuaje v2.1 - Parser CSV -> SQS",
        dist_zip="parser.zip",
    )

    # 9. Lambda ValidarPaciente
    lambda_validar_arn = create_lambda(
        LAMBDA_VALIDAR_NAME,
        "lambda/validar_paciente/lambda_function.py",
        role_arn,
        timeout=30,
        memory=256,
        env_vars=action_env,
        description="PoC Tatuaje v2.1 - Validar paciente en Multisede",
        dist_zip="validar_paciente.zip",
    )

    # 10. Lambda Disponibilidad
    lambda_disp_arn = create_lambda(
        LAMBDA_DISPONIBILIDAD_NAME,
        "lambda/disponibilidad/lambda_function.py",
        role_arn,
        timeout=30,
        memory=256,
        env_vars=action_env,
        description="PoC Tatuaje v2.1 - Consultar disponibilidad Multisede",
        dist_zip="disponibilidad.zip",
    )

    # 11. Lambda CrearCita
    lambda_cita_arn = create_lambda(
        LAMBDA_CREAR_CITA_NAME,
        "lambda/crear_cita/lambda_function.py",
        role_arn,
        timeout=30,
        memory=256,
        env_vars=action_env,
        description="PoC Tatuaje v2.1 - Crear cita en Multisede con idempotencia",
        dist_zip="crear_cita.zip",
    )

    # 12. S3 trigger -> Parser
    setup_s3_trigger(lambda_parser_arn)

    # 13. Step Functions (flujo completo v2.1)
    create_step_functions(sf_role_arn, lambda_hc_arn)

    print("\n" + "="*60)
    print("SETUP v2.1 COMPLETADO")
    print("="*60)
    print(f"\nRecursos:")
    print(f"  S3:                s3://{BUCKET_NAME}")
    print(f"  DynamoDB:          {TABLE_NAME}")
    print(f"  DynamoDB BL:       {BLACKLIST_TABLE_NAME}")
    print(f"  SQS:               {sqs_url}")
    print(f"  Lambda Parser:     {LAMBDA_PARSER_NAME}")
    print(f"  Lambda HC:         {LAMBDA_HC_NAME}")
    print(f"  Lambda Validar:    {LAMBDA_VALIDAR_NAME}")
    print(f"  Lambda Disp:       {LAMBDA_DISPONIBILIDAD_NAME}")
    print(f"  Lambda Cita:       {LAMBDA_CREAR_CITA_NAME}")
    print(f"  Step Functions:    {STATE_MACHINE_NAME}")
    print(f"  Connect:           {CONNECT_INSTANCE_ID}")


def cleanup_old_lambdas():
    """Elimina Lambdas v2 que fueron reemplazadas en v2.1."""
    for old_name in [OLD_LAMBDA_ORQ_NAME, OLD_LAMBDA_ACC_NAME]:
        try:
            lambda_cli.delete_function(FunctionName=old_name)
            print(f"  Eliminada Lambda v2: {old_name}")
        except lambda_cli.exceptions.ResourceNotFoundException:
            pass
        except Exception as e:
            print(f"  No se pudo eliminar {old_name}: {e}")


def create_s3_bucket():
    print(f"\nCreando bucket S3: {BUCKET_NAME}")
    try:
        s3.create_bucket(Bucket=BUCKET_NAME)
        s3.put_public_access_block(
            Bucket=BUCKET_NAME,
            PublicAccessBlockConfiguration={
                "BlockPublicAcls": True, "IgnorePublicAcls": True,
                "BlockPublicPolicy": True, "RestrictPublicBuckets": True,
            },
        )
        s3.put_bucket_lifecycle_configuration(
            Bucket=BUCKET_NAME,
            LifecycleConfiguration={"Rules": [{
                "ID": "delete-old-csvs",
                "Filter": {"Prefix": "input/"},
                "Status": "Enabled",
                "Expiration": {"Days": 7},
            }]},
        )
        s3.put_bucket_tagging(
            Bucket=BUCKET_NAME,
            Tagging={"TagSet": TAGS_LIST},
        )
        print(f"  OK - Bucket creado con lifecycle 7 dias")
    except s3.exceptions.BucketAlreadyOwnedByYou:
        s3.put_bucket_tagging(
            Bucket=BUCKET_NAME,
            Tagging={"TagSet": TAGS_LIST},
        )
        print(f"  Ya existe (tags actualizados)")
    except Exception as e:
        print(f"  Error: {e}")


def create_dynamodb_table(table_name: str, pk_name: str):
    print(f"\nCreando tabla DynamoDB: {table_name}")
    try:
        dynamodb.create_table(
            TableName=table_name,
            AttributeDefinitions=[{"AttributeName": pk_name, "AttributeType": "S"}],
            KeySchema=[{"AttributeName": pk_name, "KeyType": "HASH"}],
            BillingMode="PAY_PER_REQUEST",
            Tags=TAGS_LIST,
        )
        print(f"  OK - Tabla creada (on-demand)")
    except dynamodb.exceptions.ResourceInUseException:
        print(f"  Ya existe")
    except Exception as e:
        print(f"  Error: {e}")


def create_sqs_queue() -> str:
    print(f"\nCreando cola SQS: {SQS_QUEUE_NAME}")
    try:
        r = sqs_cli.create_queue(
            QueueName=SQS_QUEUE_NAME,
            Attributes={
                "VisibilityTimeout": "910",
                "MessageRetentionPeriod": "86400",  # 1 dia
                "ReceiveMessageWaitTimeSeconds": "5",
            },
            tags=TAGS,
        )
        url = r["QueueUrl"]
        print(f"  OK - Cola creada: {url}")
        return url
    except Exception as e:
        if "QueueAlreadyExists" in str(e):
            r = sqs_cli.get_queue_url(QueueName=SQS_QUEUE_NAME)
            url = r["QueueUrl"]
            print(f"  Ya existe: {url}")
            return url
        print(f"  Error: {e}")
        return ""


def create_secret() -> str:
    print(f"\nCreando secret: {SECRET_NAME}")
    secret_value = json.dumps({
        "username": MULTISEDE_USERNAME,
        "password": MULTISEDE_PASSWORD,
    })
    try:
        r = secrets.create_secret(
            Name=SECRET_NAME,
            SecretString=secret_value,
            Description="Credenciales Multisede UAT",
            Tags=TAGS_LIST,
        )
        arn = r["ARN"]
        print(f"  OK - Secret creado: {arn}")
        return arn
    except secrets.exceptions.ResourceExistsException:
        r = secrets.describe_secret(SecretId=SECRET_NAME)
        arn = r["ARN"]
        print(f"  Ya existe: {arn}")
        return arn
    except Exception as e:
        print(f"  Error: {e}")
        return ""


def create_iam_role(account_id: str) -> str:
    print(f"\nCreando IAM Role: {ROLE_NAME}")

    assume_policy = json.dumps({
        "Version": "2012-10-17",
        "Statement": [{
            "Effect": "Allow",
            "Principal": {"Service": "lambda.amazonaws.com"},
            "Action": "sts:AssumeRole",
        }],
    })

    permissions_policy = json.dumps({
        "Version": "2012-10-17",
        "Statement": [
            {"Effect": "Allow",
             "Action": ["s3:GetObject", "s3:ListBucket"],
             "Resource": [
                 f"arn:aws:s3:::auna-tatuaje-poc-input-*",
                 f"arn:aws:s3:::auna-tatuaje-poc-input-*/*",
             ]},
            {"Effect": "Allow",
             "Action": ["connect:StartOutboundVoiceContact", "connect:GetContactAttributes"],
             "Resource": "*"},
            {"Effect": "Allow",
             "Action": ["bedrock:InvokeModel", "bedrock:InvokeAgent"],
             "Resource": "*"},
            {"Effect": "Allow",
             "Action": ["dynamodb:PutItem", "dynamodb:UpdateItem", "dynamodb:GetItem",
                        "dynamodb:Query", "dynamodb:Scan"],
             "Resource": [
                 f"arn:aws:dynamodb:{REGION}:{account_id}:table/{TABLE_NAME}",
                 f"arn:aws:dynamodb:{REGION}:{account_id}:table/{BLACKLIST_TABLE_NAME}",
             ]},
            {"Effect": "Allow",
             "Action": ["secretsmanager:GetSecretValue"],
             "Resource": f"arn:aws:secretsmanager:{REGION}:{account_id}:secret:auna/*"},
            {"Effect": "Allow",
             "Action": ["sqs:SendMessage", "sqs:ReceiveMessage", "sqs:DeleteMessage",
                        "sqs:GetQueueAttributes"],
             "Resource": f"arn:aws:sqs:{REGION}:{account_id}:{SQS_QUEUE_NAME}"},
            {"Effect": "Allow",
             "Action": ["cloudwatch:PutMetricData"],
             "Resource": "*"},
            {"Effect": "Allow",
             "Action": ["logs:CreateLogGroup", "logs:CreateLogStream", "logs:PutLogEvents"],
             "Resource": "arn:aws:logs:*:*:*"},
        ],
    })

    try:
        r = iam.create_role(
            RoleName=ROLE_NAME,
            AssumeRolePolicyDocument=assume_policy,
            Description="Role para Lambdas de PoC Tatuaje Auna v2.1",
            Tags=TAGS_LIST,
        )
        role_arn = r["Role"]["Arn"]
        iam.put_role_policy(
            RoleName=ROLE_NAME,
            PolicyName="auna-tatuaje-poc-policy-v21",
            PolicyDocument=permissions_policy,
        )
        print(f"  OK - Role creado: {role_arn}")
        return role_arn
    except iam.exceptions.EntityAlreadyExistsException:
        # Update policy on existing role
        iam.put_role_policy(
            RoleName=ROLE_NAME,
            PolicyName="auna-tatuaje-poc-policy-v21",
            PolicyDocument=permissions_policy,
        )
        iam.tag_role(RoleName=ROLE_NAME, Tags=TAGS_LIST)
        # Remove old v2 policy if exists
        try:
            iam.delete_role_policy(RoleName=ROLE_NAME, PolicyName="auna-tatuaje-poc-policy-v2")
        except Exception:
            pass
        r = iam.get_role(RoleName=ROLE_NAME)
        role_arn = r["Role"]["Arn"]
        print(f"  Ya existe, politica actualizada a v2.1: {role_arn}")
        return role_arn
    except Exception as e:
        print(f"  Error: {e}")
        return ""


def create_step_functions_role(account_id: str) -> str:
    print(f"\nCreando IAM Role Step Functions: {SF_ROLE_NAME}")

    assume_policy = json.dumps({
        "Version": "2012-10-17",
        "Statement": [{
            "Effect": "Allow",
            "Principal": {"Service": "states.amazonaws.com"},
            "Action": "sts:AssumeRole",
        }],
    })

    permissions_policy = json.dumps({
        "Version": "2012-10-17",
        "Statement": [
            {"Effect": "Allow",
             "Action": ["lambda:InvokeFunction"],
             "Resource": [
                 f"arn:aws:lambda:{REGION}:{account_id}:function:auna-tatuaje-poc-*",
             ]},
            {"Effect": "Allow",
             "Action": ["dynamodb:GetItem", "dynamodb:PutItem"],
             "Resource": [
                 f"arn:aws:dynamodb:{REGION}:{account_id}:table/{TABLE_NAME}",
                 f"arn:aws:dynamodb:{REGION}:{account_id}:table/{BLACKLIST_TABLE_NAME}",
             ]},
            {"Effect": "Allow",
             "Action": ["sqs:SendMessage"],
             "Resource": f"arn:aws:sqs:{REGION}:{account_id}:{SQS_QUEUE_NAME}"},
            {"Effect": "Allow",
             "Action": ["logs:CreateLogGroup", "logs:CreateLogStream", "logs:PutLogEvents"],
             "Resource": "arn:aws:logs:*:*:*"},
        ],
    })

    try:
        r = iam.create_role(
            RoleName=SF_ROLE_NAME,
            AssumeRolePolicyDocument=assume_policy,
            Description="Role para Step Functions PoC Tatuaje Auna v2.1",
            Tags=TAGS_LIST,
        )
        role_arn = r["Role"]["Arn"]
        iam.put_role_policy(
            RoleName=SF_ROLE_NAME,
            PolicyName="auna-tatuaje-poc-sf-policy-v21",
            PolicyDocument=permissions_policy,
        )
        print(f"  OK - Role creado: {role_arn}")
        return role_arn
    except iam.exceptions.EntityAlreadyExistsException:
        iam.put_role_policy(
            RoleName=SF_ROLE_NAME,
            PolicyName="auna-tatuaje-poc-sf-policy-v21",
            PolicyDocument=permissions_policy,
        )
        iam.tag_role(RoleName=SF_ROLE_NAME, Tags=TAGS_LIST)
        try:
            iam.delete_role_policy(RoleName=SF_ROLE_NAME, PolicyName="auna-tatuaje-poc-sf-policy")
        except Exception:
            pass
        r = iam.get_role(RoleName=SF_ROLE_NAME)
        role_arn = r["Role"]["Arn"]
        print(f"  Ya existe, politica actualizada a v2.1: {role_arn}")
        return role_arn
    except Exception as e:
        print(f"  Error: {e}")
        return ""


def zip_lambda(source_file: str) -> bytes:
    buffer = io.BytesIO()
    with zipfile.ZipFile(buffer, "w", zipfile.ZIP_DEFLATED) as zf:
        zf.write(source_file, "lambda_function.py")
    return buffer.getvalue()


def create_lambda(name: str, source_path: str, role_arn: str,
                   timeout: int = 60, memory: int = 512,
                   env_vars: dict = None, description: str = "",
                   dist_zip: str = None) -> str:
    print(f"\nCreando Lambda: {name}")

    base_dir = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))

    # Try pre-packaged dist ZIP first (includes dependencies)
    if dist_zip:
        dist_path = os.path.join(base_dir, "dist", dist_zip)
        if os.path.exists(dist_path):
            with open(dist_path, "rb") as f:
                zip_data = f.read()
            print(f"  Usando dist/{dist_zip} ({len(zip_data)/(1024*1024):.1f} MB)")
        else:
            print(f"  WARN: dist/{dist_zip} no encontrado, empaquetando solo lambda_function.py")
            source = os.path.join(base_dir, source_path)
            zip_data = zip_lambda(source)
    else:
        source = os.path.join(base_dir, source_path)
        if not os.path.exists(source):
            source = source_path
        if not os.path.exists(source):
            print(f"  Error: no encontrado {source}")
            return ""
        zip_data = zip_lambda(source)

    try:
        r = lambda_cli.create_function(
            FunctionName=name,
            Runtime="python3.12",
            Role=role_arn,
            Handler="lambda_function.lambda_handler",
            Code={"ZipFile": zip_data},
            Timeout=timeout,
            MemorySize=memory,
            Environment={"Variables": env_vars or {}},
            Description=description,
            Tags=TAGS,
        )
        arn = r["FunctionArn"]
        print(f"  OK - Lambda creada: {arn}")
        return arn
    except lambda_cli.exceptions.ResourceConflictException:
        # Update code and config
        lambda_cli.update_function_code(
            FunctionName=name,
            ZipFile=zip_data,
        )
        # Wait for code update to finish
        time.sleep(5)
        lambda_cli.update_function_configuration(
            FunctionName=name,
            Timeout=timeout,
            MemorySize=memory,
            Environment={"Variables": env_vars or {}},
            Description=description,
        )
        r = lambda_cli.get_function(FunctionName=name)
        arn = r["Configuration"]["FunctionArn"]
        lambda_cli.tag_resource(Resource=arn, Tags=TAGS)
        print(f"  Actualizada: {arn}")
        return arn
    except Exception as e:
        print(f"  Error: {e}")
        return ""


def setup_s3_trigger(lambda_arn: str):
    print(f"\nConfigurando S3 trigger -> Parser")
    if not lambda_arn:
        print("  Saltando (no ARN)")
        return
    try:
        try:
            lambda_cli.add_permission(
                FunctionName=LAMBDA_PARSER_NAME,
                StatementId="s3-invoke-permission",
                Action="lambda:InvokeFunction",
                Principal="s3.amazonaws.com",
                SourceArn=f"arn:aws:s3:::{BUCKET_NAME}",
            )
        except lambda_cli.exceptions.ResourceConflictException:
            pass

        s3.put_bucket_notification_configuration(
            Bucket=BUCKET_NAME,
            NotificationConfiguration={
                "LambdaFunctionConfigurations": [{
                    "LambdaFunctionArn": lambda_arn,
                    "Events": ["s3:ObjectCreated:*"],
                    "Filter": {"Key": {"FilterRules": [
                        {"Name": "prefix", "Value": "input/"},
                        {"Name": "suffix", "Value": ".csv"},
                    ]}},
                }],
            },
        )
        print(f"  OK - S3 -> {LAMBDA_PARSER_NAME}")
    except Exception as e:
        print(f"  Error: {e}")


def create_step_functions(sf_role_arn: str, hc_arn: str):
    print(f"\nCreando Step Functions: {STATE_MACHINE_NAME}")
    if not sf_role_arn:
        print("  Saltando (no role ARN)")
        return

    # Load ASL from file and substitute Health Check ARN
    base_dir = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
    asl_path = os.path.join(base_dir, "stepfunctions", "state_machine.json")

    if os.path.exists(asl_path):
        with open(asl_path, "r", encoding="utf-8") as f:
            definition = f.read()
        definition = definition.replace("${HealthCheckLambdaArn}", hc_arn or "")
        print(f"  ASL cargado desde {asl_path}")
    else:
        print(f"  WARN: {asl_path} no encontrado, usando definicion inline")
        definition = json.dumps({
            "Comment": "PoC Tatuaje Auna v2.1",
            "StartAt": "ValidarHorario",
            "States": {
                "ValidarHorario": {
                    "Type": "Choice",
                    "Choices": [{"And": [{"Variable": "$.force_run", "BooleanEquals": True}], "Next": "ConsultarBlacklist"}],
                    "Default": "EsperarHorario",
                },
                "EsperarHorario": {"Type": "Wait", "Seconds": 300, "Next": "ConsultarBlacklist"},
                "ConsultarBlacklist": {
                    "Type": "Task",
                    "Resource": "arn:aws:states:::dynamodb:getItem",
                    "Parameters": {"TableName": BLACKLIST_TABLE_NAME, "Key": {"telefono": {"S.$": "$.telefono"}}},
                    "ResultPath": "$.blacklist_result",
                    "Next": "EvaluarBlacklist",
                    "Catch": [{"ErrorEquals": ["States.ALL"], "ResultPath": "$.blacklist_error", "Next": "HealthCheck"}],
                },
                "EvaluarBlacklist": {
                    "Type": "Choice",
                    "Choices": [{"And": [
                        {"Variable": "$.blacklist_result.Item.activo.BOOL", "BooleanEquals": True},
                        {"Variable": "$.blacklist_result.Item.intentos_fallidos.N", "StringGreaterThanEquals": "3"},
                    ], "Next": "EnBlacklist"}],
                    "Default": "HealthCheck",
                },
                "EnBlacklist": {"Type": "Succeed", "Comment": "Numero en blacklist"},
                "HealthCheck": {
                    "Type": "Task",
                    "Resource": hc_arn or "PLACEHOLDER",
                    "ResultPath": "$.health",
                    "Next": "EvaluarHealthCheck",
                    "Retry": [{"ErrorEquals": ["States.TaskFailed"], "IntervalSeconds": 30, "MaxAttempts": 2, "BackoffRate": 2}],
                },
                "EvaluarHealthCheck": {
                    "Type": "Choice",
                    "Choices": [{"Variable": "$.health.api_available", "BooleanEquals": True, "Next": "RegistrarInicio"}],
                    "Default": "EsperarAPICaida",
                },
                "EsperarAPICaida": {"Type": "Wait", "Seconds": 300, "Next": "HealthCheck"},
                "RegistrarInicio": {
                    "Type": "Task",
                    "Resource": "arn:aws:states:::dynamodb:putItem",
                    "Parameters": {
                        "TableName": TABLE_NAME,
                        "Item": {
                            "call_id": {"S.$": "$.call_id"},
                            "afiliado_dni": {"S.$": "$.dni"},
                            "afiliado_nombre": {"S.$": "$.nombre_completo"},
                            "telefono": {"S.$": "$.telefono"},
                            "sede_referencia": {"S.$": "$.sede_referencia"},
                            "programa": {"S.$": "$.programa"},
                            "timestamp_inicio": {"S.$": "$$.State.EnteredTime"},
                            "resultado": {"S": "iniciando"},
                        },
                    },
                    "ResultPath": "$.dynamo_result",
                    "Next": "IniciarLlamada",
                },
                "IniciarLlamada": {"Type": "Succeed"},
            },
        })

    try:
        r = sf_cli.create_state_machine(
            name=STATE_MACHINE_NAME,
            definition=definition,
            roleArn=sf_role_arn,
            type="STANDARD",
            tags=TAGS_LIST_SF,
        )
        print(f"  OK - State Machine: {r['stateMachineArn']}")
    except Exception as e:
        if "StateMachineAlreadyExists" in str(e):
            machines = sf_cli.list_state_machines()
            for m in machines["stateMachines"]:
                if m["name"] == STATE_MACHINE_NAME:
                    sf_cli.update_state_machine(
                        stateMachineArn=m["stateMachineArn"],
                        definition=definition,
                        roleArn=sf_role_arn,
                    )
                    sf_cli.tag_resource(resourceArn=m["stateMachineArn"], tags=TAGS_LIST_SF)
                    print(f"  Actualizada: {m['stateMachineArn']}")
                    return
        print(f"  Error: {e}")


if __name__ == "__main__":
    main()
