import sys
import time
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent.parent))

from flask import Blueprint, Response, stream_with_context
from flask_login import login_required

from jobs import get_job

bp = Blueprint("stream", __name__)


@bp.route("/api/stream/<job_id>")
@login_required
def stream(job_id):
    def generate():
        sent = 0
        last_beat = time.time()
        while True:
            job = get_job(job_id)
            if not job:
                yield "data: [job not found]\n\n"
                return
            lines = job["lines"]
            while sent < len(lines):
                line = lines[sent].replace("\\", "\\\\").replace("\n", "\\n")
                yield f"data: {line}\n\n"
                sent += 1
            if job["status"] != "running":
                yield f"event: done\ndata: {job['exit_code']}\n\n"
                return
            now = time.time()
            if now - last_beat > 15:
                yield ": heartbeat\n\n"
                last_beat = now
            time.sleep(0.1)

    return Response(
        stream_with_context(generate()),
        mimetype="text/event-stream",
        headers={
            "Cache-Control": "no-cache",
            "X-Accel-Buffering": "no",
            "Connection": "keep-alive",
        },
    )
