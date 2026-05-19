"""
Empaqueta las 5 Lambdas + layer compartido `requests` (Linux x86_64, py3.12).

Uso:
    python scripts/package_lambdas.py

Genera:
    dist/parser.zip
    dist/health_check.zip
    dist/validar_paciente.zip
    dist/disponibilidad.zip
    dist/crear_cita.zip
    dist/layer_requests.zip  (deps compartidas — montadas como Lambda Layer)

Notas:
- Cada zip de Lambda contiene SOLO el código (lambda_function.py).
- Las dependencias externas (requests) van en el Layer compartido,
  para que las Lambdas pesen pocos KB y compartan el mismo `requests` cacheado.
- El layer se compila con --platform manylinux2014_x86_64 --python-version 3.12
  para asegurar compatibilidad con el runtime de Lambda.
"""

import os
import shutil
import subprocess
import sys
import tempfile
import zipfile
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
DIST = ROOT / "dist"
LAMBDA_DIR = ROOT / "lambda"

LAMBDAS = ["parser", "health_check", "validar_paciente", "disponibilidad", "crear_cita"]
LAYER_DEPS = ["requests"]
PY_VERSION = "3.12"


def zip_lambda(name: str) -> Path:
    src = LAMBDA_DIR / name / "lambda_function.py"
    if not src.exists():
        raise FileNotFoundError(src)
    out = DIST / f"{name}.zip"
    with zipfile.ZipFile(out, "w", zipfile.ZIP_DEFLATED) as zf:
        zf.write(src, "lambda_function.py")
    print(f"  [OK] {out.name} ({out.stat().st_size:,} bytes)")
    return out


def build_layer() -> Path:
    tmp = Path(tempfile.mkdtemp(prefix="auna_layer_"))
    python_dir = tmp / "python"
    python_dir.mkdir(parents=True)
    print(f"  Instalando {LAYER_DEPS} para Linux x86_64 / py{PY_VERSION}...")
    subprocess.run(
        [
            sys.executable, "-m", "pip", "install",
            "--platform", "manylinux2014_x86_64",
            "--target", str(python_dir),
            "--implementation", "cp",
            "--python-version", PY_VERSION,
            "--only-binary=:all:",
            "--upgrade",
            "--quiet",
            *LAYER_DEPS,
        ],
        check=True,
    )
    out = DIST / "layer_requests.zip"
    with zipfile.ZipFile(out, "w", zipfile.ZIP_DEFLATED) as zf:
        for f in python_dir.rglob("*"):
            if f.is_file():
                zf.write(f, f.relative_to(tmp))
    shutil.rmtree(tmp, ignore_errors=True)
    print(f"  [OK] {out.name} ({out.stat().st_size:,} bytes)")
    return out


def main() -> int:
    DIST.mkdir(exist_ok=True)
    print("[1/2] Empaquetando Lambdas (solo código)...")
    for name in LAMBDAS:
        zip_lambda(name)
    print()
    print("[2/2] Construyendo Lambda Layer compartido...")
    build_layer()
    print()
    print(f"Listo. Outputs en: {DIST}/")
    print()
    print("Para desplegarlas, ejecutar:")
    print("    python scripts/deploy_lambdas.py --profile <perfil-aws>")
    return 0


if __name__ == "__main__":
    sys.exit(main())
