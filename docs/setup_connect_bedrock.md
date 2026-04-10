# Setup Manual: Amazon Connect + Bedrock Agent

Guia paso a paso para configurar los componentes que NO se crean automaticamente con `setup_infra.py`.

---

## 1. Amazon Connect — Crear Instancia

### 1.1 Crear instancia
1. Ir a **Amazon Connect** en la consola AWS (us-east-1)
2. Click **Create instance**
3. Identity management: **Store users within Amazon Connect**
4. Admin username: `admin` (o el que prefieran)
5. Telephony: Habilitar **Outbound calls** (inbound opcional)
6. Data storage: defaults
7. Review and create

### 1.2 Reclamar numero de telefono
1. Dentro de la instancia Connect, ir a **Phone numbers**
2. Click **Claim a phone number**
3. Seleccionar **DID** → Country: **Peru (+51)** o **Colombia (+57)** segun disponibilidad
4. Si no hay numeros Peru disponibles: usar el numero de prueba +573150020389 como source
5. Anotar el numero reclamado

### 1.3 Obtener IDs
```bash
# Instance ID (desde la URL de Connect o con CLI)
aws connect list-instances --region us-east-1

# El Instance ID es el UUID en la URL:
# https://xxx.my.connect.aws  →  ver en la consola
```

---

## 2. Amazon Bedrock — Crear Agente

### 2.1 Crear el agente
1. Ir a **Amazon Bedrock** → **Agents** (us-east-1)
2. Click **Create agent**
3. Nombre: `auna-tatuaje-valentina`
4. Descripcion: `Agente de voz para programa Tatuaje de Oncosalud`
5. Model: **Claude 3 Sonnet** (anthropic.claude-3-sonnet)
6. Instructions: Copiar contenido completo de `bedrock/system_prompt.txt`
7. Click **Create**

### 2.2 Crear Action Group
1. Dentro del agente, ir a **Action groups**
2. Click **Add action group**
3. Nombre: `auna-actions`
4. Tipo: **Define with API schemas**
5. Action group type: **Lambda function**
6. Lambda function: Seleccionar `auna-tatuaje-poc-agente-acciones`
7. API schema: **Upload** → seleccionar `bedrock/openapi_schema.json`
8. Click **Save**

### 2.3 Configurar Session Attributes
En la configuracion del agente, asegurarse de que estos atributos de sesion se pasen:
- `call_id` — ID unico de la llamada
- `afiliado_dni` — DNI del afiliado
- `afiliado_nombre` — Nombre completo
- `sede_referencia` — centerId de la sede
- `programa` — Programa del afiliado (ej: PROGRAMA ONCOCLASICO PRO)
- `cuotas_pagadas` — Cantidad de cuotas
- `grupo_cuota` — Rango de cuotas

### 2.4 Preparar y publicar
1. Click **Prepare** para compilar el agente
2. Probar en el **Test** panel con un mensaje como:
   "Hola, soy el afiliado Juan Perez"
3. Una vez validado, click **Create alias** → nombre: `prod`
4. Anotar el **Agent ID** y **Agent Alias ID**

---

## 3. Amazon Connect — Contact Flow

### 3.1 Crear Contact Flow
1. En la instancia Connect, ir a **Contact Flows**
2. Click **Create contact flow**
3. Nombre: `auna-tatuaje-poc-outbound`

### 3.2 Configurar el flujo
El flujo debe tener esta secuencia:

```
Entry Point
    ↓
Set Contact Attributes (pasar atributos de la llamada)
    - call_id, afiliado_dni, afiliado_nombre, sede_referencia, programa
    ↓
Set Voice (idioma: es-MX o es-US, voz: Lupe o Mia)
    ↓
Get Customer Input (Invoke Bedrock Agent)
    - Agent ID: [pegar Agent ID de paso 2.4]
    - Agent Alias: [pegar Alias ID]
    - Session attributes: mapear desde Contact Attributes
    ↓
Disconnect / End Flow
```

### 3.3 Alternativa: Lex Bot + Bedrock
Si Connect no soporta invocacion directa de Bedrock Agent en tu version:
1. Crear un **Amazon Lex Bot** que actue como proxy
2. El bot usa Bedrock como fulfillment
3. Connect invoca el Lex Bot con **Get Customer Input**

### 3.4 Publicar Contact Flow
1. Click **Save** y luego **Publish**
2. Anotar el **Contact Flow ID** (visible en la URL o en "Show additional flow information")

---

## 4. Actualizar Variables de Entorno

Con los IDs obtenidos, actualizar las Lambdas:

```bash
# Lambda Orquestador
aws lambda update-function-configuration \
  --function-name auna-tatuaje-poc-orquestador \
  --environment "Variables={
    CONNECT_INSTANCE_ID=xxxxxxxx-xxxx-xxxx-xxxx-xxxxxxxxxxxx,
    CONNECT_CONTACT_FLOW_ID=xxxxxxxx-xxxx-xxxx-xxxx-xxxxxxxxxxxx,
    CONNECT_SOURCE_PHONE_NUMBER=+573150020389,
    DYNAMODB_TABLE_NAME=auna-tatuaje-poc-interacciones
  }" \
  --region us-east-1
```

---

## 5. Prueba End-to-End

### 5.1 Probar con 1 afiliado
```bash
# Crear CSV con 1 solo registro
echo "numero_documento_afil,apellidos_nombres_afil,telefono,programa_final,sede_referencia,cantidad_cuotas_pagadas,grupo_cuota_pagada" > /tmp/test_1.csv
echo "76365787,Chipa Inca Luis Fernando,+573150020389,PROGRAMA ONCOPLUS,4,8,8 a 12 meses" >> /tmp/test_1.csv

# Subir a S3
aws s3 cp /tmp/test_1.csv s3://auna-tatuaje-poc-input-ACCOUNT_ID/input/test_1.csv
```

**IMPORTANTE:** Cambiar el telefono al numero de prueba (+573150020389) para la primera prueba.

### 5.2 Monitorear
```bash
# Logs Lambda Orquestador
aws logs tail /aws/lambda/auna-tatuaje-poc-orquestador --follow --region us-east-1

# Logs Lambda Agente Acciones
aws logs tail /aws/lambda/auna-tatuaje-poc-agente-acciones --follow --region us-east-1

# DynamoDB
aws dynamodb scan --table-name auna-tatuaje-poc-interacciones --region us-east-1
```

### 5.3 Validar resultado
Verificar en DynamoDB que el registro tenga:
- `resultado`: `agendado`, `rechazo`, o el estado correspondiente
- `timestamp_fin`: presente
- `cita_id`: presente si fue agendado

---

## 6. Checklist Pre-Demo

- [ ] Instancia Connect creada y numero reclamado
- [ ] Agente Bedrock creado con system_prompt.txt
- [ ] Action Group configurado con openapi_schema.json apuntando a Lambda
- [ ] Contact Flow creado y publicado
- [ ] Variables de entorno actualizadas en ambas Lambdas
- [ ] Disponibilidad endpoint desbloqueado (Alexia)
- [ ] Al menos 1 DNI de prueba funcional en UAT
- [ ] Prueba exitosa con 1 llamada al numero de prueba
