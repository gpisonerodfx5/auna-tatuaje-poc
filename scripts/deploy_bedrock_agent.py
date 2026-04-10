"""Create Bedrock Agent Valentina with action groups — PoC Tatuaje Auna."""
import boto3, json, time

session = boto3.Session(profile_name="auna-prod", region_name="us-east-1")
bedrock_agent = session.client("bedrock-agent", region_name="us-east-1")
ACCOUNT = "369037400928"
LAMBDA_ROLE_ARN = f"arn:aws:iam::{ACCOUNT}:role/auna-tatuaje-poc-lambda-role"
DISPATCHER_ARN = f"arn:aws:lambda:us-east-1:{ACCOUNT}:function:auna-tatuaje-poc-dispatcher"
TAGS = {"project": "auna-tatuaje-poc", "env": "poc"}

SYSTEM_PROMPT = (
    "Eres Valentina, asesora del programa Tatuaje de Oncosalud (Peru). "
    "Tu funcion es llamar al afiliado y ofrecerle un chequeo preventivo oncologico GRATUITO para agendarlo ahora.\n\n"
    "FLUJO:\n"
    "1. Saluda cordialmente al afiliado por su apellido.\n"
    "2. Te presentas: 'Le llama Valentina de Oncosalud.'\n"
    "3. Ofreces el chequeo preventivo gratuito.\n"
    "4. Si acepta: preguntas preferencia de dia (semana o sabado).\n"
    "5. Preguntas preferencia de horario (manana o tarde).\n"
    "6. Consultas disponibilidad con ConsultarDisponibilidad.\n"
    "7. Presentas maximo 2 opciones de forma natural.\n"
    "8. Cuando el afiliado elige, creas la cita con CrearCita.\n"
    "9. Confirmas la cita y te despides cordialmente.\n\n"
    "TONO: Espanol peruano natural, conciso, una pregunta a la vez. "
    "Nunca menciones errores tecnicos. Si rechaza: despedida cordial."
)

OPENAPI = {
    "openapi": "3.0.0",
    "info": {"title": "Valentina Tools", "description": "Herramientas Oncosalud", "version": "1.0.0"},
    "paths": {
        "/validar_elegibilidad": {
            "post": {
                "summary": "Validar elegibilidad del paciente por DNI",
                "description": "Busca al paciente en Multisede por DNI y devuelve datos para la cita.",
                "operationId": "validar_elegibilidad",
                "requestBody": {
                    "required": True,
                    "content": {"application/json": {"schema": {
                        "type": "object",
                        "properties": {
                            "dni": {"type": "string", "description": "Numero de documento del afiliado"},
                            "center_id": {"type": "string", "description": "ID del centro medico de referencia"}
                        }
                    }}}
                },
                "responses": {
                    "200": {
                        "description": "Datos del paciente y elegibilidad",
                        "content": {"application/json": {"schema": {"type": "object"}}}
                    }
                }
            }
        },
        "/consultar_disponibilidad": {
            "post": {
                "summary": "Consultar disponibilidad de citas",
                "description": "Devuelve horarios disponibles en la sede del afiliado.",
                "operationId": "consultar_disponibilidad",
                "requestBody": {
                    "required": True,
                    "content": {"application/json": {"schema": {
                        "type": "object",
                        "properties": {
                            "center_id": {"type": "string", "description": "ID del centro medico"},
                            "preferencia_dia": {"type": "string", "description": "semana o finde o cualquiera"},
                            "preferencia_horario": {"type": "string", "description": "manana o tarde o cualquiera"},
                            "dias_adelante": {"type": "integer", "description": "Dias a consultar, default 14"}
                        }
                    }}}
                },
                "responses": {
                    "200": {
                        "description": "Opciones disponibles",
                        "content": {"application/json": {"schema": {"type": "object"}}}
                    }
                }
            }
        },
        "/crear_cita": {
            "post": {
                "summary": "Crear cita en Multisede",
                "description": "Crea la cita con los datos del slot elegido por el afiliado.",
                "operationId": "crear_cita",
                "requestBody": {
                    "required": True,
                    "content": {"application/json": {"schema": {
                        "type": "object",
                        "properties": {
                            "patient_id": {"type": "string", "description": "ID del paciente en Multisede"},
                            "clinic_history_number": {"type": "string", "description": "Numero de historia clinica"},
                            "model_id": {"type": "string", "description": "ID del modelo de cita"},
                            "doctor_id": {"type": "string", "description": "ID del doctor"},
                            "service_id": {"type": "string", "description": "ID del servicio"},
                            "fecha": {"type": "string", "description": "Fecha en formato dd/mm/yyyy"},
                            "hora": {"type": "string", "description": "Hora en formato HH:mm"},
                            "holder_name": {"type": "string", "description": "Nombre del titular"},
                            "holder_last_name": {"type": "string", "description": "Apellido paterno"},
                            "holder_mother_last_name": {"type": "string", "description": "Apellido materno"},
                            "affiliate_policy_number": {"type": "string", "description": "Numero de poliza"},
                            "start_date_policy": {"type": "string", "description": "Fecha inicio poliza dd/mm/yyyy"}
                        }
                    }}}
                },
                "responses": {
                    "200": {
                        "description": "Resultado de la cita creada",
                        "content": {"application/json": {"schema": {"type": "object"}}}
                    }
                }
            }
        }
    }
}

def run():
    # Check/create agent
    agents = bedrock_agent.list_agents().get("agentSummaries", [])
    existing = [a for a in agents if a.get("agentName") == "auna-tatuaje-poc-valentina"]

    if existing:
        agent_id = existing[0]["agentId"]
        print(f"Agent EXISTS: {agent_id}")
    else:
        print("Creating agent auna-tatuaje-poc-valentina...")
        r = bedrock_agent.create_agent(
            agentName="auna-tatuaje-poc-valentina",
            description="Agente de voz Valentina — PoC Tatuaje Oncosalud",
            foundationModel="amazon.nova-pro-v1:0",
            instruction=SYSTEM_PROMPT,
            agentResourceRoleArn=LAMBDA_ROLE_ARN,
            idleSessionTTLInSeconds=600,
            tags=TAGS,
        )
        agent_id = r["agent"]["agentId"]
        print(f"Agent CREATED: {agent_id}")
        time.sleep(3)

    # Add Lambda permission for Bedrock Agent to invoke dispatcher
    lc = session.client("lambda", region_name="us-east-1")
    try:
        lc.add_permission(
            FunctionName="auna-tatuaje-poc-dispatcher",
            StatementId="bedrock-agent-invoke",
            Action="lambda:InvokeFunction",
            Principal="bedrock.amazonaws.com",
            SourceArn=f"arn:aws:bedrock:us-east-1:{ACCOUNT}:agent/{agent_id}",
        )
        print("Lambda permission for Bedrock Agent added")
    except lc.exceptions.ResourceConflictException:
        print("Lambda permission already exists")

    # Check/create action group
    ags = bedrock_agent.list_agent_action_groups(
        agentId=agent_id, agentVersion="DRAFT"
    ).get("actionGroupSummaries", [])
    ag_names = [ag["actionGroupName"] for ag in ags]

    if "auna-actions" not in ag_names:
        ag = bedrock_agent.create_agent_action_group(
            agentId=agent_id,
            agentVersion="DRAFT",
            actionGroupName="auna-actions",
            description="Herramientas: validar paciente, consultar disponibilidad, crear cita",
            actionGroupExecutor={"lambda": DISPATCHER_ARN},
            apiSchema={"payload": json.dumps(OPENAPI, ensure_ascii=False)},
        )
        print(f"Action group CREATED: {ag['agentActionGroup']['actionGroupId']}")
    else:
        print("Action group already exists")

    # Prepare agent
    print("Preparing agent (compiling)...")
    try:
        bedrock_agent.prepare_agent(agentId=agent_id)
        time.sleep(8)
        info = bedrock_agent.get_agent(agentId=agent_id)["agent"]
        print(f"Agent status: {info['agentStatus']}")
    except Exception as e:
        print(f"Prepare note: {e}")

    # Check/create alias
    aliases = bedrock_agent.list_agent_aliases(agentId=agent_id).get("agentAliasSummaries", [])
    prod_alias = [a for a in aliases if a["agentAliasName"] == "valentina-poc"]

    if prod_alias:
        alias_id = prod_alias[0]["agentAliasId"]
        print(f"Alias EXISTS: {alias_id}")
    else:
        al = bedrock_agent.create_agent_alias(
            agentId=agent_id,
            agentAliasName="valentina-poc",
            description="PoC alias para Valentina",
            tags=TAGS,
        )
        alias_id = al["agentAlias"]["agentAliasId"]
        print(f"Alias CREATED: {alias_id}")

    alias_arn = f"arn:aws:bedrock:us-east-1:{ACCOUNT}:agent-alias/{agent_id}/{alias_id}"

    print(f"\n=== Bedrock Agent ===")
    print(f"  Agent ID:  {agent_id}")
    print(f"  Alias ID:  {alias_id}")
    print(f"  Alias ARN: {alias_arn}")
    return agent_id, alias_id, alias_arn

if __name__ == "__main__":
    run()
