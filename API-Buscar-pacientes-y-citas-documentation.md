# API Documentation — Multisede basic endpoints

## Table of contents

0. [Authentication](#0-authentication)
1. [Search patient (Buscar pacientes por DNI)](#1-search-patient-buscar-pacientes-por-dni)
2. [Clinical history (Historial clínico)](#2-clinical-history-historial-clínico)
3. [Search appointment availability (Buscar cita)](#3-search-appointment-availability-buscar-cita)
4. [List specialties (Buscar especialidades)](#4-list-specialties-buscar-especialidades)
5. [Search professionals / doctors (Buscar doctores)](#5-search-professionals-doctors-buscar-doctores)
6. [List funders (Financiadores)](#6-list-funders-financiadores)
7. [Get insurance policies (Seguro)](#7-get-insurance-policies-seguro)
8. [List benefits (Ver beneficios)](#8-list-benefits-ver-beneficios)
9. [Create appointment (Crear cita)](#9-create-appointment-crear-cita)

---

Base URL (UAT): `https://17x9fh4a33.execute-api.us-east-1.amazonaws.com/uat`

All responses include a top-level `traceId` (string) for tracing. Successful payloads are under `results`.

Most endpoints require an `Authorization` header with a Bearer token:

```http
Authorization: Bearer xxxxxxx
```

## 0. Authentication

Use this login endpoint to obtain the token required by the rest of the API.

| Method | URL |
|--------|-----|
| **POST** | `https://17x9fh4a33.execute-api.us-east-1.amazonaws.com/uat/authentication/v1/login` |

### Request body

```json
{
  "username": "dsotomayor",
  "password": "password"
}
```

### Response

```json
{
  "accessToken": "token",
  "refreshToken": "token"
}
```

Use the `accessToken` value in the `Authorization` header:

```http
Authorization: Bearer <accessToken>
```

---

## 1. Search patient (Buscar pacientes por DNI)

Search patients by document number and/or name.

| Method | URL |
|--------|-----|
| **POST** | `{baseUrl}/maintainers/v1/search-patient/pe` |

### Request body

Send **one** of the following shapes (all require `pagination`):

**By document number:**
```json
{
  "document_number": "73191563",
  "pagination": {
    "number": 1,
    "size": 10
  }
}
```

**By first name:**
```json
{
  "first_name": "deyby",
  "pagination": {
    "number": 1,
    "size": 10
  }
}
```

**By first name and last name:**
```json
{
  "first_name": "deyby",
  "last_name": "asdad",
  "pagination": {
    "number": 1,
    "size": 10
  }
}
```

| Field | Type | Description |
|-------|------|-------------|
| `document_number` | string | Optional. Patient document number (e.g. DNI). |
| `first_name` | string | Optional. Patient first name. |
| `last_name` | string | Optional. Patient last name. |
| `pagination.number` | number | Page number (1-based). |
| `pagination.size` | number | Page size. |

### Response

```json
{
  "traceId": "2b5e5aae-fd94-4e06-b869-8625191f495e",
  "results": [
    {
      "id": "1656936",
      "fields": {
        "first_name": "DEYBY",
        "last_name": "SOTOMAYOR PONTE",
        "document_number": "46831148",
        "his_id": "1656936",
        "medical_record_number": "1472764",
        "phone_number_mobile": "165679399",
        "location": "Av. Peru 10200",
        "birth_date": "1990-07-31T00:00:00+00:00",
        "email": "notiene1@yopmail.com"
      }
    }
  ],
  "page": 1,
  "total": 8
}
```

---

## 2. Clinical history (Historial clínico)

Get appointment history for a patient by clinic history number.

| Method | URL |
|--------|-----|
| **GET** | `{baseUrl}/appointments/v1/history/pe` |

### Query parameters

| Parameter | Type | Description |
|-----------|------|-------------|
| `clinicHistoryNumber` | string | **Required.** Medical record / clinic history number. |
| `pageNumber` | number | Page number (e.g. 1). |
| `pageSize` | number | Page size (e.g. 100). |
| `orderDir` | string | Sort direction, e.g. `DESC`. |

**Example:**  
`?clinicHistoryNumber=8747679&pageNumber=1&pageSize=100&orderDir=DESC`

### Response

```json
{
  "traceId": "b3bb258f-bac5-445d-b3ca-d842a5a4a928",
  "results": {
    "appointments": [
      {
        "month": "01/2026",
        "appointments": [
          {
            "patientId": 2064334,
            "clinicHistoryNumber": "8747679",
            "patientName": "DEYBY VICTOR ALBERTO",
            "patientFirstSurname": "SOTOMAYOR",
            "patientSecondSurname": "PONTE",
            "documentType": "DNI",
            "documentNumber": "46831148",
            "solicNumber": 48432173,
            "guarantorId": 134,
            "guarantorName": "AUNA SALUD",
            "productId": 524,
            "productName": "PLAN CORPORATIVO AUNA SALUD",
            "benefitId": 59,
            "benefitDescription": "CONSULTA AMBULATORIA",
            "date": "2026-01-29T00:00:00.000Z",
            "hour": "15:00:00",
            "serviceId": 531,
            "serviceName": "DEL CARDIOLOGIA CEX",
            "specialtyId": 12,
            "specialtyName": "Cardiología",
            "centerId": 4,
            "centerName": "Delgado",
            "doctorId": 15137,
            "doctorName": "HENRY ALEXANDER ANCHANTE HERNANDEZ",
            "stateId": "CI",
            "state": "CITADO",
            "visitTypeId": "TC",
            "visitTypeName": "Teleconsulta",
            "officeId": 1,
            "office": "S/C",
            "copay": "70",
            "coInsurance": 20,
            "creationDate": "2026-01-29T10:22:08.000Z",
            "note": "AGENDADO DESDE INTEGRACION AUNA DIGITAL",
            "payment": { ... },
            "economicData": { ... },
            "id": "5e04d4db-8c3c-43ae-90dd-9c730292eca2"
          }
        ]
      }
    ]
  }
}
```

---

## 3. Search appointment availability (Buscar cita)

Get available slots for scheduling (by specialty, visit types, and optional filters).

| Method | URL |
|--------|-----|
| **GET** | `{baseUrl}/availability/v2/pe` |

### Query parameters

| Parameter | Type | Description |
|-----------|------|-------------|
| `specialtyId` | number | **Required.** Specialty ID (from specialties endpoint). |
| `visitTypeIds` | string | **Required.** Comma-separated visit type codes, e.g. `CM,PS,TC`. |
| `count` | number | Max number of results (e.g. 1500). |
| `offset` | number | Pagination offset (e.g. 0). |

**Example:**  
`?specialtyId=12&visitTypeIds=CM,PS,TC&count=1500&offset=0`

**Visit type examples:** `CM` (consultation type), `PS` (presential), `TC` (teleconsultation).

### Response

```json
{
  "traceId": "acc2b1b2-bf07-49d8-b157-a5c9ae604c2c",
  "results": [
    {
      "specialtyName": "Cardiología",
      "specialtyId": 12,
      "subSpecialtyId": 531,
      "subSpecialtyName": "DEL CARDIOLOGIA CEX",
      "professionalName": "Ana Cecilia Gonzales Luna",
      "professionalId": 2076,
      "centerName": "Delgado",
      "centerId": 4,
      "office": "S/C",
      "visitTypeId": "PS",
      "descriptionVisitType": "Consulta Presencial",
      "totalAdditionalSpaces": 0,
      "additionalFlag": 1,
      "date": "2026-03-11T00:00:00.000Z",
      "schedules": [
        {
          "appointmentCoreId": null,
          "appointmentId": null,
          "modelId": 296688,
          "time": "16:30:00",
          "status": "LI",
          "shiftType": 0
        }
      ]
    }
  ]
}
```

Use `modelId`, `date`, `time`, `professionalId`, `serviceId`, `visitTypeId`, etc. from these results when creating an appointment.

---

## 4. List specialties (Buscar especialidades)

Get all specialties (for filters and availability).

| Method | URL |
|--------|-----|
| **GET** | `{baseUrl}/maintainers/v1/specialty/pe` |

### Request

No body. No required query parameters.

### Response

```json
{
  "traceId": "586f1e0b-2661-4be4-b1f3-d0fc177ea549",
  "results": [
    {
      "id": 1,
      "specialtyId": 1,
      "name": "Administración De Hospitales"
    },
    {
      "id": 12,
      "specialtyId": 12,
      "name": "Cardiología"
    }
  ]
}
```

Use `specialtyId` in the availability endpoint.

---

## 5. Search professionals / doctors (Buscar doctores)

Search professionals by name.

| Method | URL |
|--------|-----|
| **GET** | `{baseUrl}/maintainers/v2/professional/pe` |

### Query parameters

| Parameter | Type | Description |
|-----------|------|-------------|
| `q` | string | **Required.** Search query (e.g. name or part of name). |

**Example:**  
`?q=carla`

### Response

```json
{
  "traceId": "049619cf-ff31-4356-b1a0-6ca9af05a3ca",
  "results": [
    {
      "id": 1656,
      "name": "Carla Becerra Valdes"
    },
    {
      "id": 2076,
      "name": "Ana Cecilia Gonzales Luna"
    }
  ]
}
```

Use `id` as `doctorId` when creating an appointment.

---

## 6. List funders (Financiadores)

Get funders and their products/plans for a center.

| Method | URL |
|--------|-----|
| **GET** | `{baseUrl}/maintainers/v1/funder/pe` |

### Query parameters

| Parameter | Type | Description |
|-----------|------|-------------|
| `centerId` | number | **Required.** Center ID (e.g. 4 for Delgado). |

**Example:**  
`?centerId=4`

### Response

```json
{
  "traceId": "8f602b45-55f2-44a6-95e7-cc26238490a3",
  "results": [
    {
      "funderId": 13,
      "name": "**GRUPO GLORIA**",
      "products": [
        {
          "productId": 50,
          "name": "PREVENCIÓN ONCOLÓGICA",
          "plans": [
            {
              "planId": 144,
              "name": "PREVENCION ONCOLÓGICA"
            }
          ]
        }
      ]
    },
    {
      "funderId": 1,
      "name": "**PRIVADO**",
      "products": [
        {
          "productId": 62,
          "name": "....",
          "plans": [
            {
              "planId": 57,
              "name": "PRIVADO OSB"
            }
          ]
        }
      ]
    }
  ]
}
```

Use `funderId`, `productId`, `planId` in the create-appointment payload and in the insurance policies request.

---

## 7. Get insurance policies (Seguro)

Get active policies for a patient (document + center + funder).

| Method | URL |
|--------|-----|
| **GET** | `{baseUrl}/insurance-client/v4/pe/policies` |

### Query parameters

| Parameter | Type | Description |
|-----------|------|-------------|
| `centerId` | number | **Required.** Center ID. |
| `document` | string | **Required.** Patient document number (e.g. DNI). |
| `documentTypeId` | number | **Required.** Document type ID (e.g. 1 = DNI). |
| `funderId` | number | **Required.** Funder ID from funders endpoint. |

**Example:**  
`?centerId=4&document=46831148&documentTypeId=1&funderId=8`

### Response

```json
{
  "traceId": "7a1eed6c-113a-4b50-92ce-2847955fc498",
  "results": [
    {
      "statusPolicy": "1",
      "statusNamePolicy": "VIGENTE",
      "startDatePolicy": "2025-04-01T05:00:00.000Z",
      "endDatePolicy": "2026-04-01T04:59:59.000Z",
      "planNumber": "00048514",
      "productId": 19,
      "productName": "MAPFRE EPS",
      "productDescription": "REGULARES",
      "relationshipId": 1,
      "relationshipName": "TITULAR",
      "contractorId": "20536435582",
      "contractorName": "GSP SERVICIOS GENERALES S.A.C. GSP",
      "affiliateName": "DEYBI VICTOR ALBERTO",
      "affiliateLastName": "SOTOMAYOR",
      "affiliateMotherLastName": "PONTE",
      "affiliateCode": "0009776756",
      "affiliatePolicyNumber": "288792",
      "holderName": "DEYBI VICTOR ALBERTO",
      "holderLastName": "SOTOMAYOR",
      "holderMotherLastName": "PONTE",
      "coverages": [
        {
          "benefitId": 98,
          "benefitName": "EMERGENCIA MEDICA",
          "fixedCopay": 0,
          "variableCopay": 100,
          "observations": "CARENCIA SOLO CAPA COMPLEJA",
          "currencyId": 1,
          "currencyName": "SOLES",
          "lackExpirationDate": "2021-06-02T04:59:59.000Z",
          "warrantyLetter": "0"
        }
      ]
    }
  ]
}
```

Use `benefitId`, holder/affiliate data and policy dates when creating an appointment.

---

## 8. List benefits (Ver beneficios)

Get benefits for a product (or context) in Peru.

| Method | URL |
|--------|-----|
| **GET** | `{baseUrl}/maintainers/v1/benefit/{productId}/pe` |

### Path parameters

| Parameter | Type | Description |
|-----------|------|-------------|
| `productId` | number | **Required.** Product ID (e.g. 10). |

**Example:**  
`/maintainers/v1/benefit/10/pe`

### Response

```json
{
  "traceId": "6f9fcdee-3a1b-4b77-bf78-92e0b0b8892b",
  "results": [
    {
      "benefitId": 1,
      "benefitCode": "4308",
      "name": "ABORTO/AMENAZA DE ABORTO AMBULATORIO"
    },
    {
      "benefitId": 59,
      "benefitCode": "4100",
      "name": "CONSULTA AMBULATORIA"
    },
    {
      "benefitId": 98,
      "benefitCode": "6100",
      "name": "EMERGENCIA MEDICA"
    }
  ]
}
```

Use `benefitId` as `medicalBenefitId` in the create-appointment body.

---

## 9. Create appointment (Crear cita)

Create a new appointment (v3).

| Method | URL |
|--------|-----|
| **POST** | `{baseUrl}/appointments/v3/pe` |

### Request body

```json
{
  "appointment": {
    "date": "11/03/2026",
    "doctorId": 2076,
    "hour": "16:30:00",
    "modelId": 296688,
    "note": "",
    "provisionId": 5,
    "reasonPrivateId": 1,
    "serviceId": 531,
    "visitTypeId": "PS"
  },
  "patient": {
    "clinicHistoryNumber": 8747679,
    "id": 2064334
  },
  "funder": {
    "id": 1,
    "productId": 1,
    "planId": 9
  },
  "economicData": {
    "affiliatePolicyNumber": "",
    "coInsurance": 0,
    "deductible": 0,
    "holderLastName": "SOTOMAYOR",
    "holderMotherLastName": "PONTE",
    "holderName": "DEYBY VICTOR ALBERTO",
    "medicalBenefitId": 1562,
    "paymentMethod": 3,
    "startDatePolicy": "11/03/2026"
  }
}
```

| Section | Field | Description |
|---------|--------|-------------|
| **appointment** | `date` | Date in `DD/MM/YYYY`. |
| | `doctorId` | From professionals search. |
| | `hour` | Time slot, e.g. `16:30:00`. |
| | `modelId` | From availability `schedules[].modelId`. |
| | `serviceId` | From availability (e.g. subSpecialtyId). |
| | `visitTypeId` | e.g. `PS`, `TC`, `CM`. |
| | `provisionId` | Provision ID. |
| | `reasonPrivateId` | Reason for private appointment. |
| **patient** | `id` | Patient ID from search-patient. |
| | `clinicHistoryNumber` | From search-patient or history. |
| **funder** | `id`, `productId`, `planId` | From funders endpoint. |
| **economicData** | `medicalBenefitId` | From benefits endpoint. |
| | `holderName`, `holderLastName`, `holderMotherLastName` | Policy holder. |
| | `startDatePolicy` | Policy start (e.g. `DD/MM/YYYY`). |
| | `paymentMethod` | Payment method ID. |
| | `deductible`, `coInsurance` | Amounts. |

### Response

```json
{
  "traceId": "8d4c4f10-0ea6-47b2-921c-585c49cd3249",
  "results": {
    "appointment": {
      "countryISO": "PE",
      "version": 3,
      "id": "878e0978-e17e-460e-9c82-e01d0934f0f5",
      "modelId": 296688,
      "visitTypeId": "PS",
      "doctorId": 2076,
      "date": "11/03/2026",
      "hour": "16:30:00",
      "patientId": 2064334,
      "medicalBenefitId": 1562,
      "serviceId": 531,
      "funderId": 1,
      "productId": 1,
      "planId": 9,
      "active": true,
      "source": "APPOINTMENT_WEB",
      "destination": "HIS",
      "createdAt": "2026-03-11T21:27:38.897Z",
      "clinicHistoryNumber": "8747679",
      "economicData": { ... }
    }
  }
}
```

---

## Centers by city

| Ciudad | Centro (Nombre) | CenterId | Ipress |
|---|---|---:|---|
| Arequipa | Vallesur | 1 | 00016744 |
| Chiclayo | Servimedicos | 16 | 00008229 |
| Chiclayo | Auna Clínica Chiclayo | 17 | 00030057 |
| Lima y Callao | OC Encalada | 9 | 00018686 |
| Lima y Callao | Oncosalud | 3 | 00017634 |
| Lima y Callao | Delgado | 4 | 00019049 |
| Lima y Callao | CENTRO EXTERNO | 5 |  |
| Lima y Callao | CONCOSALUD | 6 |  |
| Lima y Callao | CDELGADO | 7 |  |
| Lima y Callao | OC Benavides | 8 | 00016297 |
| Lima y Callao | Auna Guardia Civil | 10 | 00027320 |
| Lima y Callao | OC San Isidro | 11 | 00009845 |
| Lima y Callao | OC Radioterapia SIS | 12 | 00020323 |
| Lima y Callao | Oncocenter San Borja | 14 | 00016786 |
| Lima y Callao | Bellavista | 15 | 00009250 |
| Lima y Callao | Centro de Bienestar Independencia | 18 | 00031032 |
| Lima y Callao | Benavides | 19 | 00016297 |
| Piura | Miraflores | 13 | 00013494 |
| Trujillo | Camino Real | 2 | 00016830 |

---

## Quick reference

| # | Name | Method | Path |
|---|------|--------|------|
| 1 | Search patient | POST | `/maintainers/v1/search-patient/pe` |
| 2 | Clinical history | GET | `/appointments/v1/history/pe` |
| 3 | Availability | GET | `/availability/v2/pe` |
| 4 | Specialties | GET | `/maintainers/v1/specialty/pe` |
| 5 | Professionals | GET | `/maintainers/v2/professional/pe` |
| 6 | Funders | GET | `/maintainers/v1/funder/pe` |
| 7 | Insurance policies | GET | `/insurance-client/v4/pe/policies` |
| 8 | Benefits | GET | `/maintainers/v1/benefit/{productId}/pe` |
| 9 | Create appointment | POST | `/appointments/v3/pe` |

**Base URL (UAT):** `https://17x9fh4a33.execute-api.us-east-1.amazonaws.com/uat`
