# CLAUDE.md — PoC Tatuaje Auna v3.0
## Estado real del proyecto al 2026-04-29

> Leer completo antes de tocar cualquier cosa. Lo que está aquí es lo que hay desplegado en AWS, verificado contra las cuentas sandbox y Auna. Si algo no coincide, verificar primero antes de actuar.

---

## 1. CONTEXTO DE NEGOCIO

- **Programa Tatuaje:** Reduce la tasa de abandono de afiliados nuevos de Oncosalud. Meta: 56,5% → 65% al mes 6.
- **Frente PoC — Tatuaje 1.2:** Agente de voz IA conversacional ("Valentina") que llama a afiliados nuevos, ofrece un chequeo preventivo oncológico GRATUITO, y agenda la cita en caliente sin intervención humana.
- **Otros frentes (no esta PoC):** 1.1 Limpieza de datos, 1.3 Modelo de propensión.
- **Volumetría productiva esperada:** ~950 afiliados nuevos/mes; ~548 contactables (consentimiento=SI según BASE_MARZO 2026).

---

## 2. CUENTAS AWS Y PERFILES

| Cuenta | ID | Perfil | Uso |
|--------|----|----|-----|
| **Sandbox DFX5** | `769488154338` | `auna-sandbox` | Donde se desarrolló y validó toda la PoC. Tiene Connect, Lex y Q in Connect funcionando end-to-end. |
| **Auna productiva** | `369037400928` | `auna-client` | Cuenta del cliente. Replica de la arquitectura sin agente conversacional aún (pendiente permisos Lex + Q in Connect). |

**Región:** `us-east-1` en ambas. **Usuario IAM:** `gpisonero@dfx5.com`.

---

## 3. ARQUITECTURA — FLUJO COMPLETO (estado actual)

```
BASE_MARZO.xlsx (cohorte mensual)
    ↓ scripts/preprocess_base_marzo.py
       - filtra consentimiento=SI
       - normaliza teléfono (+51 9-dígitos, +1 10-dígitos, etc.)
       - mapea distrito_afil → sede_referencia (centerId)
       - genera CSV listo para subir
    ↓ upload a S3
Amazon S3: auna-tatuaje-poc-input-<accountId>
    ↓ S3 ObjectCreated:* (prefix=input/, suffix=.csv)
Lambda Parser (auna-tatuaje-poc-parser)
    - lee CSV con utf-8-sig
    - valida DNI (6-12 chars) y teléfono
    - publica 1 mensaje JSON por afiliado a SQS
    ↓
Amazon SQS (1 mensaje = 1 afiliado)
    ↓
EventBridge Pipe (auna-tatuaje-poc-sqs-to-sfn)
    ↓ (1 mensaje = 1 ejecución de Step Functions)
AWS Step Functions (state machine)
    ├─ ValidarHorario (force_run=true en payload lo salta — testing)
    ├─ HealthCheckHorario → Lambda health-check action=check_hours
    │                       valida L-V 9-19 o S 9-13 hora Perú
    ├─ EsHorarioValido (Choice) → si no, RegistrarFueraHorario → END
    ├─ ConsultarBlacklist (DynamoDB GetItem, PK=telefono)
    ├─ EvaluarBlacklist → si activo=true Y intentos_fallidos≥3:
    │                     RegistrarBlacklist → END
    ├─ HealthCheck → Lambda health-check (ping API Multisede)
    ├─ EvaluarHealthCheck → si api_available=false:
    │                       RegistrarApiCaida → END
    ├─ RegistrarInicio (DynamoDB PutItem, resultado=iniciando)
    └─ IniciarLlamadaConnect
            arn:aws:states:::aws-sdk:connect:startOutboundVoiceContact
            Attributes: { call_id, dni, center_id, sede_referencia,
                          programa, nombre_completo, telefono,
                          cod_campana, cuotas_pagadas, grupo_cuota }
            ↓
        RegistrarLlamadaIniciada (DynamoDB UpdateItem
                                  connect_contact_id, resultado=en_llamada)
            ↓ (si Connect falla)
        RegistrarErrorConnect (UpdateItem resultado=error_connect + detalle)
    ↓ afiliado contesta
Contact Flow auna-tatuaje-poc-outbound (o inbound-test para llamadas entrantes)
    ① set-voice: Lupe (voz neural compatible Nova Sonic 2)
    ② (sólo inbound-test) set-demo-attrs: dni=740473, center_id=1
       (en outbound los attrs vienen del StartOutboundVoiceContact)
    ③ invoke-validar → Lambda ValidarPaciente (search-patient en Multisede)
       - falla silenciosa si no_elegible (raise → flow va a error path)
    ④ set-patient-attrs: copia patient_id, holder_name, etc. a Contact Attributes
    ⑤ set-q-connect + set-wisdom-data: enlaza el Q in Connect Assistant
    ↓
[get-customer-input] (GCI principal)
    Tipo: ConnectParticipantWithLexBot
    Saludo dentro del Text del GCI:
      "Hola, soy Valentina de Oncosalud. Le llamo porque tiene disponible
       un chequeo preventivo oncológico completamente gratuito.
       ¿Le gustaría agendarlo hoy?"
    Lex bot (Nova Sonic 2 STT/TTS) ↔ Q in Connect AI Agent (Nova Pro orquesta)
    ↓ tool call (Return To Control) → NoMatchingCondition → flow retoma control
[save-tool-name] guarda $.Lex.IntentName en Contact Attribute tool_name
    ↓
[dispatch] Compare Attribute tool_name:
    │
    ├─ "ConsultarDisponibilidad"
    │     → [play-espera-disp] MessageParticipant
    │       "Un momento mientras reviso los horarios disponibles."
    │     → [invoke-disp] Lambda ConsultarDisponibilidad
    │       params (LambdaInvocationAttributes):
    │         center_id, pagina, preferencia_dia, preferencia_horario,
    │         dia_especifico (opcional)
    │     → [save-disp] guarda en Contact Attributes:
    │         opciones_0_*..opciones_2_*, hay_mas, pagina_actual,
    │         opciones_texto_con_pregunta, motivo
    │     → [play-opciones] MessageParticipant
    │       Text=$.Attributes.opciones_texto_con_pregunta
    │       (lee literalmente las 3 opciones reales devueltas por la Lambda)
    │     → [get-customer-input-disp] GCI secundario
    │           ├─ "ConsultarDisponibilidad" (otro filtro o paginación) → loop
    │           ├─ "CrearCita" → invoke-crear
    │           └─ "COMPLETE" → play-farewell → disconnect
    │
    ├─ "CrearCita"
    │     → [invoke-crear] Lambda CrearCita
    │       params: opcion_elegida, opciones_0..2_* (model_id, doctor_id,
    │       service_id, center_id, fecha, hora)
    │     → [save-crear] guarda cita_exito, cita_id, cita_mensaje
    │     → [get-customer-input-crear] GCI terciario
    │           - Nova Pro confirma agendamiento al afiliado
    │           └─ "COMPLETE" → play-farewell → disconnect
    │
    └─ "COMPLETE" → [play-farewell] → [disconnect]
```

### Decisión arquitectural clave: por qué `play-espera-disp` y `play-opciones` son MessageParticipant del flow y no parte del prompt
Nova Pro **alucina** fechas, horarios y nombres de doctores cuando se le pide leer datos del tool result palabra por palabra. La regla de "copia exacta" en el prompt no es 100% confiable. La solución arquitectural es: **el sistema (Contact Flow) reproduce literalmente** el contenido de `opciones_texto_con_pregunta` con voz Lupe, sin pasar por el LLM. Trade-off: durante esos ~15-20s la lectura no es interrumpible (sin barge-in nativo de Nova Sonic), pero garantiza datos correctos.

### Regla crítica — interpolación de variables en Connect
- `$.Attributes.*` **NO interpola** en `ConnectParticipantWithLexBot.Text` ni en `LexSessionAttributes` values.
- `$.Attributes.*` **SÍ interpola** en `MessageParticipant.Text` y en `InvokeLambdaFunction.LambdaInvocationAttributes`.
- `$.Lex.SessionAttributes.*` llega como `''` (string vacío) si Nova Pro no incluye el atributo en el tool call — siempre defender con `or "0"` / `or ""` antes de castear.
- Por eso `play-opciones` usa MessageParticipant para leer datos dinámicos, no un GCI.

---

## 4. STACK DE MODELOS IA

| Capa | Modelo | Rol |
|------|--------|-----|
| STT (voz → texto) | Nova Sonic 2 (`amazon.nova-2-sonic-v1:0`) | Speech model del Lex locale en_US |
| Orquestación / LLM | Nova Pro (`us.amazon.nova-pro-v1:0`) | Modelo del Q in Connect AI Agent — razona, decide tool calls |
| TTS (texto → voz) | Nova Sonic 2 (vía Lex/Connect) | Voz de Valentina al afiliado |
| Voz fija del Contact Flow | Polly Lupe (neural) | `play-espera-disp`, `play-opciones`, `play-farewell` (NO pasan por Nova) |

**Nova Pro es necesario** porque es el `modelId` del Q in Connect AI Agent (orchestration). Nova Sonic sólo puede ser speech model del Lex locale; no puede ser orchestration model de Q in Connect en esta arquitectura. Para usar Nova Sonic 2 como cerebro completo habría que sacar Q in Connect y hacer un Bedrock Agent nativo — arquitectura completamente diferente, con sus propios trade-offs.

---

## 5. RECURSOS AWS — IDs REALES

### 5.1 Cuenta Sandbox DFX5 (`769488154338`) — dónde corre la PoC funcionando

**Amazon Connect**
- Instance ID: `4830896a-ec8c-4ee7-9499-de31587fbb36`
- Contact Flow INBOUND (`auna-tatuaje-poc-inbound-test`): `cd86706f-68ea-4909-9e73-1fec3024f87d`
- Contact Flow OUTBOUND (`auna-tatuaje-poc-outbound`): `202c52df-5497-4e4e-a76d-0e6556308910`
- Números reclamados:
  - `+5116433701` — Perú (DID origen para outbound a Perú)
  - `+576014430375` — Colombia (asociado al inbound flow para pruebas)
  - `+18584776876` — US (uso anterior, no usado activamente)
- Log group: `/aws/connect/auna-tatuaje-poc`

**Amazon Lex V2**
- Bot: `auna-valentina-v5` — Bot ID: `EWU1UPLT9U`
- Alias activo: `TSTALIASID` (TestBotAlias, DRAFT)
- Locale: `en_US` (único locale construido — el speech model Nova Sonic 2 está disponible ahí)
- Speech model: `amazon.nova-2-sonic-v1:0`
- Log group: `/aws/lex/auna-valentina-v5`
- **Rebuild obligatorio** de la locale después de cualquier cambio de versión del AI Agent — sin rebuild el alias sirve la versión cacheada anterior.

**Amazon Q in Connect**
- Assistant ID: `bac452c1-14b3-4252-8c5a-af9e02faca9a`
- AI Agent ID: `680d88d1-66c1-4fa9-b882-d14649de998a` (nombre `auna-valentina-tatuaje`)
- Prompt ID: `2d469377-a25a-42c2-ad78-44055b5259d3`
- **Versión activa actual: `:48`** (revertida en 2026-04-29 al estado committeado en GitHub `8e9e64c` después de iteraciones que rompieron la conversación; las versiones :49-:54 quedaron creadas pero no en uso).
- Binding crítico (Bug 19): el agente DEBE estar bindeado a `orchestratorConfigurationList[Connect.SelfService]` del assistant. Sin este binding, Q in Connect usa su agente SYSTEM default y Nova Pro alucina todo el flujo. El script `scripts/update_ai_agent.py` aplica este binding automáticamente.

**Lambdas (todas con alias `:live`, `requests` inyectado vía layer común)**

| Función | Responsabilidad |
|--------|-----------------|
| `auna-tatuaje-poc-parser` | Lee CSV S3 → publica 1 msg/afiliado a SQS |
| `auna-tatuaje-poc-health-check` | Ping API Multisede + acción `check_hours` para horario laboral PE |
| `auna-tatuaje-poc-validar-paciente` | search-patient Multisede; raise si no elegible |
| `auna-tatuaje-poc-disponibilidad` | availability + filtros centerId/día/horario + paginación + `dia_especifico` |
| `auna-tatuaje-poc-crear-cita` | create appointment Multisede + idempotencia + fallback insurance on-demand |

**Otros recursos sandbox**
- S3: `auna-tatuaje-poc-input-769488154338`
- SQS: `auna-tatuaje-poc-llamadas` (FIFO)
- Step Functions: `auna-tatuaje-poc-flow`
- DynamoDB on-demand: `auna-tatuaje-poc-interacciones` (PK=call_id), `auna-tatuaje-poc-blacklist` (PK=telefono)
- Secrets Manager: `auna/multisede/credentials` → ARN `arn:aws:secretsmanager:us-east-1:769488154338:secret:auna/multisede/credentials-c23hYV`
- CloudWatch namespace de métricas: `AunaTatuajePoc`

### 5.2 Cuenta Auna (`369037400928`) — replica productiva en progreso

Estado al 2026-04-29:

**Tags estándar aplicados a todos los recursos PoC:** `project=auna-tatuaje-poc`, `env=poc`. Tags legacy (Project/Environment/Team/ManagedBy) ya fueron normalizados.

**✅ Desplegado y funcionando:**
- 5 Lambdas idénticas al sandbox, código sincronizado desde el repo, layer compartido `auna-tatuaje-poc-deps:1` (con `requests` py3.12 Linux x86_64), todas con alias `:live` apuntando a versión publicada. Smoke test OK: `validar-paciente` retorna `patient_id=2064555` (GABRIEL GERARDO PISONERO LOPEZ) desde Multisede UAT.
- DynamoDB: `auna-tatuaje-poc-interacciones`, `auna-tatuaje-poc-blacklist` (on-demand).
- SQS: `auna-tatuaje-poc-queue` (nombre legacy, no `-llamadas`).
- S3: `auna-tatuaje-poc-input-369037400928` (con notification S3 → Lambda Parser configurado).
- Step Functions: `auna-tatuaje-poc-state-machine` (nombre legacy, no `-flow`) con definición sincronizada del repo. Connect IDs en `IniciarLlamadaConnect` están como placeholders `PLACEHOLDER-CONNECT-INSTANCE-ID` / `PLACEHOLDER-CONNECT-FLOW-ID` / `+50000000000` — pendiente reemplazar tras crear flows.
- EventBridge Pipe: `auna-tatuaje-poc-sqs-to-sfn` (RUNNING).
- Secrets Manager: `auna/multisede/credentials` → ARN `arn:aws:secretsmanager:us-east-1:369037400928:secret:auna/multisede/credentials-2tFMrn`.
- Amazon Connect instance: `34eef232-49ab-47cf-a766-b3048e3fda2d` (alias `auna-tatuaje-poc-prod` — el alias `auna-tatuaje-poc` está reservado por AWS de un intento anterior). Las 4 Lambdas necesarias por el flow ya están asociadas.

**🗑️ Eliminado (legacy de la arquitectura previa Bedrock Agent):**
- Lambda `auna-tatuaje-poc-dispatcher`.
- Bedrock Agent `auna-tatuaje-poc-valentina` (`030MBYFQ3M`) + alias `valentina-poc` (`F5SBEZEZGN`).

**⏸️ Pendiente — bloqueado por permisos IAM:**
- Bot Lex V2 `auna-valentina` con Nova Sonic 2.
- Q in Connect Assistant + AI Agent + AI Prompt con Nova Pro.
- Contact Flows inbound + outbound (referencian al bot Lex y al Assistant).
- Claim de número telefónico productivo (queda para después del flow).

Email solicitando los permisos faltantes (Lex V2 + Q in Connect / Wisdom + Connect bot association) ya fue armado para enviar a Rubén/Marco del equipo Auna.

---

## 6. PROCEDIMIENTO DE DEPLOY DEL AGENTE

Para actualizar el prompt o las tools del AI Agent (corre contra sandbox por defecto):

1. Editar `scripts/update_ai_agent.py`:
   - `NEW_PROMPT` para el system prompt.
   - Lista `tools` para schemas de tool calls.
2. Ejecutar `python scripts/update_ai_agent.py --profile auna-sandbox`.
3. El script hace, en orden:
   - `update_ai_prompt` + `create_ai_prompt_version` → nueva versión `:N`.
   - `update_ai_agent` (asocia ese prompt) + `create_ai_agent_version` → nueva versión `:N`.
   - `update_assistant_ai_agent(aiAgentType="ORCHESTRATION", orchestratorUseCase="Connect.SelfService")` → bindea al `orchestratorConfigurationList` del assistant. **Sin este paso, Bug 19.**
4. **Rebuild del bot Lex** (`build-bot-locale`) — sin esto el alias `TSTALIASID` sigue sirviendo el agente cacheado.
5. Probar con una llamada real al inbound (número Colombia o Perú).

> Los bloques GCI del Contact Flow NO necesitan tener `x-amz-lex:q-in-connect:ai-agent-id` porque el binding global lo resuelve. (Tener el atributo hardcoded en el GCI sobre-escribe al binding, lo cual era la fuente del Bug 19 antes de descubrir el binding.)

---

## 7. LAMBDA DISPONIBILIDAD — comportamiento

- Parámetros: `center_id`, `preferencia_dia` (semana/sabado/cualquiera), `preferencia_horario` (manana/tarde/cualquiera), `pagina` (0,1,2,...), `dia_especifico` (lunes..sabado, opcional — si presente tiene precedencia sobre preferencia_dia).
- Paginación: 3 slots por página. `hay_mas=true/false`.
- `pagina` llega como `$.Lex.SessionAttributes.pagina` — defensa obligatoria:
  ```python
  pagina_raw = params.get("pagina", "0") or "0"
  pagina = int(pagina_raw) if pagina_raw.strip().isdigit() else 0
  ```
- Retorna campos expandidos `opciones_N_*` (N=0..2): `model_id`, `doctor_id`, `doctor_name`, `service_id`, `center_id`, `center_name`, `fecha`, `hora`, `fecha_display`.
- Retorna `opciones_texto_con_pregunta` listo para reproducirse vía MessageParticipant — incluye las 3 opciones con formato hablado natural y la pregunta final.
- Cuando `disponible=false`, `opciones_texto_con_pregunta` trae un mensaje natural ("Lo siento, no encontré horarios disponibles para [día] [horario]. ¿Quiere intentar con otro día o cambiar el horario?").
- Usa hora peruana UTC-5 para calcular "hoy" — evita filtrar slots válidos cerca de medianoche UTC.

**Regla general:** todo parámetro opcional que se castee debe defender contra `''` y `None` antes de la conversión.

---

## 8. CONTACT FLOW — bloques clave

### `save-disp` (UpdateContactAttributes después de invoke-disp)
Guarda como Contact Attributes:
```
opciones_0_model_id, opciones_0_doctor_id, opciones_0_doctor_name,
opciones_0_service_id, opciones_0_center_id, opciones_0_center_name,
opciones_0_fecha, opciones_0_hora, opciones_0_fecha_display
(idem para opciones_1_* y opciones_2_*)
hay_mas, pagina_actual, opciones_texto_con_pregunta, motivo, disponible
```

### `invoke-disp` (LambdaInvocationAttributes)
```
center_id            = $.Attributes.center_id
pagina               = $.Lex.SessionAttributes.pagina
preferencia_dia      = $.Lex.SessionAttributes.preferencia_dia
preferencia_horario  = $.Lex.SessionAttributes.preferencia_horario
dia_especifico       = $.Lex.SessionAttributes.dia_especifico
```

### `invoke-crear` (LambdaInvocationAttributes)
```
opcion_elegida       = $.Lex.SessionAttributes.opcion_elegida
opciones_0_model_id  ..  opciones_2_*  = $.Attributes.opciones_N_*
patient_id, clinic_history_number, holder_name, holder_last_name,
center_id, dni  = $.Attributes.*
```

---

## 9. PROMPT VALENTINA — estructura actual (versión `:48`)

El prompt completo está en `scripts/update_ai_agent.py` variable `NEW_PROMPT`. Puntos clave:

- Formato obligatorio: toda respuesta dentro de `<message>...</message>`. Texto fuera se considera "razonamiento" y no se vocaliza.
- **PASO 1 (saludo):** ya viene en el `Text` del primer GCI; el primer turno de Nova Pro es procesar la respuesta del afiliado, no saludar.
- **PASO 2 (rechazo inicial):** si dice no, ofrece rellamada.
- **PASO 3 (día):** "¿Tiene algún día en mente, o cualquier día de la semana le sirve?" — PROHIBIDO decir "entre semana"; usar siempre "en la semana".
- **PASO 4 (horario):** lista blanca explícita de palabras válidas (mañana / tarde / temprano / AM / PM…). Cualquier otra respuesta es ambigua.
- **PASO 5 (consultar):** invoca `ConsultarDisponibilidad` directamente; no decir mensaje de espera porque el flow ya reproduce `play-espera-disp`.
- **PASO 6 (leer opciones):** el sistema (`play-opciones`) ya leyó las opciones literalmente; el siguiente `<message>` debe ser vacío o muy corto sin datos. PROHIBIDO repetir fechas/horas/doctores.
- **PASO 7 (confirmar y agendar):** confirma el slot exacto con voz, espera "sí", luego invoca CrearCita.
- **PASO 8 (cierre exitoso):** decir el mensaje de cierre ANTES de invocar COMPLETE.
- **COMPLETE:** desconecta automáticamente — NO esperar respuesta del afiliado después.
- Manejo de silencio escalonado N1→N5 con frases predefinidas; nunca repetir el mensaje anterior ni avanzar el flujo durante silencio.
- Excepción crítica del silencio: durante una espera de tool result, NO disparar el silence handler — es tiempo de procesamiento, no silencio del afiliado.

### Tools del AI Agent (Return To Control)
| Tool | Parámetros |
|------|------------|
| `COMPLETE` | `reason` (string) |
| `ConsultarDisponibilidad` | `preferencia_dia`, `preferencia_horario`, opcional `pagina`, `dia_especifico` |
| `CrearCita` | `opcion_elegida` (1\|2\|3), `confirmado` (bool) |

(El tool `Escalate` fue removido en v43: no hay agentes humanos en la PoC; los pedidos de hablar con persona se manejan vía COMPLETE con reason="pidio_humano".)

---

## 10. BUGS RESUELTOS — historial

| # | Bug | Causa raíz | Fix |
|---|-----|------------|-----|
| 1 | Nova Pro inventaba fechas/doctores | Lambda crasheaba (`pagina=''`) → save-disp nunca corría | Defensa `pagina_raw or "0"` + `.isdigit()` en disponibilidad |
| 2 | `$.Attributes.*` vacío en GCI | No interpola en `ConnectParticipantWithLexBot.Text` | Usar MessageParticipant (`play-opciones`) para datos dinámicos |
| 3 | Doble "Perfecto, un momento…" | Prompt y `play-espera-disp` decían lo mismo | Solo el MessageParticipant lo dice; prompt no |
| 4 | Doble despedida | Prompt esperaba respuesta post-COMPLETE | Regla en prompt: "COMPLETE desconecta automáticamente" |
| 5 | Doble "¿Cuál prefiere?" | `play-opciones` sin pregunta + Nova Pro la repetía | `opciones_texto_con_pregunta` ya incluye la pregunta |
| 6 | Solo 3 opciones, "no hay más" | Lambda sin paginación | Parámetro `pagina` + `hay_mas` |
| 7 | "Faltan campos" en CrearCita | Cascada del crash de `pagina=''` | Fix de Bug 1 lo resolvió |
| 8 | CrearCita 400 — `holderName`/`holderLastName` vacíos | Fallback no cubría todos los casos | Lambda parsea `nombre_completo` en 3 partes; nunca string vacío |
| 9 | Métrica `Agendamientos` no se emitía | Dimensión `sede=""` rechazada por CloudWatch | Fallback `or "desconocida"` |
| 10 | Nova Pro avanzaba con respuesta vaga de horario | Prompt decía "si ambiguo repregunta" sin definir ambiguo | Lista blanca explícita de palabras válidas |
| 11 | Saludo con latencia ~10s | Lambda validar-paciente cargaba póliza (~2s) + cold start | Provisioned Concurrency + remover llamada insurance-client |
| 12 | "Sigue en línea?" disparándose durante tool wait | Silence handler confundía espera de tool con silencio del afiliado | Regla en prompt + arquitectural: `play-espera-disp` reproduce mensaje fijo durante el wait |
| 13 | Nova Pro decía "mayo" cuando Lambda devolvía "abril" | Alucinación irreparable vía prompt — hasta v53 todas las iteraciones fallaron | Arquitectural: `play-opciones` MessageParticipant lee literalmente el campo `opciones_texto_con_pregunta` con voz Lupe; Nova Pro NO lee opciones. |
| 14 | Pipe SQS→SFN: error "Unexpected character ('c')" en InputTemplate | Pipe pasa array no objeto | Quitar InputTemplate; agregar estado `Pass ParseInput` con `InputPath:"$[0]"` (solución previa) o ajustar state machine para aceptar el array (solución actual). |
| 15 | Step Functions: error `Invalid path '$.force_run'` cuando faltaba | Choice usaba BooleanEquals sin chequear presencia | Choice And: `IsPresent=true` + `BooleanEquals=true` |
| 16 | IAM role Step Functions sin `dynamodb:UpdateItem` | Policy faltante | Agregar al inline policy del rol `auna-tatuaje-poc-stepfunctions-role` |
| 17 | Outbound a Colombia falla con `DestinationNotAllowedException` | Quotas Connect outbound a CO no habilitadas en sandbox | Pendiente. Mientras tanto outbound funciona a Perú y US. |
| 18 | Q in Connect ignoraba la versión del agente del Contact Flow | El LexSessionAttribute `x-amz-lex:q-in-connect:ai-agent-id` no es respetado; Q usa el agente bindeado al `orchestratorConfigurationList[Connect.SelfService]` | Bindeo programático en `update_ai_agent.py` |

---

## 11. API MULTISEDE

- Base URL UAT: `https://17x9fh4a33.execute-api.us-east-1.amazonaws.com/uat`
- **Sin VPN requerida.**
- Credenciales: `<MULTISEDE_USERNAME>` / `<MULTISEDE_PASSWORD>` (ver Secrets Manager) (en Secrets Manager de cada cuenta).
- Token JWT dura ~19h, cacheado en memoria del Lambda container.

| Endpoint | Uso |
|----------|-----|
| `POST /authentication/v1/login` | Token JWT |
| `POST /maintainers/v1/search-patient/pe` | Busca paciente por DNI (validar-paciente) |
| `GET /insurance-client/v4/pe/policies` | Datos de póliza (fallback on-demand en crear-cita) |
| `GET /availability/v2/pe` | Slots disponibles (hasta 1500) |
| `POST /appointment/v1/pe` | Crea cita |

Headers obligatorios en todos los requests:
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
| `specialtyId` | `85` |
| `visitTypeId` | `PS` |
| `provisionId` | `5` |
| `reasonPrivateId` | `1` |
| `paymentMethod` | `3` |
| `benefitId` ambulatoria | `289` |

### Centers por ciudad (`centerId`)
- **Lima:** Delgado=4, OC Encalada=9, Guardia Civil=10, OC San Isidro=11, Oncocenter=14, Bellavista=15, OC Benavides=8/19, C.B. Independencia=18.
- **Provincias:** Arequipa=1, Trujillo=2, Piura=13, Chiclayo=16/17.

---

## 12. SCHEMA DYNAMODB

### `auna-tatuaje-poc-interacciones` (PK: call_id, on-demand)
```
call_id (PK), afiliado_dni, afiliado_nombre, telefono, sede_referencia,
programa, cuotas_pagadas, grupo_cuota, cod_campana, connect_contact_id,
timestamp_inicio, timestamp_fin, tmo_segundos,
resultado: iniciando | en_llamada | agendado | rechazo | no_elegible
         | sin_disponibilidad | error_connect | error_multisede
         | error_agente | api_caida | fuera_horario | en_blacklist
escucho_speech (Bool), motivo_rechazo, cita_id, sede_agendada,
fecha_cita, modelo_usado, error_detalle
```

### `auna-tatuaje-poc-blacklist` (PK: telefono, on-demand)
```
telefono (PK), afiliado_dni,
motivo: bloqueado | rechazo_repetido | numero_invalido,
intentos_fallidos (Number), fecha_agregado, activo (Bool)
```

---

## 13. VARIABLES DE ENTORNO LAMBDA (sandbox; en Auna cambian los ARNs de cuenta)

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
SQS_QUEUE_URL=https://sqs.us-east-1.amazonaws.com/<acct>/auna-tatuaje-poc-llamadas (sólo parser)
```

En Auna: account `369037400928`, secret ARN `auna/multisede/credentials-2tFMrn`, SQS `auna-tatuaje-poc-queue` (nombre legacy).

---

## 14. MÉTRICAS CLOUDWATCH

Namespace: `AunaTatuajePoc`. Emitidas vía `put_metric_data` desde las Lambdas.

| Métrica | Unidad | Dimensiones |
|---------|--------|-------------|
| `Agendamientos` | Count | sede, modelo |
| `Rechazos` | Count | motivo |
| `NoElegibles` | Count | — |
| `SinDisponibilidad` | Count | sede |
| `ErroresMultisede` | Count | — |
| `TMO` | Seconds | — |
| `LlamadasIniciadas` / `LlamadasCompletadas` | Count | — |

---

## 15. COSTOS — modelo operativo

Pricing AWS us-east-1, abril 2026, lista pública.

### Componentes
| Servicio | Tarifa | Tipo |
|----------|--------|------|
| Amazon Connect voz | USD 0,018 / min | variable (por minuto) |
| Telefonía saliente Perú (DID origen) | USD 0,022 / min | variable |
| Nova Sonic 2 (STT+TTS) | USD 0,034 / min | variable |
| Q in Connect (Nova Pro) | USD 0,016/sesión + USD 0,005/turno | por llamada conectada (~6 turnos) |
| DID Perú | USD 3 / mes | fijo |
| Secrets Manager + S3 + DDB + Lambdas + SFN + SQS + Pipe + CW | ~USD 12 / mes | casi fijo |

### Escenarios (cohortes mensuales)
Supuestos: 55% contact rate, 1,8 marcaciones promedio por afiliado, 25% AMD, TMO conectada ~4 min, AMD ~9s, no-contesta ~25s.

| Escenario | Contactables | Min voz | Costo / mes | $ / contactable |
|-----------|--------------|---------|-------------|-----------------|
| Media cohorte | 275 | 710 | USD 69 | 0,26 |
| **Base BASE_MARZO** | **548** | **1.420** | **USD 130** | **0,24** |
| Doble cohorte | 1.100 | 2.841 | USD 250 | 0,23 |
| Campaña masiva (×5) | 2.740 | 7.103 | USD 611 | 0,23 |
| Extensión nacional (×10) | 5.500 | 14.207 | USD 1.214 | 0,22 |

**Lecturas clave:**
- ~93% del costo total son los 4 componentes IA+telefonía (Sonic, telco, Connect, Q in Connect).
- Costos de infra base (Lambdas + DDB + SFN + SQS + Pipe) suman <USD 7/mes incluso a 10× volumen.
- Escala casi linealmente; no hay quiebres de precio significativos.
- Cada minuto recortado al TMO ahorra ~USD 22/mes en escenario base.

---

## 16. PIPELINE DE DESPLIEGUE / SCRIPTS DEL REPO

```
scripts/
├── preprocess_base_marzo.py    # xlsx → CSV normalizado
├── update_ai_agent.py          # prompt + tools + Connect.SelfService binding
├── deploy_connect.py           # Connect instance + flows + Lambda associations
├── (otros scripts utilitarios)

lambda/
├── parser/lambda_function.py
├── health_check/lambda_function.py
├── validar_paciente/lambda_function.py
├── disponibilidad/lambda_function.py
└── crear_cita/lambda_function.py

stepfunctions/
└── state_machine.json          # definición canonical del flow

connect/
├── inbound_flow.json           # contact flow inbound-test
└── outbound_flow.json          # contact flow outbound

docs/
├── arquitectura_tecnica.md
├── permisos_requeridos.md
├── workshop_implementation_guide.md
└── ...
```

---

## 17. EQUIPO

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
| Carlos | Líder técnico |

---

## 18. COMANDOS ÚTILES

```bash
# Verificar credenciales
aws sts get-caller-identity --profile auna-sandbox    # cuenta DFX5
aws sts get-caller-identity --profile auna-client     # cuenta Auna

# Deploy prompt + agent + Connect.SelfService binding
python scripts/update_ai_agent.py

# Rebuild bot Lex (después de actualizar agente)
aws lexv2-models build-bot-locale --bot-id EWU1UPLT9U --bot-version DRAFT \
  --locale-id en_US --profile auna-sandbox --region us-east-1

# Logs Lambda en tiempo real
aws logs describe-log-streams --log-group-identifier \
  arn:aws:logs:us-east-1:<acct>:log-group:/aws/lambda/auna-tatuaje-poc-disponibilidad \
  --order-by LastEventTime --descending --max-items 1 \
  --profile <perfil> --region us-east-1

# Invocar Lambda disponibilidad directamente
aws lambda invoke --function-name auna-tatuaje-poc-disponibilidad:live \
  --payload '{"Details":{"Parameters":{"center_id":"1","preferencia_dia":"semana","preferencia_horario":"manana","pagina":"0"},"ContactData":{"Attributes":{}}}}' \
  --profile auna-sandbox --region us-east-1 /tmp/out.json && cat /tmp/out.json

# Smoke test validar-paciente (DNI Gabriel)
aws lambda invoke --function-name auna-tatuaje-poc-validar-paciente:live \
  --payload '{"dni":"740473","center_id":"1"}' \
  --profile auna-client --region us-east-1 /tmp/vp.json && cat /tmp/vp.json

# Scan DynamoDB
aws dynamodb scan --table-name auna-tatuaje-poc-interacciones \
  --profile auna-sandbox --region us-east-1

# Multisede UAT login (token de prueba)
curl -X POST https://17x9fh4a33.execute-api.us-east-1.amazonaws.com/uat/authentication/v1/login \
  -H "Content-Type: application/json" \
  -d '{"username":"<USERNAME>","password":"<PASSWORD>"}'

# Step Functions executions recientes
aws stepfunctions list-executions \
  --state-machine-arn arn:aws:states:us-east-1:769488154338:stateMachine:auna-tatuaje-poc-flow \
  --profile auna-sandbox --region us-east-1 --max-items 10
```

---

## 19. PENDIENTES

| # | Pendiente | Estado |
|---|-----------|--------|
| 1 | Permisos Lex V2 + Q in Connect (`qconnect:*`, `wisdom:*`, `lexv2-models:*`) en cuenta Auna | 🔴 Email enviado a Rubén/Marco |
| 2 | Crear bot Lex + Q assistant + AI Agent + Prompt en cuenta Auna | ⏸️ Bloqueado por #1 |
| 3 | Crear Contact Flows inbound + outbound en cuenta Auna y reemplazar placeholders en state machine | ⏸️ Bloqueado por #2 |
| 4 | Claim de DID productivo Perú en cuenta Auna y asociar al outbound flow | ⏸️ Bloqueado por #3 |
| 5 | Outbound a Colombia (DestinationNotAllowedException) | 🟡 Quotas Connect — no urgente, sandbox usa Perú |
| 6 | TTL DynamoDB + retención de logs | 🟢 Post-PoC |
| 7 | "entre semana" vs "en la semana" — fix definitivo via GetParticipantInput de Connect con texto fijo | 🟡 Mitigado via prompt; mejora opcional |

---

## 20. NOTAS CLAVE / GOTCHAS

- **HIS** (no GIS) — sistema de historia clínica de Auna.
- **No VPN** para Multisede UAT.
- **Nova Sonic 2 = STT/TTS** en Lex; **Nova Pro = LLM orquestador** en Q in Connect. Capas distintas.
- **AMD obligatorio** en Connect — evita conectar el agente a buzones de voz.
- **Step Functions como orquestador** — las Lambdas sólo ejecutan acciones puntuales.
- **1 mensaje SQS = 1 afiliado** — el Parser parsea el CSV completo, SQS no.
- **API Multisede tiene caídas esporádicas** — health-check obligatorio antes de iniciar llamada.
- **Coaseguro lo calcula el API** — pasar `coInsurance=0`, `deductible=0` para cita gratuita.
- **Rebuild del bot Lex SIEMPRE** después de cambiar el AI Agent — sin rebuild, alias usa caché viejo.
- **Bug 19** — el binding `orchestratorConfigurationList[Connect.SelfService]` es lo que decide qué versión del AI Agent se usa, NO el LexSessionAttribute del flow. Sin binding → Q in Connect usa SYSTEM default → Nova Pro alucina.
- **Tags estándar:** `project=auna-tatuaje-poc`, `env=poc`. Tags legacy de la cuenta Auna ya fueron normalizados.
- **Cuentas distintas:** sandbox `769488154338` vs Auna `369037400928`. Verificar con `aws sts get-caller-identity` antes de cualquier operación destructiva.
