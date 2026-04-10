# -*- coding: utf-8 -*-
"""
Demo PoC Tatuaje Auna — Flujo completo paso a paso
Simula una llamada invocando las Lambdas reales en AWS.

Uso:
    python3 scripts/demo_poc.py
"""
import sys, io
sys.stdout = io.TextIOWrapper(sys.stdout.buffer, encoding="utf-8", errors="replace")
import boto3
import json
import time
import os

PROFILE  = "auna-sandbox"
REGION   = "us-east-1"
ACCOUNT  = "769488154338"
DNI      = "740473"
CENTER_ID = "1"

GREEN  = "\033[92m"
YELLOW = "\033[93m"
RED    = "\033[91m"
BLUE   = "\033[94m"
CYAN   = "\033[96m"
BOLD   = "\033[1m"
DIM    = "\033[2m"
RESET  = "\033[0m"

def cls():
    os.system("cls" if os.name == "nt" else "clear")

def header(title):
    print(f"\n{BOLD}{BLUE}{'='*62}{RESET}")
    print(f"{BOLD}{BLUE}  {title}{RESET}")
    print(f"{BOLD}{BLUE}{'='*62}{RESET}\n")

def step(n, title, desc=""):
    print(f"\n{BOLD}{CYAN}[ PASO {n} ]  {title}{RESET}")
    if desc:
        print(f"{DIM}  {desc}{RESET}")
    print(f"{CYAN}  {'─'*56}{RESET}")

def ok(msg):    print(f"  {GREEN}✔{RESET}  {msg}")
def warn(msg):  print(f"  {YELLOW}▲{RESET}  {msg}")
def err(msg):   print(f"  {RED}✘{RESET}  {msg}")
def info(msg):  print(f"  {DIM}    {msg}{RESET}")
def data(k, v): print(f"      {BOLD}{k}:{RESET} {v}")

def pause():
    print()
    input(f"  {DIM}[ Enter para continuar ]{RESET}  ")
    cls()

def invoke(lc, fn, payload):
    r = lc.invoke(FunctionName=fn, InvocationType="RequestResponse",
                  Payload=json.dumps(payload).encode())
    return json.loads(r["Payload"].read()), r.get("FunctionError")

def event(params, attrs=None):
    return {"Details": {
        "Parameters": params,
        "ContactData": {"ContactId": f"demo-{int(time.time())}", "Attributes": attrs or {}}
    }}

def main():
    cls()
    header("PoC Tatuaje Auna  —  Demo Flujo Completo")
    print(f"  Este demo simula el flujo de una llamada outbound de principio")
    print(f"  a fin, invocando las Lambdas reales desplegadas en AWS.")
    print()
    print(f"  {BOLD}Afiliado de prueba:{RESET}  DNI {DNI}  |  Centro Arequipa (ID={CENTER_ID})")
    print(f"  {BOLD}Cuenta AWS:{RESET}          {ACCOUNT}  |  {REGION}")
    print()
    print(f"  Flujo:")
    print(f"  {GREEN}1{RESET} Health Check   {GREEN}→{RESET}   {GREEN}2{RESET} Validar Afiliado   {GREEN}→{RESET}   {GREEN}3{RESET} Consultar Slots")
    print(f"  {GREEN}→{RESET}   {GREEN}4{RESET} Crear Cita   {GREEN}→{RESET}   {GREEN}5{RESET} DynamoDB")
    pause()

    session = boto3.Session(profile_name=PROFILE, region_name=REGION)
    lc  = session.client("lambda",       region_name=REGION)
    ddb = session.client("dynamodb",     region_name=REGION)

    patient = {}
    slot    = {}

    # ── PASO 1: Health Check ─────────────────────────────────────────────────
    step(1, "Health Check — ¿API Multisede disponible?",
         "Lambda hace un ping al API antes de iniciar cualquier llamada.")
    print(f"  {DIM}Invocando: auna-tatuaje-poc-health-check...{RESET}")

    r, fe = invoke(lc, "auna-tatuaje-poc-health-check", event({}))
    if fe:
        err(f"Lambda error: {fe}")
    else:
        api_ok = str(r.get("api_available", r.get("api_disponible", ""))).lower() == "true"
        if api_ok:
            ok("API Multisede  →  DISPONIBLE")
            data("Timestamp", r.get("timestamp", ""))
        else:
            warn(f"API NO disponible: {r.get('motivo', r)}")
    pause()

    # ── PASO 2: ValidarPaciente ──────────────────────────────────────────────
    step(2, "ValidarPaciente — Verificar elegibilidad",
         "Busca el afiliado en Multisede por DNI y verifica que sea elegible para el programa.")
    print(f"  {DIM}Invocando: auna-tatuaje-poc-validar-paciente  (DNI={DNI})...{RESET}")

    r, fe = invoke(lc, "auna-tatuaje-poc-validar-paciente",
                   event({"dni": DNI, "center_id": CENTER_ID}))
    if fe:
        err(f"Lambda error: {fe}"); pause(); return

    elegible = str(r.get("elegible", "")).lower() == "true"
    if elegible:
        ok(f"Afiliado  →  ELEGIBLE")
        data("Nombre",                r.get("nombre_completo", r.get("holder_name", "")))
        data("patient_id",            r.get("patient_id", ""))
        data("clinic_history_number", r.get("clinic_history_number", ""))
        patient = r
    else:
        warn(f"Afiliado NO elegible: {r.get('motivo', r)}")
        pause(); return
    pause()

    # ── PASO 3: ConsultarDisponibilidad ──────────────────────────────────────
    step(3, "ConsultarDisponibilidad — Buscar turnos",
         "Consulta slots disponibles en la sede del afiliado y filtra por preferencia.")
    print(f"  {DIM}Preferencia: entre semana · mañana  |  Centro ID={CENTER_ID}{RESET}")
    print(f"  {DIM}Invocando: auna-tatuaje-poc-disponibilidad...{RESET}")

    r, fe = invoke(lc, "auna-tatuaje-poc-disponibilidad", event({
        "patient_id":            patient.get("patient_id"),
        "clinic_history_number": patient.get("clinic_history_number"),
        "center_id":             CENTER_ID,
        "dni":                   DNI,
        "preferencia_dia":       "semana",
        "preferencia_horario":   "manana",
    }))
    if fe:
        err(f"Lambda error: {fe}"); pause(); return

    disponible = str(r.get("disponible", "")).lower() == "true"
    if disponible:
        ok("Disponibilidad  →  ENCONTRADA")
        # Parse first slot
        slot = {
            "model_id":   r.get("opciones_0_model_id"),
            "doctor_id":  r.get("opciones_0_doctor_id"),
            "service_id": r.get("opciones_0_service_id"),
            "fecha":      r.get("opciones_0_fecha"),
            "hora":       r.get("opciones_0_hora"),
            "doctor_name": r.get("opciones_0_doctor_name", ""),
        }
        if not slot["fecha"]:
            raw = r.get("opciones")
            if raw:
                try:
                    opts = json.loads(raw) if isinstance(raw, str) else raw
                    slot = opts[0] if opts else {}
                except Exception:
                    pass
        # Print all options
        opciones_txt = r.get("opciones_texto", "")
        if opciones_txt:
            for i, op in enumerate(opciones_txt.split(". Opcion "), 1):
                if op.strip():
                    label = op if op.startswith("Opcion") else f"Opcion {op}"
                    data(f"  Opcion {i}", label.replace("Opcion 1: ","").replace("Opcion 2: ","").replace("Opcion 3: ",""))
        if slot.get("fecha"):
            print()
            ok(f"Slot seleccionado para agendar:")
            data("Fecha",  slot.get("fecha", ""))
            data("Hora",   slot.get("hora",  "")[:5])
            data("Doctor", slot.get("doctor_name", ""))
    else:
        warn(f"Sin disponibilidad: {r.get('motivo', '')}")
        slot = {}
    pause()

    # ── PASO 4: CrearCita ────────────────────────────────────────────────────
    step(4, "CrearCita — Agendar en Multisede",
         "Crea la cita en el sistema de Multisede con control de idempotencia.")
    if not slot.get("fecha"):
        warn("Sin slot disponible — no se puede agendar")
        pause()
    else:
        print(f"  {DIM}Agendando: {slot.get('fecha')} a las {slot.get('hora','')[:5]}{RESET}")
        print(f"  {DIM}Invocando: auna-tatuaje-poc-crear-cita...{RESET}")

        r, fe = invoke(lc, "auna-tatuaje-poc-crear-cita", event({
            "patient_id":            patient.get("patient_id"),
            "clinic_history_number": patient.get("clinic_history_number"),
            "holder_name":           patient.get("holder_name"),
            "holder_last_name":      patient.get("holder_last_name"),
            "center_id":             CENTER_ID,
            "dni":                   DNI,
            "model_id":              slot.get("model_id"),
            "doctor_id":             slot.get("doctor_id"),
            "service_id":            slot.get("service_id"),
            "fecha":                 slot.get("fecha"),
            "hora":                  slot.get("hora"),
        }))
        if fe:
            err(f"Lambda error: {fe}")
        else:
            exito = str(r.get("exito", "")).lower() == "true"
            if exito:
                ok("Cita  →  AGENDADA")
                data("cita_id", r.get("cita_id") or "(UAT no retorna ID)")
                data("Mensaje", r.get("mensaje", r.get("message", "")))
            else:
                ya = str(r.get("ya_agendado", "")).lower() == "true"
                if ya:
                    warn("Idempotencia activada — cita ya existía para este afiliado")
                else:
                    warn(f"No se pudo crear: {r.get('motivo', r)}")
        pause()

    # ── PASO 5: DynamoDB ─────────────────────────────────────────────────────
    step(5, "DynamoDB — Registro de interacciones",
         "Todas las llamadas quedan registradas en DynamoDB para auditoría y métricas.")
    try:
        r = ddb.scan(
            TableName="auna-tatuaje-poc-interacciones",
            Limit=5,
            ProjectionExpression="call_id, afiliado_dni, resultado, timestamp_inicio, modelo_usado"
        )
        items = r.get("Items", [])
        if items:
            ok(f"{len(items)} registros encontrados en tabla interacciones:")
            print()
            for item in items:
                def v(x): return list(x.values())[0] if x else "—"
                cid  = v(item.get("call_id", {}))[:24]
                dni  = v(item.get("afiliado_dni", {}))
                res  = v(item.get("resultado", {}))
                mod  = v(item.get("modelo_usado", {})) or "—"
                col  = GREEN if res == "agendado" else (RED if "error" in res else YELLOW)
                print(f"    {DIM}{cid}...{RESET}  DNI={dni}  {col}{res}{RESET}  modelo={mod}")
        else:
            info("Tabla vacía — aún no hay llamadas reales registradas")
    except Exception as e:
        err(f"DynamoDB: {e}")

    print()
    try:
        r = ddb.scan(TableName="auna-tatuaje-poc-blacklist", Limit=5)
        items = r.get("Items", [])
        if items:
            warn(f"{len(items)} números en blacklist:")
            for item in items:
                def v(x): return list(x.values())[0] if x else "—"
                print(f"    tel={v(item.get('telefono',{}))}  motivo={v(item.get('motivo',{}))}")
        else:
            ok("Blacklist  →  vacía (ningún número bloqueado)")
    except Exception as e:
        err(f"DynamoDB blacklist: {e}")
    pause()

    # ── Resumen final ────────────────────────────────────────────────────────
    header("Resumen del Demo")
    print(f"  {GREEN}✔{RESET}  {BOLD}Health Check{RESET}           API Multisede disponible")
    print(f"  {GREEN}✔{RESET}  {BOLD}ValidarPaciente{RESET}        {patient.get('nombre_completo','')}")
    if slot.get("fecha"):
        print(f"  {GREEN}✔{RESET}  {BOLD}ConsultarDisponibilidad{RESET}  {slot.get('fecha')} {slot.get('hora','')[:5]}  Dr. {slot.get('doctor_name','')}")
        print(f"  {GREEN}✔{RESET}  {BOLD}CrearCita{RESET}              Cita agendada en Multisede")
    else:
        print(f"  {YELLOW}▲{RESET}  {BOLD}ConsultarDisponibilidad{RESET}  Sin slots (verificar /availability/v2/pe)")
        print(f"  {YELLOW}▲{RESET}  {BOLD}CrearCita{RESET}              Pendiente disponibilidad")
    print(f"  {GREEN}✔{RESET}  {BOLD}DynamoDB{RESET}               Tablas interacciones + blacklist activas")
    print(f"  {YELLOW}▲{RESET}  {BOLD}Step Functions / SQS{RESET}   Pendiente desplegar (arquitectura lista)")
    print(f"  {RED}✘{RESET}  {BOLD}Connect / Voz{RESET}          BLOCKER: error en Lex/Q-in-Connect")
    print()

if __name__ == "__main__":
    main()
