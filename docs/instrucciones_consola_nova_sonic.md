# Instrucciones Consola — Nova Sonic 2 + Contact Flow

## PASO 1: Activar Nova Sonic 2 en el Lex Bot

1. Ir a: https://us-east-1.console.aws.amazon.com/lexv2/home?region=us-east-1#bots
2. Abrir el bot **auna-tatuaje-valentina-bot** (ID: `Y1714O2UF7`)
3. Click en **Languages** → **Spanish (Latin America) (es_419)**
4. En la sección **Voice** → click **Edit**
5. En "Engine" seleccionar **Amazon Nova Sonic 2**
6. Click **Save**
7. Click **Build** (esperar ~1 min hasta que diga "Built")

---

## PASO 2: Editar el Contact Flow en Connect

1. Ir a: https://auna-tatuaje-poc.my.connect.aws/contact-flows
2. Abrir el flujo **auna-tatuaje-poc-inbound-test**
3. El flujo actual tiene este orden:
   ```
   Set voice → HC Lambda → ValidarPaciente Lambda → Greeting TTS → Disponibilidad Lambda → Mensaje → Goodbye
   ```
4. **Eliminar** los bloques desde "Greeting" en adelante (todo lo que va después de invoke-validar)
5. Después del bloque **invoke-validar** (ValidarPaciente), conectar a un nuevo bloque:

### Bloque a agregar: "Get customer input"
- **Tipo:** Get customer input
- **Configuración:**
  - En "Prompt": dejar vacío (el agente habla primero via Nova Sonic)
  - En "Lex bot": seleccionar **auna-tatuaje-valentina-bot** / alias **auna-tatuaje-poc-alias**
  - En "Session attributes" (importante): agregar estos atributos para pasar datos al agente:
    - `dni` = `$.External.dni` (o el valor del DNI del afiliado)
    - `center_id` = `1` (sede de prueba, en producción viene de los datos del afiliado)
    - `holder_name` = `$.External.holder_name`
    - `holder_last_name` = `$.External.holder_last_name`
    - `patient_id` = `$.External.patient_id`
    - `clinic_history_number` = `$.External.clinic_history_number`

### Transiciones del bloque "Get customer input":
- **Success** → Disconnect (el agente habrá cerrado la llamada)
- **No match** → Disconnect
- **Timeout** → Disconnect
- **Error** → error-msg TTS → Disconnect

6. Click **Publish** (esquina superior derecha)

---

## PASO 3: Verificar que el Bedrock Agent está como backend del Lex bot

1. En la consola de Lex: bot **auna-tatuaje-valentina-bot** → **Intents**
2. Verificar que existe el intent **AMAZON.QInConnectIntent** o un intent que apunta al Bedrock Agent `B3UYGUTJU8`
3. Si no existe, crear un intent con:
   - Nombre: `AgendarCita`
   - Sin utterances (Nova Sonic entiende lenguaje libre)
   - Fulfillment: **AWS Lambda** → `auna-tatuaje-poc-dispatcher`

---

## Flujo final esperado cuando funcione Nova Sonic 2:

```
Llaman al +1 (858) 477-6876
  ↓ set-voice (silencioso)
  ↓ HC Lambda (silencioso ~2s)
  ↓ ValidarPaciente Lambda (silencioso ~3s)
  ↓ Si OK → Get customer input (Lex + Nova Sonic 2)
      Valentina: "Buenos días señor [apellido], soy Valentina de Oncosalud..."
      Afiliado puede hablar, interrumpir, responder naturalmente
      Valentina pregunta preferencias → filtra disponibilidad → agenda
  ↓ Disconnect
```

---

## Notas

- Nova Sonic 2 requiere que la región tenga el modelo habilitado en Bedrock (us-east-1 OK)
- El Bedrock Agent ID es `B3UYGUTJU8`, alias prod `YTRXTUS7OY`
- El Dispatcher Lambda (`auna-tatuaje-poc-dispatcher`) enruta tool calls a las Lambdas especializadas