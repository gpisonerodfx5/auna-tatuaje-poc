"""
Deploy Step Functions state machine - PoC Tatuaje Auna v2.1

Crea o actualiza la state machine `auna-tatuaje-poc-flow` leyendo la ASL
desde stepfunctions/state_machine.json. Usa el perfil auna-sandbox (cuenta
769488154338) y los IDs reales ya desplegados:
  - Connect instance: 4830896a-ec8c-4ee7-9499-de31587fbb36
  - Contact flow OUTBOUND: 202c52df-5497-4e4e-a76d-0e6556308910
  - SourcePhoneNumber: +5116433701 (PE)

Las IDs estan hardcoded en el state_machine.json. Este script SOLO lo deploya.
"""
import json
import os
import sys
import boto3

BASE_DIR = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
ASL_FILE = os.path.join(BASE_DIR, "stepfunctions", "state_machine.json")

PROFILE = "auna-sandbox"
REGION = "us-east-1"
ACCOUNT = "769488154338"
SM_NAME = "auna-tatuaje-poc-flow"
SFN_ROLE_ARN = f"arn:aws:iam::{ACCOUNT}:role/auna-tatuaje-poc-stepfunctions-role"


def main():
    if not os.path.exists(ASL_FILE):
        print(f"ERROR: ASL file not found: {ASL_FILE}", file=sys.stderr)
        sys.exit(1)

    with open(ASL_FILE, "r", encoding="utf-8") as f:
        asl = json.load(f)

    session = boto3.Session(profile_name=PROFILE, region_name=REGION)
    sfn = session.client("stepfunctions")

    # Check if state machine exists
    r = sfn.list_state_machines()
    existing = [m for m in r.get("stateMachines", []) if m["name"] == SM_NAME]

    asl_json = json.dumps(asl, ensure_ascii=False)

    if existing:
        sm_arn = existing[0]["stateMachineArn"]
        print(f"Updating existing state machine: {sm_arn}")
        sfn.update_state_machine(
            stateMachineArn=sm_arn,
            definition=asl_json,
            roleArn=SFN_ROLE_ARN,
        )
        print("UPDATED")
    else:
        print(f"Creating state machine: {SM_NAME}")
        r = sfn.create_state_machine(
            name=SM_NAME,
            definition=asl_json,
            roleArn=SFN_ROLE_ARN,
            type="STANDARD",
            tags=[
                {"key": "project", "value": "auna-tatuaje-poc"},
                {"key": "env", "value": "sandbox"},
            ],
            loggingConfiguration={"level": "OFF", "includeExecutionData": False, "destinations": []},
        )
        sm_arn = r["stateMachineArn"]
        print(f"CREATED: {sm_arn}")

    print(f"\nState Machine ARN: {sm_arn}")
    print(f"ASL source of truth: {ASL_FILE}")


if __name__ == "__main__":
    main()
