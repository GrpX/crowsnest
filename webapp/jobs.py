import logging
import os
import re
import subprocess
import sys
import threading
import time
import uuid
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent))

logger = logging.getLogger(__name__)
REPO_DIR = Path(__file__).parent.parent.resolve()
WRAPPERS_DIR = Path(__file__).parent / "wrappers"
SINS = str(REPO_DIR / "sins.sh")

_jobs: dict = {}
_lock = threading.Lock()

_ANSI_RE = re.compile(r"\x1b(?:\[[0-9;?]*[A-Za-z]|[()][0-9A-Za-z]|[=>])")


def _strip(line: str) -> str:
    return _ANSI_RE.sub("", line).replace("\r", "")


def create_job(cmd: str, params: dict) -> str:
    job_id = str(uuid.uuid4())[:8]
    with _lock:
        _jobs[job_id] = {
            "id": job_id,
            "cmd": cmd,
            "params": params,
            "status": "running",
            "lines": [],
            "exit_code": None,
            "started": time.time(),
        }
    t = threading.Thread(target=_run, args=(job_id, cmd, params), daemon=True)
    t.start()
    return job_id


def get_job(job_id: str) -> dict | None:
    with _lock:
        return _jobs.get(job_id)


def get_all_jobs() -> list:
    with _lock:
        return sorted(_jobs.values(), key=lambda j: j["started"], reverse=True)


def _append(job_id: str, line: str):
    with _lock:
        _jobs[job_id]["lines"].append(_strip(line))


def _env() -> dict:
    e = os.environ.copy()
    e["BATCH_MODE"] = "1"
    return e


def _build(cmd: str, params: dict) -> tuple[list, str | None]:
    py = sys.executable

    if cmd == "report":
        return [
            py, str(WRAPPERS_DIR / "report.py"),
            params.get("dominio", ""),
            params.get("nombre", ""),
            "ciber" if params.get("ciber") else "",
        ], None

    if cmd == "diagnostico":
        args = [py, str(WRAPPERS_DIR / "diagnostico.py"), params.get("dominio", "")]
        if params.get("cliente"):
            args.append(params["cliente"])
        return args, None

    if cmd == "trabajo":
        return [
            py, str(WRAPPERS_DIR / "trabajo.py"),
            params.get("dominio", ""),
            params.get("cliente", ""),
            params.get("auth_ref", ""),
        ], None

    if cmd == "batch":
        target = params.get("target_file", "")
        workers = str(params.get("workers", 3))
        args = ["bash", SINS, "batch"]
        if target:
            args.append(str(REPO_DIR / "targets" / target))
        args += ["--workers", workers, "--confirm", "--auto-name"]
        return args, None

    raise ValueError(f"Unknown command: {cmd}")


def _run(job_id: str, cmd: str, params: dict):
    job = _jobs[job_id]
    try:
        proc_args, stdin_data = _build(cmd, params)
        domain = params.get("dominio", params.get("target_file", ""))
        _append(job_id, f"[→] {cmd} {domain}")

        proc = subprocess.Popen(
            proc_args,
            stdin=subprocess.PIPE if stdin_data else None,
            stdout=subprocess.PIPE,
            stderr=subprocess.STDOUT,
            text=True,
            cwd=str(REPO_DIR),
            env=_env(),
        )

        if stdin_data:
            proc.stdin.write(stdin_data)
            proc.stdin.close()

        for line in proc.stdout:
            _append(job_id, line.rstrip())

        proc.wait()

        with _lock:
            _jobs[job_id]["exit_code"] = proc.returncode
            _jobs[job_id]["status"] = "done" if proc.returncode == 0 else "error"

    except Exception as e:
        logger.exception("Job %s failed", job_id)
        _append(job_id, f"[✗] Error: {e}")
        with _lock:
            _jobs[job_id]["status"] = "error"
            _jobs[job_id]["exit_code"] = -1
