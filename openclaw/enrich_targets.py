#!/usr/bin/env python3
"""Enriquece db/targets.json con datos del flash JSON de cada target.

Para cada target en estado recon o enriched, busca la sesion de scan mas
reciente en reportes/<dominio_con_guiones>_<fecha>/, lee el flash_*.json y
agrega un bloque "scan_data" al target. No toca los descartados.
"""
import json
import os
import re
import sys
from collections import Counter

REPO = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
if REPO not in sys.path:
    sys.path.insert(0, REPO)
from lib.states import ENRICHED, RECON  # noqa: E402

DB = os.path.join(REPO, "db", "targets.json")
REPORTES = os.path.join(REPO, "reportes")

# Folder name: <dominio_con_guiones>_<YYYYMMDD>_<HHMMSS>
SESSION_RE = re.compile(r"^(.+)_(\d{8})_(\d{6})$")

SEV_RANK = {"critical": 0, "high": 1, "medium": 2, "low": 3, "info": 4}


def index_sessions():
    """domain_underscore -> [(timestamp, folder_path)] ordenado desc por ts."""
    sessions = {}
    for entry in os.listdir(REPORTES):
        path = os.path.join(REPORTES, entry)
        if not os.path.isdir(path):
            continue
        m = SESSION_RE.match(entry)
        if not m:
            continue
        dom, day, time = m.groups()
        sessions.setdefault(dom, []).append((day + time, path))
    for dom in sessions:
        sessions[dom].sort(key=lambda x: x[0], reverse=True)
    return sessions


def load_flash(folder, dom_underscore):
    """Devuelve el dict del flash JSON de la sesion, o None."""
    exact = os.path.join(folder, f"flash_{dom_underscore}.json")
    candidates = [exact] if os.path.isfile(exact) else []
    if not candidates:
        candidates = [
            os.path.join(folder, f)
            for f in os.listdir(folder)
            if f.startswith("flash_") and f.endswith(".json")
        ]
    for c in candidates:
        try:
            with open(c, encoding="utf-8") as fh:
                return json.load(fh)
        except (json.JSONDecodeError, OSError):
            continue
    return None


def extract_scan_data(flash):
    es = flash.get("executive_summary", {}) or {}
    by_sev = es.get("findings_by_severity", {}) or {}

    findings = flash.get("findings", []) or []
    ordered = sorted(
        findings,
        key=lambda f: (
            f.get("severity_priority", SEV_RANK.get(f.get("severity"), 99)),
            str(f.get("id", "")),
        ),
    )
    top = [
        {
            "id": f.get("id"),
            "name": f.get("name"),
            "severity": f.get("severity"),
            "category": f.get("category"),
        }
        for f in ordered[:3]
    ]

    rec = es.get("key_recommendation")
    if isinstance(rec, str):
        rec = rec[:150]

    return {
        "risk_score": es.get("risk_score"),
        "risk_level": es.get("risk_level"),
        "total_findings": es.get("total_findings"),
        "high_findings": by_sev.get("high"),
        "medium_findings": by_sev.get("medium"),
        "email_security_status": es.get("email_security_status"),
        "key_recommendation": rec,
        "top_findings": top,
    }


def main():
    solo = set(sys.argv[1:])  # dominios opcionales: enriquece solo esos

    with open(DB, encoding="utf-8") as fh:
        db = json.load(fh)

    sessions = index_sessions()
    targets = db["targets"]

    enriquecidos = []
    sin_sesion = []
    sin_flash = []

    for dominio, p in targets.items():
        if not isinstance(p, dict):
            continue
        if p.get("status") not in (RECON, ENRICHED):
            continue
        if solo and dominio not in solo:
            continue

        dom_underscore = dominio.replace(".", "_")
        matches = sessions.get(dom_underscore)
        if not matches:
            sin_sesion.append(dominio)
            continue

        # Usa la sesion mas reciente que tenga un flash JSON valido
        # (ignora carpetas de scans incompletos/fallidos).
        flash = None
        for _ts, folder in matches:
            flash = load_flash(folder, dom_underscore)
            if flash is not None:
                break
        if flash is None:
            sin_flash.append(dominio)
            continue

        scan = extract_scan_data(flash)
        scan["session_folder"] = os.path.basename(folder)
        p["scan_data"] = scan
        p["status"] = ENRICHED
        enriquecidos.append((dominio, scan["risk_score"], scan["risk_level"]))

    with open(DB, "w", encoding="utf-8") as fh:
        json.dump(db, fh, indent=2, ensure_ascii=False)
        fh.write("\n")

    # Validacion
    with open(DB, encoding="utf-8") as fh:
        json.load(fh)

    # ---- Reporte ----
    print("=" * 60)
    print("ENRIQUECIMIENTO DE TARGETS — REPORTE")
    print("=" * 60)
    print(f"Total targets enriquecidos : {len(enriquecidos)}")
    print(f"Sin sesion en reportes/        : {len(sin_sesion)}")
    if sin_flash:
        print(f"Con carpeta pero sin flash JSON: {len(sin_flash)}")

    niveles = Counter(lvl for _, _, lvl in enriquecidos)
    print("\nDistribucion de risk_level:")
    for lvl in ("Alto", "Medio", "Bajo"):
        print(f"  {lvl:6}: {niveles.get(lvl, 0)}")
    otros = {k: v for k, v in niveles.items() if k not in ("Alto", "Medio", "Bajo")}
    for k, v in otros.items():
        print(f"  {k!r}: {v}")

    ranked = sorted(enriquecidos, key=lambda x: (x[1] is None, -(x[1] or 0)))
    if solo:
        print("\nTargets enriquecidos por risk_score:")
    else:
        print("\nTop 5 targets por risk_score:")
        ranked = ranked[:5]
    for dom, score, lvl in ranked:
        print(f"  {score:>4}  {lvl:6}  {dom}")

    if sin_sesion:
        print(f"\nSin sesion encontrada ({len(sin_sesion)}):")
        for d in sorted(sin_sesion):
            print(f"  - {d}")

    print("\nJSON valido: OK (json.load sin error)")
    print("=" * 60)


if __name__ == "__main__":
    main()
