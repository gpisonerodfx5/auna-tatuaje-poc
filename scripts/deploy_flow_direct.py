# -*- coding: utf-8 -*-
import boto3, json

session = boto3.Session(profile_name="auna-sandbox", region_name="us-east-1")
cc = session.client("connect")

INSTANCE_ID    = "4830896a-ec8c-4ee7-9499-de31587fbb36"
FLOW_ID        = "cd86706f-68ea-4909-9e73-1fec3024f87d"
ASSISTANT_ARN  = "arn:aws:wisdom:us-east-1:769488154338:assistant/bac452c1-14b3-4252-8c5a-af9e02faca9a"
AI_AGENT_VERSION = "680d88d1-66c1-4fa9-b882-d14649de998a:19"
LEX_BOT_ALIAS_ARN = "arn:aws:lex:us-east-1:769488154338:bot-alias/EWU1UPLT9U/TSTALIASID"
LAMBDA_VALIDAR = "arn:aws:lambda:us-east-1:769488154338:function:auna-tatuaje-poc-validar-paciente"
LAMBDA_DISP    = "arn:aws:lambda:us-east-1:769488154338:function:auna-tatuaje-poc-disponibilidad"
LAMBDA_CREAR   = "arn:aws:lambda:us-east-1:769488154338:function:auna-tatuaje-poc-crear-cita"

flow = {
    "Version": "2019-10-30",
    "StartAction": "enable-logging",
    "Actions": [
        # 1. Logging
        {
            "Identifier": "enable-logging",
            "Type": "UpdateFlowLoggingBehavior",
            "Parameters": {"FlowLoggingBehavior": "Enabled"},
            "Transitions": {"NextAction": "set-voice"}
        },
        # 2. Voz
        {
            "Identifier": "set-voice",
            "Type": "UpdateContactTextToSpeechVoice",
            "Parameters": {"TextToSpeechVoice": "Lupe"},
            "Transitions": {
                "NextAction": "set-demo-attrs",
                "Errors": [{"NextAction": "set-demo-attrs", "ErrorType": "NoMatchingError"}]
            }
        },
        # 3. Demo attrs
        {
            "Identifier": "set-demo-attrs",
            "Type": "UpdateContactAttributes",
            "Parameters": {
                "Attributes": {"dni": "740473", "center_id": "1"},
                "TargetContact": "Current"
            },
            "Transitions": {
                "NextAction": "set-q-connect",
                "Errors": [{"NextAction": "set-q-connect", "ErrorType": "NoMatchingError"}]
            }
        },
        # 4. CreateWisdomSession PRIMERO — Nova Sonic empieza a inicializarse mientras ValidarPaciente corre
        {
            "Identifier": "set-q-connect",
            "Type": "CreateWisdomSession",
            "Parameters": {"WisdomAssistantArn": ASSISTANT_ARN},
            "Transitions": {
                "NextAction": "set-wisdom-data",
                "Errors": [{"NextAction": "disconnect", "ErrorType": "NoMatchingError"}]
            }
        },
        # 5. UpdateContactData
        {
            "Identifier": "set-wisdom-data",
            "Type": "UpdateContactData",
            "Parameters": {"WisdomSessionArn": "$.Wisdom.SessionArn"},
            "Transitions": {
                "NextAction": "invoke-validar",
                "Errors": [{"NextAction": "set-patient-attrs-fallback", "ErrorType": "NoMatchingError"}]
            }
        },
        # 6. ValidarPaciente
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
        # 7a. Guardar attrs paciente
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
                "NextAction": "get-customer-input",
                "Errors": [{"NextAction": "get-customer-input", "ErrorType": "NoMatchingError"}]
            }
        },
        # 7b. Fallback validar
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
                "NextAction": "get-customer-input",
                "Errors": [{"NextAction": "get-customer-input", "ErrorType": "NoMatchingError"}]
            }
        },
        # 8. GCI
        {
            "Identifier": "get-customer-input",
            "Type": "ConnectParticipantWithLexBot",
            "Parameters": {
                "Text": " ",
                "LexV2Bot": {"AliasArn": LEX_BOT_ALIAS_ARN},
                "LexSessionAttributes": {
                    "x-amz-lex:q-in-connect:ai-agent-id": AI_AGENT_VERSION,
                    "x-amz-lex:locale-id": "es_US",
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
        # 9. Save tool name
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
        # 10. Dispatch
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
        # 11. ConsultarDisponibilidad Lambda — timeout 15s para evitar alucinaciones por cold start
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
        # 12. Save disponibilidad
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
                    "opciones_0_fecha": "$.External.opciones_0_fecha",
                    "opciones_0_hora": "$.External.opciones_0_hora",
                    "opciones_1_model_id": "$.External.opciones_1_model_id",
                    "opciones_1_doctor_id": "$.External.opciones_1_doctor_id",
                    "opciones_1_doctor_name": "$.External.opciones_1_doctor_name",
                    "opciones_1_service_id": "$.External.opciones_1_service_id",
                    "opciones_1_fecha": "$.External.opciones_1_fecha",
                    "opciones_1_hora": "$.External.opciones_1_hora",
                    "opciones_2_model_id": "$.External.opciones_2_model_id",
                    "opciones_2_doctor_id": "$.External.opciones_2_doctor_id",
                    "opciones_2_doctor_name": "$.External.opciones_2_doctor_name",
                    "opciones_2_service_id": "$.External.opciones_2_service_id",
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
        # 13. CrearCita Lambda — timeout 15s
        {
            "Identifier": "invoke-crear",
            "Type": "InvokeLambdaFunction",
            "Parameters": {
                "LambdaFunctionARN": LAMBDA_CREAR,
                "InvocationTimeLimitSeconds": "15",
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
                    "opciones_0_service_id": "$.Attributes.opciones_0_service_id",
                    "opciones_0_fecha": "$.Attributes.opciones_0_fecha",
                    "opciones_0_hora": "$.Attributes.opciones_0_hora",
                    "opciones_1_model_id": "$.Attributes.opciones_1_model_id",
                    "opciones_1_doctor_id": "$.Attributes.opciones_1_doctor_id",
                    "opciones_1_service_id": "$.Attributes.opciones_1_service_id",
                    "opciones_1_fecha": "$.Attributes.opciones_1_fecha",
                    "opciones_1_hora": "$.Attributes.opciones_1_hora",
                    "opciones_2_model_id": "$.Attributes.opciones_2_model_id",
                    "opciones_2_doctor_id": "$.Attributes.opciones_2_doctor_id",
                    "opciones_2_service_id": "$.Attributes.opciones_2_service_id",
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
        # 14. Save crear cita
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
        # 15. Disconnect
        {
            "Identifier": "disconnect",
            "Type": "DisconnectParticipant",
            "Parameters": {},
            "Transitions": {}
        }
    ]
}

print("Desplegando flow actualizado...")
try:
    r = cc.update_contact_flow_content(
        InstanceId=INSTANCE_ID,
        ContactFlowId=FLOW_ID,
        Content=json.dumps(flow)
    )
    print("OK — Flow desplegado correctamente")
    print("Bloques:", [a["Identifier"] for a in flow["Actions"]])
except Exception as e:
    print(f"ERROR: {e}")
