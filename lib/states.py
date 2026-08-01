"""Ciclo de vida de un target de escaneo — definicion canonica.

Este modulo es la unica fuente de verdad de los estados. Todo el codigo
Python los importa de aqui; el frontend los recibe desde la webapp, que
tambien los lee de aqui (ver webapp/app.py -> dashboard.html).

    queued  ->  recon  ->  enriched  ->  reported
                  |
                  +-->  skipped

- queued   : el target esta en la base y todavia no se escanea.
- recon    : el recon pasivo corrio y dejo scan_data.
- enriched : los agentes LLM completaron los datos del target.
- reported : hay al menos un informe generado.
- skipped  : el prefiltro lo descarto (sitio muerto, sin contenido, etc.);
             skip_reason dice por que. No es parte del avance normal.
"""

QUEUED = "queued"
RECON = "recon"
ENRICHED = "enriched"
REPORTED = "reported"
SKIPPED = "skipped"

#: Orden de avance del pipeline, para barras de progreso y filtros.
PIPELINE = (QUEUED, RECON, ENRICHED, REPORTED)

#: Todos los estados validos, incluido el ramal de descarte.
ALL = PIPELINE + (SKIPPED,)

#: Estado por defecto de un target recien creado.
DEFAULT = QUEUED


def is_valid(status: str) -> bool:
    """True si `status` es un estado conocido."""
    return status in ALL


def normalize(status) -> str:
    """Devuelve un estado valido; cae a DEFAULT si el valor no se reconoce."""
    s = (status or "").strip().lower()
    return s if s in ALL else DEFAULT


def is_pending(status) -> bool:
    """True si el target todavia no fue procesado (elegible para un escaneo)."""
    return normalize(status) == QUEUED
