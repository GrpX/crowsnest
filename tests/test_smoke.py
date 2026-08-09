"""Smoke tests — lo que debe funcionar sin ninguna dependencia externa.

Sin backend LLM, sin Docker, sin red y sin API keys. Si algo aqui falla, el
repo esta roto para cualquiera que lo clone.

Lo que NO se prueba aqui: el escaneo real (necesita Docker y toca objetivos
de terceros) y los agentes LLM (ver openclaw/tests/test_models.py, que salta
de forma visible cuando no hay backend).
"""

import json
import subprocess
import sys
from pathlib import Path

import pytest

REPO_ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(REPO_ROOT))


# ─── CLI ────────────────────────────────────────────────────────────────────
def test_crowsnest_help_sale_con_cero():
    r = subprocess.run(
        ["bash", str(REPO_ROOT / "crowsnest.sh"), "help"],
        capture_output=True, text=True, timeout=60, check=False,
    )
    assert r.returncode == 0, f"help salio con {r.returncode}: {r.stderr[:400]}"
    assert "crowsnest.sh" in r.stdout


def test_crowsnest_comando_desconocido_falla():
    """Un comando invalido debe fallar, no pasar en silencio."""
    r = subprocess.run(
        ["bash", str(REPO_ROOT / "crowsnest.sh"), "comando-que-no-existe"],
        capture_output=True, text=True, timeout=60, check=False,
    )
    assert r.returncode != 0


def test_crowsnest_sintaxis_bash():
    r = subprocess.run(
        ["bash", "-n", str(REPO_ROOT / "crowsnest.sh")],
        capture_output=True, text=True, timeout=60, check=False,
    )
    assert r.returncode == 0, r.stderr


# ─── IMPORTS ────────────────────────────────────────────────────────────────
def test_modulos_lib_importan():
    from lib import (
        branding,  # noqa: F401
        states,  # noqa: F401
        version,  # noqa: F401
    )


def test_modulos_openclaw_importan():
    sys.path.insert(0, str(REPO_ROOT / "openclaw"))
    import enrich_targets  # noqa: F401
    import run_batch  # noqa: F401


def test_modulos_de_informe_importan():
    sys.path.insert(0, str(REPO_ROOT / "scripts"))
    import generate_pdf  # noqa: F401
    import nuclei_to_report  # noqa: F401


# ─── lib/states.py ──────────────────────────────────────────────────────────
def test_states_expone_el_ciclo_completo():
    from lib import states
    assert states.ALL == (states.QUEUED, states.RECON, states.ENRICHED,
                          states.REPORTED, states.SKIPPED)
    assert states.PIPELINE == (states.QUEUED, states.RECON,
                               states.ENRICHED, states.REPORTED)
    assert states.DEFAULT == states.QUEUED
    assert states.SKIPPED not in states.PIPELINE, \
        "skipped es un ramal, no un paso del avance"


def test_states_normalize_tolera_basura():
    from lib import states
    assert states.normalize("REPORTED") == states.REPORTED   # case-insensitive
    assert states.normalize("  recon ") == states.RECON      # con espacios
    assert states.normalize(None) == states.DEFAULT
    assert states.normalize("") == states.DEFAULT
    assert states.normalize("estado-inventado") == states.DEFAULT


def test_states_is_pending_solo_para_queued():
    from lib import states
    assert states.is_pending(states.QUEUED)
    assert states.is_pending(None)                       # sin estado = pendiente
    for s in (states.RECON, states.ENRICHED, states.REPORTED, states.SKIPPED):
        assert not states.is_pending(s), f"{s} no deberia contar como pendiente"


def test_states_is_valid():
    from lib import states
    assert all(states.is_valid(s) for s in states.ALL)
    assert not states.is_valid("cualquier-cosa")


# ─── lib/branding.py ────────────────────────────────────────────────────────
def test_branding_lee_el_svg_del_archivo():
    from lib import branding
    svg = branding.logo_svg()
    assert svg.startswith("<svg"), "el wordmark deberia venir del archivo SVG"
    assert "Crowsnest" in svg


def test_branding_data_uri_es_base64_de_ese_mismo_svg():
    import base64

    from lib import branding
    uri = branding.logo_data_uri()
    assert uri.startswith("data:image/svg+xml;base64,")
    crudo = base64.b64decode(uri.split(",", 1)[1]).decode()
    assert crudo == branding.logo_svg(), \
        "las dos formas deben salir del mismo archivo, no de copias distintas"


def test_branding_lee_la_marca_compacta_del_archivo():
    from lib import branding
    svg = branding.mark_svg()
    assert svg.startswith("<svg"), "la marca compacta deberia venir del archivo SVG"


def test_branding_data_uri_de_la_marca_es_base64_de_ese_mismo_svg():
    import base64

    from lib import branding
    uri = branding.mark_data_uri()
    assert uri.startswith("data:image/svg+xml;base64,")
    crudo = base64.b64decode(uri.split(",", 1)[1]).decode()
    assert crudo == branding.mark_svg(), \
        "las dos formas deben salir del mismo archivo, no de copias distintas"


@pytest.mark.parametrize("path_attr, svg_fn, uri_fn", [
    ("LOGO_PATH", "logo_svg", "logo_data_uri"),
    ("MARK_PATH", "mark_svg", "mark_data_uri"),
])
def test_branding_no_trae_copia_embebida(tmp_path, monkeypatch, path_attr, svg_fn, uri_fn):
    """Sin el archivo no hay copia de emergencia: devuelve vacio y avisa."""
    from lib import branding
    monkeypatch.setattr(branding, path_attr, tmp_path / "no-existe.svg")
    monkeypatch.setattr(branding, "_warned", set())
    assert getattr(branding, svg_fn)() == ""
    assert getattr(branding, uri_fn)() == ""


def _firma_estructural(svg: str) -> str:
    """Cadena mas larga que identifica de forma unica a un SVG de marca:
    el atributo `d` de <path> mas extenso, o el contenido del <text> mas
    largo si resulta mas distintivo que cualquier `d`. Se deriva del
    archivo en tiempo de ejecucion — nunca hardcodeada en el test, o el
    test seria la segunda copia que existe para prevenir.
    """
    import re

    candidatos = re.findall(r'\bd="([^"]+)"', svg)
    candidatos += [t.strip() for t in re.findall(r"<text[^>]*>([^<]+)</text>", svg)]
    assert candidatos, "el SVG no trae ni <path d=...> ni <text> del que derivar una firma"
    return max(candidatos, key=len)


@pytest.mark.parametrize("path_attr, svg_fn, hermano_attr", [
    ("LOGO_PATH", "logo_svg", "MARK_PATH"),
    ("MARK_PATH", "mark_svg", "LOGO_PATH"),
])
def test_la_marca_se_declara_una_sola_vez(path_attr, svg_fn, hermano_attr):
    """Ningun archivo del repo redeclara wordmark o marca compacta fuera de su SVG fuente.

    El artefacto hermano (wordmark <-> marca compacta) queda excluido: ambos
    comparten el mismo glifo por diseno, eso no es la copia que este test
    persigue.
    """
    from lib import branding
    fuente = getattr(branding, path_attr)
    hermano = getattr(branding, hermano_attr)
    firma = _firma_estructural(getattr(branding, svg_fn)())
    assert firma, "no se pudo derivar una firma del SVG"

    otros = []
    for f in REPO_ROOT.rglob("*"):
        if not f.is_file() or ".git" in f.parts or "__pycache__" in f.parts:
            continue
        if f.suffix not in (".py", ".html", ".css", ".js", ".svg"):
            continue
        if f in (fuente, hermano, Path(__file__)):
            continue
        try:
            if firma in f.read_text(encoding="utf-8"):
                otros.append(str(f.relative_to(REPO_ROOT)))
        except UnicodeDecodeError:
            continue
    assert not otros, f"la marca esta duplicada en: {otros}"


# ─── lib/version.py ─────────────────────────────────────────────────────────
def test_version_no_inventa_un_numero():
    """La revision es un SHA de git o cadena vacia; nunca un 'v1.0' fabricado."""
    from lib import version
    rev = version.revision()
    assert isinstance(rev, str)
    if rev:
        assert not rev.startswith("v"), f"version fabricada: {rev}"


# ─── MOTOR DE INFORMES: JSON -> PDF ─────────────────────────────────────────
DMARC_FICTICIO = {
    "domain": "example.com",
    "spf": {"valid": True, "record": "v=spf1 include:_spf.example.com ~all"},
    "dmarc": {"valid": False, "error": "no DMARC record"},
    "mx": {"hosts": [{"hostname": "mail.example.com", "tls": False,
                      "starttls": False}]},
}

NUCLEI_FICTICIO = [
    {"template-id": "http-missing-security-headers",
     "info": {"name": "http-missing-security-headers", "severity": "info",
              "tags": ["headers", "misconfiguration"],
              "description": "Cabeceras ausentes"},
     "host": "example.com", "matched-at": "https://example.com"},
    {"template-id": "deprecated-tls",
     "info": {"name": "deprecated-tls", "severity": "medium",
              "tags": ["ssl"], "description": "TLS obsoleto"},
     "host": "example.com", "matched-at": "example.com:443"},
]


@pytest.fixture
def entrada_ficticia(tmp_path):
    """Input 100% ficticio: example.com, sin tocar nada real."""
    nuclei = tmp_path / "nuclei.jsonl"
    nuclei.write_text("\n".join(json.dumps(x) for x in NUCLEI_FICTICIO) + "\n")
    dmarc = tmp_path / "dmarc.json"
    dmarc.write_text(json.dumps(DMARC_FICTICIO))
    return nuclei, dmarc


def _construir_informe(tmp_path, nuclei, dmarc, extra=()):
    salida = tmp_path / "report.json"
    r = subprocess.run(
        [sys.executable, str(REPO_ROOT / "scripts" / "nuclei_to_report.py"),
         "--input", str(nuclei), "--dmarc", str(dmarc),
         "--client", "Example", "--domain", "example.com",
         "--output", str(salida), "--report-type", "detailed", *extra],
        capture_output=True, text=True, timeout=180, check=False,
    )
    assert r.returncode == 0, f"el motor fallo: {r.stderr[-800:]}"
    return salida, json.loads(salida.read_text())


def test_motor_de_informes_produce_json_valido(tmp_path, entrada_ficticia):
    nuclei, dmarc = entrada_ficticia
    _, informe = _construir_informe(tmp_path, nuclei, dmarc)
    assert informe["client"]["domain"] == "example.com"
    assert informe["executive_summary"]["total_findings"] > 0
    assert informe["findings"], "deberia haber hallazgos"


def test_el_informe_no_lleva_cifras_de_dinero(tmp_path, entrada_ficticia):
    """Sin precios: la remediacion se estima en esfuerzo, no en moneda."""
    nuclei, dmarc = entrada_ficticia
    _, informe = _construir_informe(tmp_path, nuclei, dmarc)
    crudo = json.dumps(informe, ensure_ascii=False)
    for prohibido in ("cost_uf", "remediation_total_uf", "incident_cost_min_uf",
                      "max_multa_utm", "multa_oiv"):
        assert prohibido not in crudo, f"campo monetario presente: {prohibido}"
    for item in informe["business_impact"]["remediation_items"]:
        assert item["effort"] in ("low", "medium", "high")


def test_el_framework_de_cumplimiento_sale_de_config(tmp_path, entrada_ficticia):
    nuclei, dmarc = entrada_ficticia
    _, informe = _construir_informe(tmp_path, nuclei, dmarc,
                                    extra=("--compliance", "owasp-top10"))
    comp = informe["compliance"]
    assert comp["id"] == "owasp-top10"
    assert comp["controls"], "los hallazgos deberian mapear a algun control"


def test_pdf_se_genera_sin_backend_llm(tmp_path, entrada_ficticia):
    """El caso que importa: informe completo sin ningun servicio externo."""
    pytest.importorskip("weasyprint", reason="WeasyPrint no instalado")
    nuclei, dmarc = entrada_ficticia
    ruta_json, informe = _construir_informe(tmp_path, nuclei, dmarc)

    assert informe["executive_summary"]["narrative"] == "", \
        "sin --summary el resumen del LLM debe quedar vacio"

    pdf = tmp_path / "report.pdf"
    r = subprocess.run(
        [sys.executable, str(REPO_ROOT / "scripts" / "generate_pdf.py"),
         "--input", str(ruta_json), "--output", str(pdf)],
        capture_output=True, text=True, timeout=300, check=False,
    )
    assert r.returncode == 0, f"generate_pdf fallo: {r.stderr[-800:]}"
    assert pdf.is_file() and pdf.stat().st_size > 10_000
    assert pdf.read_bytes()[:4] == b"%PDF"


def test_el_resumen_del_llm_es_opcional(tmp_path, entrada_ficticia):
    """Con --summary el texto entra; sin el, el informe se genera igual."""
    nuclei, dmarc = entrada_ficticia
    resumen = tmp_path / "summary.txt"
    resumen.write_text("Fictitious executive summary for the smoke test.")
    _, informe = _construir_informe(tmp_path, nuclei, dmarc,
                                    extra=("--summary", str(resumen)))
    assert "Fictitious executive summary" in informe["executive_summary"]["narrative"]


def test_summary_inexistente_no_rompe_el_informe(tmp_path, entrada_ficticia):
    nuclei, dmarc = entrada_ficticia
    _, informe = _construir_informe(tmp_path, nuclei, dmarc,
                                    extra=("--summary", str(tmp_path / "nope.txt")))
    assert informe["executive_summary"]["narrative"] == ""


# ─── WEBAPP ─────────────────────────────────────────────────────────────────
@pytest.fixture
def cliente_web(tmp_path, monkeypatch):
    pytest.importorskip("flask", reason="Flask no instalado")
    pytest.importorskip("flask_login", reason="flask-login no instalado")
    monkeypatch.setenv("CROWSNEST_WEBAPP_PASSWORD", "smoke-test")
    monkeypatch.setenv("CROWSNEST_WEBAPP_SECRET_KEY", "0" * 32)
    sys.path.insert(0, str(REPO_ROOT / "webapp"))
    import app as webapp
    c = webapp.app.test_client()
    c.post("/login", data={"password": "smoke-test"}, follow_redirects=True)
    return c


def test_la_webapp_levanta_y_sirve_el_dashboard(cliente_web):
    r = cliente_web.get("/")
    assert r.status_code == 200
    html = r.get_data(as_text=True)
    assert "<title>Crowsnest | Dashboard</title>" in html


def test_la_api_de_targets_responde_sin_base_de_datos(cliente_web):
    """Sin db/targets.json la API devuelve lista vacia, no un 500."""
    r = cliente_web.get("/api/targets")
    assert r.status_code == 200
    assert isinstance(r.get_json(), list)


def test_el_dashboard_recibe_los_estados_desde_lib_states(cliente_web):
    from lib import states
    html = cliente_web.get("/").get_data(as_text=True)
    assert json.dumps(list(states.ALL)) in html.replace(", ", ", "), \
        "el frontend deberia recibir los estados de lib/states.py"
    for s in states.ALL:
        assert f'data-filter="{s}"' in html


def test_el_allowlist_de_comandos_rechaza_lo_desconocido(cliente_web):
    r = cliente_web.post("/api/run/rm-rf", json={})
    assert r.status_code == 400


# ─── CONFIG ─────────────────────────────────────────────────────────────────
def test_los_frameworks_de_cumplimiento_son_yaml_valido():
    yaml = pytest.importorskip("yaml", reason="PyYAML no instalado")
    archivos = list((REPO_ROOT / "config" / "compliance").glob("*.yaml"))
    assert archivos, "deberia haber al menos un framework de ejemplo"
    for f in archivos:
        d = yaml.safe_load(f.read_text(encoding="utf-8"))
        assert d.get("id"), f"{f.name} no declara id"
        assert d.get("name"), f"{f.name} no declara name"
        assert isinstance(d.get("mapping"), dict), f"{f.name} no declara mapping"


def test_el_ejemplo_de_target_usa_dominios_reservados():
    """El esquema de ejemplo no debe apuntar a nadie real."""
    d = json.loads((REPO_ROOT / "examples" / "sample_target.json")
                   .read_text(encoding="utf-8"))
    permitidos = ("example.com", "example.org", "example.net", "ejemplo.cl")
    for dominio in d["targets"]:
        assert dominio in permitidos, f"dominio no reservado en el ejemplo: {dominio}"


def test_el_env_de_ejemplo_no_trae_secretos():
    texto = (REPO_ROOT / ".env.example").read_text(encoding="utf-8")
    for linea in texto.splitlines():
        linea = linea.split("#", 1)[0].strip()
        if not linea or "=" not in linea:
            continue
        _, _, valor = linea.partition("=")
        valor = valor.strip()
        if not valor:
            continue
        assert (valor.startswith(("tu_", "genera_", "cambia_", "http://",
                                 "https://"))
                or valor in ("admin", "owasp-top10")), \
            f"posible valor real en .env.example: {linea}"
