# Arquitectura Técnica — PoC Tatuaje Auna v2.1
## Agente de Voz IA para Agendamiento Oncológico

> Última actualización: abril 2026  
> Ambiente: AWS us-east-1 — Cuenta sandbox `769488154338`

---

## Resumen ejecutivo

Sistema de voz outbound que llama afiliados de Oncosalud, ofrece un chequeo preventivo oncológico gratuito y agenda la cita en tiempo real sin intervención humana. El agente de voz IA ("Valentina") conduce la conversación en español peruano, consulta disponibilidad real en la API de Multisede y confirma el agendamiento durante la misma llamada.

---

## Diagrama de arquitectura

```
CSV afiliados
    │ upload manual S3
    ▼
Amazon S3
auna-tatuaje-poc-input-{account-id}
    │ S3 Event
    ▼
Lambda Parser
auna-tatuaje-poc-parser
Lee CSV, valida, publica 1 msg/afiliado en SQS
    │
    ▼
Amazon SQS
auna-tatuaje-poc-queue
    │ lotes controlados
    ▼
AWS Step Functions
auna-tatuaje-poc-state-machine
    ├─ Estado 0: Ventana horaria válida? (L-V 9am-7pm, S 9am-1pm Perú)
    │             └─ No → Wait hasta próximo slot
    ├─ Estado 1: ¿Número en blacklist DynamoDB?
    │             └─ Sí → termina
    ├─ Estado 2: Lambda HealthCheck → ping API Multisede
    │             └─ API caída → termina con resultado api_caida
    └─ Estado 3: StartOutboundVoiceContact → Amazon Connect
                  │
                  ▼
Amazon Connect (+18584776876 / +576014430375)
AMD habilitado — descarta buzones de voz
    │ afiliado contesta
    ▼
Contact Flow: auna-tatuaje-poc-inbound-test
    │
    ├─ [set-voice] Lupe, Generative, es-US
    ├─ [set-demo-attrs] dni=740473, center_id=1
    ├─ [invoke-validar] Lambda ValidarPaciente → patient_id, holder_name, clinic_history_number
    ├─ [set-patient-attrs] guarda resultado en contact attributes
    ├─ [set-q-connect] CreateWisdomSession → asocia Q in Connect assistant + AI agent
    ├─ [set-wisdom-data] UpdateContactData con SessionArn
    │
    └─ [get-customer-input] ConnectParticipantWithLexBot ← bucle principal
            │ AMAZON.QinConnectIntent + Enable AI Agent ON
            │
            ▼
    Amazon Lex V2 (auna-valentina-v5)
    locale: es_US — speech model: Amazon Nova Sonic
            │
            ▼
    Amazon Q in Connect — AI Agent (Orchestration)
    "Valentina" — LLM: Nova Pro (us.amazon.nova-pro-v1:0)
    Prompt :37, Agent :37 — tools: ConsultarDisponibilidad, CrearCita, COMPLETE, Escalate
    [voz via Nova Sonic 2 — STT/TTS en Lex locale]
            │
            │ tool call → NoMatchingCondition → Contact Flow retoma control
            ▼
    [save-tool-name] → [dispatch] Compare tool_name
            │
            ├─ "ConsultarDisponibilidad"
            │       ├─ [play-espera-disp] MessageParticipant "Perfecto, un momento mientras reviso..."
            │       ├─ [invoke-disp] Lambda ConsultarDisponibilidad (pasa pagina=$.Lex.SessionAttributes.pagina)
            │       ├─ [save-disp] guarda opciones_N_*, hay_mas, pagina_actual, opciones_texto_con_pregunta
            │       ├─ [play-opciones] MessageParticipant lee $.Attributes.opciones_texto_con_pregunta (incluye "¿Cuál prefiere la 1, 2 o 3?")
            │       └─ [get-customer-input-disp] GCI secundario (Text=" "), contexto: no repetir pregunta
            │               ├─ "CrearCita"   → dispatch → invoke-crear
            │               ├─ "ConsultarDisponibilidad" (otro filtro o más opciones) → dispatch → play-espera-disp → invoke-disp (loop)
            │               └─ "COMPLETE"   → dispatch → play-farewell → disconnect
            │
            ├─ "CrearCita"
            │       ├─ [invoke-crear] Lambda CrearCita
            │       ├─ [save-crear] contact attributes con resultado
            │       └─ [get-customer-input-crear] GCI terciario (Nova Pro confirma cita)
            │               └─ "COMPLETE" → dispatch → play-farewell → disconnect
            │
            ├─ "COMPLETE" → [play-farewell] MessageParticipant → [disconnect]
            └─ "Escalate"  → [disconnect]
                    │
    Lambda ValidarPaciente ──────────────────────┐
    Lambda ConsultarDisponibilidad ──────────────┤──► API Multisede (UAT)
    Lambda CrearCita ────────────────────────────┘    https://17x9fh4a33.execute-api.us-east-1.amazonaws.com/uat
                    │
                    ├──► DynamoDB auna-tatuaje-poc-interacciones (registro por llamada)
                    ├──► DynamoDB auna-tatuaje-poc-blacklist (control de reintentos)
                    └──► CloudWatch (métricas de negocio)
```

---

## Servicios AWS utilizados

### Amazon Connect
- **Propósito:** Plataforma de contact center cloud. Gestiona la llamada de voz entrante/saliente, AMD (Answering Machine Detection), y orquesta el Contact Flow.
- **Instancia:** `4830896a-ec8c-4ee7-9499-de31587fbb36`
- **Flow:** `auna-tatuaje-poc-inbound-test` (`cd86706f-68ea-4909-9e73-1fec3024f87d`)
- **Números:** `+18584776876` (US), `+576014430375` (Colombia)
- **Costo:** ~$0.038/min voz + telefonía outbound Perú

### Amazon Lex V2
- **Propósito:** Bot de conversación que actúa como puente entre Connect y Q in Connect. Activa el intent `AMAZON.QinConnectIntent` que habilita el AI Agent.
- **Bot:** `auna-valentina-v5` (ID: `EWU1UPLT9U`)
- **Alias:** `TSTALIASID` (DRAFT)
- **Locale:** `en_US` (único locale construido)
- **Speech model:** `amazon.nova-2-sonic-v1:0` (Nova Sonic 2) — convierte voz→texto del afiliado y texto→voz de las respuestas
- **Configuración crítica:** Requiere rebuild después de cada actualización de versión del AI Agent para limpiar caché de Q Connect.

### Amazon Q in Connect (Wisdom)
- **Propósito:** Motor del agente conversacional. Orquesta la conversación, decide cuándo invocar tools y genera el texto de las respuestas.
- **Assistant:** `bac452c1-14b3-4252-8c5a-af9e02faca9a`
- **AI Agent:** `680d88d1-66c1-4fa9-b882-d14649de998a` (tipo: ORCHESTRATION)
- **Prompt activo:** versión **:37**
- **Agent version activo:** versión **:37**
- **Modelo LLM:** Amazon Nova Pro (`us.amazon.nova-pro-v1:0`) — es el orchestration model de Q Connect. Nova Sonic 2 actúa como STT/TTS a nivel del Lex locale; Nova Pro genera las respuestas de conversación.
- **Tools (Return to Control):**
  - `ConsultarDisponibilidad` — busca slots en Multisede (soporta `pagina` 0-3, retorna `hay_mas`)
  - `CrearCita` — agenda la cita confirmada
  - `COMPLETE` — cierra la llamada (el flow desconecta automáticamente, Nova Pro no espera respuesta)
  - `Escalate` — transfiere a humano
- **Constraint crítico:** `$.Attributes.*` NO interpola en `ConnectParticipantWithLexBot.Text` ni en `LexSessionAttributes`. Solo interpola en `MessageParticipant` e `InvokeLambdaFunction.LambdaInvocationAttributes`.

### Stack de modelos completo
| Capa | Modelo | Rol |
|------|--------|-----|
| STT (voz → texto) | Nova Sonic 2 (`amazon.nova-2-sonic-v1:0`) | Lex locale speech model |
| Orquestación / LLM | Nova Pro (`us.amazon.nova-pro-v1:0`) | Q Connect AI Agent |
| TTS (texto → voz) | Nova Sonic 2 (a través de Lex/Connect) | Respuestas de Valentina en voz |

### AWS Lambda
Todas las funciones usan alias `:live` (Provisioned Concurrency activado para eliminar cold starts).

| Función | Responsabilidad | Timeout Connect |
|---------|----------------|-----------------|
| `auna-tatuaje-poc-validar-paciente:live` | Busca paciente por DNI en Multisede (`/search-patient`, `/insurance-client`) | 8s |
| `auna-tatuaje-poc-disponibilidad:live` (v11) | Consulta slots disponibles en `/availability/v2/pe`, filtra por centerId y preferencias día/horario. Soporta paginación (`pagina` 0-3, 3 slots/página). Retorna `hay_mas`, `opciones_texto_con_pregunta`. Ventana: hoy (UTC-5) + 60 días | 8s |
| `auna-tatuaje-poc-crear-cita:live` | Crea la cita en Multisede. Verifica idempotencia en DynamoDB antes de llamar la API | 8s |
| `auna-tatuaje-poc-parser` | Lee CSV de S3, valida, publica 1 mensaje por afiliado en SQS | — |
| `auna-tatuaje-poc-health-check` | Ping a Multisede antes de iniciar llamadas. Step Functions lo invoca como Estado 2 | — |

**Runtime:** Python 3.12  
**IAM Role:** `auna-tatuaje-poc-lambda-role`  
**Permisos de invocación:** resource policy en cada alias `:live` que permite `connect.amazonaws.com` con condición `SourceArn` de la instancia Connect.

### Amazon DynamoDB

| Tabla | PK | Propósito |
|-------|----|-----------|
| `auna-tatuaje-poc-interacciones` | `call_id` | Registro detallado por llamada: paciente, resultado, TMO, cita_id, modelo usado |
| `auna-tatuaje-poc-blacklist` | `telefono` | Números con fallos repetidos o rechazo explícito. Step Functions consulta antes de llamar |

**Modo:** On-demand (sin capacidad provisionada)

### AWS Step Functions
- **Propósito:** Orquestador principal del flujo outbound. Controla la secuencia completa por afiliado.
- **State machine:** `auna-tatuaje-poc-state-machine`
- **Estados:**
  - Estado 0: Validación de ventana horaria (L-V 9am-7pm, S 9am-1pm, hora Perú UTC-5). Usa `Wait` si está fuera de horario.
  - Estado 1: Consulta blacklist en DynamoDB. Termina si el número está bloqueado.
  - Estado 2: Invoca Lambda HealthCheck. Si Multisede está caída, no inicia la llamada.
  - Estado 3: `StartOutboundVoiceContact` → Amazon Connect inicia la llamada.

### Amazon S3
- **Bucket:** `auna-tatuaje-poc-input-{account-id}`
- **Propósito:** Recibe el CSV de afiliados. El evento S3 dispara Lambda Parser.
- **Lifecycle:** 7 días de retención.

### Amazon SQS
- **Cola:** `auna-tatuaje-poc-queue`
- **Propósito:** Buffer entre Lambda Parser y Step Functions. Controla la concurrencia de llamadas salientes.
- **1 mensaje por afiliado** — Lambda Parser es quien parsea el CSV, no SQS directamente.

### AWS Secrets Manager
- **Secret:** `auna/multisede/credentials`
- **Propósito:** Credenciales de acceso a la API Multisede (`ext2700` / `Auna2026`). Las Lambdas las leen en runtime. Token con duración ~19h cacheado en memoria.

### Amazon CloudWatch
- **Namespace:** `AunaTatuajePoc`
- **Métricas emitidas por las Lambdas:**
  - `Agendamientos` — citas creadas exitosamente (dimensión: sede, modelo)
  - `Rechazos` — afiliados que no aceptaron (dimensión: motivo)
  - `NoElegibles` — paciente no encontrado en Multisede
  - `SinDisponibilidad` — sin slots disponibles (dimensión: sede)
  - `ErroresMultisede` — fallos de API
  - `TMO` — duración de llamada en segundos
  - `LlamadasIniciadas` / `LlamadasCompletadas`
- **Log groups:** `/aws/lambda/auna-tatuaje-poc-*`, `/aws/connect/auna-tatuaje-poc`, `/aws/lex/auna-valentina-v5`

---

## API externa: Multisede

| Endpoint | Uso |
|----------|-----|
| `POST /authentication/v1/login` | Obtiene token JWT. Usado por las 3 Lambdas. |
| `GET /patient/v1/pe/search-patient` | Busca paciente por DNI y funderId. Retorna patient_id, clinic_history_number, nombre. |
| `GET /insurance-client/v1/pe/{funderId}/{patientId}` | Enriquece con datos de póliza (productId, planId). |
| `GET /availability/v2/pe` | Consulta slots disponibles por specialtyId y visitTypeId. Retorna hasta 1500 resultados. |
| `POST /appointment/v1/pe` | Crea la cita confirmada. Parámetros: modelId, doctorId, serviceId, fecha, hora, patientId. |

**Base URL UAT:** `https://17x9fh4a33.execute-api.us-east-1.amazonaws.com/uat`  
**Autenticación:** Bearer token + headers `aws-x-authorization` y `aws-x-source: app-000`  
**Sin VPN requerida**

---

## IDs de negocio Multisede confirmados

| Campo | Valor |
|-------|-------|
| `funderId` Oncosalud | `2` |
| `specialtyId` | `85` |
| `provisionId` | `5` |
| `reasonPrivateId` | `1` |
| `paymentMethod` | `3` |
| `visitTypeId` | `PS` |
| `benefitId` ambulatoria | `289` |

---

## Decisiones de arquitectura relevantes

**Por qué MessageParticipant en el flow en lugar del agente leyendo las opciones**  
El agente de Q in Connect genera su respuesta al mismo tiempo que emite el tool call, antes de que el flow ejecute la Lambda. Cuando el flow vuelve con `opciones_texto` real, el agente ya emitió datos. Además, `$.Attributes.*` no interpola en el Text del GCI — el agente recibiría string vacío e inventaría opciones. La solución es que el bloque `play-opciones` (MessageParticipant) lea `$.Attributes.opciones_texto_con_pregunta` directamente en voz alta antes de volver al GCI — el agente nunca tiene que generar ese texto. Trade-off: las opciones las lee Lupe (Connect TTS), no Nova Pro.

**Por qué Provisioned Concurrency en alias `:live`**  
Lambda con `$LATEST` tiene cold starts de 600-900ms que causan silencio perceptible durante la llamada. Con Provisioned Concurrency en una versión publicada (alias `:live`) el container está pre-calentado. Se requiere resource policy explícita en el alias — Connect no hereda la policy de `$LATEST`.

**Por qué Step Functions como orquestador y no Lambda**  
Las Lambdas tienen límite de 15 minutos y no tienen estado nativo. Step Functions maneja el ciclo completo por afiliado (esperar resultado de llamada, reintentos, blacklist), es idempotente y tiene visibilidad de ejecución por defecto.

**Por qué zona horaria UTC-5 en la Lambda de disponibilidad**  
`datetime.now(timezone.utc)` puede devolver el día siguiente si la Lambda corre cerca de medianoche UTC (7pm Perú), filtrando slots válidos de hoy como "pasados". Se usa `timezone(timedelta(hours=-5))` para calcular "hoy" en hora peruana.

---

## Recursos AWS — tabla de referencia rápida

| Recurso | ID / ARN |
|---------|----------|
| Connect instance | `4830896a-ec8c-4ee7-9499-de31587fbb36` |
| Contact flow | `cd86706f-68ea-4909-9e73-1fec3024f87d` |
| Q in Connect assistant | `bac452c1-14b3-4252-8c5a-af9e02faca9a` |
| AI Agent | `680d88d1-66c1-4fa9-b882-d14649de998a` |
| Lex bot | `EWU1UPLT9U` |
| Número US | `+18584776876` |
| Número Colombia | `+576014430375` |
| AWS Account | `769488154338` |
| Región | `us-east-1` |

---

## Costos estimados (40 000 min/mes)

| Servicio | Costo mensual |
|----------|--------------|
| Connect — voz ($0.038/min) | $1,520 |
| Connect — telefonía outbound Perú | $268 |
| Connect — DID | $3 |
| Nova Sonic 2 (~$0.017/min) | $680 |
| Step Functions | $0.04 |
| Lambda (5 funciones) | $0 (free tier) |
| SQS | $0 (free tier) |
| S3 | $0.03 |
| DynamoDB (2 tablas, on-demand) | $0.28 |
| CloudWatch | $5.52 |
| Secrets Manager | $0.85 |
| **Total con Nova Sonic 2** | **$2,477.72** |
