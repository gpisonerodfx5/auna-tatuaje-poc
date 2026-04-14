# Guía de Implementación — Amazon Connect AI Agent (Self-Service Voice)
## Basado en AWS Connect AI Agents Workshop + AWS Docs oficiales
### Para: PoC Tatuaje Auna — Agente Valentina

---

## ARQUITECTURA CORRECTA (según workshop)

```
Llamada entrante (+18584776876)
  ↓
[Set voice block]         → Voice: Lupe, Generative style, es-US
  ↓
[Connect assistant block] → Asocia el dominio Q in Connect + AI Agent
  ↓
[Get Customer Input]      → Lex bot con AMAZON.QinConnectIntent
                            Enable AI Agent: ON (activa Nova Sonic)
  ↓ NoMatchingCondition (tool call)
[Check contact attributes]
  Namespace: Lex
  Key: Session attributes
  Session Attribute Key: "Tool"
  ├── "Complete"   → [Disconnect]
  ├── "Escalate"   → [Set queue] → [Transfer to queue]
  ├── "ConsultarDisponibilidad" → [Invoke Lambda disp] → vuelve al GCI
  └── "CrearCita"  → [Invoke Lambda crear] → vuelve al GCI
```

---

## COMPONENTES NECESARIOS

### 1. Conversational AI Bot (Lex V2)
- Crear DESDE Amazon Connect admin website (no desde consola Lex) → permisos correctos automáticos
- Ruta: Amazon Connect admin → Routing → Flows → Conversational AI
- Habilitar `AMAZON.QinConnectIntent`:
  - Configuration tab → Enable Connect AI agents intent: ON
  - Ingresar ARN del assistant de Q in Connect
- Configurar Speech-to-Speech: Amazon Nova Sonic en la locale
- Build el bot locale
- Tag requerido: `AmazonConnectEnabled = true` (automático si se crea desde Connect)

**Locale para voz en español:** `es-US`
**Voice Nova Sonic compatible:** `Lupe` (es-US, Feminine)

### 2. Q in Connect Assistant (dominio)
- Ya existe: `bac452c1-14b3-4252-8c5a-af9e02faca9a`
- ARN: `arn:aws:wisdom:us-east-1:769488154338:assistant/bac452c1-14b3-4252-8c5a-af9e02faca9a`

### 3. AI Agent (Orchestration)
- Tipo: **ORCHESTRATION**
- Basado en: **SelfServiceOrchestrator** (template del sistema)
- Prompt: YAML con instrucciones + `<message>` tags OBLIGATORIOS
- Tools:
  - `Complete` (Return to Control) — cierre de conversación
  - `Escalate` (Return to Control) — transferencia a humano
  - `ConsultarDisponibilidad` (Return to Control) — buscar slots
  - `CrearCita` (Return to Control) — agendar cita
- Debe estar PUBLISHED (versión inmutable)
- Configurar como default Self-Service agent

### 4. Contact Flow
- 6 bloques principales (ver sección FLOW)
- Usar el flow existente `auna-tatuaje-poc-inbound-test`

---

## TOOL SCHEMA: Return to Control

### Complete
```json
{
  "type": "object",
  "properties": {
    "reason": {
      "type": "string",
      "description": "Reason the conversation is complete"
    }
  },
  "required": ["reason"]
}
```

### Escalate
```json
{
  "type": "object",
  "properties": {
    "customerIntent": {
      "type": "string",
      "description": "A brief phrase describing what the customer wants to accomplish"
    },
    "sentiment": {
      "type": "string",
      "description": "Customer emotional state",
      "enum": ["positive", "neutral", "frustrated"]
    },
    "escalationSummary": {
      "type": "string",
      "description": "Summary for human agent: what customer asked, what was attempted, why escalating",
      "maxLength": 500
    },
    "escalationReason": {
      "type": "string",
      "enum": ["complex_request", "technical_issue", "customer_frustration", "policy_exception", "out_of_scope", "other"]
    }
  },
  "required": ["escalationReason", "escalationSummary", "customerIntent", "sentiment"]
}
```

### ConsultarDisponibilidad
```json
{
  "type": "object",
  "properties": {
    "preferencia_dia": {
      "type": "string",
      "description": "Preferencia de día del afiliado",
      "enum": ["semana", "sabado"]
    },
    "preferencia_horario": {
      "type": "string",
      "description": "Preferencia de horario del afiliado",
      "enum": ["manana", "tarde"]
    }
  },
  "required": ["preferencia_dia", "preferencia_horario"]
}
```

### CrearCita
```json
{
  "type": "object",
  "properties": {
    "opcion_elegida": {
      "type": "string",
      "description": "Número de opción que el afiliado eligió (1, 2 o 3)",
      "enum": ["1", "2", "3"]
    },
    "confirmado": {
      "type": "boolean",
      "description": "true si el afiliado confirmó explícitamente la cita"
    }
  },
  "required": ["opcion_elegida", "confirmado"]
}
```

---

## SYSTEM PROMPT (AI Agent)

```yaml
system: |
  Eres Valentina, asesora de salud del programa Tatuaje de Oncosalud (Perú).
  Tu objetivo es agendar un chequeo preventivo oncológico GRATUITO para el afiliado.

  <formatting_requirements>
  DEBES formatear TODAS las respuestas con esta estructura:
    <message>
    Tu respuesta al cliente va aquí. Este texto se leerá en voz alta, escribe de forma natural y conversacional.
    </message>

  NUNCA pongas contenido de razonamiento dentro de las etiquetas message.
  SIEMPRE empieza con etiquetas <message>, incluso cuando uses herramientas.
  </formatting_requirements>

  <tool_instructions>
  {{$.toolConfigurationList}}
  </tool_instructions>

  ## PERSONALIDAD
  - Cálida, profesional, empática. Hablas en español peruano natural.
  - Concisa: no repites información innecesariamente.
  - Si el afiliado te interrumpe, escuchas y respondes.
  - Nunca menciones errores técnicos. Si algo falla, di "permítame un momento".
  - Escribe de forma conversacional, apta para voz — sin listas, sin bullets.

  ## CONTEXTO DEL AFILIADO
  El afiliado que llama tiene DNI: {{$.contactAttributes.dni}}
  Nombre: {{$.contactAttributes.holder_name}} {{$.contactAttributes.holder_last_name}}
  patient_id: {{$.contactAttributes.patient_id}}
  clinic_history_number: {{$.contactAttributes.clinic_history_number}}
  Centro de referencia ID: {{$.contactAttributes.center_id}}

  ## FLUJO

  ### 1. SALUDO
  El sistema ya dijo el saludo inicial. Pregunta directamente si desea agendar.
  <message>Hola, soy Valentina de Oncosalud. Le llamo porque tiene disponible un chequeo preventivo oncológico completamente gratuito. ¿Le gustaría agendarlo?</message>

  ### 2. PREFERENCIAS
  Si acepta, pregunta preferencia de día:
  <message>Para buscarle las mejores opciones, ¿prefiere la cita entre semana o un sábado?</message>
  Luego pregunta horario:
  <message>¿Y prefiere en las mañanas o en las tardes?</message>

  ### 3. DISPONIBILIDAD
  Invoca ConsultarDisponibilidad con las preferencias del afiliado.
  Espera el resultado y presenta las opciones de forma natural:
  <message>Encontré disponibilidad. Tengo [opciones]. ¿Cuál le vendría mejor?</message>

  ### 4. CONFIRMAR Y AGENDAR
  Cuando el afiliado elija una opción, confirma:
  <message>Perfecto, le agendo [fecha] a las [hora] con el [doctor]. ¿Me confirma?</message>
  Si confirma, invoca CrearCita.

  ### 5. CIERRE
  Si exitoso:
  <message>Listo, su cita queda agendada. Le llegará un mensaje con los detalles. ¿Tiene alguna pregunta más?</message>
  Despedida: invoca Complete.
  <message>Muchas gracias por confiar en Oncosalud. Que tenga un excelente día. Hasta luego.</message>

  ## SITUACIONES ESPECIALES
  - Afiliado rechaza: acepta sin insistir, invoca Complete cordialmente.
  - Sin disponibilidad: informa y ofrece alternativa de rango.
  - Afiliado pide humano: invoca Escalate.
  - Silencio +5 segundos: <message>¿Hola? ¿Sigue en línea?</message>

  Variables del sistema:
    contactId: {{$.contactId}}
    instanceId: {{$.instanceId}}
    sessionId: {{$.sessionId}}
    locale: {{$.locale}}

  SIEMPRE responde en español. SIEMPRE encierra mensajes al cliente en <message></message>.

messages:
  - "{{$.conversationHistory}}"
  - role: assistant
    content: "<message>"
```

---

## CONTACT FLOW — ESTRUCTURA

### Bloques en orden:

**1. Set voice**
- Voice: Amazon
- Language: Spanish (US) — es-US
- Voice: Lupe
- Other settings → Override speaking style → **Generative**
- Result: "Voice: Lupe (Generative)"

**2. Connect assistant**
- Assistant ARN: `arn:aws:wisdom:us-east-1:769488154338:assistant/bac452c1-14b3-4252-8c5a-af9e02faca9a`
- AI Agent: seleccionar el Orchestration agent configurado
- Branches: Success → siguiente, Error → error-msg

**3. Set contact attributes** (pasar datos del afiliado pre-cargados)
- dni → $.Attributes.dni (ya en contacto)
- center_id → $.Attributes.center_id
- patient_id → $.Attributes.patient_id
- clinic_history_number → $.Attributes.clinic_history_number
- holder_name → $.Attributes.holder_name

**4. Get Customer Input (GCI)**
- Tab: Amazon Lex
- Bot: el Conversational AI bot creado en Connect
- Alias: prod (el que tiene AMAZON.QinConnectIntent)
- **Enable AI Agent: ON** ← CRÍTICO
- Initial message: "Hola, bienvenido a Oncosalud." (el agente toma el control después)
- Intent: AMAZON.QinConnectIntent
- Timeout: 300 segundos

**5. Check contact attributes** (después de NoMatchingCondition)
- Namespace: **Lex**
- Attribute: **Session attributes**
- Session Attribute Key: **Tool**
- Conditions:
  - Equals "Complete" → Disconnect
  - Equals "Escalate" → error-msg (o transfer)
  - Equals "ConsultarDisponibilidad" → invoke-disp
  - Equals "CrearCita" → invoke-crear

**6. Invoke Lambda (ConsultarDisponibilidad)**
- Lambda: `auna-tatuaje-poc-disponibilidad`
- Params desde Lex session attrs:
  - preferencia_dia: $.Lex.SessionAttributes.preferencia_dia
  - preferencia_horario: $.Lex.SessionAttributes.preferencia_horario
  - patient_id: $.Attributes.patient_id
  - center_id: $.Attributes.center_id
  - dni: $.Attributes.dni
- Después: UpdateContactAttributes con resultado → volver al GCI (sin crear nueva Wisdom session)

**7. Invoke Lambda (CrearCita)**
- Lambda: `auna-tatuaje-poc-crear-cita`
- Params:
  - opcion_elegida: $.Lex.SessionAttributes.opcion_elegida
  - patient_id: $.Attributes.patient_id
  - clinic_history_number: $.Attributes.clinic_history_number
  - center_id: $.Attributes.center_id
  - dni: $.Attributes.dni
  - + datos del slot del contacto attrs
- Después: UpdateContactAttributes → volver al GCI

---

## DIFERENCIA CLAVE vs LO QUE TENÍAMOS

| Lo que teníamos (roto) | Lo correcto (workshop) |
|---|---|
| CreateWisdomSession + UpdateContactData manual antes de cada Lex block | NO necesario — Connect assistant block lo maneja automáticamente |
| x-amz-lex:q-in-connect:ai-agent-arn como LexSessionAttribute | NO necesario — se configura en el bot (AMAZON.QinConnectIntent con assistant ARN) |
| Múltiples ConnectParticipantWithLexBot blocks | Un solo GCI block con Enable AI Agent: ON |
| Loop manual wisdom/ucdata/lex | El GCI maneja el loop automáticamente con el agente |

---

## PASOS DE IMPLEMENTACIÓN

### PASO 1: Crear Conversational AI bot desde Connect
1. Amazon Connect admin → Routing → Flows → Conversational AI
2. Create bot → nombre: `auna-valentina-v4`
3. Agregar locale es-US
4. Configuration tab → Enable Connect AI agents intent: ON
5. Ingresar assistant ARN
6. Speech model → Speech-to-Speech: Amazon Nova Sonic
7. Build

### PASO 2: Crear/actualizar AI Agent
1. Amazon Connect admin → AI agent designer → AI agents
2. Create AI Agent → Orchestration → Copy from SelfServiceOrchestrator
3. Nombre: `auna-valentina-tatuaje` (o nuevo nombre)
4. Agregar tools: Complete, Escalate, ConsultarDisponibilidad, CrearCita
5. Editar prompt con el system prompt de arriba
6. Publish
7. Set as default Self-Service agent

### PASO 3: Actualizar Contact Flow
1. Reemplazar estructura actual del flow
2. Set voice → Lupe, Generative
3. Connect assistant block → associate assistant + ai agent
4. GCI → Enable AI Agent ON + AMAZON.QinConnectIntent
5. Check contact attributes → dispatch por Tool name
6. Lambda blocks para herramientas
7. Publish

### PASO 4: Verificar
1. Bot tag: AmazonConnectEnabled = true
2. Bot alias habilitado para uso en flows
3. Probar llamada entrante al +18584776876

---

## NOTAS CRÍTICAS

1. **`<message>` tags son OBLIGATORIOS** en el prompt — sin ellas el agente no habla
2. **Enable AI Agent toggle en GCI es OBLIGATORIO** — sin él, Lex responde pero no hay agente
3. **AMAZON.QinConnectIntent NO puede coexistir** con QnAIntent ni BedrockAgentIntent en el mismo locale
4. **El bot DEBE crearse desde Connect admin** (no Lex console) para permisos correctos
5. **Nova Sonic solo disponible en us-east-1 y us-west-2** — estamos en us-east-1 ✅
6. **NO se necesita** CreateWisdomSession ni UpdateContactData manual en el flow
7. **Return to Control** devuelve el nombre del tool en `$.Lex.SessionAttributes.Tool`
8. **Los parámetros del tool call** están disponibles como `$.Lex.SessionAttributes.[paramName]`
9. **Un solo GCI block** maneja toda la conversación — el agente hace loop automáticamente
10. Contact Lens real-time requerido para voz (Set recording and analytics behavior block)

---

## CUENTA AWS
- Instance ID: `4830896a-ec8c-4ee7-9499-de31587fbb36`
- Account: `769488154338`
- Region: `us-east-1`
- Phone: `+18584776876`
- Q in Connect Assistant: `bac452c1-14b3-4252-8c5a-af9e02faca9a`
- Flow actual: `cd86706f-68ea-4909-9e73-1fec3024f87d` (auna-tatuaje-poc-inbound-test)
