# BASE_MARZO.xlsx — Datos Completos de Afiliados

## Metadata del archivo
- **Archivo:** BASE_MARZO.xlsx
- **Hojas:** `6 a 11` (datos principales), `Hoja1` (cruce de DNIs)
- **Campaña:** Adelanto de Chequeo (6 a 11 meses)
- **Código campaña:** 4AT202602230950
- **Marca:** ONCOSALUD
- **División:** Oncológico

---

## Hoja principal: `6 a 11`

### Estadísticas generales
| Métrica | Valor |
|---------|-------|
| Total registros | 958 |
| Con consentimiento = SI | **548** (los contactables) |
| Con celular_afil_1 disponible | 932 |
| Columnas totales | 65 |

### Distribución por programa
| Programa | Registros | productId | planId |
|----------|-----------|-----------|--------|
| PROGRAMA ONCOCLASICO PRO | 657 | 105 | 133 |
| PROGRAMA ONCOPLUS | 295 | 12 | 7 |
| PROGRAMA ONCOFLEX | 6 | 280 | 455 |

### Distribución por grupo de cuota
| Grupo | Registros |
|-------|-----------|
| 8 a 12 meses | 636 |
| 4 a 7 meses | 322 |

### Distribución por canal
| Canal | Registros |
|-------|-----------|
| Telemarketing | 532 |
| Fuerza de Ventas | 426 |

### Tipos de documento del afiliado
| Tipo | Registros |
|------|-----------|
| Peru: DNI | 933 |
| Peru: Carnet de extranjería | 20 |
| Colombia: Pasaporte | 2 |
| Venezuela: Pasaporte | 1 |
| Estados Unidos: Pasaporte | 1 |
| Argentina: Pasaporte | 1 |

### Top 20 distritos (afiliado) → centerId Multisede
| Distrito | Registros | centerId |
|----------|-----------|----------|
| LIMA | 263 | 4 (Delgado) |
| SANTIAGO DE SURCO | 61 | 8 (OC Benavides) |
| SAN MARTIN DE PORRES | 39 | 10 (Auna Guardia Civil) |
| SAN JUAN DE LURIGANCHO | 37 | 18 (C.B. Independencia) |
| COMAS | 35 | 18 (C.B. Independencia) |
| MIRAFLORES | 34 | 11 (OC San Isidro) |
| LOS OLIVOS | 30 | 10 (Auna Guardia Civil) |
| SAN BORJA | 30 | 11 (OC San Isidro) |
| SAN ISIDRO | 29 | 11 (OC San Isidro) |
| SURQUILLO | 27 | 11 (OC San Isidro) |
| SAN MIGUEL | 25 | 9 (OC Encalada) |
| LA MOLINA | 24 | 8 (OC Benavides) |
| MAGDALENA DEL MAR | 21 | 9 (OC Encalada) |
| ATE | 19 | 18 (C.B. Independencia) |
| CALLAO | 18 | 15 (Bellavista) |
| VILLA MARIA DEL TRIUNFO | 18 | 8 (OC Benavides) |
| PUEBLO LIBRE | 17 | 9 (OC Encalada) |
| CHORRILLOS | 16 | 8 (OC Benavides) |
| LA VICTORIA | 16 | 4 (Delgado) |
| RIMAC | 16 | 4 (Delgado) |

---

## Columnas completas (65 columnas)

### Bloque contratante
| Columna | Descripción |
|---------|-------------|
| cod_grupo_familiar | Código del grupo familiar |
| cod_contratante | Código del contratante |
| tipo_documento_contratante | Tipo de documento |
| documento_contratante | Número de documento |
| tipodocumento_SAP_contratante | Código SAP del tipo de documento |
| fecha_nacimiento_contratante | Fecha de nacimiento |
| apellidos_nombres_contratante | Nombre completo |
| nombres_contratante | Solo nombres |
| apellido_paterno_contratante | Apellido paterno |
| apellido_materno_contratante | Apellido materno |
| celular_contratante_1 | Teléfono principal |
| celular_contratante_2 | Teléfono 2 |
| celular_contratante_3 | Teléfono 3 |
| celular_contratante_4 | Teléfono 4 |
| rango_edad_contratante | Rango de edad (ej: 36-45) |
| sexo_contratante | Masculino / Femenino |
| departamento_contratante | Departamento |
| provincia_contratante | Provincia |
| distrito_contratante | Distrito |

### Bloque afiliado (los datos que usamos en la PoC)
| Columna | Descripción | Uso en PoC |
|---------|-------------|------------|
| cod_afiliado | Código del afiliado | - |
| rango_edad_afiliado | Rango de edad | - |
| sexo_afiliado | Masculino / Femenino | - |
| tipo_documento_afil | Tipo de documento | Validación |
| **numero_documento_afil** | **DNI / CE / Pasaporte** | **→ search-patient** |
| tipodocumento_SAP_afiliado | Código SAP | - |
| **apellidos_nombres_afil** | **Nombre completo** | **→ agente (saludo)** |
| **celular_afil_1** | **Teléfono principal** | **→ Connect (llamada)** |
| celular_afil_2 | Teléfono 2 | Fallback si 1 falla |
| celular_afil_3 | Teléfono 3 | - |
| celular_afil_4 | Teléfono 4 | - |
| Email | Email del afiliado | - |
| fecha_nacimiento_afil | Fecha de nacimiento | - |
| departamento_afil | Departamento | - |
| provincia_afil | Provincia | - |
| **distrito_afil** | **Distrito** | **→ mapeo centerId** |

### Bloque del plan
| Columna | Descripción | Uso en PoC |
|---------|-------------|------------|
| segmento_comercial_abrev | Segmento (ej: P6) | - |
| programa | Programa SAP | - |
| agrupador_programa | Agrupador (Oncopro, Oncoplus, etc.) | - |
| cod_grupo_vendedor | Código del grupo vendedor | - |
| canal_distribucion | Canal (Telemarketing / Fuerza de Ventas) | - |
| frecuencia_pago | Mensual | - |
| des_plan | Descripción del plan | - |
| cat_producto | Full Price | - |
| des_oficina_venta | Oficina de venta | - |
| campana | Campaña activa | - |
| canal_sap_Actual | Canal SAP actual | - |
| flag_chequeo_preventivo | NO (todos en esta base) | - |
| edad_contratante | Edad numérica del contratante | - |
| edad_afiliado | Edad numérica del afiliado | - |
| division_por_negocio | Oncológico (todos) | - |
| marca | ONCOSALUD (todos) | - |
| **programa_final** | **PROGRAMA ONCOCLASICO PRO / ONCOPLUS / ONCOFLEX** | **→ productId/planId** |
| paciente_onco | No (todos) | - |
| uso_prog_ult_12m | No (todos) | - |
| Marca_Titular | Titular Afiliado / Titular No Afiliado | - |

### Bloque financiero y segmentación
| Columna | Descripción | Uso en PoC |
|---------|-------------|------------|
| cuotas_pendientes | Cuotas pendientes de pago | - |
| cuotas_condonadas | Cuotas condonadas | - |
| **cantidad_cuotas_pagadas** | **Cantidad de cuotas pagadas** | **→ atributo Connect** |
| **grupo_cuota_pagada** | **4 a 7 meses / 8 a 12 meses** | **→ atributo Connect** |
| cantidad_integrantes | Integrantes del grupo familiar | - |
| tiene_reclamo | No (todos) | - |
| **consentimiento** | **SI / No / NO** | **→ filtro principal** |
| en_lista_robinson | No (todos) | - |
| BD_Potencial | Adelanto de Chequeo (6 a 11) — todos | - |
| cod_campana | 4AT202602230950 — todos | - |

---

## Reglas de filtrado para el CSV de la PoC

```python
# Solo estos pasan al CSV de afiliados a llamar:
consentimiento IN ('SI', 'SÍ')     # 548 registros
AND celular_afil_1 IS NOT NULL      # 529 de los 548
# Si celular_afil_1 es null, intentar celular_contratante_1
```

---

## Mapeo programa_final → productId / planId (Multisede UAT, confirmado)

```python
PROGRAMA_A_IDS = {
    "PROGRAMA ONCOCLASICO PRO": {"productId": 105, "planId": 133},
    "PROGRAMA ONCOPLUS":         {"productId": 12,  "planId": 7},
    "PROGRAMA ONCOFLEX":         {"productId": 280, "planId": 455},
}
FUNDER_ID_ONCOSALUD = 2  # Confirmado en UAT
```

---

## Hoja2: `Hoja1` — Cruce de DNIs (46 filas)

Contiene DNIs para cruce entre corridas del 09.03 y 16.03.
**No se usa directamente en la PoC** — es para análisis interno del equipo de Auna.

```
Cruce 09.03  | Cruce 16.03
71894656     | 76912289
71894656     | 71918277
71560474     | 70445589
42219909     | 43890984
70281033     | 70753401
48667690     | 43866703
75510597     | 75787418
47430934     | 71894656
47193019     | 71894656
41011698     | 71560474
71626708     | 42219909
45609669     | 70281033
9829217      | 48667690
73460543     | 75510597
9750265      | 47430934
6602140      | 47193019
75336190     | 41011698
4682748      | 71626708
81011631     | 45609669
46276500     | 9829217
72305023     | 73460543
42703748     | 9750265
46352622     | 6602140
76663258     | 75336190
44605802     | 4682748
44012170     | 81011631
46754154     | 46276500
9111569      | 72305023
7738650      | 42703748
5583037      | 46352622
7254803      | 76663258
48016715     | 44605802
76282934     | 44012170
3956775      | 46754154
91011999     | 9111569
76190885     | 7738650
46754154     | 5583037
47473861     | 7254803
75318009     | 48016715
(null)       | 76282934
(null)       | 3956775
(null)       | 91011999
(null)       | 76190885
(null)       | 46754154
(null)       | 47473861
(null)       | 75318009
```

---

## Muestra de 5 registros reales (hoja 6 a 11)

```
DNI: 001937706 | Rodriguez Guarata Erick Noel | +51923763700
  Programa: ONCOCLASICO PRO | Distrito: BELLAVISTA → centerId=15
  Cuotas: 7 | Grupo: 4 a 7 meses | Consentimiento: SI

DNI: 76365787 | Chipa Inca Luis Fernando | +51956165138
  Programa: ONCOPLUS | Distrito: LIMA → centerId=4
  Cuotas: 8 | Grupo: 8 a 12 meses | Consentimiento: SI

DNI: 002709141 | Montilla Escobar Bety Del Carmen | +51917419456
  Programa: ONCOPLUS | Distrito: LIMA → centerId=4
  Cuotas: 11 | Grupo: 8 a 12 meses | Consentimiento: No ← EXCLUIR

DNI: 193947740 | Sulbaran Villarroel Nicole Stilyn Del Valle | +51959286773
  Programa: ONCOPLUS | Distrito: MIRAFLORES → centerId=11
  Cuotas: 6 | Grupo: 4 a 7 meses | Consentimiento: SI

DNI: 003584897 (pasaporte VEN) | Sulbaran Villarroel Nicole | +51959286773
  Programa: ONCOPLUS | Distrito: MIRAFLORES → centerId=11
  Cuotas: 6 | Grupo: 4 a 7 meses | Consentimiento: SI
```
