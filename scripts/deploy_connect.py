"""
deploy_connect.py — Amazon Connect instance + contact flow (pure Bedrock Agent, no Lex)
PoC Tatuaje Auna v2.1

PREREQUISITE (one-time admin action — only needed once per account):
  aws iam create-service-linked-role --aws-service-name connect.amazonaws.com

  Also add this policy to gpisonero@dfx5.com:
    iam:CreateServiceLinkedRole  → arn:aws:iam::369037400928:role/aws-service-role/connect.amazonaws.com/*
    connect:CreateIntegrationAssociation / DeleteIntegrationAssociation → *
    bedrock-agent-runtime:InvokeAgent / InvokeInlineAgent → *

ARCHITECTURE (NO LEX):
  Connect outbound call → OUTBOUND_WHISPER contact flow:
    set-voice (Lupe generative — compatible Nova Sonic 2)
    → invoke-hc       (Lambda health check — falla silenciosa)
    → invoke-validar  (Lambda validar paciente — falla silenciosa si no elegible)
    → set-patient-attrs (copia $.External.* a contact attributes)
    → bedrock-conversation (ConnectParticipantWithBedrockAgent — Valentina)
    → error-msg / disconnect

  El Bedrock Agent "Valentina" (ID: 030MBYFQ3M, Alias: F5SBEZEZGN) maneja
  la conversacion completa con tool calls a las Lambdas.
  Sin Lex, sin Transcribe separado, sin Polly separado.
"""
import boto3, json, time

session = boto3.Session(profile_name="auna-prod", region_name="us-east-1")
connect = session.client("connect")
lc = session.client("lambda")
ACCOUNT = "369037400928"
REGION = "us-east-1"
TAGS = {"project": "auna-tatuaje-poc", "env": "poc"}

HEALTH_CHECK_ARN = f"arn:aws:lambda:{REGION}:{ACCOUNT}:function:auna-tatuaje-poc-health-check"
VALIDAR_ARN = f"arn:aws:lambda:{REGION}:{ACCOUNT}:function:auna-tatuaje-poc-validar-paciente"
BEDROCK_AGENT_ALIAS_ARN = f"arn:aws:bedrock:{REGION}:{ACCOUNT}:agent-alias/030MBYFQ3M/F5SBEZEZGN"

# ─── STEP 1: Create Connect Instance ─────────────────────────────────────────

def create_instance():
    instances = connect.list_instances().get("InstanceSummaryList", [])
    active = [i for i in instances if i.get("InstanceStatus") == "ACTIVE"]
    if active:
        inst_id = active[0]["Id"]
        print(f"Instance EXISTS (ACTIVE): {inst_id}")
        return inst_id

    print("Creating Connect instance auna-tatuaje-poc...")
    r = connect.create_instance(
        IdentityManagementType="CONNECT_MANAGED",
        InstanceAlias="auna-tatuaje-poc",
        InboundCallsEnabled=True,
        OutboundCallsEnabled=True,
    )
    inst_id = r["Id"]
    print(f"Instance ID: {inst_id} — polling...")
    for i in range(36):
        info = connect.describe_instance(InstanceId=inst_id)["Instance"]
        status = info["InstanceStatus"]
        print(f"  [{i*10}s] {status}")
        if status == "ACTIVE":
            break
        if status == "CREATION_FAILED":
            msg = info.get("StatusReason", {}).get("Message", "?")
            raise RuntimeError(f"Connect instance creation failed: {msg}")
        time.sleep(10)

    connect.tag_resource(
        resourceArn=f"arn:aws:connect:{REGION}:{ACCOUNT}:instance/{inst_id}",
        tags=TAGS
    )
    print(f"CREATED: {inst_id}")
    return inst_id


# ─── STEP 2: Associate Lambda Functions + Bedrock Agent ──────────────────────

def associate_lambdas(instance_id):
    for arn in [HEALTH_CHECK_ARN, VALIDAR_ARN]:
        try:
            connect.associate_lambda_function(InstanceId=instance_id, FunctionArn=arn)
            try:
                lc.add_permission(
                    FunctionName=arn.split(":")[-1],
                    StatementId=f"connect-invoke-{instance_id[:8]}",
                    Action="lambda:InvokeFunction",
                    Principal="connect.amazonaws.com",
                    SourceArn=f"arn:aws:connect:{REGION}:{ACCOUNT}:instance/{instance_id}",
                )
            except lc.exceptions.ResourceConflictException:
                pass
            print(f"  Lambda associated: {arn.split(':')[-1]}")
        except Exception as e:
            if "already" in str(e).lower():
                print(f"  Lambda already associated: {arn.split(':')[-1]}")
            else:
                print(f"  Lambda error: {e}")


def associate_bedrock_agent(instance_id):
    """Associate Bedrock Agent with Connect instance (native integration, no Lex)."""
    try:
        connect.create_integration_association(
            InstanceId=instance_id,
            IntegrationType="LAMBDA",  # Some regions use "BEDROCK_AGENT" — try both
            IntegrationArn=BEDROCK_AGENT_ALIAS_ARN,
        )
        print(f"  Bedrock Agent associated (IntegrationType=LAMBDA): {BEDROCK_AGENT_ALIAS_ARN}")
    except Exception as e:
        if "already" in str(e).lower() or "Duplicate" in str(e):
            print(f"  Bedrock Agent already associated")
        else:
            # Try BEDROCK_AGENT type
            try:
                connect.create_integration_association(
                    InstanceId=instance_id,
                    IntegrationType="BEDROCK_AGENT",
                    IntegrationArn=BEDROCK_AGENT_ALIAS_ARN,
                )
                print(f"  Bedrock Agent associated (IntegrationType=BEDROCK_AGENT)")
            except Exception as e2:
                print(f"  Bedrock Agent association error: {e2}")
                print(f"  NOTE: May need to associate manually in Connect console")


# ─── STEP 3: Create Contact Flow — pure Bedrock Agent, no Lex ─────────────────

def build_contact_flow(instance_id):
    flow = {
        "Version": "2019-10-30",
        "StartAction": "set-voice",
        "Metadata": {
            "entryPointPosition": {"x": 20, "y": 20},
            "ActionMetadata": {}
        },
        "Actions": [
            # 1. Voice: Lupe generative (compatible with Nova Sonic 2 S2S)
            {
                "Identifier": "set-voice",
                "Type": "UpdateContactTextToSpeechVoice",
                "Parameters": {"TextToSpeechVoice": "Lupe", "TextToSpeechEngine": "generative"},
                "Transitions": {
                    "NextAction": "invoke-hc",
                    "Errors": [{"NextAction": "silent-disconnect", "ErrorType": "NoMatchingError"}],
                    "Conditions": []
                }
            },
            # 2. Health check — silent fail if API down
            {
                "Identifier": "invoke-hc",
                "Type": "InvokeLambdaFunction",
                "Parameters": {
                    "LambdaFunctionARN": HEALTH_CHECK_ARN,
                    "InvocationTimeLimitSeconds": "8"
                },
                "Transitions": {
                    "NextAction": "invoke-validar",
                    "Errors": [{"NextAction": "silent-disconnect", "ErrorType": "NoMatchingError"}],
                    "Conditions": []
                }
            },
            # 3. Validate patient — silent fail if not eligible
            {
                "Identifier": "invoke-validar",
                "Type": "InvokeLambdaFunction",
                "Parameters": {
                    "LambdaFunctionARN": VALIDAR_ARN,
                    "InvocationTimeLimitSeconds": "8",
                    "LambdaInvocationAttributes": {
                        "dni": "$.Attributes.dni",
                        "center_id": "$.Attributes.center_id"
                    }
                },
                "Transitions": {
                    "NextAction": "set-patient-attrs",
                    "Errors": [{"NextAction": "silent-disconnect", "ErrorType": "NoMatchingError"}],
                    "Conditions": []
                }
            },
            # 4. Copy patient data from External to contact attributes
            {
                "Identifier": "set-patient-attrs",
                "Type": "UpdateContactAttributes",
                "Parameters": {
                    "Attributes": {
                        "holder_name": "$.External.holder_name",
                        "holder_last_name": "$.External.holder_last_name",
                        "patient_id": "$.External.patient_id",
                        "clinic_history_number": "$.External.clinic_history_number",
                    }
                },
                "Transitions": {
                    "NextAction": "bedrock-conversation",
                    "Errors": [{"NextAction": "bedrock-conversation", "ErrorType": "NoMatchingError"}],
                    "Conditions": []
                }
            },
            # 5. Native Bedrock Agent conversation — Valentina handles everything
            {
                "Identifier": "bedrock-conversation",
                "Type": "ConnectParticipantWithBedrockAgent",
                "Parameters": {
                    "AgentAliasArn": BEDROCK_AGENT_ALIAS_ARN,
                    "SessionAttributes": {
                        "dni": "$.Attributes.dni",
                        "center_id": "$.Attributes.center_id",
                        "holder_name": "$.Attributes.holder_name",
                        "holder_last_name": "$.Attributes.holder_last_name",
                        "patient_id": "$.Attributes.patient_id",
                        "clinic_history_number": "$.Attributes.clinic_history_number",
                        "call_id": "$.Attributes.call_id",
                        "programa": "$.Attributes.programa",
                    }
                },
                "Transitions": {
                    "NextAction": "disconnect",
                    "Errors": [
                        {"NextAction": "error-msg", "ErrorType": "NoMatchingError"},
                        {"NextAction": "disconnect", "ErrorType": "NoMatchingCondition"},
                        {"NextAction": "disconnect", "ErrorType": "InputTimeLimitExceeded"},
                    ],
                    "Conditions": []
                }
            },
            # 6. Error message
            {
                "Identifier": "error-msg",
                "Type": "MessageParticipant",
                "Parameters": {
                    "Text": "Disculpe, tuvimos un inconveniente tecnico. "
                            "Nos comunicaremos con usted en otro momento. Hasta luego."
                },
                "Transitions": {
                    "NextAction": "disconnect",
                    "Errors": [{"NextAction": "disconnect", "ErrorType": "NoMatchingError"}],
                    "Conditions": []
                }
            },
            {"Identifier": "silent-disconnect", "Type": "DisconnectParticipant",
             "Parameters": {}, "Transitions": {}},
            {"Identifier": "disconnect", "Type": "DisconnectParticipant",
             "Parameters": {}, "Transitions": {}},
        ]
    }

    # Check if flow already exists
    flows = connect.list_contact_flows(
        InstanceId=instance_id,
        ContactFlowTypes=["OUTBOUND_WHISPER"]
    ).get("ContactFlowSummaryList", [])
    existing = [f for f in flows if f["Name"] == "auna-tatuaje-poc-flow"]

    if existing:
        flow_id = existing[0]["Id"]
        connect.update_contact_flow_content(
            InstanceId=instance_id,
            ContactFlowId=flow_id,
            Content=json.dumps(flow)
        )
        print(f"Flow UPDATED: {flow_id}")
    else:
        r = connect.create_contact_flow(
            InstanceId=instance_id,
            Name="auna-tatuaje-poc-flow",
            Type="OUTBOUND_WHISPER",
            Description="Flujo de llamada saliente Valentina — PoC Tatuaje Auna",
            Content=json.dumps(flow),
            Tags=TAGS,
        )
        flow_id = r["ContactFlowId"]
        print(f"Flow CREATED: {flow_id}")

    return flow_id


# ─── STEP 4: Claim Phone Number ───────────────────────────────────────────────

def claim_phone_number(instance_id):
    existing = connect.list_phone_numbers_v2(
        TargetArn=f"arn:aws:connect:{REGION}:{ACCOUNT}:instance/{instance_id}"
    ).get("ListPhoneNumbersSummaryList", [])

    if existing:
        num = existing[0]["PhoneNumber"]
        print(f"Phone EXISTS: {num}")
        return num

    # Search for available US number
    available = connect.search_available_phone_numbers(
        TargetArn=f"arn:aws:connect:{REGION}:{ACCOUNT}:instance/{instance_id}",
        PhoneNumberCountryCode="US",
        PhoneNumberType="DID",
        MaxResults=1,
    ).get("AvailableNumbersList", [])

    if not available:
        print("No US DID numbers available. Trying toll-free...")
        available = connect.search_available_phone_numbers(
            TargetArn=f"arn:aws:connect:{REGION}:{ACCOUNT}:instance/{instance_id}",
            PhoneNumberCountryCode="US",
            PhoneNumberType="TOLL_FREE",
            MaxResults=1,
        ).get("AvailableNumbersList", [])

    if not available:
        print("No phone numbers available. Claim manually via AWS Console.")
        return None

    number = available[0]["PhoneNumber"]
    r = connect.claim_phone_number(
        TargetArn=f"arn:aws:connect:{REGION}:{ACCOUNT}:instance/{instance_id}",
        PhoneNumber=number,
        Tags=TAGS,
    )
    print(f"Phone CLAIMED: {number}")
    return number


# ─── MAIN ─────────────────────────────────────────────────────────────────────

if __name__ == "__main__":
    print("=" * 60)
    print("PoC Tatuaje Auna — Connect Setup")
    print("=" * 60)

    instance_id = create_instance()
    associate_lambdas(instance_id)
    associate_bedrock_agent(instance_id)
    flow_id = build_contact_flow(instance_id)
    phone = claim_phone_number(instance_id)

    # Update Step Functions state machine with real IDs
    sfn = session.client("stepfunctions")
    SM_ARN = f"arn:aws:states:{REGION}:{ACCOUNT}:stateMachine:auna-tatuaje-poc-state-machine"
    print(f"\nIMPORTANT: Update Step Functions state machine with:")
    print(f"  CONNECT_INSTANCE_ID = '{instance_id}'")
    print(f"  CONNECT_CONTACT_FLOW_ID = '{flow_id}'")
    print(f"  (Edit scripts/deploy_stepfunctions.py and re-run)")

    print(f"\n=== Connect Setup Complete ===")
    print(f"  Instance ID: {instance_id}")
    print(f"  Flow ID:     {flow_id}")
    print(f"  Phone:       {phone}")
    print(f"\nBedrock Agent: arn:aws:bedrock:{REGION}:{ACCOUNT}:agent-alias/030MBYFQ3M/F5SBEZEZGN")
    print(f"Architecture: Connect → Lupe generative → HC → Validar → BedrockAgent (Valentina) → tools")
