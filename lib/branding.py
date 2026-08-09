"""Marca del proyecto — fuente unica, dos artefactos.

Hay dos formas de la marca, cada una en UN solo archivo. Nadie mas las
declara. Para reemplazar cualquiera basta con sustituir su archivo; el
informe PDF y la webapp los leen de aqui.

    templates/crowsnest_logo.svg -> wordmark horizontal (header, login, portada/contraportada del PDF)
    templates/crowsnest_mark.svg -> marca compacta cuadrada (favicon, esquina de pagina del PDF)

    logo_svg()  / logo_data_uri()  -> wordmark: markup crudo / data: URI
    mark_svg()  / mark_data_uri()  -> marca compacta: markup crudo / data: URI

Si un archivo falta, sus helpers devuelven cadena vacia y avisan por stderr
una vez. No hay copia de emergencia embebida: una segunda declaracion de
cualquiera de las dos marcas es exactamente lo que este modulo existe para
evitar.

Ambos SVG traen su propio rectangulo de fondo y su propio color de trazo
(no heredan `currentColor`): la marca es una placa autocontenida, asi que
el contraste queda garantizado sin importar sobre que fondo de pagina se
coloque, sin necesidad de una segunda variante por contexto.
"""

import base64
import sys
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parent.parent
LOGO_PATH = REPO_ROOT / "templates" / "crowsnest_logo.svg"
MARK_PATH = REPO_ROOT / "templates" / "crowsnest_mark.svg"

_warned: set[Path] = set()


def _read(path: Path) -> bytes:
    if path.is_file():
        return path.read_bytes()
    if path not in _warned:
        print(f"[!] Falta el archivo de marca: {path}", file=sys.stderr)
        _warned.add(path)
    return b""


def _data_uri(raw: bytes) -> str:
    if not raw:
        return ""
    return "data:image/svg+xml;base64," + base64.b64encode(raw).decode()


def logo_svg() -> str:
    """Wordmark: markup SVG crudo, listo para incrustar en un documento HTML."""
    return _read(LOGO_PATH).decode("utf-8")


def logo_data_uri() -> str:
    """Wordmark: data: URI base64, para el atributo src de una <img>."""
    return _data_uri(_read(LOGO_PATH))


def mark_svg() -> str:
    """Marca compacta: markup SVG crudo, listo para incrustar en un documento HTML."""
    return _read(MARK_PATH).decode("utf-8")


def mark_data_uri() -> str:
    """Marca compacta: data: URI base64, para el atributo src de una <img> o un favicon."""
    return _data_uri(_read(MARK_PATH))
