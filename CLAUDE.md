# CLAUDE.md — PoC Tatuaje Auna v2.1
## Contexto completo del proyecto para Claude Code

> Versión 2.1 — Actualizado post feedback Rubén (DevOps Auna)
> Leer completo antes de hacer cualquier cambio.

---

## 1. CONTEXTO DE NEGOCIO

- **Programa Tatuaje:** Reduce tasa de abandono de afiliados nuevos. Meta: 56.5% → 65% al mes 6.
- **PoC — Tatuaje 1.2:** Agente de voz IA que llama, ofrece chequeo preventivo oncológico gratuito y agenda en caliente sin intervención humana.
- **Frentes:** 1.1 Limpieza datos | **1.2 Agente conversacional (ESTA PoC)** | 1.3 Modelo propensión

---

## 2. ARQUITECTURA v2.1 (post feedback Rubén, DevOps Auna)

### Cambios vs v2
1. **Step Functions = orquestador principal** — no Lambda. Las Lambdas son solo ejecutores.
2. **Lambda Parser** — nueva Lambda con responsabilidad única: leer CSV de S3 y publicar 1 mensaje por afiliado en SQS. Se llamaba "Lambda Orquestador" — nombre incorrecto.
3. **Flujo S3 → Lambda Parser → SQS** — S3 ya no va directo a SQS. Lambda Parser valida, normaliza y publica.
4. **Blacklist = Estado 1 de Step Functions** — Step Functions consulta DynamoDB directamente (sin Lambda extra).
5. **Lambda Acciones dividida en 3 Lambdas especializadas:**
   - `Lambda ValidarPaciente` → search-patient en Multisede
   - `Lambda ConsultarDisponibilidad` → availability + filtro local por centerId
   - `Lambda CrearCita` → create appointment + control de idempotencia
6. **Métricas de negocio** — las Lambdas emiten via `put_metric_data` a CloudWatch directamente. DynamoDB NO alimenta CloudWatch — son destinos independientes.
7. **Idempotencia** — Lambda CrearCita verifica clave compuesta `DNI + cod_campana` en DynamoDB antes de llamar a Multisede. Evita citas duplicadas en retries de SQS.
8. **Ventana horaria** — Step Functions valida horario como Estado 0 antes de procesar. Si está fuera de horario usa `Wait` state hasta el siguiente slot válido.

### Flujo completo actualizado
```
CSV afiliados
    ↓ upload manual
Amazon S3 (auna-tatuaje-poc-input-{account-id})
    ↓ S3 Event → Lambda Parser
Lambda Parser (lee CSV, valida, normaliza, publica 1 msg/afiliado)
    ↓
Amazon SQS (1 mensaje por afiliado, control de concurrencia)
    ↓ lotes controlados
AWS Step Functions (orquestador principal)
    ├─ Estado 0: ¿Horario válido? (L-V 9am-7pm, S 9am-1pm Perú) → Wait si no
    ├─ Estado 1: ¿Número en blacklist DynamoDB? → termina si sí
    ├─ Estado 2: Lambda Health Check → ping API Multisede
    ├─ Estado 3: Si API OK → StartOutboundVoiceContact (Connect)
    └─ Estado 4+: Espera resultado de la llamada
Amazon Connect (AMD habilitado, +57 3150020389)
    ↓ afiliado contesta (persona real)
Amazon Nova Sonic 2 (speech-to-speech nativo, sin Transcribe ni Polly)
    ↓ tool calls cuando afiliado acepta
    ├─→ Lambda ValidarPaciente → search-patient Multisede → put_metric_data
    ├─→ Lambda ConsultarDisponibilidad → availability + filtro centerId → put_metric_data
    └─→ Lambda CrearCita → check idempotencia → create appointment → put_metric_data
         ├─→ DynamoDB interacciones (registro detallado)
         └─→ DynamoDB blacklist (actualiza si fallo)
Amazon CloudWatch (métricas negocio: agendamientos, rechazos, TMO, errores)
AWS Secrets Manager → credenciales Multisede (ext2700/Auna2026)
```

### Comparativa modelos (los 3 se prueban en PoC)
| Modelo | Tipo | Costo/min | Transcribe+Polly |
|--------|------|-----------|-----------------|
| **Nova Sonic 2** ⭐ | Speech-to-speech | ~$0.017/min | ❌ No necesita |
| Nova 2 Lite | LLM texto | < $0.01/min | ✅ Incluido en Connect |
| Claude Sonnet | LLM texto | ~$0.015/min | ✅ Incluido en Connect |

---

## 3. NOMBRES DE RECURSOS AWS

### Lambdas (renombradas en v2.1)
| Lambda | Nombre AWS | Responsabilidad |
|--------|-----------|-----------------|
| Lambda Parser | `auna-tatuaje-poc-parser` | Lee CSV S3 → publica SQS |
| Lambda Health Check | `auna-tatuaje-poc-health-check` | Ping API Multisede |
| Lambda ValidarPaciente | `auna-tatuaje-poc-validar-paciente` | search-patient Multisede |
| Lambda ConsultarDisponibilidad | `auna-tatuaje-poc-disponibilidad` | availability + filtro centerId |
| Lambda CrearCita | `auna-tatuaje-poc-crear-cita` | create appointment + idempotencia |

### Otros recursos
- S3: `auna-tatuaje-poc-input-{account-id}` (lifecycle 7 días)
- SQS: `auna-tatuaje-poc-queue`
- Step Functions: `auna-tatuaje-poc-state-machine`
- DynamoDB: `auna-tatuaje-poc-interacciones` (on-demand)
- DynamoDB: `auna-tatuaje-poc-blacklist` (on-demand)
- Secrets Manager: `auna/multisede/credentials`
- IAM Role: `auna-tatuaje-poc-lambda-role`

---

## 4. CREDENCIALES

### AWS
- Cuenta: pe-auna-consolidado-bi-no-prd | Account ID: 369037400928
- Usuario: gpisonero@dfx5.com | Password: s6NJ26|@
- Región: us-east-1

### API Multisede
- Base URL UAT: https://17x9fh4a33.execute-api.us-east-1.amazonaws.com/uat
- Web UAT: https://uat-agenda.auna.org/
- Usuario: ext2700 | Password: Auna2026 | Token dura: ~19h
- NO requiere VPN
- **BLOCKER:** /availability/v2/pe devuelve 401 — pendiente Alessia

### Número prueba: +573150020389

---

## 5. VARIABLES DE ENTORNO

### Lambda Parser
```
S3_BUCKET_NAME=auna-tatuaje-poc-input-{account-id}
SQS_QUEUE_URL=<URL de la cola SQS>
AWS_REGION=us-east-1
```

### Step Functions (en la definición del estado machine)
```
CONNECT_INSTANCE_ID=<POR LLENAR>
CONNECT_CONTACT_FLOW_ID=<POR LLENAR>
CONNECT_SOURCE_PHONE_NUMBER=+573150020389
DYNAMODB_BLACKLIST_TABLE=auna-tatuaje-poc-blacklist
LLAMADAS_HORA_INICIO=9        # 9am hora Perú (UTC-5) — pendiente confirmar Auna
LLAMADAS_HORA_FIN=19          # 7pm hora Perú
LLAMADAS_DIAS=1,2,3,4,5,6    # Lunes a sábado
MAX_INTENTOS_BLACKLIST=3      # Tras 3 fallos → lista negra
```

### Lambda ValidarPaciente / ConsultarDisponibilidad / CrearCita
```
MULTISEDE_BASE_URL=https://17x9fh4a33.execute-api.us-east-1.amazonaws.com/uat
SECRETS_MULTISEDE_ARN=<ARN secret>
DYNAMODB_TABLE_NAME=auna-tatuaje-poc-interacciones
DYNAMODB_BLACKLIST_TABLE=auna-tatuaje-poc-blacklist
CLOUDWATCH_NAMESPACE=AunaTatuajePoc
MULTISEDE_FUNDER_ID=2
MULTISEDE_SPECIALTY_ID=0        # POR CONFIRMAR (64 o 85)
MULTISEDE_PROVISION_ID=5
MULTISEDE_REASON_PRIVATE_ID=1
MULTISEDE_PAYMENT_METHOD=3
MULTISEDE_VISIT_TYPE_ID=PS
AWS_REGION=us-east-1
```

---

## 6. SCHEMA DYNAMODB

### auna-tatuaje-poc-interacciones (PK: call_id)
```
call_id (PK)         String   UUID por llamada
afiliado_dni         String   DNI del afiliado
afiliado_nombre      String   Nombre completo
telefono             String   +51XXXXXXXXX
sede_referencia      String   centerId de la sede
programa             String   Programa Oncosalud
cuotas_pagadas       String
grupo_cuota          String
cod_campana          String   Para idempotencia (DNI + cod_campana = unique)
connect_contact_id   String   ContactId de Connect
timestamp_inicio     String   ISO 8601
timestamp_fin        String   ISO 8601
tmo_segundos         Number   Duración llamada
resultado            String   iniciando/agendado/rechazo/no_elegible/
                              sin_disponibilidad/error_connect/
                              error_multisede/error_agente/api_caida/
                              fuera_horario/en_blacklist
escucho_speech       Boolean
motivo_rechazo       String
cita_id              String   UUID cita Multisede
sede_agendada        String   Nombre centro
fecha_cita           String
modelo_usado         String   nova-sonic-2/nova-lite/sonnet
error_detalle        String
```

### auna-tatuaje-poc-blacklist (PK: telefono)
```
telefono (PK)        String   Número en lista negra
afiliado_dni         String
motivo               String   bloqueado/rechazo_repetido/numero_invalido
intentos_fallidos    Number
fecha_agregado       String   ISO 8601
activo               Boolean
```

---

## 7. LÓGICA DE IDEMPOTENCIA (Lambda CrearCita)

```python
# Antes de llamar a Multisede, verificar si ya existe cita para este afiliado en esta campaña
def verificar_idempotencia(table, dni, cod_campana):
    response = table.query(
        IndexName='dni-campana-index',
        KeyConditionExpression=Key('afiliado_dni').eq(dni) & Key('cod_campana').eq(cod_campana),
        FilterExpression=Attr('resultado').eq('agendado')
    )
    return len(response['Items']) > 0  # True = ya agendado, no crear duplicado
```

---

## 8. MÉTRICAS CloudWatch (emitidas desde Lambdas via put_metric_data)

```python
# Namespace: AunaTatuajePoc
# Métricas a emitir:
# - Agendamientos        (Count, por sede, por modelo)
# - Rechazos             (Count, con dimensión motivo)
# - NoElegibles          (Count)
# - SinDisponibilidad    (Count, por sede)
# - ErroresMultisede     (Count)
# - TMO                  (Seconds, promedio por llamada)
# - LlamadasIniciadas    (Count)
# - LlamadasCompletadas  (Count)
```

---

## 9. IDs MULTISEDE CONFIRMADOS

| Campo | Valor |
|-------|-------|
| funderId Oncosalud | **2** |
| productId Oncoclasico Pro | **105** (planId=133) |
| productId Oncoplus | **12** (planId=7) |
| productId Oncoflex | **280** (planId=455) |
| benefitId Ambulatoria | **289** (code=0002) |
| specialtyId | **POR CONFIRMAR** (64 o 85) |
| provisionId | **5** |
| reasonPrivateId | **1** |
| paymentMethod | **3** |

### Centers by city (centerId)
Lima: Delgado=4, OC Encalada=9, Guardia Civil=10, OC San Isidro=11,
      Oncocenter=14, Bellavista=15, OC Benavides=8/19, C.B. Independencia=18
Provincias: Arequipa=1, Trujillo=2, Piura=13, Chiclayo=16/17

---

## 10. MANEJO DE ERRORES EN LLAMADA ACTIVA

| Escenario | Comportamiento agente | resultado DynamoDB |
|-----------|----------------------|-------------------|
| Multisede timeout | 3 reintentos (1s,2s,4s) → informa y cierra | error_multisede |
| Sin disponibilidad | Informa y cierra cordialmente | sin_disponibilidad |
| Paciente no encontrado | Informa y cierra | no_elegible |
| API caída (health check) | Step Functions no inicia llamada | api_caida |
| Afiliado rechaza | Cierre cordial, registra motivo | rechazo |
| Fuera de horario | Wait state en Step Functions | fuera_horario |
| En blacklist | Step Functions termina | en_blacklist |
| Cita duplicada (idempotencia) | Step Functions termina sin llamar | ya_agendado |

---

## 11. COSTOS ACTUALIZADOS v2.1

| Servicio | Mensual |
|----------|---------|
| Connect — voz ($0.038/min × 40K min) | $1,520 |
| Connect — telefonía outbound Perú | $268 |
| Connect — DID | $3 |
| **Nova Sonic 2** (recomendado) | **$680** |
| SQS | $0 (free tier) |
| Step Functions | $0.04 (~5,480 transiciones) |
| Lambda (5 funciones) | $0 (free tier) |
| S3 | $0.03 |
| DynamoDB (2 tablas) | $0.28 |
| CloudWatch | $5.52 |
| Secrets Manager | $0.85 |
| **TOTAL con Nova Sonic 2** | **$2,477.72/mes** |
| **TOTAL con Claude Sonnet** | **$1,875.72/mes** |
| **TOTAL con Nova 2 Lite** | **$1,808.72/mes** |

---

## 12. PENDIENTES CRÍTICOS

| # | Pendiente | Quién | Estado |
|---|-----------|-------|--------|
| 1 | Resolver 401 /availability/v2/pe | Alessia | 🔴 BLOCKER |
| 2 | DNIs de prueba en UAT | Alessia | 🔴 BLOCKER |
| 3 | Confirmar specialtyId (64 o 85) | Alessia | 🟡 |
| 4 | Confirmar horario de llamadas | Jennifer/Pamela | 🟡 |
| 5 | Crear instancia Connect + Contact Flow | Gabriel | 🟡 |
| 6 | Crear agente Bedrock Nova Sonic 2 | Gabriel | 🟡 |
| 7 | Implementar Step Functions state machine | Gabriel | 🟡 |
| 8 | Implementar 5 Lambdas separadas | Gabriel | 🟡 |
| 9 | Implementar idempotencia en CrearCita | Gabriel | 🟡 |
| 10 | TTL DynamoDB + retención logs CloudWatch | Gabriel | 🟢 post-PoC |

---

## 13. EQUIPO

### dfx5 + AWS
| Nombre | Rol |
|--------|-----|
| Daniela Rojas | Technical Lead |
| Gabriel | Desarrollador IA |
| Luis Carlos | AWS Account Lead |
| Daniela | Coordinadora |

### Auna
| Nombre | Rol |
|--------|-----|
| Jennifer (Yenifer) | Product Owner |
| Pamela Zúñiga | Operaciones / Speech |
| Alessia | Equipo Multisede / APIs |
| José | Coordinador Técnico |
| Rubén | DevOps / Cloud |
| Marco | Arquitectura / Infraestructura |
| Carlos | Líder técnico Auna |

---

## 14. NOTAS CLAVE

- **HIS** (no GIS) — sistema de historia clínica de Auna
- **No VPN** — confirmado Alessia 18 marzo
- **Nova Sonic 2 = sin Transcribe ni Polly** — speech-to-speech nativo
- **Nova 2 Lite / Sonnet = con Transcribe + Polly** — incluidos en tarifa Connect
- **Coaseguro lo calcula el API** — coInsurance=0, deductible=0 para cita gratuita
- **API Multisede se cae esporádicamente** — health check obligatorio antes de llamar
- **AMD obligatorio** — evita conectar agente a buzones de voz
- **Step Functions como orquestador** — no Lambda. Las Lambdas solo ejecutan acciones.
- **1 mensaje SQS por afiliado** — Lambda Parser es quien parsea el CSV, no SQS

---

## 15. COMANDOS

```bash
# Login Multisede UAT
curl -X POST https://17x9fh4a33.execute-api.us-east-1.amazonaws.com/uat/authentication/v1/login \
  -H "Content-Type: application/json" \
  -d '{"username":"ext2700","password":"Auna2026"}'

# Subir CSV y disparar flujo
aws s3 cp test_10.csv \
  s3://auna-tatuaje-poc-input-369037400928/input/test_10.csv

# Logs en tiempo real
aws logs tail /aws/lambda/auna-tatuaje-poc-parser --follow --region us-east-1
aws logs tail /aws/lambda/auna-tatuaje-poc-validar-paciente --follow --region us-east-1
aws logs tail /aws/lambda/auna-tatuaje-poc-crear-cita --follow --region us-east-1

# Ver Step Functions executions
aws stepfunctions list-executions \
  --state-machine-arn arn:aws:states:us-east-1:369037400928:stateMachine:auna-tatuaje-poc-state-machine \
  --region us-east-1

# Ver DynamoDB
aws dynamodb scan --table-name auna-tatuaje-poc-interacciones --region us-east-1
aws dynamodb scan --table-name auna-tatuaje-poc-blacklist --region us-east-1
```
