#!/usr/bin/env python3
"""Usage: report.py DOMINIO NOMBRE [CIBER]

CIBER truthy ("1"/"ciber"/"true"/"yes") → marco Ley 21.663 (sins.sh report --ciber).
"""
import os
import subprocess
import sys
from pathlib import Path

REPO_DIR = Path(__file__).parent.parent.parent.resolve()
SINS = str(REPO_DIR / "sins.sh")
REPORTES_DIR = REPO_DIR / "reportes"

dominio = sys.argv[1] if len(sys.argv) > 1 else ""
nombre = sys.argv[2] if len(sys.argv) > 2 else ""
ciber = len(sys.argv) > 3 and sys.argv[3].strip().lower() in ("1", "true", "ciber", "yes")

prioritarios = list(REPORTES_DIR.glob("recon_priority_*.txt"))
if prioritarios:
    stdin = f"m\n{dominio}\n{nombre}\ns\n"
else:
    stdin = f"{dominio}\n{nombre}\ns\n"

env = os.environ.copy()
env["BATCH_MODE"] = "1"

# cmd_report parsea --ciber antes del flujo interactivo, así que el stdin
# (dominio/nombre vía menú) sigue siendo válido con o sin el flag.
args = ["bash", SINS, "report"]
if ciber:
    args.append("--ciber")

proc = subprocess.run(
    args, input=stdin, text=True, cwd=str(REPO_DIR), env=env,
)
sys.exit(proc.returncode)
