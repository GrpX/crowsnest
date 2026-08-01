#!/usr/bin/env python3
"""Usage: report.py DOMINIO NOMBRE"""
import os
import subprocess
import sys
from pathlib import Path

REPO_DIR = Path(__file__).parent.parent.parent.resolve()
SINS = str(REPO_DIR / "sins.sh")
REPORTES_DIR = REPO_DIR / "reportes"

dominio = sys.argv[1] if len(sys.argv) > 1 else ""
nombre = sys.argv[2] if len(sys.argv) > 2 else ""
prioritarios = list(REPORTES_DIR.glob("recon_priority_*.txt"))
if prioritarios:
    stdin = f"m\n{dominio}\n{nombre}\ns\n"
else:
    stdin = f"{dominio}\n{nombre}\ns\n"

env = os.environ.copy()
env["BATCH_MODE"] = "1"

proc = subprocess.run(
    ["bash", SINS, "report"],
    input=stdin, text=True, cwd=str(REPO_DIR), env=env,
)
sys.exit(proc.returncode)
