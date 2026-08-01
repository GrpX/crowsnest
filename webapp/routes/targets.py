import json
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent.parent))

from flask import Blueprint, jsonify
from flask_login import login_required

REPO_DIR = Path(__file__).parent.parent.parent.resolve()
if str(REPO_DIR) not in sys.path:
    sys.path.insert(0, str(REPO_DIR))
from lib import states  # noqa: E402

bp = Blueprint("targets", __name__)
DB_FILE = REPO_DIR / "db" / "targets.json"


def _read_db() -> dict:
    if DB_FILE.exists():
        return json.loads(DB_FILE.read_text(encoding="utf-8"))
    return {"version": 1, "targets": {}}


@bp.route("/api/targets")
@login_required
def list_targets():
    db = _read_db()
    result = []
    for dominio, info in db.get("targets", {}).items():
        scan = info.get("scan_data") or {}
        result.append({
            "dominio": dominio,
            "name": info.get("name", ""),
            "status": states.normalize(info.get("status")),
            "report_pdf": info.get("report_pdf"),
            "report_at": info.get("report_at"),
            "detailed_report_pdf": info.get("detailed_report_pdf"),
            "remediation_pdf": info.get("remediation_pdf"),
            "remediation_at": info.get("remediation_at"),
            "skip_reason": info.get("skip_reason", ""),
            "risk_score": scan.get("risk_score"),
            "risk_level": scan.get("risk_level"),
            "total_findings": scan.get("total_findings"),
            "high_findings": scan.get("high_findings"),
            "medium_findings": scan.get("medium_findings"),
            "emails_found": info.get("emails_found") or [],
        })
    return jsonify(result)
