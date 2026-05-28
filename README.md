# PoC Tatuaje Auna — Agente de voz conversacional Valentina

[![AWS](https://img.shields.io/badge/AWS-Connect%20%7C%20Bedrock%20%7C%20Lex%20V2-orange)](https://aws.amazon.com)
[![Python](https://img.shields.io/badge/Python-3.12-blue)](https://www.python.org)
[![Status](https://img.shields.io/badge/Status-Production%20PoC-green)]()

PoC end-to-end de un agente de voz IA conversacional **("Valentina")** que llama a afiliados de Oncosalud, ofrece un chequeo preventivo oncológico gratuito y agenda la cita en caliente sin intervención humana. Construido sobre Amazon Connect + Amazon Lex V2 con Nova Sonic 2 + Amazon Q in Connect con Nova Pro.

---

## Tabla de contenidos

1. [Contexto de negocio](#1-contexto-de-negocio)
2. [Arquitectura](#2-arquitectura)
3. [Stack tecnológico](#3-stack-tecnológico)
4. [Estructura del repositorio](#4-estructura-del-repositorio)
5. [Pre-requisitos](#5-pre-requisitos)
6. [Permisos IAM necesarios](#6-permisos-iam-necesarios)
7. [Tagging obligatorio (AWS Partner Network)](#7-tagging-obligatorio-aws-partner-network)
8. [Despliegue paso a paso](#8-despliegue-paso-a-paso)
9. [Operación — pipeline mensual de llamadas](#9-operación--pipeline-mensual-de-llamadas)
10. [Iterar sobre el prompt o las tools](#10-iterar-sobre-el-prompt-o-las-tools)
11. [Monitoreo y observabilidad](#11-monitoreo-y-observabilidad)

---

## 1. Contexto de negocio

- **Programa Tatuaje** es una iniciativa de Oncosalud para reducir la tasa de abandono de afiliados nuevos durante sus primeros 6 meses (objetivo: bajar de 56,5% a 65% de retención).
- Este repositorio implementa el **frente 1.2 — agente conversacional de voz IA**, parte de un programa más amplio que también incluye 1.1 (limpieza de datos) y 1.3 (modelo de propensión).
- **Volumetría productiva esperada:** ~950 afiliados nuevos por mes; ~548 contactables (con consentimiento=SI).

El agente Valentina:
- Llama al afiliado por teléfono (saliente automático desde S3 → SQS → Step Functions → Amazon Connect).
- Saluda y ofrece el chequeo preventivo oncológico gratuito.
- Si el afiliado acepta, pregunta preferencia de día y horario.
- Consulta disponibilidad real en la API de Multisede de Auna.
- Reproduce las 3 mejores opciones al afiliado.
- Confirma la opción elegida verbalmente.
- Crea la cita en Multisede y se la confirma al afiliado.
- Cierra la llamada cordialmente.

Toda la conversación sucede en español peruano, con voz Nova Sonic 2.

---

## 2. Arquitectura

![Arquitectura](Arquitectura%20V3.png)

### Flujo outbound (productivo)

```
BASE_MARZO.xlsx (cohorte mensual de afiliados)
    │
    ▼ scripts/preprocess_base_marzo.py
       - filtra consentimiento=SI
       - normaliza teléfono (+51, +1, etc.)
       - mapea distrito → centerId Multisede
    │
    ▼ subir CSV
Amazon S3: auna-tatuaje-poc-input-<accountId>
    │ S3 ObjectCreated event
    ▼
Lambda Parser (auna-tatuaje-poc-parser)
    - lee CSV
    - valida DNI + teléfono
    - publica 1 mensaje JSON por afiliado a SQS
    │
    ▼
Amazon SQS (auna-tatuaje-poc-llamadas)
    │
    ▼ EventBridge Pipe (1 msg = 1 ejecución)
AWS Step Functions (auna-tatuaje-poc-flow)
    ├─ ValidarHorario          (Lambda health-check action=check_hours)
    ├─ ConsultarBlacklist      (DynamoDB GetItem)
    ├─ HealthCheck             (Lambda health-check — ping a Multisede)
    ├─ RegistrarInicio         (DynamoDB PutItem)
    └─ IniciarLlamadaConnect   (connect:StartOutboundVoiceContact)
        │
        ▼ afiliado contesta
    Contact Flow auna-tatuaje-poc-outbound
        ├─ set-voice: Lupe
        ├─ invoke-validar (Lambda ValidarPaciente → Multisede)
        ├─ set-q-connect (CreateWisdomSession)
        ├─ get-customer-input (ConnectParticipantWithLexBot)
        │     Lex bot ↔ Q in Connect AI Agent (Nova Pro orquesta tool calls)
        │
        ├── ConsultarDisponibilidad → Lambda → leer opciones (Lupe TTS)
        ├── CrearCita → Lambda → confirmar (Nova Sonic)
        └── COMPLETE → despedir → disconnect
```

### Decisión arquitectural clave: `MessageParticipant` para datos críticos

Nova Pro tiende a **alucinar** fechas, horarios y nombres de doctores cuando se le pide leer datos del tool result. Para eliminar este problema, el contenido devuelto por la Lambda (`opciones_texto_con_pregunta`) se reproduce **directamente con voz Polly Lupe** vía un bloque `MessageParticipant` del Contact Flow, sin pasar por el LLM. Trade-off: durante esos ~15-20s la lectura no es interrumpible, pero garantiza datos correctos.

---

## 3. Stack tecnológico

| Capa | Tecnología |
|------|-----------|
| **Telefonía + Contact Center** | Amazon Connect |
| **STT / TTS conversacional** | Amazon Lex V2 + Amazon Nova Sonic 2 (`amazon.nova-2-sonic-v1:0`) |
| **LLM orquestador** | Amazon Q in Connect + Amazon Nova Pro (`us.amazon.nova-pro-v1:0`) |
| **TTS determinístico** | Amazon Polly Lupe (neural) |
| **Compute serverless** | AWS Lambda (Python 3.12) |
| **Orquestación de workflows** | AWS Step Functions (Standard) |
| **Mensajería** | Amazon SQS + Amazon EventBridge Pipes |
| **Storage** | Amazon S3 (input CSVs), Amazon DynamoDB (interacciones + blacklist) |
| **Secrets** | AWS Secrets Manager |
| **Observabilidad** | Amazon CloudWatch Logs + custom metrics namespace `AunaTatuajePoc` |
| **IaC / Deploy** | Scripts Python con `boto3` (no Terraform / CDK para esta PoC) |
| **API externa** | Multisede UAT (Oncosalud Perú) — REST con JWT |

---

## 4. Estructura del repositorio

```
.
├── README.md                              ← este archivo
├── CLAUDE.md                              ← contexto técnico denso (estado real desplegado)
├── BASE_MARZO_context.md                  ← spec del xlsx mensual de Auna
├── API-Buscar-pacientes-y-citas-documentation.md  ← spec de Multisede API
├── Arquitectura V3.png                            ← diagrama de arquitectura
│
├── lambda/                                ← código de las 5 Lambdas
│   ├── parser/lambda_function.py          ← lee CSV S3 → SQS
│   ├── health_check/lambda_function.py    ← ping Multisede + check_hours
│   ├── validar_paciente/lambda_function.py← search-patient Multisede
│   ├── disponibilidad/lambda_function.py  ← availability + paginación + filtros
│   └── crear_cita/lambda_function.py      ← create appointment + idempotencia
│
├── scripts/                               ← deploy + utilidades
│   ├── deploy_infra.py                    ← DynamoDB + SQS + S3 + IAM + SFN + Pipe + Secrets
│   ├── package_lambdas.py                 ← zip Lambdas + layer
│   ├── deploy_lambdas.py                  ← upload + alias :live
│   ├── deploy_qconnect.py                 ← Q in Connect Assistant + AI Agent + binding
│   ├── update_ai_agent.py                 ← actualizar prompt / tools del agente existente
│   ├── retag_resources.py                 ← auditor de tags (CLI + Lambda handler)
│   ├── deploy_retagger.py                 ← deploy del auditor como Lambda + EventBridge semanal
│   └── preprocess_base_marzo.py           ← xlsx → CSV
│
├── stepfunctions/
│   └── state_machine.json                 ← definición canónica del flow outbound
│
├── docs/
│   ├── arquitectura_tecnica.md            ← profundización técnica
│   ├── permisos_requeridos.md             ← lista detallada de permisos IAM
│   ├── workshop_implementation_guide.md   ← guía de implementación paso a paso
│   ├── instrucciones_consola_nova_sonic.md
│   └── setup_connect_bedrock.md
│
└── data/                                  ← solo dummies (los CSV reales se gitignoran)
    └── afiliados_sample.csv               ← ejemplo con datos ficticios
```

---

## 5. Pre-requisitos

### En la cuenta AWS donde vas a desplegar

- Región **`us-east-1`** (Nova Sonic 2 sólo está disponible ahí al momento de esta PoC).
- Cuotas razonables de Amazon Connect (default ya alcanzan: 1 instance, varios DIDs).
- Acceso a Bedrock con los modelos:
  - `amazon.nova-2-sonic-v1:0`
  - `us.amazon.nova-pro-v1:0`
  (verificar en **Bedrock console → Model access** y habilitarlos si están en "Available to request").

### Localmente

- **Python 3.12+** (`python --version`)
- **AWS CLI v2** configurado con un perfil que tenga los [permisos requeridos](#6-permisos-iam-necesarios)
  ```bash
  aws configure --profile <tu-perfil>
  aws sts get-caller-identity --profile <tu-perfil>
  ```
- Dependencias Python:
  ```bash
  pip install boto3 openpyxl
  ```
- Acceso a la API de **Multisede UAT** (sin VPN; credenciales gestionadas por Auna).

### Credenciales de Multisede

- El equipo de Auna provee usuario y password para Multisede UAT.
- **NO se commitean al repo.** Se cargan en AWS Secrets Manager con el nombre `auna/multisede/credentials` en formato:
  ```json
  {"username": "<usuario>", "password": "<password>"}
  ```

---

## 6. Permisos IAM necesarios

El usuario que ejecute los scripts de deploy necesita estos permisos (resumido — la lista completa está en [docs/permisos_requeridos.md](docs/permisos_requeridos.md)):

- `lambda:*` sobre `auna-tatuaje-poc-*`
- `iam:CreateRole`, `iam:PutRolePolicy`, `iam:PassRole` sobre `auna-tatuaje-poc-*`
- `dynamodb:*` sobre tablas `auna-tatuaje-poc-*`
- `sqs:*` sobre colas `auna-tatuaje-poc-*`
- `s3:*` sobre buckets `auna-tatuaje-poc-*`
- `secretsmanager:CreateSecret`, `GetSecretValue` sobre `auna/multisede/*`
- `states:*` sobre state machines `auna-tatuaje-poc-*`
- `pipes:*`, `events:*` sobre rules `auna-tatuaje-poc-*`
- `connect:*` (instance + flows + asociaciones)
- `lexv2-models:*`, `lexv2-runtime:*` (V2 — NO V1)
- `lex:CreateResourcePolicy`, `lex:UpdateResourcePolicy`, `lex:DeleteBotChannel` (subset de Lex V1 que AWS exige para algunas operaciones de V2)
- `wisdom:*` y/o `qconnect:*`
- `bedrock:InvokeModel`, `bedrock:ListFoundationModels`
- `logs:*` sobre `/aws/lambda/auna-tatuaje-poc-*`, `/aws/connect/auna-tatuaje-poc*`, `/aws/lex/*`
- `iam:CreateServiceLinkedRole` para `connect.amazonaws.com` y `lexv2.amazonaws.com`

---

## 7. Tagging obligatorio (AWS Partner Network)

**TODO** recurso AWS que se cree para esta PoC, en cualquier cuenta (Dev, QA, Prod, cliente o DFX5), debe llevar los siguientes tres tags. **No se deben modificar ni eliminar** — AWS los lee para reportar el spending del partner bajo el programa Partner Revenue Measurement.

| Key | Value | Propósito |
|-----|-------|-----------|
| `project` | `auna-tatuaje-poc` | Trazabilidad interna DFX5 / Auna |
| `env` | `poc` (o `dev` / `qa` / `prod` según corresponda) | Ambiente |
| `aws-apn-id` | `pc:55xvhbzjwkkzw9hupxc9n3m2l` | Tag oficial AWS Partner Network — categoría **CX** (Contact Center). **NO modificar ni borrar.** |

### Tabla de referencia por categoría (para otros proyectos)

Este PoC es categoría **CX** (Contact Center) porque la pieza central es Amazon Connect. Para otros proyectos, AWS provee tags por categoría:

| Categoría del workload | Valor `aws-apn-id` |
|------------------------|--------------------|
| **CX (Contact Center)** ← esta PoC | `pc:55xvhbzjwkkzw9hupxc9n3m2l` |
| AM3 (Application Modernization) | `pc:2970ipijgpa7de0era0brfjst` |
| Data | `pc:9jiunck9pluqu5x7mun2wm8hk` |
| AI/ML | `pc:8qydjzwf0i36m6qgvzu0cphov` |
| GenAI | `pc:62xmwtqn30ir2mz7f9vp4t19s` |
| RDS | `pc:bpvp1zwm0mns1r1fwtfkk2q6z` |
| Fraud Detection | `pc:bdjk48h57gfdp2p9xp2nmnitq` |
| Intelligenix PCA | `pc:1q4gkk3ur7d4dyec2yo55iq2z` |

> El valor lleva el prefijo `pc:` (sin espacios).

### Cómo se aplican

Los scripts del repo (`scripts/deploy_infra.py`, `scripts/deploy_lambdas.py`, `scripts/deploy_qconnect.py`) ya incluyen los tres tags por defecto en la constante `TAGS`. Los ejemplos manuales (`aws connect claim-phone-number`, `aws lexv2-models create-bot`, etc.) que aparecen en §8 también los traen. Si necesitas agregar el tag a recursos pre-existentes sin re-desplegar:

```bash
aws resourcegroupstaggingapi tag-resources \
  --resource-arn-list <ARN1> <ARN2> ... \
  --tags "project=auna-tatuaje-poc" "env=poc" "aws-apn-id=pc:55xvhbzjwkkzw9hupxc9n3m2l" \
  --profile <TU_PERFIL> --region us-east-1
```

Para verificar que todos los recursos del PoC tienen el tag:

```bash
aws resourcegroupstaggingapi get-resources \
  --tag-filters "Key=aws-apn-id,Values=pc:55xvhbzjwkkzw9hupxc9n3m2l" \
  --profile <TU_PERFIL> --region us-east-1 \
  --query "length(ResourceTagMappingList)"
```

> **Nota legal:** DFX5 no recolecta ningún dato a partir de estos tags. AWS los usa exclusivamente para enviarle a DFX5 reportes de spending agregado por partner. Esta cláusula debe incluirse en el SoW del cliente, donde el cliente acepta los tags y se compromete a no modificarlos ni eliminarlos.

### Auditoría semanal automática

Para detectar y corregir recursos que se creen sin el tag (por ejemplo si alguien crea un recurso desde la consola web sin acordarse), el repo incluye un **auditor automático**:

```bash
# Auditoría ad-hoc (solo reporta, no modifica)
python scripts/retag_resources.py --profile <TU_PERFIL>

# Auditoría con corrección automática
python scripts/retag_resources.py --profile <TU_PERFIL> --apply
```

Para que la auditoría corra **semanalmente sin intervención**, hay un script de deploy que monta:

- Lambda `auna-tatuaje-poc-retagger` con el código del auditor
- EventBridge Schedule: cada lunes 9:00 AM hora Perú (14:00 UTC)
- SNS topic `auna-tatuaje-poc-tagging-alerts` que notifica por email si encuentra recursos sin el tag

```bash
# Deploy una sola vez (idempotente)
python scripts/deploy_retagger.py --profile <TU_PERFIL> --notify-email tu@email.com
```

El Lambda corre en modo `--apply` automáticamente, así que si alguien crea un recurso sin tag entre semanas, el lunes siguiente queda corregido y se notifica por email.

> **Trade-off:** este enfoque es reactivo (delay máximo de 7 días). Para preventivo total, migrar el deploy a IaC (Terraform `default_tags` o CloudFormation stack-level `Tags`) — fuera del scope de esta PoC.

---

## 8. Despliegue paso a paso

> Asumiendo cuenta AWS limpia. Reemplazar `<TU_PERFIL>` por el perfil AWS local.
> Si una parte ya existe, los scripts son idempotentes y no fallan.

### 8.1. Infra base (DynamoDB, SQS, S3, Secrets, IAM roles, Step Functions, Pipe)

```bash
python scripts/deploy_infra.py --profile <TU_PERFIL>
```

Output esperado: confirmaciones de creación o "ya existe" para cada recurso, y la lista de IDs/ARNs creados.

### 8.2. Cargar credenciales Multisede en Secrets Manager

```bash
aws secretsmanager put-secret-value \
  --secret-id auna/multisede/credentials \
  --secret-string '{"username":"<usuario>","password":"<password>"}' \
  --profile <TU_PERFIL> --region us-east-1
```

### 8.3. Empaquetar y desplegar las Lambdas

```bash
python scripts/package_lambdas.py
python scripts/deploy_lambdas.py --profile <TU_PERFIL>
```

Esto genera 5 ZIPs en `dist/`, 1 layer compartido `auna-tatuaje-poc-deps:N` con `requests`, sube cada Lambda, publica una versión nueva y apunta alias `:live` a esa versión.

### 8.4. Conectar S3 → Lambda Parser

```bash
# Agregar permission para que S3 invoque la Lambda
aws lambda add-permission \
  --function-name auna-tatuaje-poc-parser \
  --statement-id s3-trigger \
  --action lambda:InvokeFunction \
  --principal s3.amazonaws.com \
  --source-arn arn:aws:s3:::auna-tatuaje-poc-input-<ACCOUNT_ID> \
  --profile <TU_PERFIL>

# Notification config (S3 ObjectCreated:* en prefix=input/ suffix=.csv)
aws s3api put-bucket-notification-configuration \
  --bucket auna-tatuaje-poc-input-<ACCOUNT_ID> \
  --notification-configuration '{
    "LambdaFunctionConfigurations": [{
      "LambdaFunctionArn": "arn:aws:lambda:us-east-1:<ACCOUNT_ID>:function:auna-tatuaje-poc-parser",
      "Events": ["s3:ObjectCreated:*"],
      "Filter": {"Key": {"FilterRules": [
        {"Name": "Prefix", "Value": "input/"},
        {"Name": "Suffix", "Value": ".csv"}
      ]}}
    }]
  }' \
  --profile <TU_PERFIL>
```

### 8.5. Crear Amazon Connect instance

```bash
# Crear el service-linked role primero (una sola vez por cuenta)
aws iam create-service-linked-role --aws-service-name connect.amazonaws.com \
  --custom-suffix AunaTatuajePoc --profile <TU_PERFIL>

# Crear instance
aws connect create-instance \
  --identity-management-type CONNECT_MANAGED \
  --instance-alias auna-tatuaje-poc \
  --inbound-calls-enabled --outbound-calls-enabled \
  --tags project=auna-tatuaje-poc,env=poc,aws-apn-id=pc:55xvhbzjwkkzw9hupxc9n3m2l \
  --profile <TU_PERFIL> --region us-east-1
```

Esperar ~30-60s hasta que `DescribeInstance` devuelva `InstanceStatus: ACTIVE`. Guardá el `Id` que retorna — lo necesitás para los pasos siguientes.

### 8.6. Asociar las Lambdas al Connect instance

```bash
for fn in auna-tatuaje-poc-validar-paciente auna-tatuaje-poc-disponibilidad auna-tatuaje-poc-crear-cita auna-tatuaje-poc-health-check; do
  aws connect associate-lambda-function \
    --instance-id <CONNECT_INSTANCE_ID> \
    --function-arn "arn:aws:lambda:us-east-1:<ACCOUNT_ID>:function:$fn:live" \
    --profile <TU_PERFIL> --region us-east-1
done
```

> ⚠️ **Importante:** usar el qualifier `:live` en el ARN. Si lo asocias sin alias, los Contact Flows que invoquen `<arn>:live` fallarán silenciosamente.

### 8.7. Crear el bot Lex V2 con Nova Sonic 2

```bash
# Crear bot
BOT_ID=$(aws lexv2-models create-bot \
  --bot-name auna-valentina \
  --role-arn "arn:aws:iam::<ACCOUNT_ID>:role/aws-service-role/lexv2.amazonaws.com/AWSServiceRoleForLexV2Bots" \
  --data-privacy childDirected=false \
  --idle-session-ttl-in-seconds 300 \
  --bot-tags project=auna-tatuaje-poc,env=poc,aws-apn-id=pc:55xvhbzjwkkzw9hupxc9n3m2l \
  --profile <TU_PERFIL> --region us-east-1 \
  --query "botId" --output text)

# Crear locale en_US (Nova Sonic 2 sólo está en en_US)
aws lexv2-models create-bot-locale --bot-id $BOT_ID --bot-version DRAFT --locale-id en_US \
  --nlu-intent-confidence-threshold 0.40 \
  --profile <TU_PERFIL> --region us-east-1

# Asignar Nova Sonic 2 como speech foundation model
aws lexv2-models update-bot-locale --bot-id $BOT_ID --bot-version DRAFT --locale-id en_US \
  --nlu-intent-confidence-threshold 0.40 \
  --unified-speech-settings 'speechFoundationModel={modelArn=arn:aws:bedrock:us-east-1::foundation-model/amazon.nova-2-sonic-v1:0,voiceId=feminine}' \
  --profile <TU_PERFIL> --region us-east-1

# Crear 3 intents placeholder (los rellena Q in Connect en runtime)
for intent in ConsultarDisponibilidad CrearCita COMPLETE; do
  aws lexv2-models create-intent --bot-id $BOT_ID --bot-version DRAFT --locale-id en_US \
    --intent-name $intent --sample-utterances "utterance=__qconnect_${intent}__" \
    --profile <TU_PERFIL> --region us-east-1
done

# Build locale
aws lexv2-models build-bot-locale --bot-id $BOT_ID --bot-version DRAFT --locale-id en_US \
  --profile <TU_PERFIL> --region us-east-1

# Publicar versión 1
aws lexv2-models create-bot-version --bot-id $BOT_ID \
  --bot-version-locale-specification 'en_US={sourceBotVersion=DRAFT}' \
  --profile <TU_PERFIL> --region us-east-1

# Crear alias prod apuntando a version 1
ALIAS_ID=$(aws lexv2-models create-bot-alias --bot-id $BOT_ID \
  --bot-alias-name prod --bot-version "1" \
  --bot-alias-locale-settings '{"en_US":{"enabled":true}}' \
  --tags project=auna-tatuaje-poc,env=poc,aws-apn-id=pc:55xvhbzjwkkzw9hupxc9n3m2l \
  --profile <TU_PERFIL> --region us-east-1 \
  --query "botAliasId" --output text)

# Asociar bot al Connect instance
aws connect associate-bot \
  --instance-id <CONNECT_INSTANCE_ID> \
  --lex-v2-bot AliasArn="arn:aws:lex:us-east-1:<ACCOUNT_ID>:bot-alias/$BOT_ID/$ALIAS_ID" \
  --profile <TU_PERFIL> --region us-east-1
```

### 8.8. Desplegar Q in Connect (Assistant + AI Agent + AI Prompt)

```bash
python scripts/deploy_qconnect.py \
  --profile <TU_PERFIL> \
  --connect-instance-id <CONNECT_INSTANCE_ID>
```

El script:
1. Crea el Assistant (`auna-tatuaje-poc-assistant`).
2. Lo asocia al Connect instance.
3. Crea el AI Prompt (ORCHESTRATION, contenido en `update_ai_agent.py`).
4. Crea el AI Agent (ORCHESTRATION con las 3 tools: COMPLETE, ConsultarDisponibilidad, CrearCita).
5. **Bindea el agent al `orchestratorConfigurationList[Connect.SelfService]`** del Assistant — sin esto Q in Connect usa el SYSTEM default y todo el flujo alucina (este es el "Bug 19" documentado en CLAUDE.md).

Anotar los IDs que imprime al final (`assistant_id`, `agent_id`, `prompt_id`) — los necesitás para los Contact Flows y para `update_ai_agent.py`.

### 8.9. Crear los Contact Flows (inbound + outbound)

Esta parte es manual desde la consola de Amazon Connect porque crear flows complejos vía JSON es propenso a errores y la consola los valida en vivo.

La definición canónica de cada flow está en:
- `docs/setup_connect_bedrock.md` — instrucciones bloque a bloque
- `docs/workshop_implementation_guide.md` — guía completa

Resumen de bloques:

**Inbound (`auna-tatuaje-poc-inbound-test`):**
```
SetLoggingBehavior → SetVoice(Lupe) → SetAttributes(dni=740473,center_id=1)
→ InvokeLambdaFunction(validar-paciente:live)
→ SetAttributes(patient_id, holder_name, holder_last_name, clinic_history_number)
→ CreateWisdomSession(<assistant-arn>) → UpdateContactData
→ ConnectParticipantWithLexBot(get-customer-input) ◄────────────┐
   - bot alias: <bot-alias-arn>                                  │
   - localeId: en_US                                             │
   - Text: "Hola, soy Valentina..."                              │
   - LexSessionAttributes: x-amz-lex:q-in-connect:ai-agent-id=<agent-versioned>
→ SetAttributes(tool_name = $.Lex.IntentName)                    │
→ Compare(tool_name):                                            │
    ├ COMPLETE / Escalate → play-farewell → disconnect            │
    ├ ConsultarDisponibilidad → MessageParticipant("Un momento...")
    │     → InvokeLambda(disponibilidad:live)                    │
    │     → SetAttributes(opciones_0_*..opciones_2_*, opciones_texto_con_pregunta)
    │     → MessageParticipant($.Attributes.opciones_texto_con_pregunta)
    │     → ConnectParticipantWithLexBot(get-customer-input-disp) ┘ (loop)
    └ CrearCita → InvokeLambda(crear-cita:live)
          → SetAttributes(cita_exito, cita_mensaje)
          → ConnectParticipantWithLexBot(get-customer-input-crear) → disconnect
```

**Outbound (`auna-tatuaje-poc-outbound`):** estructura idéntica, sin el bloque `SetAttributes(dni=740473,center_id=1)` hardcoded — los attrs vienen del `StartOutboundVoiceContact` que dispara Step Functions.

### 8.10. Claim de número telefónico (DID)

```bash
# Listar DIDs disponibles
aws connect search-available-phone-numbers \
  --target-arn "arn:aws:connect:us-east-1:<ACCOUNT_ID>:instance/<CONNECT_INSTANCE_ID>" \
  --phone-number-country-code PE --phone-number-type DID --max-results 5 \
  --profile <TU_PERFIL>

# Claim uno
aws connect claim-phone-number \
  --target-arn "arn:aws:connect:us-east-1:<ACCOUNT_ID>:instance/<CONNECT_INSTANCE_ID>" \
  --phone-number "+51XXXXXXXXX" \
  --tags project=auna-tatuaje-poc,env=poc,aws-apn-id=pc:55xvhbzjwkkzw9hupxc9n3m2l \
  --profile <TU_PERFIL>

# Asociar al inbound flow para pruebas
aws connect associate-phone-number-contact-flow \
  --instance-id <CONNECT_INSTANCE_ID> \
  --phone-number-id <PHONE_NUMBER_ID> \
  --contact-flow-id <INBOUND_FLOW_ID> \
  --profile <TU_PERFIL>
```

### 8.11. Actualizar la state machine con los IDs reales

La state machine viene con placeholders en `IniciarLlamadaConnect`. Reemplazarlos:

```bash
# Editar stepfunctions/state_machine.json y reemplazar:
#   PLACEHOLDER-CONNECT-INSTANCE-ID  →  <CONNECT_INSTANCE_ID>
#   PLACEHOLDER-CONNECT-FLOW-ID      →  <OUTBOUND_FLOW_ID>
#   +50000000000                     →  +51<DID claimed>

aws stepfunctions update-state-machine \
  --state-machine-arn "arn:aws:states:us-east-1:<ACCOUNT_ID>:stateMachine:auna-tatuaje-poc-flow" \
  --definition file://stepfunctions/state_machine.json \
  --profile <TU_PERFIL>
```

### 8.12. Smoke test end-to-end

```bash
# 1) Health check Lambda
aws lambda invoke --function-name auna-tatuaje-poc-health-check:live \
  --payload '{"action":"ping"}' \
  --profile <TU_PERFIL> --region us-east-1 /tmp/hc.json && cat /tmp/hc.json

# 2) ValidarPaciente con un DNI real de UAT
aws lambda invoke --function-name auna-tatuaje-poc-validar-paciente:live \
  --payload '{"dni":"<DNI_TEST>","center_id":"1"}' \
  --profile <TU_PERFIL> --region us-east-1 /tmp/vp.json && cat /tmp/vp.json

# 3) Llamada inbound real → llamar al DID claimed desde un celular
#    Esperás escuchar a Valentina decir el saludo y responder cuando aceptás.
```

---

## 9. Operación — pipeline mensual de llamadas

Una vez por mes, cuando Auna entrega el archivo `BASE_MARZO.xlsx` (o equivalente para el mes correspondiente):

```bash
# 1) Convertir xlsx → CSV normalizado
python scripts/preprocess_base_marzo.py --input data/BASE_MARZO.xlsx --output dist/afiliados_2026_05.csv

# 2) Subir CSV al bucket S3 — esto dispara el pipeline completo
aws s3 cp dist/afiliados_2026_05.csv s3://auna-tatuaje-poc-input-<ACCOUNT_ID>/input/

# 3) Monitorear ejecuciones de Step Functions
aws stepfunctions list-executions \
  --state-machine-arn "arn:aws:states:us-east-1:<ACCOUNT_ID>:stateMachine:auna-tatuaje-poc-flow" \
  --profile <TU_PERFIL> --region us-east-1 --max-items 20

# 4) Ver resultados en DynamoDB
aws dynamodb scan --table-name auna-tatuaje-poc-interacciones \
  --profile <TU_PERFIL> --region us-east-1
```

---

## 10. Iterar sobre el prompt o las tools

El prompt de Valentina vive en `scripts/update_ai_agent.py` (variable `NEW_PROMPT`). Para iterar:

1. Editar `NEW_PROMPT` y/o la lista `tools`.
2. Setear las variables de entorno con los IDs reales (que te dio `deploy_qconnect.py`):
   ```bash
   export AWS_PROFILE=<TU_PERFIL>
   export QCONNECT_ASSISTANT_ID=<assistant-id>
   export QCONNECT_AI_AGENT_ID=<agent-id>
   export QCONNECT_PROMPT_ID=<prompt-id>
   export CONNECT_INSTANCE_ARN="arn:aws:connect:us-east-1:<ACCOUNT_ID>:instance/<CONNECT_INSTANCE_ID>"
   ```
3. Ejecutar:
   ```bash
   python scripts/update_ai_agent.py
   ```
4. El script publica una versión nueva del prompt y del agent, y re-bindea automáticamente.
5. **Rebuild del bot Lex** para que el alias recoja la nueva versión:
   ```bash
   aws lexv2-models build-bot-locale --bot-id <BOT_ID> --bot-version DRAFT --locale-id en_US \
     --profile <TU_PERFIL> --region us-east-1
   ```
6. Probar con una llamada real al DID inbound.

---

## 11. Monitoreo y observabilidad

| Recurso | Dónde mirar |
|---------|-------------|
| Logs del Contact Flow | CloudWatch → `/aws/connect/auna-tatuaje-poc*` |
| Logs de Lex V2 | CloudWatch → `/aws/lex/auna-valentina` |
| Logs de cada Lambda | CloudWatch → `/aws/lambda/auna-tatuaje-poc-*` |
| Ejecuciones Step Functions | Consola AWS → Step Functions → `auna-tatuaje-poc-flow` |
| Métricas de negocio | CloudWatch → custom namespace `AunaTatuajePoc` |
| Resultados por afiliado | DynamoDB → `auna-tatuaje-poc-interacciones` |
| Blacklist (3 intentos fallidos) | DynamoDB → `auna-tatuaje-poc-blacklist` |

Métricas emitidas:
- `Agendamientos` (Count, dimensión: sede, modelo)
- `Rechazos` (Count, dimensión: motivo)
- `NoElegibles` (Count)
- `SinDisponibilidad` (Count, dimensión: sede)
- `ErroresMultisede` (Count)
- `TMO` (Seconds — tiempo medio operativo por llamada)
- `LlamadasIniciadas` / `LlamadasCompletadas` (Count)

---

## Apéndice: documentos relacionados

- [CLAUDE.md](CLAUDE.md) — contexto técnico denso del estado real desplegado (recomendado leer antes de hacer cambios).
- [docs/arquitectura_tecnica.md](docs/arquitectura_tecnica.md) — profundización en cada componente.
- [docs/permisos_requeridos.md](docs/permisos_requeridos.md) — lista completa de permisos IAM.
- [docs/workshop_implementation_guide.md](docs/workshop_implementation_guide.md) — guía de implementación bloque a bloque.
- [BASE_MARZO_context.md](BASE_MARZO_context.md) — spec del xlsx de cohorte mensual de Auna.
- [API-Buscar-pacientes-y-citas-documentation.md](API-Buscar-pacientes-y-citas-documentation.md) — spec de la API Multisede.
