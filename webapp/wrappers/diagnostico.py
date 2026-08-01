#!/usr/bin/env python3
"""Usage: diagnostico.py DOMINIO [CLIENTE]"""
import json
import subprocess
import sys
from pathlib import Path

REPO_DIR = Path(__file__).parent.parent.parent.resolve()
SINS = str(REPO_DIR / "sins.sh")
REPORTES_DIR = REPO_DIR / "reportes"

dominio = sys.argv[1] if len(sys.argv) > 1 else ""
cliente_arg = sys.argv[2] if len(sys.argv) > 2 else ""
safe_dom = dominio.replace(".", "_")

# Detect client from most recent session JSON
sessions = sorted(REPORTES_DIR.glob(f"{safe_dom}_*"), reverse=True)
detected = ""
if sessions:
    for pat in [f"report_{safe_dom}.json", f"detailed_{safe_dom}.json"]:
        f = sessions[0] / pat
        if f.exists():
            try:
                d = json.loads(f.read_text())
                c = d.get("client", {})
                detected = c.get("name", "") if isinstance(c, dict) else str(c)
                if detected:
                    break
            except Exception:
                pass

if detected:
    # sins.sh will detect name and ask "¿Usar este nombre? [S/n]" → accept
    stdin = f"{dominio}\nS\ns\nN\n"
elif cliente_arg:
    # No auto-detected → sins.sh asks for name directly
    stdin = f"{dominio}\n{cliente_arg}\ns\nN\n"
else:
    stdin = f"{dominio}\n\ns\nN\n"

proc = subprocess.run(
    ["bash", SINS, "diagnostico"],
    input=stdin, text=True, cwd=str(REPO_DIR),
)
sys.exit(proc.returncode)
