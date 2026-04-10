"""
Genera el CSV de prueba para la PoC a partir del Excel BASE_MARZO.xlsx
Filtra solo afiliados con consentimiento=SI y teléfono disponible.
Mapea distrito → centerId según la tabla de centros confirmada.

Uso: python generate_csv.py [--limit 10]
"""
import pandas as pd
import argparse
import sys

# Mapeo distrito → centerId (confirmado con documentación Multisede)
DISTRITO_A_CENTER_ID = {
    "SAN ISIDRO":               11,
    "MIRAFLORES":               11,
    "SAN BORJA":                11,
    "SURQUILLO":                11,
    "BARRANCO":                 11,
    "SANTIAGO DE SURCO":        8,
    "CHORRILLOS":               8,
    "LA MOLINA":                8,
    "VILLA MARIA DEL TRIUNFO":  8,
    "VILLA EL SALVADOR":        8,
    "SAN MIGUEL":               9,
    "PUEBLO LIBRE":             9,
    "JESUS MARIA":              9,
    "MAGDALENA DEL MAR":        9,
    "LINCE":                    9,
    "BREÑA":                    9,
    "CALLAO":                   15,
    "BELLAVISTA":               15,
    "LA PERLA":                 15,
    "VENTANILLA":               15,
    "CARMEN DE LA LEGUA":       15,
    "SAN MARTIN DE PORRES":     10,
    "LOS OLIVOS":               10,
    "COMAS":                    18,
    "INDEPENDENCIA":            18,
    "SAN JUAN DE LURIGANCHO":   18,
    "ATE":                      18,
    "EL AGUSTINO":              18,
    "SANTA ANITA":              18,
    "LURIGANCHO":               18,
    "SAN JUAN DE MIRAFLORES":   8,
    "LIMA":                     4,
    "RIMAC":                    4,
    "SAN LUIS":                 4,
    "LA VICTORIA":              4,
    "CERCADO DE LIMA":          4,
    "PUEBLO LIBRE":             9,
    "SURCO":                    8,
}

def formatear_telefono(raw) -> str:
    if pd.isna(raw) or not raw:
        return ""
    num = str(raw).strip().split(".")[0]
    num = "".join(filter(str.isdigit, num))
    if not num:
        return ""
    if num.startswith("51") and len(num) == 11:
        return f"+{num}"
    if len(num) == 9:
        return f"+51{num}"
    return ""

def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--input",  default="BASE_MARZO.xlsx", help="Excel de entrada")
    parser.add_argument("--output", default="afiliados_poc.csv", help="CSV de salida")
    parser.add_argument("--limit",  type=int, default=None, help="Limitar registros (pruebas)")
    parser.add_argument("--sheet",  default="6 a 11", help="Hoja del Excel")
    args = parser.parse_args()

    print(f"📖 Leyendo {args.input} (hoja: {args.sheet})...")
    df = pd.read_excel(args.input, sheet_name=args.sheet)
    print(f"   Total registros: {len(df)}")

    # Filtrar por consentimiento
    df_consent = df[df["consentimiento"].str.upper().isin(["SI", "SÍ"])].copy()
    print(f"   Con consentimiento SI: {len(df_consent)}")

    # Formatear teléfono principal (afiliado primero, luego contratante)
    df_consent["telefono_formateado"] = df_consent["celular_afil_1"].apply(formatear_telefono)
    mask_sin_tel = df_consent["telefono_formateado"] == ""
    df_consent.loc[mask_sin_tel, "telefono_formateado"] = \
        df_consent.loc[mask_sin_tel, "celular_contratante_1"].apply(formatear_telefono)

    df_validos = df_consent[df_consent["telefono_formateado"] != ""].copy()
    print(f"   Con teléfono válido: {len(df_validos)}")

    # Mapear distrito → centerId
    df_validos["sede_referencia"] = df_validos["distrito_afil"].str.strip().str.upper()\
        .map(DISTRITO_A_CENTER_ID).fillna(4).astype(int)

    # Mostrar distribución de sedes
    print(f"\n   Distribución por sede:")
    sede_dist = df_validos["sede_referencia"].value_counts()
    center_names = {4:"Delgado",8:"OC Benavides",9:"OC Encalada",10:"Auna Guardia Civil",
                    11:"OC San Isidro",14:"Oncocenter San Borja",15:"Bellavista",18:"C.B. Independencia"}
    for sede_id, count in sede_dist.items():
        print(f"     centerId={sede_id} ({center_names.get(sede_id,'?')}): {count} afiliados")

    # Aplicar límite si se especificó
    if args.limit:
        df_validos = df_validos.head(args.limit)
        print(f"\n   Limitado a {args.limit} registros para pruebas")

    # Construir CSV final
    csv_data = pd.DataFrame({
        "numero_documento_afil": df_validos["numero_documento_afil"].astype(str).str.strip(),
        "apellidos_nombres_afil": df_validos["apellidos_nombres_afil"].str.strip().str.title(),
        "telefono":               df_validos["telefono_formateado"],
        "programa_final":         df_validos["programa_final"].str.strip(),
        "sede_referencia":        df_validos["sede_referencia"],
        "cantidad_cuotas_pagadas": df_validos["cantidad_cuotas_pagadas"],
        "grupo_cuota_pagada":     df_validos["grupo_cuota_pagada"],
        "consentimiento":         df_validos["consentimiento"],
        "distrito_afil":          df_validos["distrito_afil"],
    })

    csv_data.to_csv(args.output, index=False, encoding="utf-8")
    print(f"\n✅ CSV generado: {args.output}")
    print(f"   Registros: {len(csv_data)}")
    print(f"\n   Muestra de los primeros 3 registros:")
    print(csv_data.head(3).to_string())

    print(f"\n🤖 Para subir a S3:")
    print(f"   aws s3 cp {args.output} s3://auna-tatuaje-poc-input-{{ACCOUNT_ID}}/input/{args.output}")

if __name__ == "__main__":
    main()
