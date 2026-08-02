import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent.parent))

from flask import Blueprint, jsonify, request
from flask_login import login_required
from jobs import create_job

bp = Blueprint("run", __name__)

_VALID = {
    "report", "diagnostico", "trabajo", "batch",
}


@bp.route("/api/run/<cmd>", methods=["POST"])
@login_required
def run_cmd(cmd):
    if cmd not in _VALID:
        return jsonify({"error": "Comando inválido"}), 400
    params = request.get_json() or {}
    job_id = create_job(cmd, params)
    return jsonify({"job_id": job_id})


@bp.route("/api/jobs")
@login_required
def list_jobs():
    from jobs import get_all_jobs
    jobs = get_all_jobs()
    return jsonify([
        {
            "id": j["id"],
            "cmd": j["cmd"],
            "status": j["status"],
            "exit_code": j["exit_code"],
            "started": j["started"],
            "domain": j["params"].get("dominio", j["params"].get("target_file", "")),
        }
        for j in jobs[:20]
    ])
