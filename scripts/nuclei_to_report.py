#!/usr/bin/env python3
"""
nuclei_to_report.py — Convierte JSON de nuclei + checkdmarc a informe estructurado Crowsnest

Uso:
    python3 scripts/nuclei_to_report.py \
        --input  reportes/SESION/nuclei/nuclei_dominio.json \
        --dmarc  reportes/SESION/email/checkdmarc_dominio.json \
        --tech   reportes/SESION/technologies/whatweb_dominio.json \
        --client "Cliente S.A." \
        --domain dominio.cl \
        --output reportes/SESION/informe.json
"""

import json
import argparse
import os
import sys
from datetime import datetime
from pathlib import Path

import yaml

COMPLIANCE_DIR = Path(__file__).resolve().parent.parent / "config" / "compliance"


# ── FRAMEWORK DE CUMPLIMIENTO (pluggable) ─────────────────────────────────────
def available_frameworks() -> dict:
    """Devuelve {id: ruta} de los frameworks declarados en config/compliance/."""
    found = {}
    if not COMPLIANCE_DIR.is_dir():
        return found
    for path in sorted(COMPLIANCE_DIR.glob("*.yaml")) + sorted(COMPLIANCE_DIR.glob("*.yml")):
        try:
            data = yaml.safe_load(path.read_text(encoding="utf-8")) or {}
        except yaml.YAMLError:
            continue
        fid = data.get("id")
        if fid:
            found[str(fid)] = path
    return found


def load_compliance(selected: str | None):
    """Carga el framework activo.

    Precedencia: --compliance > CROWSNEST_COMPLIANCE_FRAMEWORK > el unico disponible.
    Si hay varios y ninguno fue elegido, aborta listando los ids: adivinar el
    encuadre de cumplimiento de un informe seria peor que fallar.
    """
    frameworks = available_frameworks()
    if not frameworks:
        print(f"[!] Sin frameworks en {COMPLIANCE_DIR}; el informe se genera sin "
              f"seccion de cumplimiento.")
        return None

    fid = selected or os.environ.get("CROWSNEST_COMPLIANCE_FRAMEWORK")
    if not fid:
        if len(frameworks) == 1:
            fid = next(iter(frameworks))
        else:
            print("[✗] Hay varios frameworks de cumplimiento y ninguno seleccionado.",
                  file=sys.stderr)
            print("    Usa --compliance <id> o CROWSNEST_COMPLIANCE_FRAMEWORK=<id>.", file=sys.stderr)
            print("    Disponibles: " + ", ".join(sorted(frameworks)), file=sys.stderr)
            sys.exit(2)

    if fid not in frameworks:
        print(f"[✗] Framework de cumplimiento desconocido: {fid!r}", file=sys.stderr)
        print("    Disponibles: " + ", ".join(sorted(frameworks)), file=sys.stderr)
        sys.exit(2)

    return yaml.safe_load(frameworks[fid].read_text(encoding="utf-8"))


def build_compliance_block(fw: dict | None, findings: list) -> dict | None:
    """Mapea las categorias de los hallazgos a controles del framework activo."""
    if not fw:
        return None

    mapping = fw.get("mapping") or {}
    fallback = fw.get("default") or {}

    controles = {}
    for f in findings:
        # Se mapea por tag (slug estable), no por la etiqueta legible.
        entry = None
        for tag in (f.get("tags") or []):
            if tag.lower() in mapping:
                entry = mapping[tag.lower()]
                break
        if entry is None:
            entry = fallback
        if not entry:
            continue
        clave = entry.get("control", "")
        cat = f.get("category") or ""
        item = controles.setdefault(clave, {
            "control":    clave,
            "url":        entry.get("url", ""),
            "note":       entry.get("note", ""),
            "categories": [],
            "findings":   0,
        })
        item["findings"] += 1
        if cat and cat not in item["categories"]:
            item["categories"].append(cat)

    return {
        "id":          fw.get("id", ""),
        "name":        fw.get("name", ""),
        "reference":   fw.get("reference", ""),
        "description": (fw.get("description") or "").strip(),
        "controls":    sorted(controles.values(), key=lambda c: c["control"]),
    }

# ── SEVERIDADES ───────────────────────────────────────────────────────────────
SEVERITY_MAP = {
    "critical": {"label": "Crítica",     "cvss_range": "9.0–10.0", "priority": 1},
    "high":     {"label": "Alta",        "cvss_range": "7.0–8.9",  "priority": 2},
    "medium":   {"label": "Media",       "cvss_range": "4.0–6.9",  "priority": 3},
    "low":      {"label": "Baja",        "cvss_range": "0.1–3.9",  "priority": 4},
    "info":     {"label": "Informativa", "cvss_range": "0.0",      "priority": 5},
    "unknown":  {"label": "Sin definir", "cvss_range": "N/A",      "priority": 6},
}

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
}

# Etiqueta legible de cada tag. Sin codigos de control: esos los aporta el
# framework de cumplimiento activo (config/compliance/), que es intercambiable.
TAG_TO_CATEGORY = {
    "ssl":              "Configuración TLS/SSL",
    "dmarc":            "Seguridad de correo electrónico",
    "spf":              "Seguridad de correo electrónico",
    "exposure":         "Exposición de información sensible",
    "misconfiguration": "Mala configuración de seguridad",
    "config":           "Mala configuración de seguridad",
    "dns":              "Configuración DNS",
    "headers":          "Cabeceras HTTP de seguridad",
    "default-login":    "Credenciales por defecto",
    "panel":            "Panel de administración expuesto",
    "cve":              "Vulnerabilidad conocida (CVE)",
    "wordpress":        "CMS WordPress",
    "token":            "Token o credencial expuesta",
}

RECOMMENDATIONS = {
    "ssl":              "Actualizar la configuración TLS a 1.2/1.3 únicamente, deshabilitar cipher suites débiles.",
    "dmarc":            "Escalar política DMARC a p=reject. Configurar SPF con -all y DKIM 2048 bits.",
    "spf":              "Cambiar mecanismo SPF de ~all a -all para bloquear servidores no autorizados.",
    "exposure":         "Restringir acceso a archivos y rutas sensibles. Deshabilitar listado de directorios.",
    "misconfiguration": "Revisar configuración del servidor según guías CIS Benchmarks.",
    "headers":          "Implementar: Content-Security-Policy, X-Frame-Options, Strict-Transport-Security.",
    "default-login":    "Cambiar credenciales por defecto y restringir acceso por IP o VPN.",
    "panel":            "Restringir panel de administración por IP e implementar 2FA.",
    "cve":              "Aplicar parche de seguridad oficial o actualizar a versión corregida.",
    "generic":          "Revisar configuración según guías de seguridad del fabricante y OWASP.",
}

# Puertos de alto riesgo para nmap: (descripción, severidad, tags)
RISKY_PORTS = {
    21:    ("FTP expuesto — protocolo sin cifrado",        "medium",   ["exposure", "ssl"]),
    23:    ("Telnet expuesto — protocolo inseguro",        "high",     ["exposure", "misconfiguration"]),
    25:    ("SMTP expuesto sin control de relay",          "low",      ["exposure", "misconfiguration"]),
    445:   ("SMB expuesto a internet",                     "high",     ["exposure", "misconfiguration"]),
    3306:  ("MySQL expuesto directamente a internet",      "high",     ["exposure", "default-login"]),
    5432:  ("PostgreSQL expuesto directamente a internet", "high",     ["exposure", "default-login"]),
    5900:  ("VNC expuesto — acceso remoto sin 2FA",        "high",     ["exposure", "default-login"]),
    6379:  ("Redis expuesto sin autenticación",            "critical", ["exposure", "default-login"]),
    8080:  ("Puerto HTTP alternativo expuesto",            "low",      ["exposure", "misconfiguration"]),
    27017: ("MongoDB expuesto sin autenticación",          "critical", ["exposure", "default-login"]),
    2375:  ("Docker API expuesta sin TLS",                 "critical", ["exposure", "misconfiguration"]),
    3389:  ("RDP expuesto directamente a internet",        "high",     ["exposure", "misconfiguration"]),
}

# Riesgo de continuidad: qué tan disruptivo es implementar la remediación
CONTINUITY_RISK_BY_TAG = {
    "dmarc":            "Bajo",
    "spf":              "Bajo",
    "dns":              "Bajo",
    "tls":              "Medio",
    "ssl":              "Medio",
    "headers":          "Bajo",
    "exposure":         "Medio",
    "misconfiguration": "Alto",
    "config":           "Alto",
    "default-login":    "Bajo",
    "panel":            "Bajo",
    "cve":              "Alto",
    "wordpress":        "Medio",
    "token":            "Bajo",
}

# Esfuerzo de remediacion: low | medium | high.
# Es una estimacion de trabajo tecnico, NO un precio. El motor no emite
# valores monetarios en ninguna parte del informe.
REMEDIATION_EFFORT = {
    "dmarc_none":      {"label": "Configurar DMARC con política p=reject",  "effort": "medium"},
    "dmarc_p_none":    {"label": "Endurecer DMARC de p=none a p=reject",    "effort": "low"},
    "spf_softfail":    {"label": "Cambiar SPF de ~all a -all",              "effort": "low"},
    "spf_absent":      {"label": "Implementar registro SPF",                "effort": "low"},
    "tls_absent":      {"label": "Activar TLS/STARTTLS en servidor MX",     "effort": "medium"},
    "mta_sts_missing": {"label": "Implementar MTA-STS y reporting",         "effort": "medium"},
    "dnssec_absent":   {"label": "Activar DNSSEC en zona DNS",              "effort": "high"},
}

EFFORT_ORDER = {"low": 0, "medium": 1, "high": 2}

# ── HELPERS ───────────────────────────────────────────────────────────────────
def load_json_lines(path: Path) -> list:
    """Carga hallazgos desde JSONL o JSON array (nuclei -json-export usa array)."""
    results = []
    if not path.exists() or path.stat().st_size == 0:
        return results
    with open(path) as f:
        content = f.read().strip()
    if not content:
        return results
    # nuclei -json-export produce un JSON array; -json produce JSONL
    if content.lstrip().startswith('['):
        try:
            items = json.loads(content)
            if isinstance(items, list):
                return [item for item in items if isinstance(item, dict)]
        except json.JSONDecodeError:
            pass
    # Fallback: JSONL (una línea por objeto)
    for line in content.splitlines():
        line = line.strip()
        if not line:
            continue
        try:
            obj = json.loads(line)
            if isinstance(obj, dict):
                results.append(obj)
        except json.JSONDecodeError:
            continue
    return results

def load_json(path: Path):
    if not path or not Path(path).exists():
        return None
    with open(path) as f:
        return json.load(f)

def get_category(tags: list) -> str:
    for tag in (tags or []):
        if tag.lower() in TAG_TO_CATEGORY:
            return TAG_TO_CATEGORY[tag.lower()]
    return "Sin categoría"

def get_recommendation(tags: list) -> str:
    for tag in (tags or []):
        if tag.lower() in RECOMMENDATIONS:
            return RECOMMENDATIONS[tag.lower()]
    return RECOMMENDATIONS["generic"]

def get_continuity_risk(tags: list) -> str:
    for tag in (tags or []):
        risk = CONTINUITY_RISK_BY_TAG.get(tag.lower())
        if risk:
            return risk
    return "Medio"

def make_finding(idx, name, severity, category, host, description, recommendation,
                 cvss_score=None, cve=None, cwe=None, references=None, tags=None,
                 continuity_risk=None):
    sev = severity.lower()
    _risk = continuity_risk or get_continuity_risk(tags or [])
    if sev == "info":
        _risk = "Bajo"
    return {
        "id":               f"VULN-{idx:03d}",
        "name":             name,
        "severity":         sev,
        "severity_label":   SEVERITY_MAP.get(sev, SEVERITY_MAP["unknown"])["label"],
        "severity_priority":SEVERITY_MAP.get(sev, SEVERITY_MAP["unknown"])["priority"],
        "cvss_range":       SEVERITY_MAP.get(sev, SEVERITY_MAP["unknown"])["cvss_range"],
        "cvss_score":       cvss_score,
        "category":         category,
        "tags":             tags or [],
        "host":             host,
        "matched_at":       host,
        "description":      description,
        "recommendation":   recommendation,
        "references":       references or [],
        "cve":              cve,
        "cwe":              cwe or [],
        "continuity_risk":  _risk,
    }

# ── PARSERS ───────────────────────────────────────────────────────────────────
def parse_nuclei_findings(raw: list) -> list:
    findings = []
    seen = set()
    for item in raw:
        if not isinstance(item, dict):
            continue
        info     = item.get("info", {})
        tmpl_id  = item.get("template-id", "unknown")
        host     = item.get("host", "unknown")
        key      = f"{tmpl_id}:{host}"
        if key in seen:
            continue
        seen.add(key)

        severity = info.get("severity", "unknown").lower()
        tags     = info.get("tags", [])
        if isinstance(tags, str):
            tags = [t.strip() for t in tags.split(",")]

        raw_name = info.get("name", tmpl_id)
        name_es  = TEMPLATE_NAME_ES.get(raw_name) or TEMPLATE_NAME_ES.get(tmpl_id) or raw_name
        findings.append(make_finding(
            idx            = len(findings) + 1,
            name           = name_es,
            severity       = severity,
            category       = get_category(tags),
            host           = host,
            description    = info.get("description", "Sin descripción disponible."),
            recommendation = get_recommendation(tags),
            cvss_score     = info.get("classification", {}).get("cvss-score"),
            cve            = next((t for t in tags if t.upper().startswith("CVE-")), None),
            cwe            = info.get("classification", {}).get("cwe-id", []),
            references     = info.get("reference", []),
            tags           = tags,
        ))
    findings.sort(key=lambda x: x["severity_priority"])
    return findings


def parse_dmarc(dmarc_data: dict | None, finding_offset: int = 0):
    """
    Retorna (email_block, formal_findings).
    email_block  → va al resumen ejecutivo (bloque visual SPF/DMARC/DKIM)
    formal_findings → van a la tabla de hallazgos con severidad real
    """
    if not dmarc_data:
        return {"status": "no_analizado", "findings": []}, []

    email_findings = []   # bloque visual
    formal         = []   # hallazgos formales para la tabla
    idx            = finding_offset + 1
    domain         = dmarc_data.get("domain", "")

    # ── SPF ──────────────────────────────────────────────────────────────────
    spf    = dmarc_data.get("spf", {})
    record = spf.get("record", "")
    valid  = spf.get("valid", False)
    parsed = spf.get("parsed", {})
    spf_all = parsed.get("all", "")

    if not valid:
        email_findings.append({
            "component": "SPF", "status": "error",
            "detail": spf.get("error", "Registro SPF inválido o ausente"),
            "record": record,
            "risk": "Alto — suplantación de identidad por correo (BEC)",
        })
        formal.append(make_finding(
            idx=idx, name="Registro SPF ausente o inválido", severity="high",
            category="Seguridad de correo electrónico", host=domain,
            description=(
                "El dominio no cuenta con registro SPF válido. Cualquier servidor "
                "puede enviar correos suplantando este dominio, facilitando phishing "
                "y fraude BEC (Business Email Compromise)."
            ),
            recommendation="Crear registro SPF: v=spf1 include:[proveedor] -all",
            references=["https://www.rfc-editor.org/rfc/rfc7208"],
            tags=["spf", "email"],
        ))
        idx += 1
    elif spf_all == "softfail" or (record and "-all" not in record):
        email_findings.append({
            "component": "SPF", "status": "advertencia",
            "detail": f"SPF con mecanismo permisivo (~all): {record}",
            "record": record,
            "risk": "Medio — spoofing parcial posible desde IPs no listadas",
        })
        formal.append(make_finding(
            idx=idx, name="SPF configurado con softfail (~all)", severity="medium",
            category="Seguridad de correo electrónico", host=domain,
            description=(
                f"El registro SPF usa ~all (softfail) en lugar de -all (hardfail). "
                f"Esto permite que servidores no autorizados envíen correos que "
                f"pueden pasar filtros antispam. Registro actual: {record}"
            ),
            recommendation=(
                "Cambiar el mecanismo final de ~all a -all una vez verificadas "
                "todas las fuentes legítimas de envío del dominio."
            ),
            references=["https://www.rfc-editor.org/rfc/rfc7208"],
            tags=["spf", "email"],
        ))
        idx += 1
    else:
        email_findings.append({
            "component": "SPF", "status": "ok",
            "detail": "SPF configurado correctamente con -all",
            "record": record, "risk": "Bajo",
        })

    # ── DMARC ─────────────────────────────────────────────────────────────────
    dmarc  = dmarc_data.get("dmarc", {})
    record = dmarc.get("record", "")
    valid  = dmarc.get("valid", False)
    policy = dmarc.get("tags", {}).get("p", {}).get("value", "none") if valid else None
    rua    = dmarc.get("tags", {}).get("rua") if valid else None

    if not valid:
        email_findings.append({
            "component": "DMARC", "status": "error",
            "detail": dmarc.get("error", "Registro DMARC ausente"),
            "record": "", "risk": "Crítico — sin protección contra phishing y BEC",
        })
        formal.append(make_finding(
            idx=idx, name="Registro DMARC ausente", severity="critical",
            category="Seguridad de correo electrónico", host=domain,
            description=(
                "El dominio no tiene registro DMARC. Cualquier actor puede enviar "
                "correos suplantando este dominio sin restricción alguna."
            ),
            recommendation=(
                "Implementar DMARC: v=DMARC1; p=reject; "
                f"rua=mailto:dmarc@{domain}"
            ),
            references=["https://dmarc.org/overview/"],
            tags=["dmarc", "email"],
        ))
        idx += 1
    elif policy == "none":
        email_findings.append({
            "component": "DMARC", "status": "advertencia",
            "detail": f"DMARC presente pero con p=none (sin efecto real): {record}",
            "record": record,
            "risk": "Alto — correos fraudulentos no son rechazados automáticamente",
        })
        formal.append(make_finding(
            idx=idx, name="DMARC configurado con p=none (sin enforcement)", severity="high",
            category="Seguridad de correo electrónico", host=domain,
            description=(
                f"El dominio tiene DMARC pero con política p=none, que solo monitorea "
                f"sin rechazar correos fraudulentos. Cualquier servidor puede suplantar "
                f"@{domain} y los destinatarios recibirán el correo normalmente. "
                f"Registro actual: {record}"
            ),
            recommendation=(
                "Escalar la política DMARC progresivamente: "
                "1) p=quarantine para mover sospechosos a spam, "
                "2) p=reject para bloquear definitivamente. "
                f"Agregar rua=mailto:dmarc@{domain} para recibir reportes."
            ),
            references=["https://dmarc.org/overview/", "https://dmarcguide.globalcyberalliance.org/"],
            tags=["dmarc", "email"],
        ))
        idx += 1
    elif policy == "quarantine":
        email_findings.append({
            "component": "DMARC", "status": "advertencia",
            "detail": f"DMARC con p=quarantine (nivel intermedio): {record}",
            "record": record, "risk": "Medio — escalar a p=reject",
        })
        formal.append(make_finding(
            idx=idx, name="DMARC con política p=quarantine (incompleto)", severity="medium",
            category="Seguridad de correo electrónico", host=domain,
            description=(
                f"DMARC está configurado con p=quarantine, que mueve correos "
                f"fraudulentos a spam pero no los bloquea definitivamente."
            ),
            recommendation="Escalar a p=reject para bloqueo total de suplantación.",
            references=["https://dmarc.org/overview/"],
            tags=["dmarc", "email"],
        ))
        idx += 1
    else:
        email_findings.append({
            "component": "DMARC", "status": "ok",
            "detail": f"DMARC configurado con p=reject",
            "record": record, "risk": "Bajo",
        })

# ── HALLAZGO: RIESGO DE REBOTE Y SPAM ────────────────────────────────────
    # Se activa si SPF o DMARC están ausentes o mal configurados
    spf_missing  = not spf.get("valid", False)
    dmarc_missing = (not dmarc.get("valid", False)) or policy == "none"
    if spf_missing or dmarc_missing:
        rebote_detail = []
        if spf_missing:
            rebote_detail.append("SPF ausente o inválido")
        if dmarc_missing:
            rebote_detail.append("DMARC ausente o sin enforcement")
        email_findings.append({
            "component": "Entregabilidad de correo",
            "status": "error",
            "detail": (
                f"El correo saliente del dominio puede ser rechazado o filtrado: "
                f"{', '.join(rebote_detail)}. Los servidores de destino rechazan o "
                f"filtran correo de dominios sin autenticación válida."
            ),
            "record": "",
            "risk": "Crítico — correo saliente rechazado o filtrado",
        })

    # ── MX / TLS ──────────────────────────────────────────────────────────────
    mx = dmarc_data.get("mx", {})
    for host_entry in mx.get("hosts", []):
        hostname = host_entry.get("hostname", "")
        tls      = host_entry.get("tls", False)
        starttls = host_entry.get("starttls", False)
        if not tls and not starttls:
            email_findings.append({
                "component": "TLS correo", "status": "error",
                "detail": f"Servidor {hostname} no usa TLS — correos viajan sin cifrar",
                "record": hostname,
                "risk": "Alto — interceptación de correos en tránsito",
            })
            formal.append(make_finding(
                idx=idx, name=f"Servidor de correo sin TLS ({hostname})", severity="high",
                category="Configuración TLS/SSL", host=hostname,
                description=(
                    f"El servidor de correo {hostname} no tiene TLS habilitado. "
                    "Los correos entre servidores viajan en texto plano y pueden "
                    "ser interceptados o modificados, comprometiendo la "
                    "confidencialidad de las comunicaciones con clientes, "
                    "proveedores y contrapartes."
                ),
                recommendation=(
                    "Habilitar STARTTLS en el servidor de correo. "
                    "Configurar MTA-STS para forzar TLS en todas las conexiones entrantes."
                ),
                references=["https://www.rfc-editor.org/rfc/rfc3207"],
                tags=["ssl", "email", "tls"],
            ))
            idx += 1

    # ── MTA-STS ───────────────────────────────────────────────────────────────
    mta_sts = dmarc_data.get("mta_sts", {})
    if not mta_sts.get("valid", False):
        email_findings.append({
            "component": "MTA-STS", "status": "advertencia",
            "detail": "MTA-STS no configurado — TLS no forzado en correos entrantes",
            "record": "", "risk": "Medio — sin garantía de cifrado en tránsito",
        })
        formal.append(make_finding(
            idx=idx, name="MTA-STS no configurado", severity="low",
            category="Seguridad de correo electrónico", host=domain,
            description=(
                "MTA-STS no configurado — no hay garantía de que los servidores "
                "externos usen TLS al conectarse a este dominio."
            ),
            recommendation=(
                f"Publicar política MTA-STS en _mta-sts.{domain} y registro TXT "
                f"_smtp._tls.{domain} para forzar TLS en conexiones entrantes."
            ),
            references=["https://www.rfc-editor.org/rfc/rfc8461"],
            tags=["email", "tls", "mta-sts"],
        ))
        idx += 1

    errors   = [f for f in email_findings if f["status"] == "error"]
    warnings = [f for f in email_findings if f["status"] == "advertencia"]

    email_block = {
        "status":        "error" if errors else ("advertencia" if warnings else "ok"),
        "findings":      email_findings,
        "error_count":   len(errors),
        "warning_count": len(warnings),
    }

    return email_block, formal


def parse_technologies(whatweb_data) -> list:
    if not whatweb_data or not isinstance(whatweb_data, list):
        return []
    techs = []
    for entry in whatweb_data:
        if not isinstance(entry, dict):
            continue
        target  = entry.get("target", "")
        plugins = entry.get("plugins", {})
        detected = []
        for name, details in plugins.items():
            version = details.get("version", [])
            detected.append({"name": name, "version": version[0] if version else ""})
        if detected:
            techs.append({"url": target, "technologies": detected})
    return techs


def _nmap_hosts(nmap_data: dict) -> list:
    nmaprun = nmap_data.get("nmaprun", nmap_data)
    hosts = nmaprun.get("host", [])
    return [hosts] if isinstance(hosts, dict) else hosts

def _nmap_host_addr(host: dict) -> str:
    addr = host.get("address", {})
    if isinstance(addr, list):
        for a in addr:
            if isinstance(a, dict) and a.get("addrtype") == "ipv4":
                return a.get("addr", "unknown")
        return addr[0].get("addr", "unknown") if addr else "unknown"
    return addr.get("addr", "unknown")

def _nmap_hostname(host: dict) -> str:
    hns = host.get("hostnames", {})
    hn = hns.get("hostname", []) if isinstance(hns, dict) else []
    if isinstance(hn, dict):
        return hn.get("name", "")
    return hn[0].get("name", "") if hn else ""

def _nmap_ports(host: dict) -> list:
    ports = host.get("ports", {})
    pl = ports.get("port", []) if isinstance(ports, dict) else []
    return [pl] if isinstance(pl, dict) else pl

def parse_nmap_findings(nmap_data: dict | None, finding_offset: int = 0) -> list:
    if not nmap_data:
        return []
    findings = []
    seen: set = set()
    idx = finding_offset + 1
    for host in _nmap_hosts(nmap_data):
        ip       = _nmap_host_addr(host)
        hostname = _nmap_hostname(host) or ip
        for port_entry in _nmap_ports(host):
            state = port_entry.get("state", {})
            if (state.get("state") if isinstance(state, dict) else str(state)) != "open":
                continue
            portid   = int(port_entry.get("portid", 0))
            protocol = port_entry.get("protocol", "tcp")
            svc      = port_entry.get("service", {})
            svc_name = svc.get("name", "unknown")
            svc_ver  = f"{svc.get('product','')} {svc.get('version','')}".strip()
            key = f"{hostname}:{portid}"
            if key in seen or portid not in RISKY_PORTS:
                continue
            seen.add(key)
            name, severity, tags = RISKY_PORTS[portid]
            ver_detail = f" Versión detectada: {svc_ver}." if svc_ver else ""
            findings.append(make_finding(
                idx=idx, name=name, severity=severity,
                category=get_category(tags), host=hostname,
                description=(
                    f"Puerto {portid}/{protocol} ({svc_name}) abierto en {hostname}.{ver_detail} "
                    f"Este servicio está expuesto directamente a internet."
                ),
                recommendation=get_recommendation(tags),
                tags=tags,
            ))
            idx += 1
    findings.sort(key=lambda x: x["severity_priority"])
    return findings


def generate_impact_scenarios(dmarc_data: dict | None, domain: str, client: str) -> dict:
    """Escenarios de riesgo tecnico derivados de los hallazgos de correo.

    Describe consecuencias operacionales, no financieras: el motor no emite
    valores monetarios ni referencias normativas. El encuadre de cumplimiento
    lo aporta el framework activo (config/compliance/).
    """
    scenarios = []
    empty = {
        "scenarios":         scenarios,
        "remediation_items": [],
        "remediation_effort": None,
        "remediation_note": (
            "El esfuerzo indicado es una estimacion de trabajo tecnico de "
            "configuracion; no incluye validacion ni monitoreo posterior."
        ),
    }

    if not dmarc_data:
        return empty

    dmarc  = dmarc_data.get("dmarc", {})
    spf    = dmarc_data.get("spf", {})
    mx     = dmarc_data.get("mx", {})

    dmarc_valid  = dmarc.get("valid", False)
    dmarc_policy = dmarc.get("tags", {}).get("p", {}).get("value", "none") if dmarc_valid else None
    spf_valid    = spf.get("valid", False)
    spf_record   = spf.get("record", "")

    # ── ESCENARIO 1: BEC (DMARC ausente o p=none) ────────────────────────────
    if not dmarc_valid or dmarc_policy in ("none", None):
        if not dmarc_valid:
            trigger_desc = f"El dominio @{domain} no tiene DMARC configurado."
            severity     = "Crítico"
            trigger      = "dmarc_none"
        else:
            trigger_desc = (f"El dominio @{domain} tiene DMARC en p=none: la política "
                            f"no instruye rechazar ni poner en cuarentena.")
            severity     = "Alto"
            trigger      = "dmarc_p_none"

        scenarios.append({
            "title":    "Suplantación de identidad por correo (BEC)",
            "severity": severity,
            "trigger":  trigger,
            "description": (
                f"{trigger_desc} Sin una política DMARC que instruya al receptor, un "
                f"tercero puede enviar correo con el dominio {domain} en el remitente "
                f"y los servidores de destino no tienen una señal para rechazarlo."
            ),
            "attack_vector": "Email spoofing → instrucción falsa → acción del destinatario",
            "operational_impact": (
                "Correo fraudulento con remitente aparentemente legítimo puede llegar a "
                "destinatarios internos y externos. Sin registros DMARC agregados, la "
                "organización no tiene visibilidad de los envíos que suplantan su dominio."
            ),
            "reputational_impact": (
                f"Los destinatarios no pueden distinguir un correo suplantado de uno "
                f"emitido por {client}. La confianza en el canal de correo del dominio "
                f"se degrada para todos sus interlocutores."
            ),
        })

    # ── ESCENARIO 2: SPF ausente ─────────────────────────────────────────────
    if not spf_valid:
        scenarios.append({
            "title":    "Ausencia de restricción de origen (SPF)",
            "severity": "Alto",
            "trigger":  "spf_absent",
            "description": (
                f"Sin registro SPF válido en {domain}, no existe una lista de servidores "
                f"autorizados a enviar correo por el dominio. Cualquier servidor puede "
                f"originar correo con ese remitente."
            ),
            "attack_vector": "Sin barrera SPF → envío desde infraestructura arbitraria",
            "operational_impact": (
                "El dominio queda sin el control de origen más básico del correo. "
                "La reputación del dominio ante filtros antispam puede degradarse por "
                "envíos de terceros."
            ),
            "reputational_impact": (
                f"No es posible demostrar técnicamente que un correo fraudulento no "
                f"fue originado por {client}."
            ),
        })
    elif spf_valid and "-all" not in spf_record:
        scenarios.append({
            "title":    "Restricción de origen permisiva (SPF ~all)",
            "severity": "Medio",
            "trigger":  "spf_softfail",
            "description": (
                f"El SPF de {domain} termina en ~all (softfail): el registro declara qué "
                f"servidores son legítimos, pero indica al receptor que acepte igualmente "
                f"el correo de los demás, marcándolo como sospechoso."
            ),
            "attack_vector": "SPF ~all → el receptor acepta correo de origen no autorizado",
            "operational_impact": (
                "El correo enviado desde servidores no autorizados puede ser entregado "
                "en lugar de rechazado. Cambiar ~all por -all es una modificación de un "
                "solo registro DNS."
            ),
            "reputational_impact": (
                "El correo suplantado puede circular sin ser rechazado en origen."
            ),
        })

    # ── ESCENARIO 3: transporte sin cifrar (TLS ausente) ─────────────────────
    for host_entry in mx.get("hosts", []):
        hostname = host_entry.get("hostname", "")
        if not host_entry.get("tls") and not host_entry.get("starttls"):
            scenarios.append({
                "title":    f"Transporte de correo sin cifrar ({hostname})",
                "severity": "Alto",
                "trigger":  "tls_absent",
                "description": (
                    f"El servidor de correo {hostname} no ofrece TLS ni STARTTLS. El "
                    f"correo entre servidores viaja en texto plano y puede ser leído o "
                    f"modificado por cualquier actor con acceso a la ruta de red."
                ),
                "attack_vector": "MITM en tránsito SMTP → lectura o modificación sin detección",
                "operational_impact": (
                    "El contenido de los mensajes y sus adjuntos queda expuesto en "
                    "tránsito. La modificación en ruta no deja rastro para el receptor."
                ),
                "reputational_impact": (
                    "La correspondencia con terceros circula sin garantía de "
                    "confidencialidad ni de integridad."
                ),
            })
            break

    # ── Plan de remediación: esfuerzo, nunca precio ──────────────────────────
    remediation_items = []
    triggers_vistos = set()
    for scenario in scenarios:
        t = scenario.get("trigger")
        if t and t in REMEDIATION_EFFORT and t not in triggers_vistos:
            item = REMEDIATION_EFFORT[t]
            remediation_items.append({
                "label":  item["label"],
                "effort": item["effort"],
            })
            triggers_vistos.add(t)

    # Esfuerzo agregado = el mayor de los items, no una suma.
    total_effort = None
    if remediation_items:
        total_effort = max(
            (i["effort"] for i in remediation_items),
            key=lambda e: EFFORT_ORDER.get(e, 0),
        )

    return {
        "scenarios":          scenarios,
        "remediation_items":  remediation_items,
        "remediation_effort": total_effort,
        "remediation_note":   empty["remediation_note"],
    }


def group_findings(findings: list) -> list:
    """
    Agrupa hallazgos informativos por categoría.
    Los de severity critical/high/medium/low se mantienen individuales.
    Los info se agrupan en una fila resumen por categoría.
    """
    individual = []
    grouped_cats = {}

    for f in findings:
        if f["severity"] in ("critical", "high", "medium", "low"):
            individual.append(f)
        else:
            cat = f["category"]
            if cat not in grouped_cats:
                grouped_cats[cat] = {
                    "count": 0,
                    "hosts": set(),
                    "sample": f,
                }
            grouped_cats[cat]["count"] += 1
            grouped_cats[cat]["hosts"].add(f.get("host", ""))

    idx = len(individual) + 1
    for cat, data in grouped_cats.items():
        hosts_str = ", ".join(sorted(data["hosts"])[:3])
        if len(data["hosts"]) > 3:
            hosts_str += f" (+{len(data['hosts']) - 3} más)"
        individual.append({
            "id": f"GRP-{idx:03d}",
            "name": f"{cat} ({data['count']} hallazgos)",
            "severity": "info",
            "severity_label": "INFORMATIVA",
            "severity_priority": 5,
            "cvss_range": "0.0",
            "cvss_score": None,
            "category": cat,
            "tags": data["sample"].get("tags", []),
            "host": hosts_str,
            "matched_at": hosts_str,
            "description": (
                f"Se detectaron {data['count']} hallazgos informativos en la categoría "
                f"'{cat}' distribuidos en {len(data['hosts'])} host(s). "
                f"Estos hallazgos no representan vulnerabilidades explotables pero "
                f"constituyen información útil para el hardening de la infraestructura."
            ),
            "recommendation": data["sample"].get("recommendation", ""),
            "references": [],
            "continuity_risk": "Bajo",
        })
        idx += 1

    individual.sort(key=lambda x: x["severity_priority"])
    return individual


def calculate_risk_score(findings: list) -> dict:
    weights = {"critical": 40, "high": 20, "medium": 8, "low": 2, "info": 0, "unknown": 0}
    total   = 0
    counts  = {"critical": 0, "high": 0, "medium": 0, "low": 0, "info": 0}
    for f in findings:
        sev    = f.get("severity", "unknown")
        total += weights.get(sev, 0)
        if sev in counts:
            counts[sev] += 1
    score = min(100, total)

    if   score >= 80: level = "Crítico"
    elif score >= 50: level = "Alto"
    elif score >= 25: level = "Medio"
    elif score >  0:  level = "Bajo"
    else:             level = "Sin hallazgos significativos"

    return {"score": score, "level": level, "counts": counts}


def spanish_date() -> str:
    months = ["enero","febrero","marzo","abril","mayo","junio",
              "julio","agosto","septiembre","octubre","noviembre","diciembre"]
    now = datetime.now()
    return f"{now.day} de {months[now.month-1]} de {now.year}"


def build_report(args, nuclei_findings, email_block, email_formal, technologies,
                 dmarc_data=None, nmap_findings=None, compliance_fw=None) -> dict:
    # Combinar hallazgos: email → nuclei → nmap; re-numerar IDs
    all_findings = []
    for i, f in enumerate(email_formal + nuclei_findings + (nmap_findings or []), 1):
        f = dict(f)
        f["id"] = f"VULN-{i:03d}"
        all_findings.append(f)

    if args.report_type == "detailed":
        all_findings = group_findings(all_findings)

    risk = calculate_risk_score(all_findings)
    date = spanish_date()

    report_type = getattr(args, "report_type", "summary")
    has_risk    = risk["counts"]["critical"] > 0 or risk["counts"]["high"] > 0

    business_impact = generate_impact_scenarios(dmarc_data, args.domain, args.client)
    key_rec = (
        "Se identificaron debilidades en la configuración de correo del dominio "
        "@{domain} que permiten suplantar el remitente. Se recomienda implementar "
        "DMARC con política p=reject como prioridad inmediata."
        .format(domain=args.domain)
        if has_risk
        else "No se identificaron hallazgos de alto impacto en el escaneo de superficie."
    )

    # Encuadre de cumplimiento: lo aporta el framework activo, no el motor.
    compliance = build_compliance_block(compliance_fw, all_findings)

    return {
        "report_type": report_type,
        "compliance":  compliance,
        "meta": {
            "version":              "1.0",
            "generated_at":         datetime.now().isoformat(),
            "generated_date_human": date,
            "tool":                 "crowsnest",
            "methodology":          "OSINT pasivo + análisis de superficie no intrusivo",
            "disclaimer": (
                "Este informe fue generado mediante reconocimiento pasivo e inspección de "
                "servicios expuestos públicamente. No se realizaron pruebas de explotación "
                "activa ni acceso no autorizado a sistemas. Los hallazgos representan riesgos "
                "potenciales identificados desde internet, sin autenticación."
            ),
        },
        "client": {
            "name":   args.client,
            "domain": args.domain,
        },
        "executive_summary": {
            "risk_score":            risk["score"],
            "risk_level":            risk["level"],
            "total_findings":        len(all_findings),
            "findings_by_severity":  risk["counts"],
            "email_security_status": email_block.get("status", "no_analizado"),
            "key_recommendation":    key_rec,
        },
        "findings":        all_findings,
        "email_security":  email_block,
        "business_impact": business_impact,
        "technologies":    technologies,
    }


# ── MAIN ──────────────────────────────────────────────────────────────────────
def main():
    parser = argparse.ArgumentParser(description="Generador de informes Crowsnest")
    parser.add_argument("--input",       required=True,  help="JSONL de nuclei (puede estar vacío)")
    parser.add_argument("--dmarc",       default=None,   help="JSON de checkdmarc")
    parser.add_argument("--tech",        default=None,   help="JSON de whatweb")
    parser.add_argument("--client",      required=True)
    parser.add_argument("--domain",      required=True)
    parser.add_argument("--output",      required=True)
    parser.add_argument("--nmap",        default=None,   help="JSON de nmap (-oJ)")
    parser.add_argument("--report-type", default="summary",
                        choices=["summary", "detailed", "remediation"],
                        help="Tipo de informe: summary (default), detailed o remediation")
    parser.add_argument("--compliance", default=None,
                        help="Id del framework de cumplimiento (config/compliance/). "
                             "Si se omite, usa CROWSNEST_COMPLIANCE_FRAMEWORK o el unico disponible.")
    args = parser.parse_args()

    print(f"[*] Procesando hallazgos de nuclei: {args.input}")
    nuclei_findings = parse_nuclei_findings(load_json_lines(Path(args.input)))
    print(f"[+] {len(nuclei_findings)} hallazgos de nuclei procesados")

    print(f"[*] Analizando seguridad de correo...")
    dmarc_data = load_json(Path(args.dmarc)) if args.dmarc else None
    email_block, email_formal = parse_dmarc(dmarc_data, finding_offset=0)
    print(f"[+] Estado de correo: {email_block['status']} — {len(email_formal)} hallazgos formales")

    print(f"[*] Procesando tecnologías...")
    tech_raw     = load_json(Path(args.tech)) if args.tech else None
    technologies = parse_technologies(tech_raw if isinstance(tech_raw, list) else [])

    nmap_findings = []
    if args.nmap:
        print(f"[*] Procesando hallazgos de nmap: {args.nmap}")
        nmap_data     = load_json(Path(args.nmap))
        nmap_findings = parse_nmap_findings(nmap_data,
                                            finding_offset=len(email_formal) + len(nuclei_findings))
        print(f"[+] {len(nmap_findings)} hallazgos de nmap procesados")

    compliance_fw = load_compliance(args.compliance)
    if compliance_fw:
        print(f"[*] Framework de cumplimiento: {compliance_fw.get('name')} "
              f"({compliance_fw.get('id')})")

    print(f"[*] Construyendo informe ({args.report_type})...")
    report = build_report(args, nuclei_findings, email_block, email_formal, technologies,
                          dmarc_data=dmarc_data, nmap_findings=nmap_findings,
                          compliance_fw=compliance_fw)

    out = Path(args.output)
    out.parent.mkdir(parents=True, exist_ok=True)
    with open(out, "w", encoding="utf-8") as f:
        json.dump(report, f, ensure_ascii=False, indent=2)

    r = report["executive_summary"]
    print(f"\n{'='*56}")
    print(f"  {args.client} ({args.domain})")
    print(f"{'='*56}")
    print(f"  Riesgo   : {r['risk_level']} ({r['risk_score']}/100)")
    print(f"  Total    : {r['total_findings']} hallazgos")
    print(f"  Críticos : {r['findings_by_severity']['critical']}")
    print(f"  Altos    : {r['findings_by_severity']['high']}")
    print(f"  Medios   : {r['findings_by_severity']['medium']}")
    print(f"  Bajos    : {r['findings_by_severity']['low']}")
    print(f"  Correo   : {r['email_security_status']}")
    print(f"{'='*56}\n")


if __name__ == "__main__":
    main()
