"""Actualiza el Bedrock Agent con system prompt completo y schema mejorado."""
import boto3
import json
import time

session = boto3.Session(profile_name="auna-sandbox", region_name="us-east-1")
bedrock = session.client("bedrock-agent")

AGENT_ID = "B3UYGUTJU8"
ACTION_GROUP_ID = "VNF8PHXAIX"

# ─── SYSTEM PROMPT ────────────────────────────────────────────────────────────
INSTRUCTIONS = """Eres Valentina, una asesora de salud del programa Tatuaje de Oncosalud (Peru).
Tu objetivo es agendar un chequeo preventivo oncologico GRATUITO para el afiliado que ya fue verificado en el sistema antes de esta llamada.

## PERSONALIDAD
- Cálida, profesional, empática. Hablas en español peruano natural.
- Eres concisa: no repites información innecesariamente.
- Si el afiliado te interrumpe, escuchas y respondes a lo que dijo.
- Si el afiliado no entiende algo, lo explicas de otra manera, sin frustrarte.

## DATOS QUE YA TIENES (vienen en los atributos de la llamada)
- Nombre del afiliado: usa el atributo `holder_name` y `holder_last_name`
- DNI: atributo `dni`
- Sede de referencia: atributo `center_id` (siempre usar este para consultar disponibilidad)
- patient_id, clinic_history_number: para crear la cita

## FLUJO DE LA LLAMADA

### 1. SALUDO PERSONALIZADO
Saluda por el nombre del afiliado. Ejemplo:
"Buenos días señor [apellido], soy Valentina de Oncosalud y le llamo porque usted tiene disponible un chequeo preventivo oncológico completamente gratuito como parte de su plan. ¿Tiene un momentito?"

Si dice que no puede hablar ahora, pregunta cuándo sería un buen momento y despídete cordialmente.

### 2. PREGUNTAR PREFERENCIA DE DÍA
Antes de consultar disponibilidad, pregunta:
"Para buscarle las mejores opciones, ¿prefiere la cita entre semana o un sábado?"

Escucha la respuesta. Ejemplos de respuestas validas:
- "entre semana" / "de lunes a viernes" / "días de semana" → preferencia_dia = "semana"
- "sábado" / "fin de semana" / "el finde" → preferencia_dia = "finde"
- "cualquiera" / "me da igual" / "lo que haya" → preferencia_dia = "cualquiera"

### 3. PREGUNTAR PREFERENCIA DE HORARIO
"¿Y prefiere en las mañanas o en las tardes?"

- "mañana" / "mañanas" / "temprano" / "antes del mediodía" → preferencia_horario = "manana"
- "tarde" / "tardes" / "por la tarde" / "después del mediodía" → preferencia_horario = "tarde"
- "cualquiera" / "lo que haya" → preferencia_horario = "cualquiera"

### 4. CONSULTAR DISPONIBILIDAD
Llama a consultar_disponibilidad con:
- center_id: del atributo de sesion
- preferencia_dia: lo que dijo el afiliado
- preferencia_horario: lo que dijo el afiliado

### 5. PRESENTAR OPCIONES
Presenta MÁXIMO 2 opciones de forma natural y conversacional. NO leas una lista robótica.
Ejemplo:
"Encontré disponibilidad con el doctor Rodríguez. Tengo el martes 8 a las 9 de la mañana, o el jueves 10 a las 11. ¿Cuál le vendría mejor?"

### 6. CONFIRMAR Y AGENDAR
Cuando el afiliado elija una opción:
- Confirma: "Perfecto, entonces le agendo el [día] a las [hora] con el doctor [nombre]. ¿Le confirmo?"
- Si confirma: llama a crear_cita con los datos del slot elegido + datos del paciente de la sesión
- Si no: ofrece la otra opción o pregunta si prefiere otra fecha

### 7. CONFIRMACIÓN FINAL
Si la cita se creó exitosamente:
"¡Listo! Su chequeo queda agendado para el [fecha] a las [hora] con el doctor [nombre] en [sede]. Le llegará un mensaje de texto con los detalles. ¿Tiene alguna pregunta?"

### 8. CIERRE
"Muchas gracias por su tiempo. Que tenga un excelente día. Hasta luego."

## MANEJO DE SITUACIONES ESPECIALES

**Si no hay disponibilidad:**
"Por el momento no tenemos turnos disponibles en su sede para ese horario. ¿Le parece si busco en otro rango de fechas?" (aumenta dias_adelante a 30)
Si tampoco hay: "Le informamos que por ahora no tenemos disponibilidad en su sede. Nuestro equipo se comunicará con usted cuando se liberen turnos. Disculpe el inconveniente."

**Si el afiliado rechaza:**
"Entiendo perfectamente. ¿Hay algún motivo por el que prefiere no realizarlo ahora?" (registra motivo)
Despídete cordialmente sin insistir.

**Si el afiliado hace preguntas sobre el chequeo:**
- Es gratuito, incluido en su plan Oncosalud
- Dura aproximadamente 30-45 minutos
- Incluye consulta con especialista en oncología
- No requiere ayuno ni preparación especial

**Si preguntan sobre ubicación de la sede:**
Di el nombre de la sede (center_name) que viene en los resultados de disponibilidad.

## REGLAS IMPORTANTES
- NUNCA menciones errores técnicos al afiliado. Si algo falla, di "permítame un momento" e intenta de nuevo.
- NUNCA hagas preguntas de sí/no seguidas. Una pregunta a la vez.
- NO ofrezcas más de 3 opciones de horario — abruma al afiliado.
- Si el afiliado dice su nombre diferente al del sistema, no lo corrijas, usa el nombre que él usa.
- Habla con ritmo natural: no demasiado rápido, no demasiado lento.
- Si hay silencio por más de 5 segundos, di "¿Hola? ¿Sigue en línea?"
"""

# ─── OPENAPI SCHEMA (con preferencias en consultar_disponibilidad) ────────────
SCHEMA = {
    "openapi": "3.0.0",
    "info": {
        "title": "Valentina - Acciones del Agente de Voz Oncosalud",
        "version": "2.0.0",
        "description": "Herramientas para validar afiliados, consultar disponibilidad y agendar citas."
    },
    "paths": {
        "/validar_elegibilidad": {
            "post": {
                "summary": "Valida si el afiliado es elegible por DNI",
                "operationId": "validarElegibilidad",
                "requestBody": {
                    "required": True,
                    "content": {
                        "application/json": {
                            "schema": {
                                "type": "object",
                                "required": ["dni"],
                                "properties": {
                                    "dni": {"type": "string", "description": "DNI del afiliado"}
                                }
                            }
                        }
                    }
                },
                "responses": {
                    "200": {
                        "description": "Resultado de validacion",
                        "content": {
                            "application/json": {
                                "schema": {
                                    "type": "object",
                                    "properties": {
                                        "elegible": {"type": "boolean"},
                                        "patient_id": {"type": "integer"},
                                        "clinic_history_number": {"type": "integer"},
                                        "holder_name": {"type": "string"},
                                        "holder_last_name": {"type": "string"},
                                        "holder_mother_last_name": {"type": "string"},
                                        "nombre_completo": {"type": "string"},
                                        "motivo": {"type": "string"}
                                    }
                                }
                            }
                        }
                    }
                }
            }
        },
        "/consultar_disponibilidad": {
            "post": {
                "summary": "Consulta horarios disponibles filtrando por preferencia del afiliado",
                "operationId": "consultarDisponibilidad",
                "requestBody": {
                    "required": True,
                    "content": {
                        "application/json": {
                            "schema": {
                                "type": "object",
                                "required": ["center_id"],
                                "properties": {
                                    "center_id": {
                                        "type": "integer",
                                        "description": "ID de la sede del afiliado"
                                    },
                                    "preferencia_dia": {
                                        "type": "string",
                                        "enum": ["semana", "finde", "cualquiera"],
                                        "description": "Preferencia de dia: 'semana' (lunes-viernes), 'finde' (sabado), 'cualquiera'",
                                        "default": "cualquiera"
                                    },
                                    "preferencia_horario": {
                                        "type": "string",
                                        "enum": ["manana", "tarde", "cualquiera"],
                                        "description": "Preferencia de horario: 'manana' (antes de 13:00), 'tarde' (13:00+), 'cualquiera'",
                                        "default": "cualquiera"
                                    },
                                    "dias_adelante": {
                                        "type": "integer",
                                        "description": "Dias hacia adelante para buscar. Default 14, usar 30 si no hay resultados.",
                                        "default": 14
                                    }
                                }
                            }
                        }
                    }
                },
                "responses": {
                    "200": {
                        "description": "Opciones de horario disponibles",
                        "content": {
                            "application/json": {
                                "schema": {
                                    "type": "object",
                                    "properties": {
                                        "disponible": {"type": "boolean"},
                                        "cantidad_opciones": {"type": "integer"},
                                        "opciones_texto": {"type": "string"},
                                        "opciones": {
                                            "type": "array",
                                            "items": {
                                                "type": "object",
                                                "properties": {
                                                    "model_id": {"type": "integer"},
                                                    "doctor_id": {"type": "integer"},
                                                    "doctor_name": {"type": "string"},
                                                    "service_id": {"type": "integer"},
                                                    "center_name": {"type": "string"},
                                                    "center_id": {"type": "integer"},
                                                    "fecha": {"type": "string"},
                                                    "hora": {"type": "string"},
                                                    "fecha_display": {"type": "string"}
                                                }
                                            }
                                        },
                                        "motivo": {"type": "string"}
                                    }
                                }
                            }
                        }
                    }
                }
            }
        },
        "/crear_cita": {
            "post": {
                "summary": "Agenda la cita cuando el afiliado confirma un horario",
                "operationId": "crearCita",
                "requestBody": {
                    "required": True,
                    "content": {
                        "application/json": {
                            "schema": {
                                "type": "object",
                                "required": ["patient_id", "clinic_history_number", "model_id", "doctor_id", "service_id", "fecha", "hora"],
                                "properties": {
                                    "patient_id": {"type": "integer", "description": "ID del paciente de validar_elegibilidad"},
                                    "clinic_history_number": {"type": "integer", "description": "Nro historia clinica de validar_elegibilidad"},
                                    "model_id": {"type": "integer", "description": "ID del slot de consultar_disponibilidad"},
                                    "doctor_id": {"type": "integer", "description": "ID del doctor de consultar_disponibilidad"},
                                    "service_id": {"type": "integer", "description": "ID del servicio de consultar_disponibilidad"},
                                    "fecha": {"type": "string", "description": "Fecha DD/MM/YYYY"},
                                    "hora": {"type": "string", "description": "Hora HH:MM:SS"},
                                    "holder_name": {"type": "string"},
                                    "holder_last_name": {"type": "string"},
                                    "holder_mother_last_name": {"type": "string"},
                                    "start_date_policy": {"type": "string", "default": "01/01/2025"},
                                    "programa": {"type": "string"}
                                }
                            }
                        }
                    }
                },
                "responses": {
                    "200": {
                        "description": "Resultado de la cita",
                        "content": {
                            "application/json": {
                                "schema": {
                                    "type": "object",
                                    "properties": {
                                        "exito": {"type": "boolean"},
                                        "cita_id": {"type": "string"},
                                        "mensaje": {"type": "string"},
                                        "motivo": {"type": "string"}
                                    }
                                }
                            }
                        }
                    }
                }
            }
        }
    }
}

print("1. Actualizando agent instructions...")
bedrock.update_agent(
    agentId=AGENT_ID,
    agentName="auna-tatuaje-valentina",
    instruction=INSTRUCTIONS,
    foundationModel="anthropic.claude-3-sonnet-20240229-v1:0",
    agentResourceRoleArn=bedrock.get_agent(agentId=AGENT_ID)["agent"]["agentResourceRoleArn"],
    description="Agente de voz Valentina - Programa Tatuaje Oncosalud"
)
print("   OK")

print("2. Actualizando OpenAPI schema del action group...")
bedrock.update_agent_action_group(
    agentId=AGENT_ID,
    agentVersion="DRAFT",
    actionGroupId=ACTION_GROUP_ID,
    actionGroupName="auna-actions",
    actionGroupExecutor={"lambda": f"arn:aws:lambda:us-east-1:769488154338:function:auna-tatuaje-poc-dispatcher"},
    apiSchema={"payload": json.dumps(SCHEMA, ensure_ascii=False)},
    actionGroupState="ENABLED"
)
print("   OK")

print("3. Preparando (prepare) el agente...")
bedrock.prepare_agent(agentId=AGENT_ID)
time.sleep(5)

# Wait for PREPARED status
for _ in range(12):
    status = bedrock.get_agent(agentId=AGENT_ID)["agent"]["agentStatus"]
    print(f"   Status: {status}")
    if status == "PREPARED":
        break
    time.sleep(5)

print("4. Creando nueva version del agente...")
try:
    ver = bedrock.create_agent_alias(
        agentId=AGENT_ID,
        agentAliasName="v2-conversacional",
        description="Version 2 con preferencias de dia/horario y flujo conversacional"
    )
    alias_id = ver["agentAlias"]["agentAliasId"]
    print(f"   Nuevo alias: {alias_id}")
except Exception as e:
    print(f"   (alias ya existe o error: {e})")
    # Use existing prod alias
    aliases = bedrock.list_agent_aliases(agentId=AGENT_ID)
    for a in aliases["agentAliasSummaries"]:
        print(f"   Alias existente: {a['agentAliasName']} | {a['agentAliasId']}")

print("\nDONE")