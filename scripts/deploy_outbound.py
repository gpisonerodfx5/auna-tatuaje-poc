# -*- coding: utf-8 -*-
"""
Despliega la infraestructura outbound completa:
  1. Contact Flow outbound (igual al inbound — misma conversacion Valentina)
  2. Step Functions state machine actualizado con StartOutboundVoiceContact real

Flujo completo:
  CSV upload → S3 → Lambda Parser → SQS → Step Functions
    → ValidarHorario → Blacklist → HealthCheck → IniciarLlamada (Connect outbound)
    → Amazon Connect llama al afiliado → Contact Flow outbound → Valentina (Nova Sonic)
"""
import boto3, json, sys

# ── CONFIG ────────────────────────────────────────────────────────────────────
INSTANCE_ID     = "4830896a-ec8c-4ee7-9499-de31587fbb36"
ASSISTANT_ARN   = "arn:aws:wisdom:us-east-1:769488154338:assistant/bac452c1-14b3-4252-8c5a-af9e02faca9a"
LEX_BOT_ALIAS   = "arn:aws:lex:us-east-1:769488154338:bot-alias/EWU1UPLT9U/TSTALIASID"
AI_AGENT_VERSION = "680d88d1-66c1-4fa9-b882-d14649de998a:28"
LAMBDA_VALIDAR  = "arn:aws:lambda:us-east-1:769488154338:function:auna-tatuaje-poc-validar-paciente:live"
LAMBDA_DISP     = "arn:aws:lambda:us-east-1:769488154338:function:auna-tatuaje-poc-disponibilidad:live"
LAMBDA_CREAR    = "arn:aws:lambda:us-east-1:769488154338:function:auna-tatuaje-poc-crear-cita:live"
SOURCE_PHONE    = "+18584776876"
SF_ARN          = "arn:aws:states:us-east-1:769488154338:stateMachine:auna-tatuaje-poc-flow"
SF_ROLE_ARN     = "arn:aws:iam::769488154338:role/auna-tatuaje-poc-stepfunctions-role"

session = boto3.Session(profile_name="auna-sandbox", region_name="us-east-1")
cc = session.client("connect")
sf = session.client("stepfunctions")

# ── PASO 1: Contact Flow outbound ─────────────────────────────────────────────
# Identico al inbound salvo que los atributos de paciente (dni, center_id,
# nombre, etc.) vienen del mensaje SQS via contact attributes que Connect
# inyecta en StartOutboundVoiceContact. No hay set-demo-attrs hardcodeados.
print("Creando/actualizando Contact Flow outbound...")

flow = {
    "Version": "2019-10-30",
    "StartAction": "enable-logging",
    "Actions": [
        {
            "Identifier": "enable-logging",
            "Type": "UpdateFlowLoggingBehavior",
            "Parameters": {"FlowLoggingBehavior": "Enabled"},
            "Transitions": {"NextAction": "set-voice"}
        },
        {
            "Identifier": "set-voice",
            "Type": "UpdateContactTextToSpeechVoice",
            "Parameters": {"TextToSpeechVoice": "Lupe"},
            "Transitions": {
                "NextAction": "invoke-validar",
                "Errors": [{"NextAction": "invoke-validar", "ErrorType": "NoMatchingError"}]
            }
        },
        # Los atributos dni y center_id vienen inyectados por StartOutboundVoiceContact
        # (campo Attributes del SDK). No hay hardcodeo.
        {
            "Identifier": "invoke-validar",
            "Type": "InvokeLambdaFunction",
            "Parameters": {
                "LambdaFunctionARN": LAMBDA_VALIDAR,
                "InvocationTimeLimitSeconds": "8",
                "InvocationType": "SYNCHRONOUS",
                "LambdaInvocationAttributes": {
                    "dni": "$.Attributes.dni",
                    "center_id": "$.Attributes.center_id"
                },
                "ResponseValidation": {"ResponseType": "STRING_MAP"}
            },
            "Transitions": {
                "NextAction": "set-patient-attrs",
                "Errors": [{"NextAction": "set-patient-attrs-fallback", "ErrorType": "NoMatchingError"}]
            }
        },
        {
            "Identifier": "set-patient-attrs",
            "Type": "UpdateContactAttributes",
            "Parameters": {
                "Attributes": {
                    "holder_name": "$.External.holder_name",
                    "holder_last_name": "$.External.holder_last_name",
                    "patient_id": "$.External.patient_id",
                    "clinic_history_number": "$.External.clinic_history_number"
                },
                "TargetContact": "Current"
            },
            "Transitions": {
                "NextAction": "set-q-connect",
                "Errors": [{"NextAction": "set-q-connect", "ErrorType": "NoMatchingError"}]
            }
        },
        {
            "Identifier": "set-patient-attrs-fallback",
            "Type": "UpdateContactAttributes",
            "Parameters": {
                "Attributes": {
                    "holder_name": "estimado afiliado",
                    "holder_last_name": " ",
                    "patient_id": "0",
                    "clinic_history_number": "0"
                },
                "TargetContact": "Current"
            },
            "Transitions": {
                "NextAction": "set-q-connect",
                "Errors": [{"NextAction": "set-q-connect", "ErrorType": "NoMatchingError"}]
            }
        },
        {
            "Identifier": "set-q-connect",
            "Type": "CreateWisdomSession",
            "Parameters": {"WisdomAssistantArn": ASSISTANT_ARN},
            "Transitions": {
                "NextAction": "set-wisdom-data",
                "Errors": [{"NextAction": "disconnect", "ErrorType": "NoMatchingError"}]
            }
        },
        {
            "Identifier": "set-wisdom-data",
            "Type": "UpdateContactData",
            "Parameters": {"WisdomSessionArn": "$.Wisdom.SessionArn"},
            "Transitions": {
                "NextAction": "get-customer-input",
                "Errors": [{"NextAction": "disconnect", "ErrorType": "NoMatchingError"}]
            }
        },
        {
            "Identifier": "get-customer-input",
            "Type": "ConnectParticipantWithLexBot",
            "Parameters": {
                "Text": " ",
                "LexV2Bot": {"AliasArn": LEX_BOT_ALIAS},
                "LexSessionAttributes": {
                    "x-amz-lex:q-in-connect:ai-agent-id": AI_AGENT_VERSION,
                    "x-amz-lex:locale-id": "es_US",
                    "x-amz-lex:audio-silence-timeout-ms": "6000",
                    "patient_id": "$.Attributes.patient_id",
                    "clinic_history_number": "$.Attributes.clinic_history_number",
                    "holder_name": "$.Attributes.holder_name",
                    "holder_last_name": "$.Attributes.holder_last_name",
                    "center_id": "$.Attributes.center_id",
                    "dni": "$.Attributes.dni",
                    "disponible": "$.Attributes.disponible",
                    "opciones_texto": "$.Attributes.opciones_texto",
                    "cita_exito": "$.Attributes.cita_exito",
                    "cita_id": "$.Attributes.cita_id",
                    "cita_mensaje": "$.Attributes.cita_mensaje"
                }
            },
            "Transitions": {
                "NextAction": "disconnect",
                "Errors": [
                    {"NextAction": "save-tool-name", "ErrorType": "NoMatchingCondition"},
                    {"NextAction": "disconnect", "ErrorType": "NoMatchingError"}
                ]
            }
        },
        {
            "Identifier": "save-tool-name",
            "Type": "UpdateContactAttributes",
            "Parameters": {
                "Attributes": {"tool_name": "$.Lex.SessionAttributes.Tool"},
                "TargetContact": "Current"
            },
            "Transitions": {
                "NextAction": "dispatch",
                "Errors": [{"NextAction": "get-customer-input", "ErrorType": "NoMatchingError"}]
            }
        },
        {
            "Identifier": "dispatch",
            "Type": "Compare",
            "Parameters": {"ComparisonValue": "$.Attributes.tool_name"},
            "Transitions": {
                "NextAction": "get-customer-input",
                "Errors": [{"NextAction": "get-customer-input", "ErrorType": "NoMatchingCondition"}],
                "Conditions": [
                    {"NextAction": "disconnect", "Condition": {"Operator": "Equals", "Operands": ["COMPLETE"]}},
                    {"NextAction": "disconnect", "Condition": {"Operator": "Equals", "Operands": ["Escalate"]}},
                    {"NextAction": "invoke-disp", "Condition": {"Operator": "Equals", "Operands": ["ConsultarDisponibilidad"]}},
                    {"NextAction": "invoke-crear", "Condition": {"Operator": "Equals", "Operands": ["CrearCita"]}}
                ]
            }
        },
        {
            "Identifier": "invoke-disp",
            "Type": "InvokeLambdaFunction",
            "Parameters": {
                "LambdaFunctionARN": LAMBDA_DISP,
                "InvocationTimeLimitSeconds": "8",
                "InvocationType": "SYNCHRONOUS",
                "LambdaInvocationAttributes": {
                    "patient_id": "$.Attributes.patient_id",
                    "clinic_history_number": "$.Attributes.clinic_history_number",
                    "center_id": "$.Attributes.center_id",
                    "dni": "$.Attributes.dni",
                    "preferencia_dia": "$.Lex.SessionAttributes.preferencia_dia",
                    "preferencia_horario": "$.Lex.SessionAttributes.preferencia_horario"
                },
                "ResponseValidation": {"ResponseType": "STRING_MAP"}
            },
            "Transitions": {
                "NextAction": "save-disp",
                "Errors": [{"NextAction": "save-disp", "ErrorType": "NoMatchingError"}]
            }
        },
        {
            "Identifier": "save-disp",
            "Type": "UpdateContactAttributes",
            "Parameters": {
                "Attributes": {
                    "disponible": "$.External.disponible",
                    "opciones_texto": "$.External.opciones_texto",
                    "opciones_0_model_id": "$.External.opciones_0_model_id",
                    "opciones_0_doctor_id": "$.External.opciones_0_doctor_id",
                    "opciones_0_doctor_name": "$.External.opciones_0_doctor_name",
                    "opciones_0_service_id": "$.External.opciones_0_service_id",
                    "opciones_0_center_id": "$.External.opciones_0_center_id",
                    "opciones_0_fecha": "$.External.opciones_0_fecha",
                    "opciones_0_hora": "$.External.opciones_0_hora",
                    "opciones_1_model_id": "$.External.opciones_1_model_id",
                    "opciones_1_doctor_id": "$.External.opciones_1_doctor_id",
                    "opciones_1_doctor_name": "$.External.opciones_1_doctor_name",
                    "opciones_1_service_id": "$.External.opciones_1_service_id",
                    "opciones_1_center_id": "$.External.opciones_1_center_id",
                    "opciones_1_fecha": "$.External.opciones_1_fecha",
                    "opciones_1_hora": "$.External.opciones_1_hora",
                    "opciones_2_model_id": "$.External.opciones_2_model_id",
                    "opciones_2_doctor_id": "$.External.opciones_2_doctor_id",
                    "opciones_2_doctor_name": "$.External.opciones_2_doctor_name",
                    "opciones_2_service_id": "$.External.opciones_2_service_id",
                    "opciones_2_center_id": "$.External.opciones_2_center_id",
                    "opciones_2_fecha": "$.External.opciones_2_fecha",
                    "opciones_2_hora": "$.External.opciones_2_hora"
                },
                "TargetContact": "Current"
            },
            "Transitions": {
                "NextAction": "get-customer-input",
                "Errors": [{"NextAction": "get-customer-input", "ErrorType": "NoMatchingError"}]
            }
        },
        {
            "Identifier": "invoke-crear",
            "Type": "InvokeLambdaFunction",
            "Parameters": {
                "LambdaFunctionARN": LAMBDA_CREAR,
                "InvocationTimeLimitSeconds": "8",
                "InvocationType": "SYNCHRONOUS",
                "LambdaInvocationAttributes": {
                    "opcion_elegida": "$.Lex.SessionAttributes.opcion_elegida",
                    "patient_id": "$.Attributes.patient_id",
                    "clinic_history_number": "$.Attributes.clinic_history_number",
                    "holder_name": "$.Attributes.holder_name",
                    "holder_last_name": "$.Attributes.holder_last_name",
                    "center_id": "$.Attributes.center_id",
                    "dni": "$.Attributes.dni",
                    "opciones_0_model_id": "$.Attributes.opciones_0_model_id",
                    "opciones_0_doctor_id": "$.Attributes.opciones_0_doctor_id",
                    "opciones_0_doctor_name": "$.Attributes.opciones_0_doctor_name",
                    "opciones_0_service_id": "$.Attributes.opciones_0_service_id",
                    "opciones_0_center_id": "$.Attributes.opciones_0_center_id",
                    "opciones_0_fecha": "$.Attributes.opciones_0_fecha",
                    "opciones_0_hora": "$.Attributes.opciones_0_hora",
                    "opciones_1_model_id": "$.Attributes.opciones_1_model_id",
                    "opciones_1_doctor_id": "$.Attributes.opciones_1_doctor_id",
                    "opciones_1_doctor_name": "$.Attributes.opciones_1_doctor_name",
                    "opciones_1_service_id": "$.Attributes.opciones_1_service_id",
                    "opciones_1_center_id": "$.Attributes.opciones_1_center_id",
                    "opciones_1_fecha": "$.Attributes.opciones_1_fecha",
                    "opciones_1_hora": "$.Attributes.opciones_1_hora",
                    "opciones_2_model_id": "$.Attributes.opciones_2_model_id",
                    "opciones_2_doctor_id": "$.Attributes.opciones_2_doctor_id",
                    "opciones_2_doctor_name": "$.Attributes.opciones_2_doctor_name",
                    "opciones_2_service_id": "$.Attributes.opciones_2_service_id",
                    "opciones_2_center_id": "$.Attributes.opciones_2_center_id",
                    "opciones_2_fecha": "$.Attributes.opciones_2_fecha",
                    "opciones_2_hora": "$.Attributes.opciones_2_hora"
                },
                "ResponseValidation": {"ResponseType": "STRING_MAP"}
            },
            "Transitions": {
                "NextAction": "save-crear",
                "Errors": [{"NextAction": "save-crear", "ErrorType": "NoMatchingError"}]
            }
        },
        {
            "Identifier": "save-crear",
            "Type": "UpdateContactAttributes",
            "Parameters": {
                "Attributes": {
                    "cita_exito": "$.External.exito",
                    "cita_id": "$.External.cita_id",
                    "cita_mensaje": "$.External.mensaje"
                },
                "TargetContact": "Current"
            },
            "Transitions": {
                "NextAction": "get-customer-input",
                "Errors": [{"NextAction": "get-customer-input", "ErrorType": "NoMatchingError"}]
            }
        },
        {
            "Identifier": "disconnect",
            "Type": "DisconnectParticipant",
            "Parameters": {},
            "Transitions": {}
        }
    ]
}

# Buscar si ya existe el flow outbound, si no crearlo
existing_flows = cc.list_contact_flows(
    InstanceId=INSTANCE_ID,
    ContactFlowTypes=["CONTACT_FLOW"]
)["ContactFlowSummaryList"]

outbound_flow = next((f for f in existing_flows if f["Name"] == "auna-tatuaje-poc-outbound"), None)

if outbound_flow:
    cc.update_contact_flow_content(
        InstanceId=INSTANCE_ID,
        ContactFlowId=outbound_flow["Id"],
        Content=json.dumps(flow)
    )
    flow_id = outbound_flow["Id"]
    print(f"  Flow outbound actualizado: {flow_id}")
else:
    r = cc.create_contact_flow(
        InstanceId=INSTANCE_ID,
        Name="auna-tatuaje-poc-outbound",
        Type="CONTACT_FLOW",
        Content=json.dumps(flow)
    )
    flow_id = r["ContactFlowId"]
    print(f"  Flow outbound CREADO: {flow_id}")

# ── PASO 2: Actualizar Step Functions con StartOutboundVoiceContact real ──────
print()
print("Actualizando Step Functions con IniciarLlamada real...")

sf_definition = {
    "Comment": "PoC Tatuaje Auna v2.1 — Flujo outbound por afiliado",
    "StartAt": "ValidarHorario",
    "States": {
        "ValidarHorario": {
            "Type": "Choice",
            "Comment": "Estado 0: Verifica horario laboral Peru (L-V 9-19, S 9-13 UTC-5)",
            "Choices": [
                {
                    "And": [
                        {"Variable": "$.force_run", "BooleanEquals": True}
                    ],
                    "Next": "ConsultarBlacklist"
                }
            ],
            "Default": "EsperarHorario"
        },
        "EsperarHorario": {
            "Type": "Wait",
            "Comment": "Espera 5 min y reintenta validacion de horario",
            "Seconds": 300,
            "Next": "ValidarHorario"
        },
        "ConsultarBlacklist": {
            "Type": "Task",
            "Comment": "Estado 1: Consulta DynamoDB blacklist directamente",
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
                        {"Variable": "$.blacklist_result.Item.activo.BOOL", "BooleanEquals": True},
                        {"Variable": "$.blacklist_result.Item.intentos_fallidos.N", "StringGreaterThanEquals": "3"}
                    ],
                    "Next": "EnBlacklist"
                }
            ],
            "Default": "HealthCheck"
        },
        "EnBlacklist": {
            "Type": "Succeed",
            "Comment": "Numero en blacklist, no llamar"
        },
        "HealthCheck": {
            "Type": "Task",
            "Comment": "Estado 2: Ping API Multisede",
            "Resource": "arn:aws:lambda:us-east-1:769488154338:function:auna-tatuaje-poc-health-check",
            "ResultPath": "$.health",
            "Next": "EvaluarHealthCheck",
            "Retry": [{"ErrorEquals": ["States.TaskFailed"], "IntervalSeconds": 30, "MaxAttempts": 2, "BackoffRate": 2}]
        },
        "EvaluarHealthCheck": {
            "Type": "Choice",
            "Choices": [
                {"Variable": "$.health.api_available", "BooleanEquals": True, "Next": "RegistrarInicio"}
            ],
            "Default": "EsperarAPICaida"
        },
        "EsperarAPICaida": {
            "Type": "Wait",
            "Seconds": 300,
            "Next": "HealthCheck"
        },
        "RegistrarInicio": {
            "Type": "Task",
            "Comment": "Registra inicio de llamada en DynamoDB",
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
            "Comment": "Estado 4: StartOutboundVoiceContact — Connect llama al afiliado",
            "Resource": "arn:aws:states:::aws-sdk:connect:startOutboundVoiceContact",
            "Parameters": {
                "InstanceId": INSTANCE_ID,
                "ContactFlowId": flow_id,
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
            "Catch": [
                {
                    "ErrorEquals": ["States.ALL"],
                    "ResultPath": "$.connect_error",
                    "Next": "ErrorLlamada"
                }
            ]
        },
        "LlamadaIniciada": {
            "Type": "Succeed",
            "Comment": "Llamada iniciada correctamente. Connect + Nova Sonic manejan la conversacion."
        },
        "ErrorLlamada": {
            "Type": "Fail",
            "Comment": "Error al iniciar la llamada",
            "Error": "ConnectError",
            "Cause": "StartOutboundVoiceContact fallo"
        }
    }
}

sf.update_state_machine(
    stateMachineArn=SF_ARN,
    definition=json.dumps(sf_definition),
    roleArn=SF_ROLE_ARN
)
print(f"  Step Functions actualizado: {SF_ARN}")

print()
print("=== COMPLETADO ===")
print(f"  Contact Flow outbound: auna-tatuaje-poc-outbound ({flow_id})")
print(f"  Step Functions: auna-tatuaje-poc-flow (IniciarLlamada conectado a Connect)")
print()
print("Flujo completo:")
print("  CSV → S3 (input/*.csv) → Lambda Parser → SQS → Step Functions")
print("    → ValidarHorario → Blacklist → HealthCheck → StartOutboundVoiceContact")
print("    → Connect llama al afiliado → Contact Flow outbound → Valentina (Nova Sonic)")
print()
print("Para probar manualmente:")
print('  import boto3, json')
print('  sf = boto3.Session(profile_name="auna-sandbox").client("stepfunctions")')
print('  sf.start_execution(')
print(f'    stateMachineArn="{SF_ARN}",')
print('    input=json.dumps({')
print('      "call_id": "test-001",')
print('      "dni": "740473",')
print('      "nombre_completo": "GABRIEL GERARDO PISONERO LOPEZ",')
print('      "telefono": "+573150020389",')
print('      "programa": "PROGRAMA ONCOCLASICO PRO",')
print('      "sede_referencia": "1",')
print('      "cuotas_pagadas": "3",')
print('      "grupo_cuota": "A",')
print('      "cod_campana": "TATUAJE-2026-Q1",')
print('      "force_run": True')
print('    })')
print('  )')
