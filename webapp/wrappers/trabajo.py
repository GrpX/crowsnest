#!/usr/bin/env python3
"""Usage: trabajo.py DOMINIO CLIENTE AUTH_REF"""
import subprocess
import sys
from pathlib import Path

REPO_DIR = Path(__file__).parent.parent.parent.resolve()
CROWSNEST = str(REPO_DIR / "crowsnest.sh")

dominio  = sys.argv[1] if len(sys.argv) > 1 else ""
cliente  = sys.argv[2] if len(sys.argv) > 2 else ""
auth_ref = sys.argv[3] if len(sys.argv) > 3 else ""

stdin = f"{dominio}\n{cliente}\n{auth_ref}\ny\nN\n"

proc = subprocess.run(
    ["bash", CROWSNEST, "trabajo"],
    input=stdin, text=True, cwd=str(REPO_DIR),
)
sys.exit(proc.returncode)
