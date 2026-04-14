# CLAUDE.md — PoC Tatuaje Auna v2.1
## Contexto completo del proyecto — estado real al 2026-04-14

> Leer completo antes de hacer cualquier cambio. Todo lo que está aquí es el estado REAL desplegado en AWS, verificado directamente contra la cuenta.

---

## 1. CONTEXTO DE NEGOCIO

- **Programa Tatuaje:** Reduce tasa de abandono de afiliados nuevos de Oncosalud. Meta: 56.5% → 65% al mes 6.
- **PoC — Tatuaje 1.2:** Agente de voz IA que llama afiliados, ofrece chequeo preventivo oncológico gratuito y agenda la cita en caliente sin intervención humana.
- **Frentes del programa:** 1.1 Limpieza datos | **1.2 Agente conversacional (ESTA PoC)** | 1.3 Modelo propensión

---

## 2. CUENTA AWS Y RECURSOS GLOBALES

- **Cuenta activa (sandbox PoC):** `769488154338` — perfil `auna-sandbox`
- **Región:** `us-east-1`
- **Usuario:** `gpisonero@dfx5.com`
- **IMPORTANTE:** El CLAUDE.md viejo decía account `369037400928` — eso es incorrecto. Todo está en `769488154338`.

---

## 3. ARQUITECTURA — FLUJO COMPLETO

### Pipeline outbound (produccion real)

```
BASE_MARZO.xlsx
    ↓ scripts/preprocess_base_marzo.py (xlsx->csv, filtra consentimiento=SI,
       normaliza telefono +51, mapea distrito_afil->sede_referencia)
    ↓ upload a S3 (o -s3 flag del script)
Amazon S3: auna-tatuaje-poc-input-769488154338
    ↓ S3 Event
Lambda Parser: auna-tatuaje-poc-parser
    (lee CSV, valida DNI+telefono, publica 1 msg/afiliado a SQS)
    ↓
Amazon SQS: auna-tatuaje-poc-llamadas
    ↓ (1 msg = 1 ejecucion de Step Functions)
AWS Step Functions: auna-tatuaje-poc-flow
    ├─ ValidarHorario (force_run=true para testing lo salta)
    ├─ HealthCheckHorario -> invoca health-check con action=check_hours
    │                        Lambda verifica si estamos en L-V 9-19 o S 9-13 Peru
    ├─ EsHorarioValido (Choice) -> si no, RegistrarFueraHorario -> End
    ├─ ConsultarBlacklist (DynamoDB GetItem auna-tatuaje-poc-blacklist)
    ├─ EvaluarBlacklist -> si activo=true y intentos>=3: RegistrarBlacklist -> End
    ├─ HealthCheck -> invoca health-check (valida API Multisede disponible)
    ├─ EvaluarHealthCheck -> si api_available=false: RegistrarApiCaida -> End
    ├─ RegistrarInicio (DynamoDB PutItem con resultado=iniciando)
    └─ IniciarLlamadaConnect
            arn:aws:states:::aws-sdk:connect:startOutboundVoiceContact
            InstanceId: 4830896a-ec8c-4ee7-9499-de31587fbb36
            ContactFlowId: 202c52df-5497-4e4e-a76d-0e6556308910 (outbound flow)
            SourcePhoneNumber: +5116433701 (PE) — el DID peruano
            DestinationPhoneNumber: $.telefono
            Attributes: { call_id, dni, center_id (de sede_referencia),
                          sede_referencia, programa, nombre_completo,
                          telefono, cod_campana, cuotas_pagadas, grupo_cuota }
            ↓
        RegistrarLlamadaIniciada (DynamoDB UpdateItem connect_contact_id + resultado=en_llamada)
            ↓ (error path)
        RegistrarErrorConnect (DynamoDB UpdateItem con resultado=error_connect + error_detalle)
    ↓ afiliado contesta
Contact Flow: auna-tatuaje-poc-outbound (o inbound-test para llamadas entrantes de prueba)
    ① set-voice: Lupe
    ② (solo inbound-test) set-demo-attrs: dni=740473, center_id=1  ← datos hardcodeados para testing inbound
    ② (outbound) las contact attributes vienen del StartOutboundVoiceContact del Step Functions
    ③ invoke-validar: Lambda ValidarPaciente → guarda patient_id, holder_name
    ④ set-q-connect + set-wisdom-data: asocia Q Connect assistant + AI Agent
    ↓
[get-customer-input] GCI principal — ConnectParticipantWithLexBot
    Text=" " (espacio — $.Attributes.* NO interpola aquí)
    Amazon Lex V2 → Q Connect AI Agent (Nova Pro orquesta, Nova Sonic 2 STT/TTS)
    ↓ tool call → NoMatchingCondition → flow retoma control
[save-tool-name] → [dispatch] Compare tool_name
    │
    ├─ "ConsultarDisponibilidad"
    │       → [invoke-disp] Lambda ConsultarDisponibilidad v12 (pagina, dia_especifico, preferencia_* desde $.Lex.SessionAttributes)
    │          (NOTA: play-espera-disp fue REMOVIDO del path en v40 — Nova Pro habla su propio preámbulo; sin duplicado.)
    │       → [save-disp] guarda en contact attributes: opciones_0_* .. opciones_2_*, hay_mas, opciones_texto_con_pregunta
    │       → [play-opciones] MessageParticipant: lee $.Attributes.opciones_texto_con_pregunta
    │                          (incluye las 3 opciones + "¿Cuál prefiere la 1, la 2 o la 3?")
    │       → [get-customer-input-disp] GCI secundario, Text=" "
    │               ├─ "ConsultarDisponibilidad" (otro filtro o más opciones) → dispatch → play-espera-disp → loop
    │               ├─ "CrearCita" → dispatch → invoke-crear
    │               └─ "COMPLETE" → dispatch → play-farewell → disconnect
    │
    ├─ "CrearCita"
    │       → [invoke-crear] Lambda CrearCita v7 (opcion_elegida=1|2|3)
    │       → [save-crear] guarda resultado de la cita
    │       → [get-customer-input-crear] GCI terciario — Nova Pro confirma cita al afiliado
    │               └─ "COMPLETE" → dispatch → play-farewell → disconnect
    │
    ├─ "COMPLETE" → [play-farewell] MessageParticipant (despedida) → [disconnect]
    └─ "Escalate" → [disconnect]
```

### Regla crítica — interpolación de variables en Connect
- `$.Attributes.*` **NO interpola** en `ConnectParticipantWithLexBot.Text` ni en `LexSessionAttributes` values.
- `$.Attributes.*` **SÍ interpola** en `MessageParticipant.Text` y en `InvokeLambdaFunction.LambdaInvocationAttributes`.
- `$.Lex.SessionAttributes.*` llega como `''` (string vacío) si Nova Pro no lo incluye en el tool call — siempre defender con `or "0"` / `or ""`.
- Por eso `play-opciones` usa `MessageParticipant` (no GCI) para leer las opciones reales de la Lambda.

---

## 4. STACK DE MODELOS IA

| Capa | Modelo | Rol |
|------|--------|-----|
| STT (voz → texto) | Nova Sonic 2 (`amazon.nova-2-sonic-v1:0`) | Speech model del Lex locale en_US |
| Orquestación / LLM | Nova Pro (`us.amazon.nova-pro-v1:0`) | Q Connect AI Agent — razona, decide tools |
| TTS (texto → voz) | Nova Sonic 2 (vía Lex/Connect) | Voz de Valentina al afiliado |

**Nova Pro es necesario** — es el `modelId` del Q Connect AI Agent (orchestration). Nova Sonic solo puede ser speech model del Lex locale en esta arquitectura; no puede ser el orchestration model de Q Connect. Para usar Nova Sonic 2 como cerebro completo habría que sacar Q Connect y hacer un Bedrock Agent nativo — arquitectura completamente diferente.

---

## 5. RECURSOS AWS — IDs REALES (verificados)

### Amazon Connect
- Instance ID: `4830896a-ec8c-4ee7-9499-de31587fbb36`
- Contact Flow INBOUND: `auna-tatuaje-poc-inbound-test` — ID: `cd86706f-68ea-4909-9e73-1fec3024f87d` — **sincronizado a v48** (con set-demo-attrs hardcoded)
- Contact Flow OUTBOUND: `auna-tatuaje-poc-outbound` — ID: `202c52df-5497-4e4e-a76d-0e6556308910` — **sincronizado a v48** (sin set-demo-attrs; contact attributes vienen del StartOutboundVoiceContact API call)
- **Números claimed:**
  - `+5116433701` (PE) — Peru
  - `+576014430375` (CO) — Colombia — "Auna Tatuaje PoC - Colombia"
  - `+18584776876` (US) — "PoC Tatuaje - source outbound"
- Todas las pruebas de esta sesión fueron INBOUND al número Colombia. Peru también es inbound (al mismo flow inbound-test v48).
- Log group: `/aws/connect/auna-tatuaje-poc`

### Amazon Lex V2
- Bot: `auna-valentina-v5` — Bot ID: `EWU1UPLT9U`
- Alias: `TSTALIASID` (TestBotAlias, DRAFT)
- Locale: `en_US` (único locale construido — no es_US)
- Speech model: `amazon.nova-2-sonic-v1:0` (Nova Sonic 2)
- **Rebuild obligatorio** después de cada cambio de versión del AI Agent

### Amazon Q in Connect (Wisdom)
- Assistant ID: `bac452c1-14b3-4252-8c5a-af9e02faca9a`
- AI Agent ID: `680d88d1-66c1-4fa9-b882-d14649de998a`
- AI Agent name: `auna-valentina-tatuaje`
- Prompt ID: `2d469377-a25a-42c2-ad78-44055b5259d3`
- **Versión activa: `:41`** (prompt y agent) — bindeado a `orchestratorConfigurationList[Connect.SelfService]` del assistant. Sin este binding Q Connect usa el SYSTEM default y todo Nova Pro alucina (ver memory Bug 19).
- Modelo LLM: `us.amazon.nova-pro-v1:0`

### Lambdas (todas en alias `:live`)
| Función | Versión :live | Responsabilidad |
|---------|--------------|-----------------|
| `auna-tatuaje-poc-parser` | — | Lee CSV S3 → publica SQS |
| `auna-tatuaje-poc-health-check` | — | Ping API Multisede |
| `auna-tatuaje-poc-validar-paciente` | — | search-patient Multisede |
| `auna-tatuaje-poc-disponibilidad` | **v12** | availability + filtro centerId + paginación + `dia_especifico` (weekday exacto) |
| `auna-tatuaje-poc-crear-cita` | **v8** | create appointment + idempotencia |

### Otros recursos
- S3: `auna-tatuaje-poc-input-769488154338`
- SQS: `auna-tatuaje-poc-llamadas` (nombre real — no "auna-tatuaje-poc-queue")
- Step Functions: `auna-tatuaje-poc-flow` (nombre real — no "auna-tatuaje-poc-state-machine")
- DynamoDB: `auna-tatuaje-poc-interacciones` (on-demand)
- DynamoDB: `auna-tatuaje-poc-blacklist` (on-demand)
- Secrets Manager: `auna/multisede/credentials` (ARN: `arn:aws:secretsmanager:us-east-1:769488154338:secret:auna/multisede/credentials-c23hYV`)
- CloudWatch namespace: `AunaTatuajePoc`
- Log group Lex: `/aws/lex/auna-valentina-v5`

---

## 6. PROCEDIMIENTO DE DEPLOY — ORDEN OBLIGATORIO

Para actualizar el prompt o el AI Agent:
1. Editar `scripts/update_ai_agent.py` (prompt en `NEW_PROMPT`, tools en `tools`)
2. Ejecutar: `python scripts/update_ai_agent.py --profile auna-sandbox`
3. El script publica nueva versión y devuelve el nuevo número (ej: `:38`)
4. En el Contact Flow, actualizar los 3 bloques GCI (`get-customer-input`, `get-customer-input-disp`, `get-customer-input-crear`) — campo `x-amz-lex:q-in-connect:ai-agent-id` con la nueva versión
5. **Rebuild del bot Lex** — sin esto, el alias TSTALIASID sigue usando caché del agente anterior

Los 3 bloques GCI deben tener **siempre el mismo número de versión** del AI Agent.

---

## 7. LAMBDA DISPONIBILIDAD — COMPORTAMIENTO ACTUAL (v11)

- Parámetros: `center_id`, `preferencia_dia` (semana/finde/cualquiera), `preferencia_horario` (manana/tarde/cualquiera), `pagina` (0,1,2,3), `dia_especifico` (lunes..sabado, opcional — si presente tiene precedencia sobre preferencia_dia)
- Paginación: 3 slots por página. `hay_mas=true/false` indica si hay más.
- `pagina` llega como `$.Lex.SessionAttributes.pagina` — defensa obligatoria:
  ```python
  pagina_raw = params.get("pagina", "0") or "0"
  pagina = int(pagina_raw) if pagina_raw.strip().isdigit() else 0
  ```
- Retorna campos expandidos `opciones_N_*` (N=0,1,2) con: `model_id`, `doctor_id`, `doctor_name`, `service_id`, `center_id`, `center_name`, `fecha`, `hora`, `fecha_display`
- Retorna `opciones_texto_con_pregunta` = texto de las 3 opciones + "¿Cuál de estas opciones prefiere, la 1, la 2 o la 3?"
- Usa hora peruana UTC-5 para calcular "hoy" — evita filtrar slots válidos cerca de medianoche UTC
- Variables de entorno reales: `MULTISEDE_SPECIALTY_ID=85`, `MULTISEDE_VISIT_TYPE_ID=PS`, `MULTISEDE_FUNDER_ID=2`, `MULTISEDE_BENEFIT_ID=289`, `MULTISEDE_PROVISION_ID=5`

**Regla general:** Todos los parámetros opcionales que se castean deben tener defensa contra `''` y `None`.

---

## 8. CONTACT FLOW — BLOQUES CLAVE Y DATOS QUE PASAN

### save-disp guarda estos contact attributes:
```
opciones_0_model_id, opciones_0_doctor_id, opciones_0_doctor_name,
opciones_0_service_id, opciones_0_center_id, opciones_0_center_name,
opciones_0_fecha, opciones_0_hora, opciones_0_fecha_display
(ídem para opciones_1_* y opciones_2_*)
hay_mas, pagina_actual, opciones_texto_con_pregunta
```

### invoke-disp pasa a Lambda vía LambdaInvocationAttributes:
```
center_id            = $.Attributes.center_id
pagina               = $.Lex.SessionAttributes.pagina
preferencia_dia      = $.Lex.SessionAttributes.preferencia_dia
preferencia_horario  = $.Lex.SessionAttributes.preferencia_horario
dia_especifico       = $.Lex.SessionAttributes.dia_especifico
```

### invoke-crear pasa a Lambda vía LambdaInvocationAttributes:
```
opcion_elegida = $.Lex.SessionAttributes.opcion_elegida
opciones_0_model_id  .. opciones_2_*  = $.Attributes.opciones_N_*
```

---

## 9. PROMPT VALENTINA — ESTRUCTURA ACTUAL (versión :37)

El prompt completo está en `scripts/update_ai_agent.py` variable `NEW_PROMPT`. Puntos clave:

- Formato obligatorio: toda respuesta al afiliado dentro de `<message>...</message>`
- **PASO 3:** "¿Prefiere la cita **en la semana** o un sábado?" — PROHIBIDO decir "entre semana"
- **PASO 5:** NO decir nada antes de invocar ConsultarDisponibilidad — el flow ya reproduce play-espera-disp
- **PASO 6:** El sistema (play-opciones) ya leyó las opciones — Nova Pro solo pregunta cuál prefiere
- **PASO 8:** Decir mensaje de cierre exitoso ANTES de invocar COMPLETE
- **COMPLETE:** Desconecta automáticamente — NO esperar respuesta del afiliado después
- Paginación: `hay_mas="true"` → invocar con mismos filtros + pagina N+1. Cambio de filtro → siempre pagina=0

### Tools del AI Agent (Return to Control):
| Tool | Parámetros requeridos |
|------|-----------------------|
| `COMPLETE` | `reason` (string) |
| `Escalate` | `escalationReason`, `escalationSummary`, `customerIntent`, `sentiment` |
| `ConsultarDisponibilidad` | `preferencia_dia`, `preferencia_horario` (+ opcional `pagina`) |
| `CrearCita` | `opcion_elegida` (1\|2\|3), `confirmado` (bool) |

---

## 10. BUGS RESUELTOS — NO VOLVER A COMETER

| Bug | Causa raíz | Fix |
|-----|-----------|-----|
| Nova Pro inventaba fechas/doctores | Lambda crasheaba (`pagina=''`) → save-disp nunca ejecutaba | `pagina_raw or "0"` + `.isdigit()` guard en Lambda disponibilidad v11 |
| `$.Attributes.*` vacío en GCI | No interpola en ConnectParticipantWithLexBot.Text | Usar MessageParticipant (`play-opciones`) para leer datos dinámicos |
| Doble "Perfecto, un momento..." | Prompt Y play-espera-disp decían lo mismo | Eliminar del prompt — solo el bloque MessageParticipant lo dice |
| Doble despedida | Prompt esperaba respuesta del afiliado post-COMPLETE | "COMPLETE desconecta automáticamente, no esperes respuesta" |
| Doble "¿Cuál prefiere?" | play-opciones sin pregunta + Nova Pro la repetía | `opciones_texto_con_pregunta` incluye la pregunta; context del GCI dice "no repetir" |
| Solo 3 opciones, "no hay más" | Lambda sin paginación | Parámetro `pagina` + `hay_mas` en Lambda disponibilidad v11 |
| `Faltan campos` en CrearCita | Consecuencia del crash de pagina='' | Fix de Lambda disponibilidad v11 resuelve esto |
| CrearCita 400 — `holderName`/`holderLastName` vacíos | `holder_name` llegaba como `""` cuando no existía como campo separado; fallback viejo solo cubría `holder_last_name` | Lambda crear-cita v8: parsea `nombre_completo` en tres partes (apellido pat, mat, nombre); garantiza que nunca sean string vacío |
| Métrica Agendamientos no se emitía | Dimensión `sede` llegaba como `""` → CloudWatch rechaza | Lambda crear-cita v8: `or "desconocida"` como fallback final en ambos paths (éxito y timeout) |
| Nova Pro avanzaba a ConsultarDisponibilidad con respuesta vaga de horario | Prompt PASO 4 solo decía "si ambiguo → repregunta" sin definir qué cuenta como ambiguo — Nova Pro interpretaba frases vagas como horario confirmado | Prompt :38: lista blanca explícita de palabras válidas para horario; cualquier respuesta fuera de esa lista es ambigua obligatoriamente |

---

## 11. API MULTISEDE

- Base URL UAT: `https://17x9fh4a33.execute-api.us-east-1.amazonaws.com/uat`
- Sin VPN requerida
- Credenciales: `ext2700` / `Auna2026` (en Secrets Manager)
- Token JWT dura ~19h, cacheado en memoria de Lambda

| Endpoint | Uso |
|----------|-----|
| `POST /authentication/v1/login` | Token JWT |
| `GET /patient/v1/pe/search-patient` | Busca por DNI + funderId |
| `GET /insurance-client/v1/pe/{funderId}/{patientId}` | Datos de póliza |
| `GET /availability/v2/pe` | Slots disponibles (hasta 1500 resultados) |
| `POST /appointment/v1/pe` | Crea la cita |

Headers requeridos en todos los requests:
```
Authorization: Bearer {token}
Content-Type: application/json
aws-x-authorization: {token}
aws-x-source: app-000
```

### IDs de negocio Multisede confirmados
| Campo | Valor |
|-------|-------|
| `funderId` Oncosalud | `2` |
| `specialtyId` | `85` (confirmado) |
| `visitTypeId` | `PS` |
| `provisionId` | `5` |
| `reasonPrivateId` | `1` |
| `paymentMethod` | `3` |
| `benefitId` ambulatoria | `289` |

### Centers by city (centerId)
Lima: Delgado=4, OC Encalada=9, Guardia Civil=10, OC San Isidro=11, Oncocenter=14, Bellavista=15, OC Benavides=8/19, C.B. Independencia=18
Provincias: Arequipa=1, Trujillo=2, Piura=13, Chiclayo=16/17

---

## 12. SCHEMA DYNAMODB

### auna-tatuaje-poc-interacciones (PK: call_id)
```
call_id (PK), afiliado_dni, afiliado_nombre, telefono, sede_referencia,
programa, cuotas_pagadas, grupo_cuota, cod_campana, connect_contact_id,
timestamp_inicio, timestamp_fin, tmo_segundos,
resultado: iniciando|agendado|rechazo|no_elegible|sin_disponibilidad|
           error_connect|error_multisede|error_agente|api_caida|fuera_horario|en_blacklist
escucho_speech (Boolean), motivo_rechazo, cita_id, sede_agendada, fecha_cita,
modelo_usado, error_detalle
```

### auna-tatuaje-poc-blacklist (PK: telefono)
```
telefono (PK), afiliado_dni, motivo (bloqueado|rechazo_repetido|numero_invalido),
intentos_fallidos (Number), fecha_agregado, activo (Boolean)
```

---

## 13. VARIABLES DE ENTORNO REALES (Lambda disponibilidad/crear-cita)

```
MULTISEDE_BASE_URL=https://17x9fh4a33.execute-api.us-east-1.amazonaws.com/uat
SECRETS_MULTISEDE_ARN=arn:aws:secretsmanager:us-east-1:769488154338:secret:auna/multisede/credentials-c23hYV
DYNAMODB_TABLE_NAME=auna-tatuaje-poc-interacciones
DYNAMODB_BLACKLIST_TABLE=auna-tatuaje-poc-blacklist
CLOUDWATCH_NAMESPACE=AunaTatuajePoc
MULTISEDE_FUNDER_ID=2
MULTISEDE_SPECIALTY_ID=85
MULTISEDE_BENEFIT_ID=289
MULTISEDE_PROVISION_ID=5
MULTISEDE_REASON_PRIVATE_ID=1
MULTISEDE_PAYMENT_METHOD=3
MULTISEDE_VISIT_TYPE_ID=PS
```

---

## 14. MÉTRICAS CLOUDWATCH

Emitidas desde Lambdas vía `put_metric_data`. Namespace: `AunaTatuajePoc`.
- `Agendamientos` (Count, dim: sede, modelo)
- `Rechazos` (Count, dim: motivo)
- `NoElegibles` (Count)
- `SinDisponibilidad` (Count, dim: sede)
- `ErroresMultisede` (Count)
- `TMO` (Seconds)
- `LlamadasIniciadas` / `LlamadasCompletadas` (Count)

---

## 15. PENDIENTES

| # | Pendiente | Estado |
|---|-----------|--------|
| 1 | CrearCita end-to-end verificado | ✅ Resuelto — Lambda v8 crea citas reales en Multisede UAT (ID confirmado en logs del 14/04) |
| 2 | Step Functions `auna-tatuaje-poc-flow` | ✅ Implementado y con ejecuciones reales — estados: ValidarHorario → ConsultarBlacklist → HealthCheck → RegistrarInicio → IniciarLlamada |
| 3 | "entre semana" vs "en la semana" | 🟡 Parcialmente mitigado en prompt :37. Fix definitivo: mover pregunta a GetParticipantInput de Connect con texto fijo. |
| 4 | Lambda Parser + S3 trigger a SQS | 🟡 Lambda existe pero falta validar trigger S3 → Parser → SQS end-to-end |
| 5 | TTL DynamoDB + retención logs | 🟢 Post-PoC |

---

## 16. EQUIPO

### dfx5 + AWS
| Nombre | Rol |
|--------|-----|
| Daniela Rojas | Technical Lead |
| Gabriel Pisonero | Desarrollador IA |
| Luis Carlos | AWS Account Lead |

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

## 17. COMANDOS ÚTILES

```bash
# Verificar credenciales
aws sts get-caller-identity --profile auna-sandbox

# Deploy prompt + agent
python scripts/update_ai_agent.py

# Logs Lambda en tiempo real
aws logs tail /aws/lambda/auna-tatuaje-poc-disponibilidad --follow --profile auna-sandbox --region us-east-1
aws logs tail /aws/lambda/auna-tatuaje-poc-crear-cita --follow --profile auna-sandbox --region us-east-1

# Invocar Lambda disponibilidad directamente (verificar que funciona)
aws lambda invoke --function-name auna-tatuaje-poc-disponibilidad:live \
  --payload '{"Details":{"Parameters":{"center_id":"1","preferencia_dia":"semana","preferencia_horario":"manana","pagina":"0"},"ContactData":{"Attributes":{}}}}' \
  --profile auna-sandbox --region us-east-1 /tmp/out.json && cat /tmp/out.json

# Ver DynamoDB
aws dynamodb scan --table-name auna-tatuaje-poc-interacciones --profile auna-sandbox --region us-east-1
aws dynamodb scan --table-name auna-tatuaje-poc-blacklist --profile auna-sandbox --region us-east-1

# Login Multisede UAT
curl -X POST https://17x9fh4a33.execute-api.us-east-1.amazonaws.com/uat/authentication/v1/login \
  -H "Content-Type: application/json" \
  -d '{"username":"ext2700","password":"Auna2026"}'

# Step Functions executions
aws stepfunctions list-executions \
  --state-machine-arn arn:aws:states:us-east-1:769488154338:stateMachine:auna-tatuaje-poc-flow \
  --profile auna-sandbox --region us-east-1
```

---

## 18. NOTAS CLAVE

- **HIS** (no GIS) — sistema de historia clínica de Auna
- **No VPN** — acceso a Multisede UAT sin VPN, confirmado
- **Nova Sonic 2** = STT/TTS en Lex. **Nova Pro** = LLM orquestador en Q Connect. Son capas distintas.
- **AMD obligatorio** — evita conectar agente a buzones de voz
- **Step Functions como orquestador** — las Lambdas solo ejecutan acciones puntuales
- **1 mensaje SQS por afiliado** — Lambda Parser parsea el CSV, no SQS directamente
- **Coaseguro lo calcula el API** — coInsurance=0, deductible=0 para cita gratuita
- **API Multisede se cae esporádicamente** — health check obligatorio antes de llamar
- **Rebuild del bot Lex siempre** — sin rebuild, Q Connect usa caché aunque el flow tenga versión nueva
