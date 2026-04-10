"""
Script para descubrir los IDs necesarios para la PoC Tatuaje
Ejecutar localmente: python discover_ids.py
Los resultados van al archivo ids_output.json para luego hardcodear en Lambda
"""
import requests
import json

BASE = "https://17x9fh4a33.execute-api.us-east-1.amazonaws.com/uat"
USERNAME = "ext2700"
PASSWORD = "Auna2026"

# Centers relevantes para Lima (de la documentación confirmada)
LIMA_CENTERS = {
    4:  "Delgado",
    8:  "OC Benavides",
    9:  "OC Encalada",
    10: "Auna Guardia Civil",
    11: "OC San Isidro",
    14: "Oncocenter San Borja",
    15: "Bellavista",
    18: "Centro de Bienestar Independencia",
    19: "Benavides",
}

def login():
    print("=== LOGIN ===")
    r = requests.post(f"{BASE}/authentication/v1/login",
                      json={"username": USERNAME, "password": PASSWORD})
    r.raise_for_status()
    data = r.json()
    # Token puede estar en raíz o dentro de "results"
    if "results" in data and "accessToken" in data["results"]:
        token = data["results"]["accessToken"]
    else:
        token = data["accessToken"]
    print(f"[OK] Token OK (primeros 30 chars): {token[:30]}...")
    return token

def get_headers(token):
    return {"Authorization": f"Bearer {token}", "Content-Type": "application/json"}

def get_specialties(token):
    print("\n=== ESPECIALIDADES ===")
    r = requests.get(f"{BASE}/maintainers/v1/specialty/pe", headers=get_headers(token))
    r.raise_for_status()
    specialties = r.json()["results"]
    print(f"Total especialidades: {len(specialties)}")
    # Buscar las relevantes para Tatuaje/Oncosalud
    keywords = ["general", "preventiv", "oncol", "medicina", "chequeo", "control"]
    print("\nEspecialidades relevantes:")
    relevant = []
    for s in specialties:
        name_lower = s["name"].lower()
        if any(k in name_lower for k in keywords):
            print(f"  id={s['specialtyId']} | {s['name']}")
            relevant.append(s)
    print("\nTodas las especialidades:")
    for s in specialties:
        print(f"  id={s['specialtyId']} | {s['name']}")
    return specialties, relevant

def get_funders(token):
    print("\n=== FINANCIADORES POR CENTRO ===")
    all_funders = {}
    for center_id, center_name in LIMA_CENTERS.items():
        r = requests.get(f"{BASE}/maintainers/v1/funder/pe",
                         headers=get_headers(token),
                         params={"centerId": center_id})
        if r.status_code == 200:
            funders = r.json().get("results", [])
            print(f"\n  Centro {center_id} ({center_name}): {len(funders)} financiadores")
            for f in funders:
                name_lower = f["name"].lower().replace("*", "").strip()
                if any(k in name_lower for k in ["auna", "oncosalud", "salud"]):
                    print(f"    >>> funderId={f['funderId']} | {f['name']}")
                    for p in f.get("products", []):
                        print(f"       productId={p['productId']} | {p['name']}")
                        for pl in p.get("plans", []):
                            print(f"         planId={pl['planId']} | {pl['name']}")
            all_funders[center_id] = funders
        else:
            print(f"  Centro {center_id} ({center_name}): ERROR {r.status_code}")
    return all_funders

def get_benefits(token, product_ids):
    print("\n=== BENEFICIOS POR PRODUCTO ===")
    all_benefits = {}
    for pid in product_ids:
        r = requests.get(f"{BASE}/maintainers/v1/benefit/{pid}/pe",
                         headers=get_headers(token))
        if r.status_code == 200:
            benefits = r.json().get("results", [])
            print(f"\n  productId={pid}: {len(benefits)} beneficios")
            for b in benefits:
                name_lower = b["name"].lower()
                if any(k in name_lower for k in ["consul", "gratui", "ambulat", "preventiv", "chequeo"]):
                    print(f"    >>> benefitId={b['benefitId']} | code={b['benefitCode']} | {b['name']}")
            all_benefits[pid] = benefits
        else:
            print(f"  productId={pid}: ERROR {r.status_code}")
    return all_benefits

def check_availability(token, specialty_id, center_id=4):
    print(f"\n=== DISPONIBILIDAD (specialtyId={specialty_id}, filtro centerId={center_id}) ===")
    r = requests.get(f"{BASE}/availability/v2/pe",
                     headers=get_headers(token),
                     params={"specialtyId": specialty_id, "visitTypeIds": "PS,CM", "count": 10, "offset": 0})
    if r.status_code == 200:
        results = r.json().get("results", [])
        print(f"  Total slots: {len(results)}")
        # Filter by center
        filtered = [x for x in results if x.get("centerId") == center_id]
        print(f"  Slots en centerId={center_id}: {len(filtered)}")
        for slot in filtered[:3]:
            print(f"    {slot['centerName']} | {slot['professionalName']} | {slot['date'][:10]}")
            for sch in slot.get("schedules", [])[:2]:
                print(f"      modelId={sch['modelId']} | {sch['time']} | status={sch['status']}")
    else:
        print(f"  ERROR {r.status_code}: {r.text[:200]}")

def search_patient(token, dni="73191563"):
    print(f"\n=== BUSCAR PACIENTE (DNI={dni}) ===")
    r = requests.post(f"{BASE}/maintainers/v1/search-patient/pe",
                      headers=get_headers(token),
                      json={"document_number": dni, "pagination": {"number": 1, "size": 5}})
    if r.status_code == 200:
        results = r.json().get("results", [])
        print(f"  Resultados: {len(results)}")
        for p in results:
            f = p.get("fields", {})
            print(f"  id={p['id']} | clinicHistoryNumber={f.get('medical_record_number')} | {f.get('first_name')} {f.get('last_name')}")
        return results
    else:
        print(f"  ERROR {r.status_code}: {r.text[:200]}")
        return []

def main():
    output = {}

    token = login()
    output["token_sample"] = token[:30]

    # 1. Especialidades
    specialties, relevant = get_specialties(token)
    output["specialties_relevant"] = relevant

    # 2. Financiadores — usar centerId 4 (Delgado) como base
    funders = get_funders(token)
    output["funders_center4"] = funders.get(4, [])

    # 3. Beneficios — probar con los productIds que encontremos de Auna/Oncosalud
    # Primero extraer productIds del funder de Auna/Oncosalud
    product_ids_to_check = set()
    for center_id, funder_list in funders.items():
        for f in funder_list:
            if any(k in f["name"].lower().replace("*","") for k in ["auna", "oncosalud"]):
                for p in f.get("products", []):
                    product_ids_to_check.add(p["productId"])

    print(f"\nProductIds a revisar: {product_ids_to_check}")
    if product_ids_to_check:
        benefits = get_benefits(token, list(product_ids_to_check)[:5])
        output["benefits"] = {str(k): v for k, v in benefits.items()}

    # 4. Buscar paciente de prueba con DNI del Excel
    patients = search_patient(token)
    output["test_patient"] = patients

    # 5. Si tenemos specialtyId de adelanto preventivo, probar disponibilidad
    # Probar con id 1 primero como fallback
    if relevant:
        check_availability(token, relevant[0]["specialtyId"])

    # Guardar output
    with open("ids_output.json", "w", encoding="utf-8") as f:
        json.dump(output, f, ensure_ascii=False, indent=2, default=str)
    print("\n[OK] Resultados guardados en ids_output.json")
    print("   Comparte ese archivo para continuar con la PoC.")

if __name__ == "__main__":
    main()
