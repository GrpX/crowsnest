#!/usr/bin/env python3
"""Usage: diagnostico.py DOMINIO [CLIENTE]"""
import json
import subprocess
import sys
from pathlib import Path

REPO_DIR = Path(__file__).parent.parent.parent.resolve()
CROWSNEST = str(REPO_DIR / "crowsnest.sh")
REPORTS_DIR = REPO_DIR / "reports"

dominio = sys.argv[1] if len(sys.argv) > 1 else ""
cliente_arg = sys.argv[2] if len(sys.argv) > 2 else ""
safe_dom = dominio.replace(".", "_")

# Detect client from most recent session JSON
sessions = sorted(REPORTS_DIR.glob(f"{safe_dom}_*"), reverse=True)
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
    # crowsnest.sh will detect name and ask "¿Usar este nombre? [S/n]" → accept
    stdin = f"{dominio}\nY\ny\nN\n"
elif cliente_arg:
    # No auto-detected → crowsnest.sh asks for name directly
    stdin = f"{dominio}\n{cliente_arg}\ny\nN\n"
else:
    stdin = f"{dominio}\n\ny\nN\n"

proc = subprocess.run(
    ["bash", CROWSNEST, "diagnostico"],
    input=stdin, text=True, cwd=str(REPO_DIR),
)
sys.exit(proc.returncode)
