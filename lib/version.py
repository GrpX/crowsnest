"""Identificador de la revision en ejecucion.

No hay numero de version declarado en ninguna parte: no existen tags ni un
archivo VERSION, asi que inventar "v1.0" seria mentir en la UI. Lo que si es
verificable es el commit sobre el que corre el proceso, y eso es lo que se
muestra.

Devuelve "" fuera de un repo git (por ejemplo, desplegado desde un tarball).
Quien lo consuma debe omitir la etiqueta cuando este vacia.
"""

import subprocess
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parent.parent

_cache = None


def revision() -> str:
    """Commit corto de HEAD, con sufijo '-dirty' si hay cambios sin commitear."""
    global _cache
    if _cache is not None:
        return _cache
    _cache = ""
    try:
        sha = subprocess.run(
            ["git", "rev-parse", "--short", "HEAD"],
            cwd=str(REPO_ROOT), capture_output=True, text=True, timeout=5,
        )
        if sha.returncode != 0:
            return _cache
        rev = sha.stdout.strip()
        if not rev:
            return _cache
        sucio = subprocess.run(
            ["git", "status", "--porcelain"],
            cwd=str(REPO_ROOT), capture_output=True, text=True, timeout=5,
        )
        if sucio.returncode == 0 and sucio.stdout.strip():
            rev += "-dirty"
        _cache = rev
    except (OSError, subprocess.SubprocessError):
        pass
    return _cache
