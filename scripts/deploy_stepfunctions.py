"""
Create Step Functions state machine — PoC Tatuaje Auna v2.1
Orquesta: horario → blacklist → health check → StartOutboundVoiceContact
Run after Connect instance is created; update CONNECT_INSTANCE_ID below.
"""
import boto3, json

session = boto3.Session(profile_name="auna-prod", region_name="us-east-1")
sfn = session.client("stepfunctions")
ACCOUNT = "369037400928"
REGION = "us-east-1"
SFN_ROLE_ARN = f"arn:aws:iam::{ACCOUNT}:role/auna-tatuaje-poc-sfn-role"
SM_NAME = "auna-tatuaje-poc-state-machine"
TAGS = [{"key": "project", "value": "auna-tatuaje-poc"}, {"key": "env", "value": "poc"}]

# Fill these once Connect instance is created
CONNECT_INSTANCE_ID = "PENDING_CONNECT_INSTANCE_ID"
CONNECT_CONTACT_FLOW_ID = "PENDING_CONTACT_FLOW_ID"
CONNECT_SOURCE_PHONE = "+573150020389"

HEALTH_CHECK_ARN = f"arn:aws:lambda:{REGION}:{ACCOUNT}:function:auna-tatuaje-poc-health-check"
BLACKLIST_TABLE = "auna-tatuaje-poc-blacklist"
INTERACTIONS_TABLE = "auna-tatuaje-poc-interacciones"

# ASL — Amazon States Language definition
ASL = {
    "Comment": "PoC Tatuaje Auna v2.1 — Outbound call orchestrator",
    "StartAt": "CheckWorkingHours",
    "States": {
        # State 0: Validate working hours (L-V 9-19, S 9-13 UTC-5 = 14-00 / 14-18 UTC)
        "CheckWorkingHours": {
            "Type": "Task",
            "Resource": "arn:aws:states:::lambda:invoke",
            "Parameters": {
                "FunctionName": HEALTH_CHECK_ARN,
                "Payload": {
                    "action": "check_hours",
                    "call_id.$": "$.call_id"
                }
            },
            "ResultPath": "$.hours_check",
            "Next": "IsWorkingHours",
            "Catch": [{"ErrorEquals": ["States.ALL"], "Next": "RecordFueraHorario", "ResultPath": "$.error"}]
        },
        "IsWorkingHours": {
            "Type": "Choice",
            "Choices": [
                {
                    "Variable": "$.hours_check.Payload.api_available",
                    "BooleanEquals": True,
                    "Next": "CheckBlacklist"
                }
            ],
            "Default": "WaitForWorkingHours"
        },
        "WaitForWorkingHours": {
            "Type": "Wait",
            "Seconds": 1800,
            "Next": "CheckWorkingHours"
        },
        # State 1: Check blacklist in DynamoDB
        "CheckBlacklist": {
            "Type": "Task",
            "Resource": "arn:aws:states:::dynamodb:getItem",
            "Parameters": {
                "TableName": BLACKLIST_TABLE,
                "Key": {
                    "telefono": {"S.$": "$.telefono"}
                }
            },
            "ResultPath": "$.blacklist_result",
            "Next": "IsBlacklisted",
            "Catch": [{"ErrorEquals": ["States.ALL"], "Next": "HealthCheck", "ResultPath": "$.error"}]
        },
        "IsBlacklisted": {
            "Type": "Choice",
            "Choices": [
                {
                    "And": [
                        {"Variable": "$.blacklist_result.Item", "IsPresent": True},
                        {"Variable": "$.blacklist_result.Item.activo.BOOL", "BooleanEquals": True}
                    ],
                    "Next": "RecordBlacklisted"
                }
            ],
            "Default": "HealthCheck"
        },
        # State 2: Health check
        "HealthCheck": {
            "Type": "Task",
            "Resource": "arn:aws:states:::lambda:invoke",
            "Parameters": {
                "FunctionName": HEALTH_CHECK_ARN,
                "Payload.$": "$"
            },
            "ResultPath": "$.hc_result",
            "Next": "RecordLlamadaIniciada",
            "Catch": [{"ErrorEquals": ["States.ALL"], "Next": "RecordApiCaida", "ResultPath": "$.error"}]
        },
        # Record call initiation
        "RecordLlamadaIniciada": {
            "Type": "Task",
            "Resource": "arn:aws:states:::dynamodb:putItem",
            "Parameters": {
                "TableName": INTERACTIONS_TABLE,
                "Item": {
                    "call_id": {"S.$": "$.call_id"},
                    "afiliado_dni": {"S.$": "$.dni"},
                    "afiliado_nombre": {"S.$": "$.nombre_completo"},
                    "telefono": {"S.$": "$.telefono"},
                    "sede_referencia": {"S.$": "$.sede_referencia"},
                    "programa": {"S.$": "$.programa"},
                    "cuotas_pagadas": {"S.$": "$.cuotas_pagadas"},
                    "grupo_cuota": {"S.$": "$.grupo_cuota"},
                    "cod_campana": {"S.$": "$.cod_campana"},
                    "resultado": {"S": "iniciando"},
                    "modelo_usado": {"S": "nova-pro"}
                }
            },
            "ResultPath": None,
            "Next": "StartOutboundCall",
            "Catch": [{"ErrorEquals": ["States.ALL"], "Next": "StartOutboundCall", "ResultPath": "$.error"}]
        },
        # State 3: Start outbound call
        "StartOutboundCall": {
            "Type": "Task",
            "Resource": "arn:aws:states:::aws-sdk:connect:startOutboundVoiceContact",
            "Parameters": {
                "InstanceId": CONNECT_INSTANCE_ID,
                "ContactFlowId": CONNECT_CONTACT_FLOW_ID,
                "DestinationPhoneNumber.$": "$.telefono",
                "SourcePhoneNumber": CONNECT_SOURCE_PHONE,
                "Attributes": {
                    "call_id.$": "$.call_id",
                    "dni.$": "$.dni",
                    "center_id.$": "$.sede_referencia",
                    "cod_campana.$": "$.cod_campana",
                    "programa.$": "$.programa",
                    "nombre_completo.$": "$.nombre_completo"
                }
            },
            "ResultPath": "$.connect_result",
            "Next": "CallStartedSuccess",
            "Catch": [{"ErrorEquals": ["States.ALL"], "Next": "RecordErrorConnect", "ResultPath": "$.error"}]
        },
        "CallStartedSuccess": {
            "Type": "Task",
            "Resource": "arn:aws:states:::dynamodb:updateItem",
            "Parameters": {
                "TableName": INTERACTIONS_TABLE,
                "Key": {"call_id": {"S.$": "$.call_id"}},
                "UpdateExpression": "SET connect_contact_id = :cid, resultado = :res",
                "ExpressionAttributeValues": {
                    ":cid": {"S.$": "$.connect_result.ContactId"},
                    ":res": {"S": "en_llamada"}
                }
            },
            "ResultPath": None,
            "End": True
        },
        # Terminal states
        "RecordBlacklisted": {
            "Type": "Task",
            "Resource": "arn:aws:states:::dynamodb:putItem",
            "Parameters": {
                "TableName": INTERACTIONS_TABLE,
                "Item": {
                    "call_id": {"S.$": "$.call_id"},
                    "afiliado_dni": {"S.$": "$.dni"},
                    "telefono": {"S.$": "$.telefono"},
                    "resultado": {"S": "en_blacklist"}
                }
            },
            "ResultPath": None,
            "End": True
        },
        "RecordApiCaida": {
            "Type": "Task",
            "Resource": "arn:aws:states:::dynamodb:putItem",
            "Parameters": {
                "TableName": INTERACTIONS_TABLE,
                "Item": {
                    "call_id": {"S.$": "$.call_id"},
                    "afiliado_dni": {"S.$": "$.dni"},
                    "telefono": {"S.$": "$.telefono"},
                    "resultado": {"S": "api_caida"},
                    "error_detalle": {"S.$": "States.Format('{}', $.error)"}
                }
            },
            "ResultPath": None,
            "End": True
        },
        "RecordFueraHorario": {
            "Type": "Task",
            "Resource": "arn:aws:states:::dynamodb:putItem",
            "Parameters": {
                "TableName": INTERACTIONS_TABLE,
                "Item": {
                    "call_id": {"S.$": "$.call_id"},
                    "afiliado_dni": {"S.$": "$.dni"},
                    "telefono": {"S.$": "$.telefono"},
                    "resultado": {"S": "fuera_horario"}
                }
            },
            "ResultPath": None,
            "End": True
        },
        "RecordErrorConnect": {
            "Type": "Task",
            "Resource": "arn:aws:states:::dynamodb:putItem",
            "Parameters": {
                "TableName": INTERACTIONS_TABLE,
                "Item": {
                    "call_id": {"S.$": "$.call_id"},
                    "afiliado_dni": {"S.$": "$.dni"},
                    "telefono": {"S.$": "$.telefono"},
                    "resultado": {"S": "error_connect"},
                    "error_detalle": {"S.$": "States.Format('{}', $.error)"}
                }
            },
            "ResultPath": None,
            "End": True
        }
    }
}

# Check if state machine already exists
machines = sfn.list_state_machines().get("stateMachines", [])
existing = [m for m in machines if m["name"] == SM_NAME]

if existing:
    sm_arn = existing[0]["stateMachineArn"]
    print(f"Updating existing state machine: {sm_arn}")
    sfn.update_state_machine(
        stateMachineArn=sm_arn,
        definition=json.dumps(ASL, ensure_ascii=False),
        roleArn=SFN_ROLE_ARN,
    )
    print("UPDATED")
else:
    print(f"Creating state machine: {SM_NAME}")
    r = sfn.create_state_machine(
        name=SM_NAME,
        definition=json.dumps(ASL, ensure_ascii=False),
        roleArn=SFN_ROLE_ARN,
        type="STANDARD",
        tags=TAGS,
        loggingConfiguration={"level": "OFF", "includeExecutionData": False, "destinations": []}
    )
    sm_arn = r["stateMachineArn"]
    print(f"CREATED: {sm_arn}")

print(f"\nState Machine ARN: {sm_arn}")
print(f"\nNOTE: Update CONNECT_INSTANCE_ID and CONNECT_CONTACT_FLOW_ID")
print(f"      once Connect instance is provisioned.")
