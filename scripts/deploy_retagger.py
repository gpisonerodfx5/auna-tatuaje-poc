"""
Despliega el auditor de tagging (scripts/retag_resources.py) como Lambda
con schedule semanal de EventBridge + notificaciones SNS.

Crea:
  - IAM role para la Lambda (con permisos de tagging y SNS publish)
  - SNS topic auna-tatuaje-poc-tagging-alerts (con subscripción opcional)
  - Lambda auna-tatuaje-poc-retagger (handler retag_handler)
  - EventBridge Schedule semanal (cada lunes 9:00 AM Perú = 14:00 UTC)

Uso:
    python scripts/deploy_retagger.py --profile <perfil>

    # Con notificación a un email:
    python scripts/deploy_retagger.py --profile <perfil> --notify-email tu@email.com

Idempotente: si ya existe, actualiza.
"""

import argparse
import json
import sys
import time
import zipfile
from pathlib import Path

import boto3
from botocore.exceptions import ClientError

ROOT = Path(__file__).resolve().parent.parent

# Tags estándar — mismo set que los demás scripts
TAGS = {
    "project": "auna-tatuaje-poc",
    "env": "poc",
    "aws-apn-id": "pc:55xvhbzjwkkzw9hupxc9n3m2l",
}
TAGS_KV = [{"Key": k, "Value": v} for k, v in TAGS.items()]

LAMBDA_NAME = "auna-tatuaje-poc-retagger"
ROLE_NAME = "auna-tatuaje-poc-retagger-role"
SNS_TOPIC_NAME = "auna-tatuaje-poc-tagging-alerts"
SCHEDULE_RULE_NAME = "auna-tatuaje-poc-retagger-weekly"


def ensure_sns_topic(sns, notify_email: str | None) -> str:
    r = sns.create_topic(Name=SNS_TOPIC_NAME, Tags=TAGS_KV)
    topic_arn = r["TopicArn"]
    print(f"  SNS topic: {topic_arn}")
    if notify_email:
        existing = sns.list_subscriptions_by_topic(TopicArn=topic_arn).get("Subscriptions", [])
        if any(s.get("Endpoint") == notify_email for s in existing):
            print(f"  Email {notify_email} ya suscripto")
        else:
            sns.subscribe(TopicArn=topic_arn, Protocol="email", Endpoint=notify_email)
            print(f"  Suscripción enviada a {notify_email} (revisar inbox y confirmar)")
    return topic_arn


def ensure_role(iam, sns_topic_arn: str) -> str:
    trust = {
        "Version": "2012-10-17",
        "Statement": [{"Effect": "Allow",
                       "Principal": {"Service": "lambda.amazonaws.com"},
                       "Action": "sts:AssumeRole"}],
    }
    policy = {
        "Version": "2012-10-17",
        "Statement": [
            {"Effect": "Allow", "Action": "logs:*", "Resource": "*"},
            # Tagging API
            {"Effect": "Allow",
             "Action": ["tag:GetResources", "tag:TagResources", "tag:GetTagKeys", "tag:GetTagValues"],
             "Resource": "*"},
            # Cada servicio valida también su propio permiso de tagging
            {"Effect": "Allow",
             "Action": [
                 "lambda:TagResource", "lambda:ListTags",
                 "dynamodb:TagResource", "dynamodb:ListTagsOfResource",
                 "sqs:TagQueue", "sqs:ListQueueTags",
                 "s3:PutBucketTagging", "s3:GetBucketTagging",
                 "states:TagResource", "states:ListTagsForResource",
                 "secretsmanager:TagResource",
                 "events:TagResource",
                 "pipes:TagResource",
                 "connect:TagResource", "connect:UntagResource",
                 "lex:TagResource", "lexv2-models:TagResource",
                 "wisdom:TagResource", "qconnect:TagResource",
                 "bedrock:TagResource",
             ],
             "Resource": "*"},
            {"Effect": "Allow", "Action": "sns:Publish", "Resource": sns_topic_arn},
        ],
    }
    try:
        iam.get_role(RoleName=ROLE_NAME)
        print(f"  Role {ROLE_NAME} ya existe")
    except ClientError as e:
        if e.response["Error"]["Code"] != "NoSuchEntity":
            raise
        iam.create_role(
            RoleName=ROLE_NAME,
            AssumeRolePolicyDocument=json.dumps(trust),
            Description="Role del auditor de tagging del PoC Tatuaje",
            Tags=TAGS_KV,
        )
        print(f"  Role {ROLE_NAME} creado")
    iam.put_role_policy(
        RoleName=ROLE_NAME,
        PolicyName="retagger-inline",
        PolicyDocument=json.dumps(policy),
    )
    return iam.get_role(RoleName=ROLE_NAME)["Role"]["Arn"]


def package_lambda() -> bytes:
    """Empaqueta retag_resources.py como zip en memoria."""
    src = ROOT / "scripts" / "retag_resources.py"
    out = ROOT / "dist" / "retagger.zip"
    out.parent.mkdir(exist_ok=True)
    with zipfile.ZipFile(out, "w", zipfile.ZIP_DEFLATED) as z:
        z.write(src, "retag_resources.py")
    return out.read_bytes()


def ensure_lambda(lam, role_arn: str, sns_topic_arn: str, region: str) -> str:
    code_zip = package_lambda()
    env = {"Variables": {"AWS_REGION_TARGET": region, "SNS_NOTIFY_TOPIC_ARN": sns_topic_arn}}
    try:
        lam.get_function(FunctionName=LAMBDA_NAME)
        print(f"  Lambda {LAMBDA_NAME} ya existe — actualizando código")
        lam.update_function_code(FunctionName=LAMBDA_NAME, ZipFile=code_zip)
        lam.get_waiter("function_updated").wait(FunctionName=LAMBDA_NAME)
        lam.update_function_configuration(
            FunctionName=LAMBDA_NAME, Role=role_arn,
            Handler="retag_resources.retag_handler",
            Timeout=120, MemorySize=256,
            Environment=env,
        )
    except ClientError as e:
        if e.response["Error"]["Code"] != "ResourceNotFoundException":
            raise
        print(f"  Esperando 10s a que IAM propague el rol...")
        time.sleep(10)
        lam.create_function(
            FunctionName=LAMBDA_NAME,
            Runtime="python3.12",
            Role=role_arn,
            Handler="retag_resources.retag_handler",
            Code={"ZipFile": code_zip},
            Timeout=120, MemorySize=256,
            Environment=env,
            Architectures=["x86_64"],
            Tags=TAGS,
        )
        lam.get_waiter("function_active").wait(FunctionName=LAMBDA_NAME)
        print(f"  Lambda {LAMBDA_NAME} creada")
    return lam.get_function(FunctionName=LAMBDA_NAME)["Configuration"]["FunctionArn"]


def ensure_schedule(events, lambda_arn: str, account_id: str, region: str):
    """EventBridge rule semanal (lunes 14:00 UTC = 9:00 AM Perú)."""
    rule_arn = events.put_rule(
        Name=SCHEDULE_RULE_NAME,
        ScheduleExpression="cron(0 14 ? * MON *)",
        State="ENABLED",
        Description="Audita semanalmente que todos los recursos del PoC tengan aws-apn-id",
        Tags=TAGS_KV,
    )["RuleArn"]
    print(f"  Schedule rule: {rule_arn}")

    events.put_targets(
        Rule=SCHEDULE_RULE_NAME,
        Targets=[{"Id": "retagger-lambda", "Arn": lambda_arn}],
    )

    # Permitir que EventBridge invoque la Lambda
    lam = boto3.Session(region_name=region).client("lambda")
    try:
        lam.add_permission(
            FunctionName=LAMBDA_NAME,
            StatementId="eventbridge-weekly-invoke",
            Action="lambda:InvokeFunction",
            Principal="events.amazonaws.com",
            SourceArn=rule_arn,
        )
        print(f"  Permission de EventBridge agregado")
    except ClientError as e:
        if e.response["Error"]["Code"] == "ResourceConflictException":
            print(f"  Permission de EventBridge ya existía")
        else:
            raise


def main() -> int:
    p = argparse.ArgumentParser(description="Deploy del Lambda retagger semanal.")
    p.add_argument("--profile", required=True)
    p.add_argument("--region", default="us-east-1")
    p.add_argument("--notify-email", default=None,
                   help="Email opcional para suscribir al SNS topic de alertas")
    args = p.parse_args()

    sess = boto3.Session(profile_name=args.profile, region_name=args.region)
    sts = sess.client("sts")
    account_id = sts.get_caller_identity()["Account"]
    print(f"Account: {account_id}  Region: {args.region}")

    print("\n[1/4] SNS topic...")
    sns_topic_arn = ensure_sns_topic(sess.client("sns"), args.notify_email)

    print("\n[2/4] IAM role...")
    role_arn = ensure_role(sess.client("iam"), sns_topic_arn)

    print("\n[3/4] Lambda...")
    lambda_arn = ensure_lambda(sess.client("lambda"), role_arn, sns_topic_arn, args.region)

    print("\n[4/4] EventBridge Schedule (cron lunes 14:00 UTC = 9:00 AM Perú)...")
    ensure_schedule(sess.client("events"), lambda_arn, account_id, args.region)

    print("\n[OK] Retagger desplegado.")
    print(f"     Test manual: aws lambda invoke --function-name {LAMBDA_NAME} \\")
    print(f"       --profile {args.profile} --region {args.region} /tmp/out.json")
    return 0


if __name__ == "__main__":
    sys.exit(main())
