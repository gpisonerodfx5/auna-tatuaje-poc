import boto3, json, time

session = boto3.Session(profile_name="auna-sandbox", region_name="us-east-1")
sf = session.client("stepfunctions")

SF_ARN = "arn:aws:states:us-east-1:769488154338:stateMachine:auna-tatuaje-poc-flow"
SF_ROLE = "arn:aws:iam::769488154338:role/auna-tatuaje-poc-stepfunctions-role"
INSTANCE_ID = "4830896a-ec8c-4ee7-9499-de31587fbb36"
FLOW_ID = "202c52df-5497-4e4e-a76d-0e6556308910"
SOURCE_PHONE = "+18584776876"

sf_definition = {
    "Comment": "PoC Tatuaje Auna v2.1 - Flujo outbound por afiliado",
    "StartAt": "ValidarHorario",
    "States": {
        "ValidarHorario": {
            "Type": "Choice",
            "Choices": [
                {"And": [{"Variable": "$.force_run", "BooleanEquals": True}], "Next": "ConsultarBlacklist"}
            ],
            "Default": "EsperarHorario"
        },
        "EsperarHorario": {
            "Type": "Wait",
            "Seconds": 300,
            "Next": "ValidarHorario"
        },
        "ConsultarBlacklist": {
            "Type": "Task",
            "Resource": "arn:aws:states:::dynamodb:getItem",
            "Parameters": {
                "TableName": "auna-tatuaje-poc-blacklist",
                "Key": {"telefono": {"S.$": "$.telefono"}}
            },
            "ResultPath": "$.blacklist_result",
            "Next": "EvaluarBlacklist",
            "Catch": [{"ErrorEquals": ["States.ALL"], "ResultPath": "$.blacklist_error", "Next": "HealthCheck"}]
        },
        "EvaluarBlacklist": {
            "Type": "Choice",
            "Choices": [
                {
                    "And": [
                        {"Variable": "$.blacklist_result.Item", "IsPresent": True},
                        {"Variable": "$.blacklist_result.Item.activo.BOOL", "BooleanEquals": True},
                        {"Variable": "$.blacklist_result.Item.intentos_fallidos.N", "StringGreaterThanEquals": "3"}
                    ],
                    "Next": "EnBlacklist"
                }
            ],
            "Default": "HealthCheck"
        },
        "EnBlacklist": {"Type": "Succeed"},
        "HealthCheck": {
            "Type": "Task",
            "Resource": "arn:aws:lambda:us-east-1:769488154338:function:auna-tatuaje-poc-health-check",
            "ResultPath": "$.health",
            "Next": "EvaluarHealthCheck",
            "Retry": [{"ErrorEquals": ["States.TaskFailed"], "IntervalSeconds": 30, "MaxAttempts": 2, "BackoffRate": 2}]
        },
        "EvaluarHealthCheck": {
            "Type": "Choice",
            "Choices": [{"Variable": "$.health.api_available", "BooleanEquals": True, "Next": "RegistrarInicio"}],
            "Default": "EsperarAPICaida"
        },
        "EsperarAPICaida": {"Type": "Wait", "Seconds": 300, "Next": "HealthCheck"},
        "RegistrarInicio": {
            "Type": "Task",
            "Resource": "arn:aws:states:::dynamodb:putItem",
            "Parameters": {
                "TableName": "auna-tatuaje-poc-interacciones",
                "Item": {
                    "call_id": {"S.$": "$.call_id"},
                    "afiliado_dni": {"S.$": "$.dni"},
                    "afiliado_nombre": {"S.$": "$.nombre_completo"},
                    "telefono": {"S.$": "$.telefono"},
                    "sede_referencia": {"S.$": "$.sede_referencia"},
                    "programa": {"S.$": "$.programa"},
                    "cuotas_pagadas": {"S.$": "$.cuotas_pagadas"},
                    "grupo_cuota": {"S.$": "$.grupo_cuota"},
                    "timestamp_inicio": {"S.$": "$$.State.EnteredTime"},
                    "resultado": {"S": "iniciando"}
                }
            },
            "ResultPath": "$.dynamo_result",
            "Next": "IniciarLlamada"
        },
        "IniciarLlamada": {
            "Type": "Task",
            "Resource": "arn:aws:states:::aws-sdk:connect:startOutboundVoiceContact",
            "Parameters": {
                "InstanceId": INSTANCE_ID,
                "ContactFlowId": FLOW_ID,
                "DestinationPhoneNumber.$": "$.telefono",
                "SourcePhoneNumber": SOURCE_PHONE,
                "Attributes": {
                    "dni.$": "$.dni",
                    "center_id.$": "$.sede_referencia",
                    "call_id.$": "$.call_id",
                    "nombre_completo.$": "$.nombre_completo",
                    "programa.$": "$.programa",
                    "cod_campana.$": "$.cod_campana"
                }
            },
            "ResultPath": "$.connect_result",
            "Next": "LlamadaIniciada",
            "Catch": [{"ErrorEquals": ["States.ALL"], "ResultPath": "$.connect_error", "Next": "ErrorLlamada"}]
        },
        "LlamadaIniciada": {"Type": "Succeed"},
        "ErrorLlamada": {"Type": "Fail", "Error": "ConnectError", "Cause": "StartOutboundVoiceContact fallo"}
    }
}

sf.update_state_machine(
    stateMachineArn=SF_ARN,
    definition=json.dumps(sf_definition),
    roleArn=SF_ROLE
)
print("Step Functions actualizado (fix blacklist IsPresent)")

time.sleep(2)

r = sf.start_execution(
    stateMachineArn=SF_ARN,
    input=json.dumps({
        "call_id": "test-outbound-002",
        "dni": "740473",
        "nombre_completo": "GABRIEL GERARDO PISONERO LOPEZ",
        "telefono": "+573150020389",
        "programa": "PROGRAMA ONCOCLASICO PRO",
        "sede_referencia": "1",
        "cuotas_pagadas": "3",
        "grupo_cuota": "A",
        "cod_campana": "TATUAJE-2026-Q1",
        "force_run": True
    })
)
exec_arn = r["executionArn"]
print("Execution started:", exec_arn.split(":")[-1])

time.sleep(10)

status = sf.describe_execution(executionArn=exec_arn)["status"]
print("Status:", status)

hist = sf.get_execution_history(executionArn=exec_arn, maxResults=30)
for e in hist["events"]:
    detail = ""
    if "stateEnteredEventDetails" in e:
        detail = "ENTER: " + e["stateEnteredEventDetails"]["name"]
    elif "stateExitedEventDetails" in e:
        detail = "EXIT:  " + e["stateExitedEventDetails"]["name"]
    elif "taskFailedEventDetails" in e:
        detail = "FAIL:  " + str(e["taskFailedEventDetails"])[:300]
    elif "executionFailedEventDetails" in e:
        detail = "EXEC_FAIL: " + str(e["executionFailedEventDetails"])[:300]
    elif "taskSucceededEventDetails" in e:
        detail = "OK:    " + e["taskSucceededEventDetails"].get("output", "")[:100]
    if detail:
        print(" ", detail)
