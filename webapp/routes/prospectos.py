import json
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent.parent))

from flask import Blueprint, jsonify, request
from flask_login import login_required

bp = Blueprint("prospectos", __name__)

REPO_DIR = Path(__file__).parent.parent.parent.resolve()
DB_FILE = REPO_DIR / "db" / "prospectos.json"


def _read_db() -> dict:
    if DB_FILE.exists():
        return json.loads(DB_FILE.read_text(encoding="utf-8"))
    return {"version": 1, "prospectos": {}}


def _write_db(db: dict):
    DB_FILE.parent.mkdir(parents=True, exist_ok=True)
    DB_FILE.write_text(
        json.dumps(db, ensure_ascii=False, indent=2), encoding="utf-8"
    )


@bp.route("/api/prospectos")
@login_required
def list_prospectos():
    db = _read_db()
    result = []
    for dominio, info in db.get("prospectos", {}).items():
        scan = info.get("scan_data") or {}
        outreach = info.get("outreach") or {}
        result.append({
            "dominio": dominio,
            "nombre": info.get("nombre", ""),
            "estado": info.get("estado", "nuevo"),
            "flash_pdf": info.get("flash_pdf"),
            "flash_fecha": info.get("flash_fecha"),
            "diagnostico_pdf": info.get("diagnostico_pdf"),
            "trabajo_pdf": info.get("trabajo_pdf"),
            "trabajo_fecha": info.get("trabajo_fecha"),
            "score_captacion": info.get("score_captacion"),
            "risk_score": scan.get("risk_score"),
            "risk_level": scan.get("risk_level"),
            "email_contacto": info.get("email_contacto"),
            "outreach_estado": outreach.get("estado"),
            "outreach_notas": outreach.get("notas"),
        })
    return jsonify(result)


@bp.route("/api/prospectos/<path:dominio>/outreach", methods=["PATCH"])
@login_required
def actualizar_outreach(dominio):
    db = _read_db()
    info = db.get("prospectos", {}).get(dominio)
    if info is None:
        return jsonify({"ok": False, "error": "prospecto no encontrado"}), 404

    data = request.get_json(silent=True) or {}
    outreach = info.get("outreach") or {}
    if "estado" in data:
        outreach["estado"] = data["estado"]
    if "notas" in data:
        outreach["notas"] = data["notas"]
    info["outreach"] = outreach

    _write_db(db)
    return jsonify({"ok": True, "outreach": outreach})
