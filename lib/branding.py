"""Wordmark del proyecto — fuente unica.

El logo vive en UN solo archivo: templates/crowsnest_logo.svg. Nadie mas
declara el wordmark. Para reemplazarlo basta con sustituir ese archivo; el
informe PDF y la webapp lo leen de aqui.

    logo_svg()       -> markup SVG crudo (para incrustar en HTML)
    logo_data_uri()  -> data: URI base64 (para src de <img>)

Si el archivo falta, ambas devuelven cadena vacia y avisan por stderr. No hay
copia de emergencia embebida: una segunda declaracion del wordmark es
exactamente lo que este modulo existe para evitar.
"""

import base64
import sys
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parent.parent
LOGO_PATH = REPO_ROOT / "templates" / "crowsnest_logo.svg"

_warned = False


def _read() -> bytes:
    global _warned
    if LOGO_PATH.is_file():
        return LOGO_PATH.read_bytes()
    if not _warned:
        print(f"[!] Falta el logo: {LOGO_PATH}", file=sys.stderr)
        _warned = True
    return b""


def logo_svg() -> str:
    """Markup SVG crudo, listo para incrustar en un documento HTML."""
    return _read().decode("utf-8")


def logo_data_uri() -> str:
    """data: URI base64 del SVG, para el atributo src de una <img>."""
    raw = _read()
    if not raw:
        return ""
    return "data:image/svg+xml;base64," + base64.b64encode(raw).decode()
