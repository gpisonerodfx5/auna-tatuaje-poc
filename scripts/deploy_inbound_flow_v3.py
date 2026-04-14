# -*- coding: utf-8 -*-
"""
Despliega el Contact Flow correcto segun el workshop de AWS Connect AI Agents.

Arquitectura:
  enable-logging
  → set-voice         (Lupe, Generative)
  → set-demo-attrs    (dni, center_id para demo — en prod vienen del outbound)
  → invoke-validar    (ValidarPaciente lambda)
  → set-patient-attrs (copiar resultado al contacto)
  → set-q-connect     (Connect assistant block — asocia Q in Connect assistant + AI agent)
  → get-customer-input (GCI — Enable AI Agent ON, AMAZON.QinConnectIntent)
      ↓ NoMatchingCondition (tool call recibido)
  → save-tool-name    (copia $.Lex.q-in-connect:tool-name a $.Attributes.tool_name)
  → dispatch          (Compare $.Attributes.tool_name)
      "COMPLETE"                → disconnect
      "Escalate"                → error-msg
      "ConsultarDisponibilidad" → invoke-disp → save-disp → get-customer-input (loop)
      "CrearCita"               → invoke-crear → save-crear → get-customer-input (loop)
  ↓ Timeout/Error
  → error-msg
  → disconnect

PREREQUISITO: Crear el bot auna-valentina-v4 desde Connect admin console
  (Routing → Flows → Conversational AI) ANTES de correr este script.
  Luego actualizar LEX_BOT_ALIAS_ARN con el ARN del alias generado.

Uso:
    python3 scripts/deploy_inbound_flow_v3.py [--lex-alias-arn ARN]
"""
import boto3, json, sys, argparse

# ── CONFIGURACION ──────────────────────────────────────────────────────────────
INSTANCE_ID    = "4830896a-ec8c-4ee7-9499-de31587fbb36"
FLOW_ID        = "cd86706f-68ea-4909-9e73-1fec3024f87d"
ASSISTANT_ARN  = "arn:aws:wisdom:us-east-1:769488154338:assistant/bac452c1-14b3-4252-8c5a-af9e02faca9a"
AI_AGENT_ID    = "680d88d1-66c1-4fa9-b882-d14649de998a"
LAMBDA_VALIDAR = "arn:aws:lambda:us-east-1:769488154338:function:auna-tatuaje-poc-validar-paciente:live"
LAMBDA_DISP    = "arn:aws:lambda:us-east-1:769488154338:function:auna-tatuaje-poc-disponibilidad:live"
LAMBDA_CREAR   = "arn:aws:lambda:us-east-1:769488154338:function:auna-tatuaje-poc-crear-cita:live"

# AliasArn del bot creado desde Connect admin → Routing → Flows → Conversational AI
# Actualizar con el ARN real una vez creado el bot auna-valentina-v4
# Bot auna-valentina-v5 (EWU1UPLT9U) — creado desde Connect admin console
# TSTALIASID apunta a DRAFT con en_US + Nova Sonic + AMAZON.QinConnectIntent
LEX_BOT_ALIAS_ARN_DEFAULT = "arn:aws:lex:us-east-1:769488154338:bot-alias/EWU1UPLT9U/TSTALIASID"
# Usar ultima version publicada del agente
AI_AGENT_VERSION = "680d88d1-66c1-4fa9-b882-d14649de998a:30"
AI_AGENT_ARN = f"arn:aws:wisdom:us-east-1:769488154338:ai-agent/bac452c1-14b3-4252-8c5a-af9e02faca9a/{AI_AGENT_VERSION}"
AI_AGENT_ARN_LATEST = f"arn:aws:wisdom:us-east-1:769488154338:ai-agent/bac452c1-14b3-4252-8c5a-af9e02faca9a/680d88d1-66c1-4fa9-b882-d14649de998a:$LATEST"

# ── PARSE ARGS ─────────────────────────────────────────────────────────────────
parser = argparse.ArgumentParser()
parser.add_argument("--lex-alias-arn", default=None,
                    help="AliasArn del bot auna-valentina-v4 creado en Connect")
args = parser.parse_args()

LEX_BOT_ALIAS_ARN = args.lex_alias_arn or LEX_BOT_ALIAS_ARN_DEFAULT

if LEX_BOT_ALIAS_ARN == "PENDIENTE":
    print("ERROR: Debes crear el bot auna-valentina-v4 primero y pasar su AliasArn.")
    print()
    print("Pasos:")
    print("1. Amazon Connect admin → Routing → Flows → Conversational AI")
    print("2. Create bot → nombre: auna-valentina-v4")
    print("3. Add locale: Spanish (US) — es-US")
    print("4. Configuration → Enable Connect AI agents intent: ON")
    print(f"5. Q in Connect assistant ARN: {ASSISTANT_ARN}")
    print("6. Speech model → Speech-to-Speech → Amazon Nova Sonic")
    print("7. Build the locale")
    print()
    print("Luego corre:")
    print("  python3 scripts/deploy_inbound_flow_v3.py --lex-alias-arn arn:aws:lex:us-east-1:769488154338:bot-alias/BOTID/ALIASID")
    sys.exit(1)

print(f"Usando bot alias: {LEX_BOT_ALIAS_ARN}")

# ── FLOW CONTENT ───────────────────────────────────────────────────────────────
flow = {
    "Version": "2019-10-30",
    "StartAction": "enable-logging",
    "Actions": [
        # 1. Habilitar logging
        {
            "Identifier": "enable-logging",
            "Type": "UpdateFlowLoggingBehavior",
            "Parameters": {"FlowLoggingBehavior": "Enabled"},
            "Transitions": {"NextAction": "set-voice"}
        },
        # 2. Configurar voz Lupe (Generative no se puede via API — se configura en UI)
        {
            "Identifier": "set-voice",
            "Type": "UpdateContactTextToSpeechVoice",
            "Parameters": {"TextToSpeechVoice": "Lupe"},
            "Transitions": {
                "NextAction": "set-demo-attrs",
                "Errors": [{"NextAction": "set-demo-attrs", "ErrorType": "NoMatchingError"}]
            }
        },
        # 3. Atributos de demo (DNI y centro para pruebas)
        {
            "Identifier": "set-demo-attrs",
            "Type": "UpdateContactAttributes",
            "Parameters": {
                "Attributes": {
                    "dni": "740473",
                    "center_id": "1"
                },
                "TargetContact": "Current"
            },
            "Transitions": {
                "NextAction": "invoke-validar",
                "Errors": [{"NextAction": "invoke-validar", "ErrorType": "NoMatchingError"}]
            }
        },
        # 4. Validar paciente (obtener patient_id, clinic_history_number, nombre)
        {
            "Identifier": "invoke-validar",
            "Type": "InvokeLambdaFunction",
            "Parameters": {
                "LambdaFunctionARN": LAMBDA_VALIDAR,
                "InvocationTimeLimitSeconds": "15",
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
        # 5a. Guardar datos del paciente si la lambda respondio bien
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
        # 5b. Fallback si no se pudo validar
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
        # 6. CreateWisdomSession
        {
            "Identifier": "set-q-connect",
            "Type": "CreateWisdomSession",
            "Parameters": {
                "WisdomAssistantArn": ASSISTANT_ARN
            },
            "Transitions": {
                "NextAction": "set-wisdom-data",
                "Errors": [{"NextAction": "disconnect", "ErrorType": "NoMatchingError"}]
            }
        },
        # 7. UpdateContactData
        {
            "Identifier": "set-wisdom-data",
            "Type": "UpdateContactData",
            "Parameters": {
                "WisdomSessionArn": "$.Wisdom.SessionArn"
            },
            "Transitions": {
                "NextAction": "get-customer-input",
                "Errors": [{"NextAction": "disconnect", "ErrorType": "NoMatchingError"}]
            }
        },
        # 8. ConnectParticipantWithLexBot con Enable AI Agent ON
        # El bot auna-valentina-v4 tiene AMAZON.QinConnectIntent con el assistant ARN
        # Connect ya creó la sesión Wisdom — el bot la usa automaticamente
        # NO se pasa x-amz-lex:q-in-connect:ai-agent-arn como session attr
        # (eso causaba el error de acceso al assistant)
        # El AI agent especifico se selecciona via la sesion Wisdom creada arriba
        # NoMatchingCondition = tool call recibido del agente
        {
            "Identifier": "get-customer-input",
            "Type": "ConnectParticipantWithLexBot",
            "Parameters": {
                "Text": " ",
                "LexV2Bot": {
                    "AliasArn": LEX_BOT_ALIAS_ARN
                },
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
                    {
                        "NextAction": "save-tool-name",
                        "ErrorType": "NoMatchingCondition"
                    },
                    {
                        "NextAction": "disconnect",
                        "ErrorType": "NoMatchingError"
                    }
                ]
            }
        },
        # 8. Copiar nombre del tool a contact attribute (el colon en la key de Lex causa error en Compare)
        {
            "Identifier": "save-tool-name",
            "Type": "UpdateContactAttributes",
            "Parameters": {
                "Attributes": {
                    "tool_name": "$.Lex.SessionAttributes.Tool"
                },
                "TargetContact": "Current"
            },
            "Transitions": {
                "NextAction": "dispatch",
                "Errors": [{"NextAction": "get-customer-input", "ErrorType": "NoMatchingError"}]
            }
        },
        # 9. Dispatch segun tool name
        {
            "Identifier": "dispatch",
            "Type": "Compare",
            "Parameters": {
                "ComparisonValue": "$.Attributes.tool_name"
            },
            "Transitions": {
                "NextAction": "get-customer-input",
                "Errors": [
                    {"NextAction": "get-customer-input", "ErrorType": "NoMatchingCondition"}
                ],
                "Conditions": [
                    {
                        "NextAction": "disconnect",
                        "Condition": {"Operator": "Equals", "Operands": ["COMPLETE"]}
                    },
                    {
                        "NextAction": "disconnect",
                        "Condition": {"Operator": "Equals", "Operands": ["Escalate"]}
                    },
                    {
                        "NextAction": "invoke-disp",
                        "Condition": {"Operator": "Equals", "Operands": ["ConsultarDisponibilidad"]}
                    },
                    {
                        "NextAction": "invoke-crear",
                        "Condition": {"Operator": "Equals", "Operands": ["CrearCita"]}
                    }
                ]
            }
        },
        # 10. ConsultarDisponibilidad Lambda
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
        # 11. Guardar resultado de disponibilidad
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
        # 12. CrearCita Lambda
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
                "Errors": [{"NextAction": "set-crear-error", "ErrorType": "NoMatchingError"}]
            }
        },
        # 12b. Si invoke-crear falla (timeout/error), setear cita_exito=false explicitamente
        {
            "Identifier": "set-crear-error",
            "Type": "UpdateContactAttributes",
            "Parameters": {
                "Attributes": {
                    "cita_exito": "false",
                    "cita_mensaje": "Error al procesar la cita"
                },
                "TargetContact": "Current"
            },
            "Transitions": {
                "NextAction": "get-customer-input",
                "Errors": [{"NextAction": "get-customer-input", "ErrorType": "NoMatchingError"}]
            }
        },
        # 13. Guardar resultado de crear cita y volver al agente
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
        # 14. Desconectar
        {
            "Identifier": "disconnect",
            "Type": "DisconnectParticipant",
            "Parameters": {},
            "Transitions": {}
        }
    ]
}

# ── DEPLOY ─────────────────────────────────────────────────────────────────────
session = boto3.Session(profile_name="auna-sandbox", region_name="us-east-1")
cc = session.client("connect", region_name="us-east-1")

print("Desplegando nuevo Contact Flow (arquitectura workshop)...")
print(f"  Flow: {FLOW_ID}")
print(f"  Bot alias: {LEX_BOT_ALIAS_ARN}")
print(f"  AI Agent: {AI_AGENT_ID}")
print()

try:
    r = cc.update_contact_flow_content(
        InstanceId=INSTANCE_ID,
        ContactFlowId=FLOW_ID,
        Content=json.dumps(flow)
    )
    print("  Flow actualizado correctamente.")
    print()
    print("=== COMPLETADO ===")
    print("  Bloques desplegados:")
    for a in flow["Actions"]:
        print(f"    {a['Identifier']}")
    print()
    print("SIGUIENTE PASO: Verificar en Connect admin que el flow se ve correcto")
    print(f"  https://us-east-1.console.aws.amazon.com/connect/home")
    print()
    print("VERIFICACION FINAL: Llamar al +18584776876 y confirmar que Valentina responde.")
except Exception as e:
    print(f"ERROR desplegando flow: {e}")
    sys.exit(1)
