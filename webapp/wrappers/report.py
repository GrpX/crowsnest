#!/usr/bin/env python3
"""Usage: report.py DOMINIO NOMBRE"""
import os
import subprocess
import sys
from pathlib import Path

REPO_DIR = Path(__file__).parent.parent.parent.resolve()
CROWSNEST = str(REPO_DIR / "crowsnest.sh")
REPORTES_DIR = REPO_DIR / "reportes"

dominio = sys.argv[1] if len(sys.argv) > 1 else ""
nombre = sys.argv[2] if len(sys.argv) > 2 else ""
prioritarios = list(REPORTES_DIR.glob("recon_priority_*.txt"))
if prioritarios:
    stdin = f"m\n{dominio}\n{nombre}\ny\n"
else:
    stdin = f"{dominio}\n{nombre}\ny\n"

env = os.environ.copy()
env["CROWSNEST_BATCH_MODE"] = "1"

proc = subprocess.run(
    ["bash", CROWSNEST, "report"],
    input=stdin, text=True, cwd=str(REPO_DIR), env=env,
)
sys.exit(proc.returncode)
