"""
Deploy improved auna-tatuaje-poc-inbound-test flow.

Architecture (single main loop):
  setup → play-greeting
    → [loop-wisdom] CreateWisdomSession
    → [loop-ucdata] UpdateContactData
    → [loop-lex] ConnectParticipantWithLexBot
        Success (intent fulfilled / agent closes) → play-bye → disconnect
        NoMatchingCondition (tool call) → save-tool-name (copy $.Lex.q-in-connect:tool-name)
            → dispatch (Compare $.Attributes.tool_name)
                ValidarPaciente        → invoke-validar-tool → save-validar → loop
                ConsultarDisponibilidad→ invoke-disp         → save-disp   → loop
                CrearCita              → invoke-crear        → save-crear  → loop
                COMPLETE               → play-bye → disconnect
                (no match)             → loop (unknown tool, keep going)
        NoMatchingError → error-msg → disconnect

ValidarPaciente is also run upfront before greeting to pre-populate patient attrs.
All Lambda results are stored as contact attributes so AI agent reads them via $.Attributes.*
in the next LexSessionAttributes injection.
"""
import boto3, json

session = boto3.Session(profile_name="auna-sandbox", region_name="us-east-1")
connect = session.client("connect")

INSTANCE_ID   = "4830896a-ec8c-4ee7-9499-de31587fbb36"
FLOW_ID       = "cd86706f-68ea-4909-9e73-1fec3024f87d"
REGION        = "us-east-1"
ACCOUNT       = "769488154338"

ASSISTANT_ARN = f"arn:aws:wisdom:{REGION}:{ACCOUNT}:assistant/bac452c1-14b3-4252-8c5a-af9e02faca9a"
AI_AGENT_ARN  = (
    "arn:aws:wisdom:us-east-1:769488154338:ai-agent"
    "/bac452c1-14b3-4252-8c5a-af9e02faca9a"
    "/680d88d1-66c1-4fa9-b882-d14649de998a:$LATEST"
)
LEX_ALIAS_ARN = f"arn:aws:lex:{REGION}:{ACCOUNT}:bot-alias/GYW4HZIRVC/PJ35DZ7U3U"

VALIDAR_ARN   = f"arn:aws:lambda:{REGION}:{ACCOUNT}:function:auna-tatuaje-poc-validar-paciente"
DISP_ARN      = f"arn:aws:lambda:{REGION}:{ACCOUNT}:function:auna-tatuaje-poc-disponibilidad"
CREAR_ARN     = f"arn:aws:lambda:{REGION}:{ACCOUNT}:function:auna-tatuaje-poc-crear-cita"

flow = {
    "Version": "2019-10-30",
    "StartAction": "enable-logging",
    "Metadata": {
        "entryPointPosition": {"x": 20, "y": 20},
        "ActionMetadata": {}
    },
    "Actions": [

        # ── 1. Enable logging ─────────────────────────────────────────────
        {
            "Identifier": "enable-logging",
            "Type": "UpdateFlowLoggingBehavior",
            "Parameters": {"FlowLoggingBehavior": "Enabled"},
            "Transitions": {"NextAction": "set-voice"}
        },

        # ── 2. Voice = Lupe ───────────────────────────────────────────────
        {
            "Identifier": "set-voice",
            "Type": "UpdateContactTextToSpeechVoice",
            "Parameters": {"TextToSpeechVoice": "Lupe"},
            "Transitions": {
                "NextAction": "set-demo-attrs",
                "Errors": [{"NextAction": "set-demo-attrs", "ErrorType": "NoMatchingError"}]
            }
        },

        # ── 3. Demo attrs + Lex audio tuning ─────────────────────────────
        {
            "Identifier": "set-demo-attrs",
            "Type": "UpdateContactAttributes",
            "Parameters": {
                "Attributes": {
                    "dni": "740473",
                    "center_id": "1",
                    "x-amz-lex:audio-start-timeout-ms:*:*": "4000",
                    "x-amz-lex:audio-end-timeout-ms:*:*": "1200",
                    "x-amz-lex:max-speech-duration-ms:*:*": "15000",
                    "x-amz-lex:end-timeout-ms:*:*": "1200"
                },
                "TargetContact": "Current"
            },
            "Transitions": {
                "NextAction": "invoke-validar",
                "Errors": [{"NextAction": "invoke-validar", "ErrorType": "NoMatchingError"}]
            }
        },

        # ── 4. ValidarPaciente upfront ────────────────────────────────────
        {
            "Identifier": "invoke-validar",
            "Type": "InvokeLambdaFunction",
            "Parameters": {
                "LambdaFunctionARN": VALIDAR_ARN,
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

        # ── 5a. Patient attrs from Lambda ─────────────────────────────────
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
                "NextAction": "play-greeting",
                "Errors": [{"NextAction": "play-greeting", "ErrorType": "NoMatchingError"}]
            }
        },

        # ── 5b. Fallback patient attrs ────────────────────────────────────
        {
            "Identifier": "set-patient-attrs-fallback",
            "Type": "UpdateContactAttributes",
            "Parameters": {
                "Attributes": {
                    "holder_name": "estimado afiliado",
                    "holder_last_name": "afiliado",
                    "patient_id": "0",
                    "clinic_history_number": "0"
                },
                "TargetContact": "Current"
            },
            "Transitions": {
                "NextAction": "play-greeting",
                "Errors": [{"NextAction": "play-greeting", "ErrorType": "NoMatchingError"}]
            }
        },

        # ── 6. Play greeting ──────────────────────────────────────────────
        {
            "Identifier": "play-greeting",
            "Type": "MessageParticipant",
            "Parameters": {
                "Text": (
                    "Hola, le saluda Valentina de Oncosalud. "
                    "Le llamo para ofrecerle su chequeo preventivo oncologico completamente gratuito. "
                    "Le gustaria agendarlo?"
                )
            },
            "Transitions": {
                "NextAction": "loop-wisdom",
                "Errors": [{"NextAction": "loop-wisdom", "ErrorType": "NoMatchingError"}]
            }
        },

        # ── MAIN LOOP ─────────────────────────────────────────────────────
        {
            "Identifier": "loop-wisdom",
            "Type": "CreateWisdomSession",
            "Parameters": {
                "WisdomAssistantArn": ASSISTANT_ARN
            },
            "Transitions": {
                "NextAction": "loop-ucdata",
                "Errors": [{"NextAction": "error-msg", "ErrorType": "NoMatchingError"}]
            }
        },
        {
            "Identifier": "loop-ucdata",
            "Type": "UpdateContactData",
            "Parameters": {
                "WisdomSessionArn": "$.Wisdom.SessionArn"
            },
            "Transitions": {
                "NextAction": "loop-lex",
                "Errors": [{"NextAction": "error-msg", "ErrorType": "NoMatchingError"}]
            }
        },
        {
            "Identifier": "loop-lex",
            "Type": "ConnectParticipantWithLexBot",
            "Parameters": {
                "Text": "Como le puedo ayudar?",
                "LexV2Bot": {"AliasArn": LEX_ALIAS_ARN},
                "LexSessionAttributes": {
                    "x-amz-lex:q-in-connect:ai-agent-arn": AI_AGENT_ARN,
                    # Patient data (for AI agent context)
                    "patient_id": "$.Attributes.patient_id",
                    "clinic_history_number": "$.Attributes.clinic_history_number",
                    "holder_name": "$.Attributes.holder_name",
                    "holder_last_name": "$.Attributes.holder_last_name",
                    "center_id": "$.Attributes.center_id",
                    "dni": "$.Attributes.dni",
                    # Availability results
                    "disponible": "$.Attributes.disponible",
                    "opciones_texto": "$.Attributes.opciones_texto",
                    "slot_fecha": "$.Attributes.slot_fecha",
                    "slot_hora": "$.Attributes.slot_hora",
                    "slot_fecha_display": "$.Attributes.slot_fecha_display",
                    "doctor_name": "$.Attributes.doctor_name",
                    # Appointment result
                    "cita_id": "$.Attributes.cita_id",
                    "cita_exito": "$.Attributes.cita_exito",
                    "cita_mensaje": "$.Attributes.cita_mensaje"
                }
            },
            "Transitions": {
                "NextAction": "play-bye",
                "Errors": [
                    {"NextAction": "save-tool-name", "ErrorType": "NoMatchingCondition"},
                    {"NextAction": "error-msg",      "ErrorType": "NoMatchingError"}
                ]
            }
        },

        # ── After tool call: save tool name to clean attribute ────────────
        # $.Lex.q-in-connect:tool-name can't be used directly in Compare
        # so we copy it to $.Attributes.tool_name first
        {
            "Identifier": "save-tool-name",
            "Type": "UpdateContactAttributes",
            "Parameters": {
                "Attributes": {
                    "tool_name": "$.Lex.q-in-connect:tool-name"
                },
                "TargetContact": "Current"
            },
            "Transitions": {
                "NextAction": "dispatch",
                "Errors": [{"NextAction": "loop-wisdom", "ErrorType": "NoMatchingError"}]
            }
        },

        # ── Dispatch to correct Lambda based on tool name ─────────────────
        {
            "Identifier": "dispatch",
            "Type": "Compare",
            "Parameters": {
                "ComparisonValue": "$.Attributes.tool_name"
            },
            "Transitions": {
                "NextAction": "loop-wisdom",
                "Errors": [
                    {"NextAction": "loop-wisdom", "ErrorType": "NoMatchingCondition"}
                ],
                "Conditions": [
                    {"NextAction": "invoke-validar-tool", "Condition": {"Operator": "Equals", "Operands": ["ValidarPaciente"]}},
                    {"NextAction": "invoke-disp",         "Condition": {"Operator": "Equals", "Operands": ["ConsultarDisponibilidad"]}},
                    {"NextAction": "invoke-crear",        "Condition": {"Operator": "Equals", "Operands": ["CrearCita"]}},
                    {"NextAction": "play-bye",            "Condition": {"Operator": "Equals", "Operands": ["COMPLETE"]}}
                ]
            }
        },

        # ── ValidarPaciente (mid-conversation) ────────────────────────────
        {
            "Identifier": "invoke-validar-tool",
            "Type": "InvokeLambdaFunction",
            "Parameters": {
                "LambdaFunctionARN": VALIDAR_ARN,
                "InvocationTimeLimitSeconds": "8",
                "InvocationType": "SYNCHRONOUS",
                "LambdaInvocationAttributes": {
                    "dni": "$.Attributes.dni",
                    "center_id": "$.Attributes.center_id"
                },
                "ResponseValidation": {"ResponseType": "STRING_MAP"}
            },
            "Transitions": {
                "NextAction": "save-validar",
                "Errors": [{"NextAction": "save-validar", "ErrorType": "NoMatchingError"}]
            }
        },
        {
            "Identifier": "save-validar",
            "Type": "UpdateContactAttributes",
            "Parameters": {
                "Attributes": {
                    "patient_id": "$.External.patient_id",
                    "clinic_history_number": "$.External.clinic_history_number",
                    "holder_name": "$.External.holder_name",
                    "holder_last_name": "$.External.holder_last_name",
                    "validar_result": "$.External.elegible"
                },
                "TargetContact": "Current"
            },
            "Transitions": {
                "NextAction": "loop-wisdom",
                "Errors": [{"NextAction": "loop-wisdom", "ErrorType": "NoMatchingError"}]
            }
        },

        # ── ConsultarDisponibilidad ────────────────────────────────────────
        {
            "Identifier": "invoke-disp",
            "Type": "InvokeLambdaFunction",
            "Parameters": {
                "LambdaFunctionARN": DISP_ARN,
                "InvocationTimeLimitSeconds": "8",
                "InvocationType": "SYNCHRONOUS",
                "LambdaInvocationAttributes": {
                    "patient_id": "$.Attributes.patient_id",
                    "clinic_history_number": "$.Attributes.clinic_history_number",
                    "center_id": "$.Attributes.center_id",
                    "dni": "$.Attributes.dni"
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
                    # disponible = "true"/"false"
                    "disponible": "$.External.disponible",
                    # Human-readable text with all options — AI agent reads this
                    "opciones_texto": "$.External.opciones_texto",
                    # First option fields (flattened by _connect_response as opciones_0_*)
                    "model_id": "$.External.opciones_0_model_id",
                    "doctor_id": "$.External.opciones_0_doctor_id",
                    "doctor_name": "$.External.opciones_0_doctor_name",
                    "service_id": "$.External.opciones_0_service_id",
                    "slot_fecha": "$.External.opciones_0_fecha",
                    "slot_hora": "$.External.opciones_0_hora",
                    "slot_fecha_display": "$.External.opciones_0_fecha_display",
                    # Second option
                    "slot_fecha_2": "$.External.opciones_1_fecha",
                    "slot_hora_2": "$.External.opciones_1_hora",
                    "model_id_2": "$.External.opciones_1_model_id",
                    "doctor_id_2": "$.External.opciones_1_doctor_id",
                    "service_id_2": "$.External.opciones_1_service_id"
                },
                "TargetContact": "Current"
            },
            "Transitions": {
                "NextAction": "loop-wisdom",
                "Errors": [{"NextAction": "loop-wisdom", "ErrorType": "NoMatchingError"}]
            }
        },

        # ── CrearCita ─────────────────────────────────────────────────────
        {
            "Identifier": "invoke-crear",
            "Type": "InvokeLambdaFunction",
            "Parameters": {
                "LambdaFunctionARN": CREAR_ARN,
                "InvocationTimeLimitSeconds": "8",
                "InvocationType": "SYNCHRONOUS",
                "LambdaInvocationAttributes": {
                    "patient_id": "$.Attributes.patient_id",
                    "clinic_history_number": "$.Attributes.clinic_history_number",
                    "center_id": "$.Attributes.center_id",
                    "dni": "$.Attributes.dni",
                    "holder_name": "$.Attributes.holder_name",
                    "holder_last_name": "$.Attributes.holder_last_name",
                    "model_id": "$.Attributes.model_id",
                    "doctor_id": "$.Attributes.doctor_id",
                    "service_id": "$.Attributes.service_id",
                    "fecha": "$.Attributes.slot_fecha",
                    "hora": "$.Attributes.slot_hora"
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
                    "cita_id": "$.External.cita_id",
                    "cita_exito": "$.External.exito",
                    "cita_mensaje": "$.External.mensaje"
                },
                "TargetContact": "Current"
            },
            "Transitions": {
                "NextAction": "loop-wisdom",
                "Errors": [{"NextAction": "loop-wisdom", "ErrorType": "NoMatchingError"}]
            }
        },

        # ── Goodbye ───────────────────────────────────────────────────────
        {
            "Identifier": "play-bye",
            "Type": "MessageParticipant",
            "Parameters": {
                "Text": "Muchas gracias por su tiempo. Que tenga un excelente dia. Hasta luego."
            },
            "Transitions": {
                "NextAction": "disconnect",
                "Errors": [{"NextAction": "disconnect", "ErrorType": "NoMatchingError"}]
            }
        },

        # ── Error ─────────────────────────────────────────────────────────
        {
            "Identifier": "error-msg",
            "Type": "MessageParticipant",
            "Parameters": {
                "Text": "Disculpe, tuvimos un inconveniente tecnico. Nos comunicaremos con usted en otro momento. Hasta luego."
            },
            "Transitions": {
                "NextAction": "disconnect",
                "Errors": [{"NextAction": "disconnect", "ErrorType": "NoMatchingError"}]
            }
        },

        # ── Disconnect ────────────────────────────────────────────────────
        {
            "Identifier": "disconnect",
            "Type": "DisconnectParticipant",
            "Parameters": {},
            "Transitions": {}
        }
    ]
}

content_str = json.dumps(flow)
print(f"Flow: {len(content_str)} chars, {len(flow['Actions'])} actions")

r = connect.update_contact_flow_content(
    InstanceId=INSTANCE_ID,
    ContactFlowId=FLOW_ID,
    Content=content_str
)
print(f"HTTP: {r['ResponseMetadata']['HTTPStatusCode']}")
print("\nActions:")
for a in flow["Actions"]:
    t = a.get("Transitions", {})
    nxt = t.get("NextAction", "—")
    errs = [(e['ErrorType'], e['NextAction']) for e in t.get("Errors", [])]
    print(f"  {a['Identifier']:30s} {a['Type']:40s} → {nxt}  {errs}")
