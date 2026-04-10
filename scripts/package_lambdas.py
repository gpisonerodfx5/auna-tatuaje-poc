"""
Empaqueta las Lambdas v2.1 con sus dependencias para despliegue en AWS.

Ejecutar: python scripts/package_lambdas.py
Genera:
  - dist/parser.zip
  - dist/health_check.zip
  - dist/validar_paciente.zip
  - dist/disponibilidad.zip
  - dist/crear_cita.zip
"""

import os
import subprocess
import shutil
import zipfile
import sys
import tempfile

BASE_DIR = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
DIST_DIR = os.path.join(BASE_DIR, "dist")

# Usar tempdir fuera de OneDrive para evitar PermissionError
TEMP_BASE = tempfile.mkdtemp(prefix="auna_pkg_")


def package_lambda(name: str, source_dir: str, dependencies: list[str] = None):
    """Empaqueta una Lambda con sus dependencias en un ZIP."""
    print(f"\n--- Empaquetando {name} ---")

    zip_path = os.path.join(DIST_DIR, f"{name}.zip")
    temp_dir = os.path.join(TEMP_BASE, f"_temp_{name}")

    if os.path.exists(temp_dir):
        shutil.rmtree(temp_dir)
    os.makedirs(temp_dir, exist_ok=True)

    source_file = os.path.join(source_dir, "lambda_function.py")
    if not os.path.exists(source_file):
        print(f"  [ERROR] No encontrado: {source_file}")
        return None
    shutil.copy2(source_file, temp_dir)
    print(f"  Copiado: lambda_function.py")

    if dependencies:
        print(f"  Instalando dependencias: {', '.join(dependencies)}")
        subprocess.run(
            [sys.executable, "-m", "pip", "install"] + dependencies
            + ["-t", temp_dir, "--quiet", "--no-cache-dir"],
            check=True,
        )

    if os.path.exists(zip_path):
        os.remove(zip_path)

    with zipfile.ZipFile(zip_path, "w", zipfile.ZIP_DEFLATED) as zf:
        for root, dirs, files in os.walk(temp_dir):
            for file in files:
                file_path = os.path.join(root, file)
                arcname = os.path.relpath(file_path, temp_dir)
                zf.write(file_path, arcname)

    shutil.rmtree(temp_dir)

    size_mb = os.path.getsize(zip_path) / (1024 * 1024)
    print(f"  [OK] {zip_path} ({size_mb:.1f} MB)")

    return zip_path


def main():
    os.makedirs(DIST_DIR, exist_ok=True)

    # Lambda Parser — solo boto3 (incluido en runtime)
    package_lambda(
        name="parser",
        source_dir=os.path.join(BASE_DIR, "lambda", "parser"),
        dependencies=None,
    )

    # Lambda Health Check — necesita requests
    package_lambda(
        name="health_check",
        source_dir=os.path.join(BASE_DIR, "lambda", "health_check"),
        dependencies=["requests"],
    )

    # Lambda ValidarPaciente — necesita requests
    package_lambda(
        name="validar_paciente",
        source_dir=os.path.join(BASE_DIR, "lambda", "validar_paciente"),
        dependencies=["requests"],
    )

    # Lambda ConsultarDisponibilidad — necesita requests
    package_lambda(
        name="disponibilidad",
        source_dir=os.path.join(BASE_DIR, "lambda", "disponibilidad"),
        dependencies=["requests"],
    )

    # Lambda CrearCita — necesita requests
    package_lambda(
        name="crear_cita",
        source_dir=os.path.join(BASE_DIR, "lambda", "crear_cita"),
        dependencies=["requests"],
    )

    # Limpiar temp base
    shutil.rmtree(TEMP_BASE, ignore_errors=True)

    print(f"\n{'='*50}")
    print(f"[OK] ZIPs listos en {DIST_DIR}/")

    lambdas = {
        "parser":            "auna-tatuaje-poc-parser",
        "health_check":      "auna-tatuaje-poc-health-check",
        "validar_paciente":  "auna-tatuaje-poc-validar-paciente",
        "disponibilidad":    "auna-tatuaje-poc-disponibilidad",
        "crear_cita":        "auna-tatuaje-poc-crear-cita",
    }

    print(f"\nPara desplegar:")
    for zip_name, func_name in lambdas.items():
        print(f"  aws lambda update-function-code \\")
        print(f"    --function-name {func_name} \\")
        print(f"    --zip-file fileb://dist/{zip_name}.zip \\")
        print(f"    --region us-east-1")
        print()


if __name__ == "__main__":
    main()
