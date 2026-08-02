import os
import sys
from pathlib import Path

WEBAPP_DIR = Path(__file__).parent.resolve()
REPO_DIR = WEBAPP_DIR.parent.resolve()

if str(WEBAPP_DIR) not in sys.path:
    sys.path.insert(0, str(WEBAPP_DIR))


def _load_env():
    env_path = REPO_DIR / ".env"
    if not env_path.exists():
        return
    for raw in env_path.read_text(encoding="utf-8").splitlines():
        line = raw.strip()
        if not line or line.startswith("#") or "=" not in line:
            continue
        k, _, v = line.partition("=")
        k, v = k.strip(), v.split("#")[0].strip()
        if k not in os.environ:
            os.environ[k] = v


_load_env()

from flask import Flask, render_template
from flask_login import login_required

if str(REPO_DIR) not in sys.path:
    sys.path.insert(0, str(REPO_DIR))

from auth import SECRET_KEY, auth_bp, get_password, init_auth
from routes import files_bp, run_bp, stream_bp, targets_bp

from lib import states
from lib.branding import logo_svg
from lib.version import revision

app = Flask(__name__,
    template_folder=str(WEBAPP_DIR / "templates"),
    static_folder=str(WEBAPP_DIR / "static"),
)
app.secret_key = SECRET_KEY

init_auth(app)


@app.context_processor
def inject_branding():
    """El wordmark viene de templates/crowsnest_logo.svg — fuente unica."""
    return {"logo_svg": logo_svg(), "revision": revision()}


app.register_blueprint(auth_bp)
app.register_blueprint(targets_bp)
app.register_blueprint(run_bp)
app.register_blueprint(stream_bp)
app.register_blueprint(files_bp)


@app.route("/")
@login_required
def dashboard():
    targets_dir = REPO_DIR / "targets"
    target_files = sorted(
        [f.name for f in targets_dir.glob("*.txt")] if targets_dir.exists() else []
    )
    reportes_dir = REPO_DIR / "reportes"
    sessions = []
    if reportes_dir.exists():
        sessions = sorted(
            [d.name for d in reportes_dir.iterdir()
             if d.is_dir() and not d.name.startswith("batch")],
            reverse=True,
        )[:50]
    return render_template(
        "dashboard.html",
        target_files=target_files,
        sessions=sessions,
        target_states=list(states.ALL),
    )


if __name__ == "__main__":
    pwd = get_password()
    print(f"\n[Crowsnest] dashboard at http://0.0.0.0:5000  admin / {pwd}\n")
    app.run(host="0.0.0.0", port=5000, debug=False, threaded=True)
