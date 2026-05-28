# -*- coding: utf-8 -*-
"""
Despliega Q in Connect (Assistant + AI Prompt + AI Agent + binding Connect.SelfService)
en una cuenta AWS. Toma el prompt y los tools desde scripts/update_ai_agent.py.

Pre-requisitos:
  - Connect instance ya creado en la cuenta (script imprime cómo crearlo si falta).
  - IAM con permisos wisdom:* / qconnect:* y connect:CreateIntegrationAssociation.

Uso:
    python scripts/deploy_qconnect.py \\
        --profile <perfil-aws> \\
        --connect-instance-id <connect-instance-id> \\
        [--region us-east-1] \\
        [--assistant-name auna-tatuaje-poc-assistant]

Hace, en orden:
  1. Crea (o reusa) el Q in Connect Assistant.
  2. Asocia el Assistant al Connect instance (Integration Association).
  3. Crea AI Prompt ORCHESTRATION con el contenido de NEW_PROMPT.
  4. Crea AI Agent ORCHESTRATION que apunta al prompt + tools.
  5. Publica versión del prompt y del agent.
  6. Bindea el agent al orchestratorConfigurationList[Connect.SelfService]
     del Assistant — paso CRÍTICO (sin esto, Q in Connect usa SYSTEM default).

Imprime al final los IDs reales que hay que usar en el Contact Flow.
"""

import argparse
import re
import sys
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
TAGS = {
    "project": "auna-tatuaje-poc",
    "env": "poc",
    "aws-apn-id": "pc:55xvhbzjwkkzw9hupxc9n3m2l",
}


def load_prompt_and_tools() -> tuple[str, list]:
    """Extrae NEW_PROMPT y la lista 'tools' del script update_ai_agent.py."""
    src = (ROOT / "scripts" / "update_ai_agent.py").read_text(encoding="utf-8")
    m_prompt = re.search(r'NEW_PROMPT = """(.*?)"""', src, re.DOTALL)
    if not m_prompt:
        raise RuntimeError("No pude encontrar NEW_PROMPT en update_ai_agent.py")
    new_prompt = m_prompt.group(1)
    m_start = src.find("tools = [")
    m_end = src.find("\n]\n", m_start) + 2
    if m_start < 0 or m_end < 0:
        raise RuntimeError("No pude extraer la lista 'tools' de update_ai_agent.py")
    ns: dict = {}
    exec(src[m_start:m_end], ns)
    return new_prompt, ns["tools"]


def ensure_assistant(qc, name: str) -> str:
    for page in qc.get_paginator("list_assistants").paginate():
        for a in page.get("assistantSummaries", []):
            if a["name"] == name:
                print(f"  Assistant '{name}' ya existe: {a['assistantId']}")
                return a["assistantId"]
    print(f"  Creando Assistant '{name}'...")
    r = qc.create_assistant(
        name=name, type="AGENT",
        description="Q in Connect Assistant para PoC Tatuaje Auna (orquesta Valentina con Nova Pro)",
        tags=TAGS,
    )
    return r["assistant"]["assistantId"]


def ensure_integration_association(connect, instance_id: str, assistant_arn: str, region: str):
    paginator = connect.get_paginator("list_integration_associations")
    for page in paginator.paginate(InstanceId=instance_id, IntegrationType="WISDOM_ASSISTANT"):
        for assoc in page.get("IntegrationAssociationSummaryList", []):
            if assoc.get("IntegrationArn") == assistant_arn:
                print(f"  Integration association ya existe")
                return
    print(f"  Asociando Q in Connect al Connect instance...")
    connect.create_integration_association(
        InstanceId=instance_id,
        IntegrationType="WISDOM_ASSISTANT",
        IntegrationArn=assistant_arn,
        Tags=TAGS,
    )


def main() -> int:
    p = argparse.ArgumentParser(description="Deploy Q in Connect del PoC Tatuaje Auna.")
    p.add_argument("--profile", required=True, help="Perfil AWS local")
    p.add_argument("--connect-instance-id", required=True, help="ID del Connect instance")
    p.add_argument("--region", default="us-east-1")
    p.add_argument("--assistant-name", default="auna-tatuaje-poc-assistant")
    p.add_argument("--ai-agent-name", default="auna-valentina-tatuaje")
    p.add_argument("--ai-prompt-name", default="auna-tatuaje-poc-prompt")
    args = p.parse_args()

    sess = boto3.Session(profile_name=args.profile, region_name=args.region)
    sts = sess.client("sts")
    qc = sess.client("qconnect")
    connect = sess.client("connect")

    account_id = sts.get_caller_identity()["Account"]
    connect_arn = f"arn:aws:connect:{args.region}:{account_id}:instance/{args.connect_instance_id}"
    print(f"Account: {account_id}  Region: {args.region}")
    print(f"Connect instance: {args.connect_instance_id}")

    # Validar que el Connect instance existe
    try:
        connect.describe_instance(InstanceId=args.connect_instance_id)
    except ClientError as e:
        print(f"\n[ERROR] El Connect instance {args.connect_instance_id} no existe.")
        print("Crearlo primero con:")
        print(f"  aws connect create-instance --identity-management-type CONNECT_MANAGED \\")
        print(f"    --instance-alias auna-tatuaje-poc-prod \\")
        print(f"    --inbound-calls-enabled --outbound-calls-enabled \\")
        print(f"    --profile {args.profile} --region {args.region}")
        return 1

    new_prompt, tools = load_prompt_and_tools()
    print(f"\nPrompt: {len(new_prompt):,} chars, {len(tools)} tools cargados")

    print("\n[1/5] Q in Connect Assistant...")
    assistant_id = ensure_assistant(qc, args.assistant_name)
    assistant_arn = f"arn:aws:wisdom:{args.region}:{account_id}:assistant/{assistant_id}"

    print("\n[2/5] Asociar Assistant al Connect instance...")
    ensure_integration_association(connect, args.connect_instance_id, assistant_arn, args.region)

    print("\n[3/5] AI Prompt (ORCHESTRATION)...")
    r = qc.create_ai_prompt(
        assistantId=assistant_id,
        name=args.ai_prompt_name,
        type="ORCHESTRATION",
        apiFormat="MESSAGES",
        modelId="us.amazon.nova-pro-v1:0",
        templateConfiguration={
            "textFullAIPromptEditTemplateConfiguration": {"text": new_prompt}
        },
        templateType="TEXT",
        visibilityStatus="PUBLISHED",
        description="Prompt sistema para Valentina - PoC Tatuaje",
        tags=TAGS,
    )
    prompt_id = r["aiPrompt"]["aiPromptId"]
    print(f"  AI Prompt: {prompt_id}")

    r = qc.create_ai_prompt_version(assistantId=assistant_id, aiPromptId=prompt_id)
    prompt_version = r["aiPrompt"]["aiPromptArn"].split(":")[-1]
    prompt_versioned = f"{prompt_id}:{prompt_version}"
    print(f"  Versión: {prompt_versioned}")

    print("\n[4/5] AI Agent (ORCHESTRATION)...")
    r = qc.create_ai_agent(
        assistantId=assistant_id,
        name=args.ai_agent_name,
        type="ORCHESTRATION",
        visibilityStatus="PUBLISHED",
        description="Agente conversacional Valentina - orquesta tools con Nova Pro",
        configuration={
            "orchestrationAIAgentConfiguration": {
                "orchestrationAIPromptId": prompt_versioned,
                "toolConfigurations": tools,
                "connectInstanceArn": connect_arn,
                "locale": "es_US",
            }
        },
        tags=TAGS,
    )
    agent_id = r["aiAgent"]["aiAgentId"]
    print(f"  AI Agent: {agent_id}")

    r = qc.create_ai_agent_version(assistantId=assistant_id, aiAgentId=agent_id)
    agent_version = r["aiAgent"]["aiAgentArn"].split(":")[-1]
    agent_versioned = f"{agent_id}:{agent_version}"
    print(f"  Versión: {agent_versioned}")

    print("\n[5/5] Binding crítico Connect.SelfService (Bug 19 fix)...")
    qc.update_assistant_ai_agent(
        assistantId=assistant_id,
        aiAgentType="ORCHESTRATION",
        configuration={"aiAgentId": agent_versioned},
        orchestratorUseCase="Connect.SelfService",
    )
    print(f"  Binding aplicado")

    print("\n[OK] Q in Connect desplegado:")
    print(f"  Assistant ID:    {assistant_id}")
    print(f"  AI Prompt ID:    {prompt_id}")
    print(f"  AI Agent ID:     {agent_id}")
    print(f"  Prompt versión:  {prompt_versioned}")
    print(f"  Agent versión:   {agent_versioned}")
    print()
    print("Siguientes pasos:")
    print(f"  1. En el Contact Flow inbound + outbound, usar como WisdomAssistantArn:")
    print(f"     {assistant_arn}")
    print(f"  2. En los bloques GetCustomerInput, usar como LexSessionAttributes:")
    print(f"     x-amz-lex:q-in-connect:ai-agent-id = {agent_versioned}")
    print(f"  3. Para iteraciones posteriores del prompt, usar update_ai_agent.py")
    return 0


if __name__ == "__main__":
    sys.exit(main())
