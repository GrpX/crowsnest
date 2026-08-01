import json
from pathlib import Path

from flask import Blueprint, abort, jsonify, redirect, send_from_directory
from flask_login import login_required

bp = Blueprint("files", __name__)
REPO_DIR = Path(__file__).parent.parent.parent.resolve()
REPORTES_DIR = REPO_DIR / "reportes"
TARGETS_DIR  = REPO_DIR / "targets"
DB_FILE      = REPO_DIR / "db" / "targets.json"


@bp.route("/reportes/<path:filepath>")
@login_required
def serve_file(filepath):
    filename = Path(filepath).name
    if not filename or ".." in filename:
        abort(403)
    for candidate in REPORTES_DIR.rglob(filename):
        if candidate.is_file():
            resolved = candidate.resolve()
            if str(resolved).startswith(str(REPORTES_DIR)):
                return send_from_directory(str(candidate.parent), candidate.name)
    abort(404)


@bp.route("/api/target-files")
@login_required
def list_target_files():
    if TARGETS_DIR.exists():
        files = sorted(f.name for f in TARGETS_DIR.glob("*.txt"))
    else:
        files = []
    return jsonify(files)


@bp.route("/api/sesiones")
@login_required
def list_sesiones():
    if REPORTES_DIR.exists():
        sessions = sorted(
            (d.name for d in REPORTES_DIR.iterdir()
             if d.is_dir()
             and not d.name.startswith("batch")
             and any(d.glob("*.pdf"))),
            reverse=True,
        )[:50]
    else:
        sessions = []
    return jsonify(sessions)


@bp.route("/api/pdf/<tipo>/<path:dominio>")
@login_required
def get_pdf(tipo, dominio):
    key_map = {
        "report":      "report_pdf",
        "detailed":    "detailed_report_pdf",
        "remediation": "remediation_pdf",
    }
    key = key_map.get(tipo)
    if not key:
        abort(400)
    if not DB_FILE.exists():
        abort(404)
    db = json.loads(DB_FILE.read_text(encoding="utf-8"))
    info = db.get("targets", {}).get(dominio, {})
    pdf_path = info.get(key)
    if not pdf_path:
        abort(404)
    return redirect(f"/reportes/{pdf_path}")
