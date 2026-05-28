"""
Despliega la infra base del PoC Tatuaje Auna en una cuenta AWS.

Crea (idempotente — si ya existe, no falla):
  - IAM role para Lambdas y para Step Functions
  - DynamoDB: auna-tatuaje-poc-interacciones, auna-tatuaje-poc-blacklist
  - SQS: auna-tatuaje-poc-llamadas
  - S3 bucket: auna-tatuaje-poc-input-<accountId>
  - Secrets Manager: auna/multisede/credentials (vacío, hay que ponerle credenciales reales)
  - Step Functions: auna-tatuaje-poc-flow (desde stepfunctions/state_machine.json)
  - EventBridge Pipe: auna-tatuaje-poc-sqs-to-sfn

Uso:
    python scripts/deploy_infra.py --profile <perfil-aws>

Después de esto, hay que:
  1. Setear la secret en Secrets Manager con las credenciales reales de Multisede:
       aws secretsmanager put-secret-value \\
         --secret-id auna/multisede/credentials \\
         --secret-string '{"username":"...","password":"..."}'
  2. Empaquetar Lambdas: python scripts/package_lambdas.py
  3. Desplegar Lambdas: python scripts/deploy_lambdas.py --profile <perfil>
  4. Conectar S3 -> Lambda Parser trigger (manual desde consola o
     con aws s3api put-bucket-notification-configuration)
  5. Crear Connect instance + flows (instrucciones en README.md).
"""

import argparse
import json
import sys
import time
from pathlib import Path

import boto3
from botocore.exceptions import ClientError

ROOT = Path(__file__).resolve().parent.parent

# Tags estándar — TODOS los recursos del PoC deben llevarlos.
# - project / env: convención DFX5 para trazabilidad interna.
# - aws-apn-id: tag oficial de AWS Partner Network (Partner Revenue
#   Measurement). Valor pc:55xvhbzjwkkzw9hupxc9n3m2l = categoría CX
#   (Contact Center). NO MODIFICAR NI ELIMINAR — AWS lo usa para
#   reportar spending del partner.
TAGS_DICT = {
    "project": "auna-tatuaje-poc",
    "env": "poc",
    "aws-apn-id": "pc:55xvhbzjwkkzw9hupxc9n3m2l",
}
TAGS_KV = [{"Key": k, "Value": v} for k, v in TAGS_DICT.items()]

LAMBDA_ROLE_NAME = "auna-tatuaje-poc-lambda-role"
SFN_ROLE_NAME = "auna-tatuaje-poc-stepfunctions-role"
PIPE_ROLE_NAME = "auna-tatuaje-poc-pipe-role"
INTERACCIONES_TBL = "auna-tatuaje-poc-interacciones"
BLACKLIST_TBL = "auna-tatuaje-poc-blacklist"
SQS_NAME = "auna-tatuaje-poc-llamadas"
SECRET_NAME = "auna/multisede/credentials"
SFN_NAME = "auna-tatuaje-poc-flow"
PIPE_NAME = "auna-tatuaje-poc-sqs-to-sfn"


def ensure_role(iam, name: str, trust: dict, inline_policies: dict):
    try:
        iam.get_role(RoleName=name)
        print(f"  Role {name} ya existe")
    except ClientError as e:
        if e.response["Error"]["Code"] != "NoSuchEntity":
            raise
        print(f"  Creando role {name}...")
        iam.create_role(
            RoleName=name,
            AssumeRolePolicyDocument=json.dumps(trust),
            Tags=TAGS_KV,
        )
    for pol_name, pol_doc in inline_policies.items():
        iam.put_role_policy(
            RoleName=name,
            PolicyName=pol_name,
            PolicyDocument=json.dumps(pol_doc),
        )
        print(f"    Inline policy {pol_name} aplicada")
    return iam.get_role(RoleName=name)["Role"]["Arn"]


def ensure_dynamodb(ddb, table_name: str, pk: str):
    try:
        ddb.describe_table(TableName=table_name)
        print(f"  Tabla {table_name} ya existe")
        return
    except ClientError as e:
        if e.response["Error"]["Code"] != "ResourceNotFoundException":
            raise
    print(f"  Creando tabla {table_name}...")
    ddb.create_table(
        TableName=table_name,
        KeySchema=[{"AttributeName": pk, "KeyType": "HASH"}],
        AttributeDefinitions=[{"AttributeName": pk, "AttributeType": "S"}],
        BillingMode="PAY_PER_REQUEST",
        Tags=TAGS_KV,
    )
    ddb.get_waiter("table_exists").wait(TableName=table_name)


def ensure_sqs(sqs, account_id: str, region: str) -> str:
    try:
        url = sqs.get_queue_url(QueueName=SQS_NAME)["QueueUrl"]
        print(f"  SQS {SQS_NAME} ya existe")
        return url
    except ClientError as e:
        if "NonExistentQueue" not in str(e):
            raise
    print(f"  Creando SQS {SQS_NAME}...")
    sqs.create_queue(
        QueueName=SQS_NAME,
        Attributes={"VisibilityTimeout": "180", "MessageRetentionPeriod": "86400"},
        tags=TAGS_DICT,
    )
    return sqs.get_queue_url(QueueName=SQS_NAME)["QueueUrl"]


def ensure_s3(s3, account_id: str):
    bucket = f"auna-tatuaje-poc-input-{account_id}"
    try:
        s3.head_bucket(Bucket=bucket)
        print(f"  Bucket {bucket} ya existe")
        return bucket
    except ClientError as e:
        if e.response["Error"]["Code"] not in ("404", "NoSuchBucket"):
            raise
    print(f"  Creando bucket {bucket}...")
    s3.create_bucket(Bucket=bucket)
    s3.put_public_access_block(
        Bucket=bucket,
        PublicAccessBlockConfiguration={
            "BlockPublicAcls": True, "IgnorePublicAcls": True,
            "BlockPublicPolicy": True, "RestrictPublicBuckets": True,
        },
    )
    s3.put_bucket_tagging(Bucket=bucket, Tagging={"TagSet": TAGS_KV})
    return bucket


def ensure_secret(sm) -> str:
    try:
        r = sm.describe_secret(SecretId=SECRET_NAME)
        print(f"  Secret {SECRET_NAME} ya existe")
        return r["ARN"]
    except ClientError as e:
        if e.response["Error"]["Code"] != "ResourceNotFoundException":
            raise
    print(f"  Creando secret {SECRET_NAME} (con placeholder, hay que poner valor real después)...")
    r = sm.create_secret(
        Name=SECRET_NAME,
        Description="Credenciales API Multisede UAT - PoC Tatuaje",
        SecretString=json.dumps({"username": "REPLACE_ME", "password": "REPLACE_ME"}),
        Tags=TAGS_KV,
    )
    print(f"    Recordar: aws secretsmanager put-secret-value --secret-id {SECRET_NAME} --secret-string ...")
    return r["ARN"]


def ensure_sfn(sfn, name: str, role_arn: str, region: str, account_id: str) -> str:
    definition_file = ROOT / "stepfunctions" / "state_machine.json"
    definition = definition_file.read_text(encoding="utf-8")
    # Reemplazar placeholders del JSON con valores reales del account
    definition = definition.replace("PLACEHOLDER_ACCOUNT_ID", account_id)
    arn = f"arn:aws:states:{region}:{account_id}:stateMachine:{name}"
    try:
        sfn.describe_state_machine(stateMachineArn=arn)
        print(f"  Step Functions {name} ya existe — actualizando definición")
        sfn.update_state_machine(stateMachineArn=arn, definition=definition, roleArn=role_arn)
        return arn
    except ClientError as e:
        if "DoesNotExist" not in str(e):
            raise
    print(f"  Creando Step Functions {name}...")
    r = sfn.create_state_machine(
        name=name,
        definition=definition,
        roleArn=role_arn,
        type="STANDARD",
        tags=TAGS_KV,
    )
    return r["stateMachineArn"]


def ensure_pipe(pipes, sfn_arn: str, sqs_arn: str, role_arn: str):
    try:
        pipes.describe_pipe(Name=PIPE_NAME)
        print(f"  Pipe {PIPE_NAME} ya existe")
        return
    except ClientError as e:
        if "NotFound" not in str(e):
            raise
    print(f"  Creando Pipe {PIPE_NAME}...")
    pipes.create_pipe(
        Name=PIPE_NAME,
        Source=sqs_arn,
        Target=sfn_arn,
        RoleArn=role_arn,
        SourceParameters={"SqsQueueParameters": {"BatchSize": 1}},
        TargetParameters={
            "StepFunctionStateMachineParameters": {"InvocationType": "FIRE_AND_FORGET"}
        },
        Tags=TAGS_DICT,
    )


def main() -> int:
    p = argparse.ArgumentParser(description="Deploy infra base PoC Tatuaje Auna.")
    p.add_argument("--profile", required=True)
    p.add_argument("--region", default="us-east-1")
    args = p.parse_args()

    sess = boto3.Session(profile_name=args.profile, region_name=args.region)
    sts = sess.client("sts")
    iam = sess.client("iam")
    ddb = sess.client("dynamodb")
    sqs = sess.client("sqs")
    s3 = sess.client("s3")
    sm = sess.client("secretsmanager")
    sfn = sess.client("stepfunctions")
    pipes = sess.client("pipes")

    account_id = sts.get_caller_identity()["Account"]
    print(f"Account: {account_id}  Region: {args.region}")

    print("\n[1/7] DynamoDB tables...")
    ensure_dynamodb(ddb, INTERACCIONES_TBL, "call_id")
    ensure_dynamodb(ddb, BLACKLIST_TBL, "telefono")

    print("\n[2/7] SQS queue...")
    sqs_url = ensure_sqs(sqs, account_id, args.region)
    sqs_arn = f"arn:aws:sqs:{args.region}:{account_id}:{SQS_NAME}"
    print(f"  SQS ARN: {sqs_arn}")

    print("\n[3/7] S3 bucket...")
    bucket = ensure_s3(s3, account_id)
    print(f"  S3: s3://{bucket}")

    print("\n[4/7] Secret Multisede...")
    secret_arn = ensure_secret(sm)
    print(f"  Secret ARN: {secret_arn}")

    print("\n[5/7] IAM roles...")
    lambda_role = ensure_role(
        iam, LAMBDA_ROLE_NAME,
        trust={"Version": "2012-10-17", "Statement": [{"Effect": "Allow",
                "Principal": {"Service": "lambda.amazonaws.com"}, "Action": "sts:AssumeRole"}]},
        inline_policies={"auna-poc-lambda-policy": {"Version": "2012-10-17", "Statement": [
            {"Effect": "Allow", "Action": "logs:*", "Resource": "*"},
            {"Effect": "Allow", "Action": ["dynamodb:*"], "Resource": f"arn:aws:dynamodb:{args.region}:{account_id}:table/auna-tatuaje-poc-*"},
            {"Effect": "Allow", "Action": "sqs:*", "Resource": sqs_arn},
            {"Effect": "Allow", "Action": "s3:*", "Resource": [f"arn:aws:s3:::{bucket}", f"arn:aws:s3:::{bucket}/*"]},
            {"Effect": "Allow", "Action": "secretsmanager:GetSecretValue", "Resource": secret_arn},
            {"Effect": "Allow", "Action": "cloudwatch:PutMetricData", "Resource": "*"},
        ]}},
    )

    sfn_role = ensure_role(
        iam, SFN_ROLE_NAME,
        trust={"Version": "2012-10-17", "Statement": [{"Effect": "Allow",
                "Principal": {"Service": "states.amazonaws.com"}, "Action": "sts:AssumeRole"}]},
        inline_policies={"auna-poc-sfn-policy": {"Version": "2012-10-17", "Statement": [
            {"Effect": "Allow", "Action": "lambda:InvokeFunction", "Resource": f"arn:aws:lambda:{args.region}:{account_id}:function:auna-tatuaje-poc-*"},
            {"Effect": "Allow", "Action": ["dynamodb:PutItem", "dynamodb:UpdateItem", "dynamodb:GetItem"],
             "Resource": f"arn:aws:dynamodb:{args.region}:{account_id}:table/auna-tatuaje-poc-*"},
            {"Effect": "Allow", "Action": "connect:StartOutboundVoiceContact", "Resource": "*"},
            {"Effect": "Allow", "Action": "logs:*", "Resource": "*"},
        ]}},
    )

    pipe_role = ensure_role(
        iam, PIPE_ROLE_NAME,
        trust={"Version": "2012-10-17", "Statement": [{"Effect": "Allow",
                "Principal": {"Service": "pipes.amazonaws.com"}, "Action": "sts:AssumeRole"}]},
        inline_policies={"auna-poc-pipe-policy": {"Version": "2012-10-17", "Statement": [
            {"Effect": "Allow",
             "Action": ["sqs:ReceiveMessage", "sqs:DeleteMessage", "sqs:GetQueueAttributes"],
             "Resource": sqs_arn},
            {"Effect": "Allow", "Action": "states:StartExecution",
             "Resource": f"arn:aws:states:{args.region}:{account_id}:stateMachine:{SFN_NAME}"},
        ]}},
    )

    print("\n[6/7] Step Functions...")
    # Esperar 10s a que IAM propague el rol
    print("  Esperando propagación de IAM (10s)...")
    time.sleep(10)
    sfn_arn = ensure_sfn(sfn, SFN_NAME, sfn_role, args.region, account_id)
    print(f"  SFN ARN: {sfn_arn}")

    print("\n[7/7] EventBridge Pipe SQS -> Step Functions...")
    ensure_pipe(pipes, sfn_arn, sqs_arn, pipe_role)

    print("\n[OK] Infra base lista. Siguientes pasos:")
    print(f"  1. Poner credenciales reales del secret {SECRET_NAME}:")
    print(f"     aws secretsmanager put-secret-value --secret-id {SECRET_NAME} \\")
    print(f"       --secret-string '{{\"username\":\"...\",\"password\":\"...\"}}' \\")
    print(f"       --profile {args.profile} --region {args.region}")
    print(f"  2. python scripts/package_lambdas.py")
    print(f"  3. python scripts/deploy_lambdas.py --profile {args.profile}")
    print(f"  4. Configurar trigger S3 -> Lambda Parser (ver README)")
    print(f"  5. Crear Connect instance + bot Lex + Q in Connect + flows (ver README)")
    return 0


if __name__ == "__main__":
    sys.exit(main())
