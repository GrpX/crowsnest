#!/usr/bin/env python3
import json, sys
from pathlib import Path
from datetime import datetime
from jinja2 import Environment, BaseLoader
from weasyprint import HTML, CSS
from weasyprint.text.fonts import FontConfiguration

TEMPLATE_NAME_ES = {
    "Weak Cipher Suites Detection":    "Cifrados TLS débiles detectados",
    "wordpress-readme-file":           "Archivo README de WordPress expuesto",
    "http-missing-security-headers":   "Cabeceras de seguridad HTTP ausentes",
    "deprecated-tls":                  "Versión TLS obsoleta habilitada",
    "tls-version":                     "Versión TLS detectada",
    "ssl-issuer":                      "Emisor del certificado SSL",
    "ssl-dns-names":                   "Nombres DNS del certificado SSL",
    "wildcard-tls":                    "Certificado TLS wildcard detectado",
    "weak-hsts-detect":                "Política HSTS débil o ausente",
    "mx-fingerprint":                  "Servidor de correo identificado",
    "nameserver-fingerprint":          "Servidor DNS identificado",
    "spf-record-detect":               "Registro SPF detectado",
    "txt-fingerprint":                 "Registro TXT identificado",
    "caa-fingerprint":                 "Registro CAA detectado",
    "aaaa-fingerprint":                "Registro IPv6 (AAAA) detectado",
    "dns-saas-service-detection":      "Servicio SaaS detectado via DNS",
    "google-client-id":                "Client ID de Google expuesto",
    "wordpress-detect":                "CMS WordPress detectado",
    "tech-detect":                     "Tecnología web detectada",
    "Riesgo de rebote y filtrado a spam del correo propio": "Riesgo de rebote y filtrado a spam del correo propio",
    "Registro DMARC ausente":                "Registro DMARC ausente",
    "Registro SPF ausente o inválido":       "Registro SPF ausente o inválido",
    "DMARC configurado con p=none (sin enforcement)": "DMARC sin enforcement (p=none)",
    "SPF configurado con softfail (~all)":   "SPF con softfail (~all) — enforcement incompleto",
    "MTA-STS no configurado":                "Cifrado SMTP forzado (MTA-STS) no configurado",

}

def translate_finding_names(data: dict) -> dict:
    for finding in data.get("findings", []):
        name = finding.get("name", "")
        finding["name"] = TEMPLATE_NAME_ES.get(name, name)
    return data

TEMPLATES_DIR = Path(__file__).parent.parent / "templates"

# El wordmark tiene una sola fuente: templates/crowsnest_logo.svg via lib.branding.
REPO_ROOT = Path(__file__).resolve().parent.parent
if str(REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(REPO_ROOT))
from lib.branding import logo_data_uri  # noqa: E402

# Una sola plantilla. Lo que antes eran dos variantes de marco legal ahora se
# resuelve con el framework de cumplimiento activo (config/compliance/), que el
# motor deja en el campo "compliance" del informe.
TEMPLATE_PATH = TEMPLATES_DIR / "report_template.html"

# Etiqueta visible de cada nivel de esfuerzo. Nunca un precio.
EFFORT_LABEL = {
    "low":    "Bajo",
    "medium": "Medio",
    "high":   "Alto",
}

def render_html(data, template_path):
    template_str = template_path.read_text(encoding="utf-8")
    env = Environment(loader=BaseLoader())
    env.tests['in'] = lambda v, s: v in s
    template = env.from_string(template_str)
    return template.render(**data)

def generate_pdf(html_content, output_path):
    font_config = FontConfiguration()
    html_doc = HTML(string=html_content)
    css = CSS(string="@page{size:A4;margin:0}", font_config=font_config)
    html_doc.write_pdf(str(output_path), stylesheets=[css], font_config=font_config, presentational_hints=True)

if __name__ == "__main__":
    import argparse
    parser = argparse.ArgumentParser()
    parser.add_argument("--input",  required=True)
    parser.add_argument("--output", required=True)
    args = parser.parse_args()

    print("[*] Cargando informe...")
    data = json.loads(Path(args.input).read_text(encoding="utf-8"))
    data = translate_finding_names(data)
    data["logo_b64"] = logo_data_uri()

    data["EFFORT_LABEL"] = EFFORT_LABEL

    if not TEMPLATE_PATH.exists():
        print(f"[✗] Template no encontrado: {TEMPLATE_PATH}")
        sys.exit(1)

    compliance = data.get("compliance") or {}
    print(f"[*] Renderizando template "
          f"(cumplimiento: {compliance.get('id') or 'ninguno'})...")
    html = render_html(data, TEMPLATE_PATH)

    print("[*] Generando PDF...")
    generate_pdf(html, Path(args.output))
    size = Path(args.output).stat().st_size // 1024
    print(f"[✓] PDF generado: {args.output} ({size} KB)")
