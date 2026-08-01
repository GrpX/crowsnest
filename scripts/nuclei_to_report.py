#!/usr/bin/env python3
"""
nuclei_to_report.py — Convierte JSON de nuclei + checkdmarc a informe estructurado S.I.N.S.

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
from datetime import datetime
from pathlib import Path

# ── SECTORES CON REPUTACIÓN COMO ACTIVO CENTRAL ───────────────────────────────
REPUTATION_SECTORS = {
    "legal":     ["abogad", "ley", "legal", "juridi", "notari", "litig", "tribunal",
                  "demand", "defensa", "penal", "civil", "laboral", "tributari",
                  "asesoria", "consultoria juridica", "estudio", "bufete"],
    "salud":     ["clinic", "medico", "dental", "dentista", "odontolog", "salud",
                  "veterinar", "centro medico", "consulta", "hospital", "nutricion",
                  "kinesiolog", "psicolog", "psiquiatr", "fisioterap"],
    "contable":  ["contad", "contabilidad", "audit", "tributari", "impuesto",
                  "asesoria contable", "consultoria contable"],
    "financiero": ["financier", "banco", "credito", "inversi", "patrimoni",
                  "corredora", "seguros", "fondos"],
    "educacion": ["colegio", "escuela", "instituto", "universidad", "educacion",
                  "centro educativo", "preescolar"],
    "inmobiliario": ["inmobiliari", "corredora de propiedades", "bienes raices"],
}

def detect_reputation_sector(client_name: str, domain: str, technologies: list,
                              subdomains: list = None) -> str | None:
    """
    Detecta si la empresa pertenece a un sector dependiente de reputación.
    Retorna el sector detectado (str) o None si no aplica.
    Búsqueda case-insensitive en nombre, dominio, tecnologías y subdominios.
    """
    haystack = " ".join([
        (client_name or "").lower(),
        (domain or "").lower(),
        " ".join(str(t.get("name", "")).lower() for t in (technologies or [])),
        " ".join(str(s).lower() for s in (subdomains or [])),
    ])

    for sector, keywords in REPUTATION_SECTORS.items():
        for kw in keywords:
            if kw in haystack:
                return sector
    return None

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

TAG_TO_CATEGORY = {
    "ssl":              "Configuración TLS/SSL (A02:2021)",
    "dmarc":            "Seguridad de correo electrónico",
    "spf":              "Seguridad de correo electrónico",
    "exposure":         "Exposición de información sensible (A01:2021)",
    "misconfiguration": "Mala configuración de seguridad (A05:2021)",
    "config":           "Mala configuración de seguridad (A05:2021)",
    "dns":              "Configuración DNS",
    "headers":          "Cabeceras HTTP de seguridad (A05:2021)",
    "default-login":    "Credenciales por defecto (A07:2021)",
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

REMEDIATION_COSTS = {
    "dmarc_none":      {"label": "Configurar DMARC con política p=reject",      "cost_uf": 1.5},
    "dmarc_p_none":    {"label": "Endurecer DMARC de p=none a p=reject",        "cost_uf": 1.0},
    "spf_softfail":    {"label": "Cambiar SPF de ~all a -all",                  "cost_uf": 0.5},
    "spf_absent":      {"label": "Implementar registro SPF",                    "cost_uf": 1.0},
    "tls_absent":      {"label": "Activar TLS/STARTTLS en servidor MX",         "cost_uf": 2.0},
    "mta_sts_missing": {"label": "Implementar MTA-STS y reporting",             "cost_uf": 1.5},
    "dnssec_absent":   {"label": "Activar DNSSEC en zona DNS",                  "cost_uf": 1.5},
}

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
                f"Sus correos pueden rebotar o llegar a spam: {', '.join(rebote_detail)}. "
                f"Los servidores de destino rechazan o filtran correos de dominios sin "
                f"autenticación válida."
            ),
            "record": "",
            "risk": "Crítico — correos propios rebotando o en spam",
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
                category="Configuración TLS/SSL (A02:2021)", host=hostname,
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
    """Genera escenarios de impacto en el negocio a partir de hallazgos de correo."""
    scenarios = []

    if not dmarc_data:
        return {
            "scenarios": scenarios,
            "legal_obligations": [],
            "remediation_items": [],
            "remediation_total_uf": 0,
            "incident_cost_min_uf": 500,
            "incident_cost_max_uf": 5000,
            "max_multa_utm": 20000,
            "max_multa_clp_aprox": "1.480 millones",
            "remediation_note": "",
        }

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
            trigger_desc = f"El dominio @{domain} tiene DMARC activo pero con política p=none, que solo monitorea sin bloquear."
            severity     = "Alto"
            trigger      = "dmarc_p_none"

        scenarios.append({
            "title":    "Fraude BEC — Suplantación de Identidad por Correo",
            "severity": severity,
            "trigger":  trigger,
            "description": (
                f"{trigger_desc} Cualquier atacante puede enviar correos suplantando @{domain} "
                f"a clientes, proveedores o autoridades sin restricción técnica. En un estudio jurídico "
                f"esto permite emitir instrucciones falsas de pago, modificar plazos procesales "
                f"o suplantar comunicaciones con tribunales."
            ),
            "attack_vector": "Email spoofing → instrucción falsa → transferencia o acción fraudulenta",
            "financial_impact": (
                "Fraude promedio BEC en Latinoamérica: USD 62.000 por incidente (FBI IC3 2023). "
                "Para PYMES chilenas: pérdidas estimadas entre UF 500–5.000 por evento. "
                "Bajo la Ley 21.719, un incidente que exponga datos personales puede derivar "
                "en multas de hasta 10.000 UTM (~CLP 740 millones)."
            ),
            "reputational_impact": (
                f"Los clientes de {client} pueden recibir correos fraudulentos que parecen legítimos. "
                "La obligación de notificar a la APDP y a los afectados dentro de 72 horas "
                "agrava el impacto reputacional y puede derivar en demandas de responsabilidad civil."
            ),
            "sector_note": (
                "Para estudios jurídicos, clínicas y oficinas contables, la suplantación de "
                "correo permite acceder a datos personales sensibles (información médica, "
                "judicial, financiera). La Ley 21.719 exige consentimiento explícito para "
                "datos sensibles — un compromiso de correo destruye esa cadena de consentimiento."
            ),
        })

    # ── ESCENARIO 2: SPOOFING PARCIAL (SPF softfail o ausente) ───────────────
    if not spf_valid:
        scenarios.append({
            "title":    "Suplantación Total del Dominio por Correo",
            "severity": "Alto",
            "trigger":  "spf_absent",
            "description": (
                f"Sin registro SPF válido en {domain}, cualquier servidor puede enviar "
                f"correos como @{domain} sin restricción técnica alguna. "
                f"No existe barrera que diferencie correos legítimos de fraudulentos."
            ),
            "attack_vector": "Sin barrera SPF → suplantación trivial desde cualquier servidor",
            "financial_impact": (
                "Campaña de phishing masiva contra clientes puede resultar en demandas. "
                "Costo estimado de limpieza de reputación de dominio y notificación: UF 15–80. "
                "Sanción bajo Ley 21.719 por tratamiento inseguro de datos personales: hasta 10.000 UTM."
            ),
            "reputational_impact": (
                f"Imposible demostrar ante clientes que un correo fraudulento no fue enviado por {client}. "
                "La reputación del dominio puede ser degradada en listas negras de correo."
            ),
            "sector_note": (
                "Phishing dirigido a clientes constituye uso no autorizado de la identidad "
                "del responsable del tratamiento. Las víctimas pueden ejercer derechos ARCO "
                "(acceso, rectificación, cancelación, oposición) y exigir explicaciones bajo "
                "Art. 5° de la Ley 21.719."
            ),
        })
    elif spf_valid and "-all" not in spf_record:
        scenarios.append({
            "title":    "Spoofing Parcial — Correos desde Servidores No Autorizados",
            "severity": "Medio",
            "trigger":  "spf_softfail",
            "description": (
                f"El SPF de {domain} usa ~all (softfail): servidores no autorizados pueden "
                f"enviar correos que algunos sistemas antispam aceptan. Un atacante puede "
                f"usar infraestructura de terceros para distribuir phishing en nombre de {client}."
            ),
            "attack_vector": "SPF ~all bypass → phishing dirigido → robo de credenciales o fraude",
            "financial_impact": (
                "Campañas dirigidas a clientes pueden resultar en demandas por daños. "
                "Corrección de ~all a -all: costo técnico mínimo, impacto preventivo alto."
            ),
            "reputational_impact": (
                "Los correos phishing pueden circular durante días antes de ser detectados. "
                "Cada cliente afectado representa un riesgo legal para la organización."
            ),
            "sector_note": (
                "Phishing dirigido a clientes constituye uso no autorizado de la identidad "
                "del responsable del tratamiento. Las víctimas pueden ejercer derechos ARCO "
                "(acceso, rectificación, cancelación, oposición) y exigir explicaciones bajo "
                "Art. 5° de la Ley 21.719."
            ),
        })

    # ── ESCENARIO 3: INTERCEPTACIÓN DE CORREOS (TLS ausente) ─────────────────
    for host_entry in mx.get("hosts", []):
        hostname = host_entry.get("hostname", "")
        if not host_entry.get("tls") and not host_entry.get("starttls"):
            scenarios.append({
                "title":    f"Interceptación de Correos en Tránsito ({hostname})",
                "severity": "Alto",
                "trigger":  "tls_absent",
                "description": (
                    f"El servidor de correo {hostname} no cifra las conexiones SMTP. "
                    f"Los correos entre servidores viajan en texto plano y pueden ser "
                    f"interceptados, leídos o modificados por cualquier actor con acceso "
                    f"a la ruta de red — incluyendo documentos y datos personales adjuntos."
                ),
                "attack_vector": "MITM en tránsito SMTP → lectura o modificación de correos sin detección",
                "financial_impact": (
                    "Una filtración de correspondencia confidencial puede anular contratos, "
                    "comprometer estrategias legales y generar demandas de clientes afectados. "
                    "Costo estimado de un incidente de este tipo: UF 200–2.000."
                ),
                "reputational_impact": (
                    "La revelación de comunicaciones privilegiadas daña de forma permanente "
                    "la reputación ante clientes y pares del sector."
                ),
                "sector_note": (
                    "Datos personales transmitidos sin cifrado constituyen infracción directa al "
                    "deber de seguridad del Art. 14 ter. Para datos sensibles (salud, datos "
                    "biométricos, información jurídica privilegiada), califica como infracción "
                    "GRAVÍSIMA — hasta 20.000 UTM."
                ),
            })
            break

    legal_obligations = [
        {
            "law":        "Ley 21.719",
            "article":    "Art. 14 ter — Medidas de seguridad",
            "obligation": (
                "Las organizaciones que tratan datos personales deben implementar medidas "
                "técnicas y organizativas apropiadas al riesgo del tratamiento. La configuración "
                "de correo electrónico (DMARC/SPF/TLS) es un control técnico básico exigible, "
                "especialmente al manejar datos sensibles como información médica, jurídica o financiera."
            ),
            "consequence": (
                "Infracción grave: hasta 10.000 UTM (~CLP 740 millones). "
                "Para PYMEs durante el primer año de vigencia (diciembre 2026 - diciembre 2027), "
                "la sanción es amonestación pública en el Registro Nacional de Sanciones y Cumplimiento. "
                "Después de ese período, las multas aplican plenamente."
            ),
        },
        {
            "law":        "Ley 21.719",
            "article":    "Art. 14 quinquies — Notificación de brechas",
            "obligation": (
                "Obligación de notificar a la Agencia de Protección de Datos Personales (APDP) "
                "y a los titulares afectados dentro de 72 horas ante una brecha de seguridad "
                "que represente riesgo para los derechos de las personas. La notificación debe "
                "incluir naturaleza de la brecha, datos afectados y medidas adoptadas."
            ),
            "consequence": (
                "Omitir o demorar la notificación califica como infracción gravísima: "
                "hasta 20.000 UTM (~CLP 1.480 millones) o 4% de los ingresos anuales en "
                "caso de reincidencia. Las sanciones se publican en el Registro Nacional "
                "de Sanciones por 5 años."
            ),
        },
        {
            "law":        "Ley 21.719",
            "article":    "Art. 14 bis — Registro de actividades de tratamiento",
            "obligation": (
                "Mantener un registro actualizado de las actividades de tratamiento de datos "
                "personales. La APDP fiscaliza evidencia operativa — logs, inventarios y "
                "registros datados — no solo políticas. Las medidas de seguridad técnicas "
                "deben ser demostrables."
            ),
            "consequence": (
                "La falta de registro o evidencia técnica documentada se considera infracción "
                "leve a grave según gravedad: 1-10.000 UTM. La existencia de vulnerabilidades "
                "conocidas sin remediación documentada agrava cualquier sanción."
            ),
        },
    ]

    remediation_items = []
    total_uf = 0
    triggers_vistos = set()
    for scenario in scenarios:
        t = scenario.get("trigger")
        if t and t in REMEDIATION_COSTS and t not in triggers_vistos:
            item = REMEDIATION_COSTS[t]
            remediation_items.append({
                "label":   item["label"],
                "cost_uf": item["cost_uf"],
            })
            total_uf += item["cost_uf"]
            triggers_vistos.add(t)

    return {
        "scenarios":            scenarios,
        "legal_obligations":    legal_obligations,
        "remediation_items":    remediation_items,
        "remediation_total_uf": total_uf,
        "incident_cost_min_uf": 500,
        "incident_cost_max_uf": 5000,
        "max_multa_utm":        20000,
        "max_multa_clp_aprox":  "1.480 millones",
        "remediation_note": (
            "La remediación de los hallazgos identificados tiene un costo técnico "
            "documentado y se ejecuta una sola vez. El ROI frente al costo potencial "
            "de un incidente y las multas asociadas a la Ley 21.719 es excepcional."
        ),
    }


# ── MARCO LEY 21.663 — LEY MARCO DE CIBERSEGURIDAD ────────────────────────────
# Multas del Art. 40 de la Ley 21.663. Conversión referencial (mayo 2026):
# 1 UTM ≈ CLP 74.000 · 1 UF ≈ CLP 39.500  →  1 UTM ≈ 1,87 UF
M_LEVE      = "5.000 UTM (≈ UF 9.400)"
M_GRAVE     = "10.000 UTM (≈ UF 18.700)"
M_GRAVISIMA = "20.000 UTM (≈ UF 37.500)"
M_OIV       = "40.000 UTM (≈ UF 75.000)"


def _ciber_legal_obligations() -> list:
    """Deberes de la Ley 21.663 relevantes para un proveedor de servicios esenciales."""
    return [
        {
            "law":     "Ley 21.663",
            "article": "Art. 7° — Deberes generales de ciberseguridad",
            "obligation": (
                "Toda institución obligada debe aplicar de forma permanente medidas "
                "para prevenir, reportar y resolver incidentes de ciberseguridad. La "
                "configuración de correo electrónico (DMARC/SPF/TLS), DNS y superficie "
                "web son controles técnicos básicos y exigibles. La ANCI fiscaliza "
                "evidencia técnica operativa, no solo políticas documentadas."
            ),
            "consequence": (
                f"El incumplimiento de estos deberes se sanciona con multas de {M_LEVE} "
                f"a {M_GRAVE} para la institución obligada. Como su cliente OIV responde "
                f"ante la ANCI por estos controles en toda su cadena de suministro, exigirá "
                f"evidencia de que su empresa los aplica; no poder acreditarlo lo descarta "
                f"como proveedor."
            ),
        },
        {
            "law":     "Ley 21.663",
            "article": "Art. 9° — Deber de reportar al CSIRT Nacional",
            "obligation": (
                "Ante un ciberataque o incidente con efectos significativos existe la "
                "obligación de enviar una alerta temprana al CSIRT Nacional dentro de "
                "3 horas, una actualización dentro de 72 horas y un reporte final "
                "dentro de 15 días corridos. Una infraestructura vulnerable hace "
                "materialmente imposible detectar y reportar un incidente a tiempo."
            ),
            "consequence": (
                f"Esta obligación recae sobre su cliente OIV, cuya infracción gravísima "
                f"se sanciona con multas de hasta {M_OIV}. Una infraestructura suya que "
                f"impida detectar a tiempo un incidente que lo afecte compromete su "
                f"capacidad de reportar y, con ello, su continuidad como proveedor."
            ),
        },
        {
            "law":     "Ley 21.663",
            "article": "Art. 8° — Cadena de suministro de los Operadores de Importancia Vital",
            "obligation": (
                "Los Operadores de Importancia Vital deben implementar un Sistema de "
                "Gestión de Seguridad de la Información (SGSI) continuo que cubre los "
                "riesgos de sus redes y sistemas, incluidos los introducidos por sus "
                "proveedores. Su cliente está legalmente obligado a verificar y exigir "
                "la seguridad de los terceros que lo abastecen."
            ),
            "consequence": (
                f"Su cliente OIV está legalmente obligado a verificar y exigir la "
                f"seguridad de sus proveedores. Un proveedor que no pueda acreditar "
                f"control de su seguridad cuando la ANCI lo requiera es excluido del "
                f"registro de proveedores y pierde el contrato. Las multas de hasta "
                f"{M_OIV} recaen sobre el OIV, lo que le da un incentivo directo para "
                f"sustituir a los proveedores no conformes antes de una auditoría."
            ),
        },
    ]


def generate_impact_scenarios_ciber(dmarc_data: dict | None, domain: str, client: str) -> dict:
    """Escenarios de impacto bajo la Ley 21.663 — Ley Marco de Ciberseguridad.

    Audiencia: empresas proveedoras de operadores de servicios esenciales y de
    Operadores de Importancia Vital (OIV). Reformula los hallazgos OSINT como
    riesgo de incumplimiento de los deberes de ciberseguridad y como vector de
    ataque hacia la infraestructura crítica del cliente final.
    """
    scenarios = []
    result = {
        "scenarios":            scenarios,
        "legal_obligations":    [],
        "remediation_items":    [],
        "remediation_total_uf": 0,
        "incident_cost_min_uf": 800,
        "incident_cost_max_uf": 8000,
        "max_multa_utm":        20000,
        "max_multa_uf":         "37.500",
        "max_multa_clp_aprox":  "1.480 millones",
        "multa_gravisima":      M_GRAVISIMA,
        "multa_oiv":            M_OIV,
        "remediation_note": (
            f"La remediación de los hallazgos identificados tiene un costo técnico "
            f"documentado y se ejecuta una sola vez. Frente a la pérdida del contrato "
            f"con su cliente OIV —que enfrenta multas de la ANCI de hasta {M_OIV} y por "
            f"ley debe exigir seguridad a toda su cadena de suministro—, la inversión en "
            f"remediación es marginal."
        ),
    }
    if not dmarc_data:
        return result

    dmarc = dmarc_data.get("dmarc", {})
    spf   = dmarc_data.get("spf", {})
    mx    = dmarc_data.get("mx", {})

    dmarc_valid  = dmarc.get("valid", False)
    dmarc_policy = dmarc.get("tags", {}).get("p", {}).get("value", "none") if dmarc_valid else None
    spf_valid    = spf.get("valid", False)
    spf_record   = spf.get("record", "")

    # ── ESCENARIO 1: SUPLANTACIÓN DEL PROVEEDOR (DMARC ausente / p=none) ──────
    if not dmarc_valid or dmarc_policy in ("none", None):
        if not dmarc_valid:
            trigger_desc = f"El dominio @{domain} no tiene DMARC configurado."
            severity     = "Crítico"
            trigger      = "dmarc_none"
        else:
            trigger_desc = (f"El dominio @{domain} tiene DMARC activo pero con política "
                            f"p=none, que solo monitorea sin bloquear.")
            severity     = "Alto"
            trigger      = "dmarc_p_none"
        scenarios.append({
            "title":    "Suplantación del Proveedor — Compromiso de la Cadena de Suministro",
            "severity": severity,
            "trigger":  trigger,
            "description": (
                f"{trigger_desc} Cualquier atacante puede enviar correos haciéndose pasar "
                f"por @{domain}. Para un proveedor de operadores de servicios esenciales, "
                f"esto convierte a {client} en el eslabón débil de la cadena de suministro: "
                f"un atacante puede dirigir correos fraudulentos —con instrucciones de pago, "
                f"facturas o archivos maliciosos— al operador de servicios esenciales que es "
                f"su cliente, usando la confianza de la relación comercial como vector de "
                f"entrada hacia su infraestructura crítica."
            ),
            "attack_vector": "Email spoofing del proveedor → correo de confianza al operador esencial → acceso inicial a infraestructura crítica",
            "financial_impact": (
                f"Un ataque a la cadena de suministro que interrumpa un servicio esencial "
                f"expone a su cliente OIV a sanciones de la ANCI de hasta {M_OIV} por "
                f"infracción gravísima. Aunque su empresa no sea la sancionada, ser el "
                f"vector de entrada del incidente implica la terminación del contrato y la "
                f"exclusión de la cadena de suministro, además del costo de la interrupción "
                f"operacional."
            ),
            "reputational_impact": (
                "Ser identificado como el origen de un incidente que afectó a un operador "
                "de servicios esenciales implica la exclusión de los registros de proveedores "
                "y la pérdida de futuras licitaciones. La ANCI puede ordenar la publicación "
                "de la infracción del operador afectado, lo que hace pública la falla en su "
                "cadena de suministro."
            ),
            "sector_note": (
                "El Art. 7° de la Ley 21.663 obliga a aplicar permanentemente medidas para "
                "prevenir incidentes. El Art. 8° exige a los Operadores de Importancia Vital "
                "gestionar los riesgos de su cadena de suministro: su cliente está obligado "
                "por ley a verificar la seguridad de sus proveedores."
            ),
        })

    # ── ESCENARIO 2: SUPLANTACIÓN TOTAL DEL DOMINIO (SPF) ────────────────────
    if not spf_valid:
        scenarios.append({
            "title":    "Suplantación Total del Dominio — Vector de Ataque a Servicios Esenciales",
            "severity": "Alto",
            "trigger":  "spf_absent",
            "description": (
                f"Sin registro SPF válido en {domain}, cualquier servidor puede enviar "
                f"correos como @{domain} sin restricción técnica alguna. No existe barrera "
                f"que diferencie un correo legítimo de {client} de uno fraudulento dirigido "
                f"a su cliente operador de servicios esenciales."
            ),
            "attack_vector": "Sin barrera SPF → suplantación trivial → phishing dirigido al operador esencial",
            "financial_impact": (
                "Una campaña de phishing que use la identidad de la empresa como puerta de "
                "entrada a un operador de servicios esenciales puede provocar un incidente "
                "que exponga a su cliente a sanciones de la ANCI y derive en la terminación "
                "anticipada de su contrato. La corrección de SPF tiene costo técnico mínimo "
                "e impacto preventivo alto."
            ),
            "reputational_impact": (
                f"Es imposible demostrar ante el operador esencial que un correo fraudulento "
                f"no fue enviado por {client}. El dominio puede ser degradado en listas negras, "
                f"afectando toda la comunicación operativa con el cliente."
            ),
            "sector_note": (
                "Los controles de correo son parte de los deberes del Art. 7° de la Ley "
                "21.663 que su cliente OIV debe acreditar en toda su cadena; su ausencia es "
                "un hallazgo que debilita la posición de la empresa frente a las auditorías "
                "de ciberseguridad que el operador está obligado a exigirle."
            ),
        })
    elif spf_valid and "-all" not in spf_record:
        scenarios.append({
            "title":    "Spoofing Parcial — Correos desde Servidores No Autorizados",
            "severity": "Medio",
            "trigger":  "spf_softfail",
            "description": (
                f"El SPF de {domain} usa ~all (softfail): servidores no autorizados pueden "
                f"enviar correos que algunos sistemas antispam aceptan. Un atacante puede usar "
                f"infraestructura de terceros para distribuir phishing en nombre de {client} "
                f"hacia su cliente operador de servicios esenciales."
            ),
            "attack_vector": "SPF ~all bypass → phishing dirigido → acceso a infraestructura del operador esencial",
            "financial_impact": (
                "Las campañas dirigidas al operador esencial pueden derivar en un incidente "
                "que su cliente deba reportar a la ANCI y que ponga en riesgo su contrato. "
                "El endurecimiento de ~all a -all tiene costo técnico mínimo y alto impacto "
                "preventivo."
            ),
            "reputational_impact": (
                "Los correos de phishing pueden circular durante días antes de ser detectados. "
                "Cada incidente debilita la evaluación de seguridad del proveedor."
            ),
            "sector_note": (
                "El Art. 7° de la Ley 21.663 exige medidas permanentes de prevención a la "
                "institución obligada; un SPF permisivo es una brecha conocida y documentable "
                "que su cliente OIV detectará al auditar su cadena de proveedores."
            ),
        })

    # ── ESCENARIO 3: INTERCEPTACIÓN DE CORREOS EN TRÁNSITO (TLS ausente) ─────
    for host_entry in mx.get("hosts", []):
        hostname = host_entry.get("hostname", "")
        if not host_entry.get("tls") and not host_entry.get("starttls"):
            scenarios.append({
                "title":    f"Interceptación de Comunicaciones con el Operador de Servicios Esenciales ({hostname})",
                "severity": "Alto",
                "trigger":  "tls_absent",
                "description": (
                    f"El servidor de correo {hostname} no cifra las conexiones SMTP. Los "
                    f"correos entre servidores viajan en texto plano y pueden ser interceptados, "
                    f"leídos o modificados por cualquier actor con acceso a la ruta de red — "
                    f"incluyendo órdenes de servicio, credenciales de acceso y documentación "
                    f"técnica intercambiada con el operador de servicios esenciales."
                ),
                "attack_vector": "MITM en tránsito SMTP → lectura o alteración de comunicaciones con el operador esencial",
                "financial_impact": (
                    f"La interceptación de credenciales o instrucciones operativas puede "
                    f"habilitar un ataque directo a la infraestructura crítica del cliente. "
                    f"La multa de la ANCI de hasta {M_OIV} recae sobre el operador esencial "
                    f"afectado; para su empresa, el costo combinado de la interrupción del "
                    f"servicio, la respuesta al incidente y la pérdida del contrato supera "
                    f"con creces la inversión en cifrado."
                ),
                "reputational_impact": (
                    "La revelación de comunicaciones operativas confidenciales daña de forma "
                    "permanente la relación con el operador de servicios esenciales y la "
                    "posición de la empresa en futuras licitaciones."
                ),
                "sector_note": (
                    "Transmitir información operativa sin cifrado contradice las medidas "
                    "técnicas apropiadas que exige el Art. 7° de la Ley 21.663 y es un "
                    "hallazgo recurrente en las auditorías que los OIV aplican a sus "
                    "proveedores."
                ),
            })
            break

    triggers_vistos = set()
    total_uf = 0
    for scenario in scenarios:
        t = scenario.get("trigger")
        if t and t in REMEDIATION_COSTS and t not in triggers_vistos:
            item = REMEDIATION_COSTS[t]
            result["remediation_items"].append({
                "label":   item["label"],
                "cost_uf": item["cost_uf"],
            })
            total_uf += item["cost_uf"]
            triggers_vistos.add(t)
    result["remediation_total_uf"] = total_uf
    result["legal_obligations"]    = _ciber_legal_obligations()
    return result


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
                 dmarc_data=None, nmap_findings=None) -> dict:
    # Combinar hallazgos: email → nuclei → nmap; re-numerar IDs
    all_findings = []
    for i, f in enumerate(email_formal + nuclei_findings + (nmap_findings or []), 1):
        f = dict(f)
        f["id"] = f"VULN-{i:03d}"
        all_findings.append(f)

    if args.report_type == "diagnostico":
        all_findings = group_findings(all_findings)

    risk = calculate_risk_score(all_findings)
    date = spanish_date()

    report_type = getattr(args, "report_type", "flash")
    framework   = getattr(args, "framework", "datos")
    has_risk    = risk["counts"]["critical"] > 0 or risk["counts"]["high"] > 0

    if framework == "ciber":
        business_impact = generate_impact_scenarios_ciber(dmarc_data, args.domain, args.client)
        key_rec = (
            "Se identificaron vulnerabilidades en la configuración de correo y la "
            "superficie web de @{domain} que permiten suplantar a {client} y utilizar "
            "la relación comercial con su cliente como vector de ataque hacia un "
            "operador de servicios esenciales. Esto constituye un incumplimiento del "
            "deber de seguridad del Art. 7° de la Ley 21.663 y expone a la empresa a "
            "sanciones de la ANCI. Se recomienda implementar DMARC con p=reject como "
            "prioridad inmediata."
            .format(domain=args.domain, client=args.client)
            if has_risk
            else ("No se identificaron vulnerabilidades de alto impacto en el escaneo "
                  "de superficie. Se recomienda mantener el monitoreo continuo de "
                  "ciberseguridad exigido por el Art. 7° de la Ley 21.663.")
        )
    else:
        business_impact = generate_impact_scenarios(dmarc_data, args.domain, args.client)
        key_rec = (
            "Se identificaron vulnerabilidades en la configuración de correo electrónico "
            "que permiten la suplantación del dominio (@{domain}). Un atacante puede enviar "
            "correos haciéndose pasar por {client}, comprometiendo datos personales de clientes "
            "y vulnerando el deber de seguridad bajo la Ley 21.719. Se recomienda implementar "
            "DMARC con p=reject como prioridad inmediata."
            .format(domain=args.domain, client=args.client)
            if has_risk
            else "No se identificaron vulnerabilidades de alto impacto en el escaneo de superficie."
        )

    reputation_sector = detect_reputation_sector(
        client_name=args.client,
        domain=args.domain,
        technologies=technologies,
        subdomains=[],
    )

    if framework == "ciber":
        appendix = {
            "ley_marco_ciber_relevance": (
                "Los hallazgos de este informe se relacionan directamente con la Ley 21.663, "
                "Ley Marco de Ciberseguridad e Infraestructura Crítica de la Información, que "
                "crea la Agencia Nacional de Ciberseguridad (ANCI). La ley obliga a las "
                "instituciones que prestan servicios esenciales —y, a través de los deberes "
                "de gestión de riesgos de sus operadores, a los proveedores que los abastecen— "
                "a aplicar medidas de seguridad permanentes (Art. 7°) y a reportar los "
                "incidentes al CSIRT Nacional dentro de plazos estrictos: alerta temprana en "
                "3 horas, actualización en 72 horas y reporte final en 15 días corridos "
                "(Art. 9°). La ANCI fiscaliza evidencia técnica operativa, no solo políticas "
                "documentadas. Las infracciones se sancionan con multas de hasta 20.000 UTM "
                "(≈ UF 37.500), que se duplican a 40.000 UTM (≈ UF 75.000) para los "
                "Operadores de Importancia Vital."
            ),
            "owasp_top10_reference": "https://owasp.org/www-project-top-ten/",
            "nist_framework":        "https://www.nist.gov/cyberframework",
        }
    else:
        appendix = {
            "ley_proteccion_datos_relevance": (
                "Los hallazgos de este informe se relacionan directamente con la Ley 21.719 "
                "de Protección de Datos Personales, que entra en plena vigencia el 1 de diciembre "
                "de 2026. La ley aplica a toda organización que trate datos personales en Chile, "
                "sin importar su tamaño. La Agencia de Protección de Datos Personales (APDP) "
                "fiscaliza evidencia técnica operativa, no solo políticas: medidas de seguridad "
                "documentadas, registro de tratamientos y notificación oportuna de brechas. "
                "Para PYMEs, el primer año (diciembre 2026 - diciembre 2027) las sanciones "
                "se limitan a amonestaciones públicas inscritas en el Registro Nacional de "
                "Sanciones y Cumplimiento por 5 años."
            ),
            "owasp_top10_reference": "https://owasp.org/www-project-top-ten/",
            "nist_framework":        "https://www.nist.gov/cyberframework",
        }

    return {
        "report_type": report_type,
        "framework":   framework,
        "meta": {
            "version":              "1.0",
            "generated_at":         datetime.now().isoformat(),
            "generated_date_human": date,
            "tool":                 "ciber-workstation / S.I.N.S.",
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
        "technologies":      technologies,
        "reputation_sector": reputation_sector,
        "appendix": appendix,
    }


# ── MAIN ──────────────────────────────────────────────────────────────────────
def main():
    parser = argparse.ArgumentParser(description="Generador de informes S.I.N.S.")
    parser.add_argument("--input",       required=True,  help="JSONL de nuclei (puede estar vacío)")
    parser.add_argument("--dmarc",       default=None,   help="JSON de checkdmarc")
    parser.add_argument("--tech",        default=None,   help="JSON de whatweb")
    parser.add_argument("--client",      required=True)
    parser.add_argument("--domain",      required=True)
    parser.add_argument("--output",      required=True)
    parser.add_argument("--nmap",        default=None,   help="JSON de nmap (-oJ)")
    parser.add_argument("--report-type", default="flash",
                        choices=["flash", "diagnostico", "trabajo"],
                        help="Tipo de informe: flash (default), diagnostico o trabajo")
    parser.add_argument("--framework", default="datos",
                        choices=["datos", "ciber"],
                        help="Marco legal: datos (Ley 21.719, default) o "
                             "ciber (Ley 21.663 — Ley Marco de Ciberseguridad)")
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

    print(f"[*] Construyendo informe ({args.report_type})...")
    report = build_report(args, nuclei_findings, email_block, email_formal, technologies,
                          dmarc_data=dmarc_data, nmap_findings=nmap_findings)

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
