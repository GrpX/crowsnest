#!/usr/bin/env python3
# =============================================================================
# OpenClaw Orchestrator — Crowsnest
# =============================================================================
# Recibe una lista de dominios y devuelve targets enriquecidos
# mediante una cadena de 3 agentes LLM:
#
#   orquestador  -> triage del negocio y angulo de abordaje
#   descubridor  -> extrae dominio, email y cargo objetivo desde el sitio web
#   summarizer   -> redacta el resumen ejecutivo del informe (en ingles)
#
# El scraping del sitio usa Crawl4AI, con fallback a requests + BeautifulSoup.
#
# Salida: lista JSON de objetos
#   {name, dominio, cargo_objetivo, email, summary, summary_status,
#    confianza, flash_json_usado, hallazgos_usados}
#
# Uso:
#   python3 run_batch.py --input targets/domains.txt --output enriched.json
#   cat google_places.json | python3 run_batch.py
# =============================================================================
from __future__ import annotations

import argparse
import asyncio
import html as _html_entities
import json
import os
import re
import sys
import time
from datetime import datetime
from email.utils import parsedate_to_datetime
from pathlib import Path
from urllib.parse import unquote, urljoin, urlparse

import requests

try:                       # paquete oficial de Ollama (opcional: hay fallback REST)
    import ollama
except Exception:          # noqa: BLE001
    ollama = None

try:                       # dnspython (opcional): validacion de MX de los emails
    import dns.exception
    import dns.resolver
except Exception:          # noqa: BLE001
    dns = None

MODULE_DIR = Path(__file__).resolve().parent
DEFAULT_CONFIG = MODULE_DIR / "config.json"

# Estados del target: definicion canonica en lib/states.py (raiz del repo).
if str(MODULE_DIR.parent) not in sys.path:
    sys.path.insert(0, str(MODULE_DIR.parent))
from lib.states import QUEUED, SKIPPED  # noqa: E402

# ─── COLORES / LOG ──────────────────────────────────────────────────────────
# Todo el log va a stderr; stdout queda libre para el JSON de salida.
def _c(code: str) -> str:
    return f"\033[{code}m"

BG, CY, YL, BR, GR, W, NC = (_c("1;32"), _c("0;36"), _c("1;33"),
                             _c("1;31"), _c("0;37"), _c("1;37"), _c("0"))


def log(m):   print(f"{BG}[✓]{NC} {m}", file=sys.stderr, flush=True)
def info(m):  print(f"{CY}[→]{NC} {m}", file=sys.stderr, flush=True)
def warn(m):  print(f"{YL}[!]{NC} {m}", file=sys.stderr, flush=True)
def error(m): print(f"{BR}[✗]{NC} {m}", file=sys.stderr, flush=True)
def step(m):  print(f"\n{W}{m}{NC}\n{GR}{'-' * 58}{NC}", file=sys.stderr, flush=True)


# ─── CONFIG ─────────────────────────────────────────────────────────────────
def load_config(path=DEFAULT_CONFIG) -> dict:
    """Carga y valida config.json."""
    p = Path(path)
    if not p.is_file():
        raise FileNotFoundError(f"No se encontro la configuracion: {p}")
    cfg = json.loads(p.read_text(encoding="utf-8"))
    agentes = cfg.get("agentes", {})
    for nombre in ("orquestador", "descubridor", "summarizer"):
        if nombre not in agentes:
            raise ValueError(f"Falta el agente '{nombre}' en {p}")
        if not agent_model(cfg, nombre):
            raise ValueError(
                f"El agente '{nombre}' no declara modelo en {p} ni en "
                f"{model_env_var(nombre)}")
    return cfg


def model_env_var(agente: str) -> str:
    """Variable de entorno que sobreescribe el modelo de un agente."""
    return f"CROWSNEST_MODEL_{agente.upper()}"


def agent_model(config: dict, agente: str) -> str:
    """Modelo de un agente.

    Precedencia: CROWSNEST_MODEL_<AGENTE> > CROWSNEST_MODEL > config.json.
    Ningun nombre de modelo vive en el codigo: si config y entorno estan
    vacios, devuelve "" y load_config aborta.
    """
    env = (os.environ.get(model_env_var(agente))
           or os.environ.get("CROWSNEST_MODEL") or "").strip()
    if env:
        return env
    return str(config.get("agentes", {}).get(agente, {}).get("model", "")).strip()


def required_models(config: dict) -> set:
    """Conjunto de modelos referenciados por los agentes, ya resueltos."""
    modelos = {agent_model(config, n) for n in config.get("agentes", {})}
    return {m for m in modelos if m}


# ─── CLIENTE OLLAMA ─────────────────────────────────────────────────────────
class OllamaClient:
    """Cliente del servidor Ollama.

    Usa el paquete oficial `ollama` si esta instalado; si no, cae a la
    API REST (`/api/tags`, `/api/chat`) vIa requests.
    """

    def __init__(self, host: str, timeout: int = 180, keep_alive: str = "5m"):
        self.host = host.rstrip("/")
        self.timeout = timeout
        self.keep_alive = keep_alive
        self._pkg = None
        if ollama is not None:
            try:
                self._pkg = ollama.Client(host=self.host, timeout=timeout)
            except Exception:  # noqa: BLE001
                self._pkg = None

    @classmethod
    def from_config(cls, config: dict) -> "OllamaClient":
        """Construye el cliente desde config + entorno.

        El endpoint no esta quemado en el codigo. Precedencia:
        LLM_BASE_URL > OLLAMA_HOST > config.llm.base_url. Si ninguno esta
        definido, aborta: adivinar un endpoint hace fallar el batch entero
        con un error de red confuso en vez de uno de configuracion.
        """
        o = config.get("llm", config.get("ollama", {}))
        host = (os.environ.get("LLM_BASE_URL")
                or os.environ.get("OLLAMA_HOST")
                or o.get("base_url") or o.get("host") or "").strip()
        if not host:
            raise ValueError(
                "Sin endpoint del backend LLM. Define LLM_BASE_URL, OLLAMA_HOST "
                "o llm.base_url en config.json.")
        return cls(host, int(o.get("request_timeout", 180)), o.get("keep_alive", "5m"))

    def list_models(self) -> set:
        """Nombres de modelos disponibles en el servidor."""
        if self._pkg is not None:
            data = self._pkg.list()
            models = data.get("models", []) if isinstance(data, dict) \
                else getattr(data, "models", [])
            names = set()
            for m in models:
                name = (m.get("model") or m.get("name")) if isinstance(m, dict) \
                    else (getattr(m, "model", None) or getattr(m, "name", None))
                if name:
                    names.add(name)
            return names
        r = requests.get(f"{self.host}/api/tags", timeout=self.timeout)
        r.raise_for_status()
        return {m["name"] for m in r.json().get("models", []) if m.get("name")}

    def chat(self, model: str, system: str, prompt: str, *,
             temperature: float = 0.3, num_predict: int = 512,
             json_mode: bool = False) -> str:
        """Una ronda de chat de un solo turno. Devuelve el texto de la respuesta."""
        messages = [{"role": "system", "content": system},
                    {"role": "user", "content": prompt}]
        options = {"temperature": float(temperature), "num_predict": int(num_predict)}
        if self._pkg is not None:
            kw = dict(model=model, messages=messages, options=options,
                      keep_alive=self.keep_alive)
            if json_mode:
                kw["format"] = "json"
            resp = self._pkg.chat(**kw)
            msg = resp.get("message", {}) if isinstance(resp, dict) \
                else getattr(resp, "message", {})
            content = msg.get("content") if isinstance(msg, dict) \
                else getattr(msg, "content", "")
            return content or ""
        payload = {"model": model, "messages": messages, "stream": False,
                   "options": options, "keep_alive": self.keep_alive}
        if json_mode:
            payload["format"] = "json"
        r = requests.post(f"{self.host}/api/chat", json=payload, timeout=self.timeout)
        r.raise_for_status()
        return r.json().get("message", {}).get("content", "") or ""


# ─── PREFLIGHT: VERIFICACION DE MODELOS ─────────────────────────────────────
def _model_present(name: str, available) -> bool:
    """True si `name` (o una variante con sufijo) esta entre los disponibles."""
    return any(a == name or a.startswith(name) for a in available)


def verify_models(config: dict, client: "OllamaClient | None" = None):
    """Verifica que Ollama responda y tenga los modelos requeridos.

    Devuelve (ok: bool, report: dict). `report` siempre incluye host,
    ollama_ok, requeridos, disponibles y faltantes.
    """
    client = client or OllamaClient.from_config(config)
    requeridos = sorted(required_models(config))
    report = {"host": client.host, "ollama_ok": False,
              "requeridos": requeridos, "disponibles": [],
              "faltantes": list(requeridos)}
    try:
        disponibles = client.list_models()
    except Exception as e:  # noqa: BLE001
        report["error"] = str(e)
        return False, report
    report["ollama_ok"] = True
    report["disponibles"] = sorted(disponibles)
    faltantes = [m for m in requeridos if not _model_present(m, disponibles)]
    report["faltantes"] = faltantes
    return (not faltantes), report


def print_preflight(report: dict, agentes: dict) -> None:
    step("Preflight - verificacion de modelos Ollama")
    info(f"Host Ollama: {report['host']}")
    if not report["ollama_ok"]:
        error(f"Ollama no responde: {report.get('error', 'sin detalle')}")
        warn("Arranca el servidor con: ollama serve")
        return
    disponibles = set(report["disponibles"])
    for nombre, a in agentes.items():
        modelo = a.get("model", "")
        marca = f"{BG}disponible{NC}" if _model_present(modelo, disponibles) \
            else f"{BR}FALTA{NC}"
        info(f"  {nombre:<12} -> {modelo:<16} [{marca}]")
    if report["faltantes"]:
        error("Modelos faltantes: " + ", ".join(report["faltantes"]))
        for m in report["faltantes"]:
            print(f"      ollama pull {m}", file=sys.stderr)
    else:
        log("Todos los modelos requeridos estan disponibles.")


# ─── ENTRADA: LISTA DE DOMINIOS ─────────────────────────────────────────────
def parse_target_list(texto: str) -> list:
    """Lee una lista de dominios en texto plano: uno por linea, # para comentar.

    Devuelve la estructura interna que consume el pipeline. El nombre visible
    del target es el dominio mismo; el enriquecimiento por LLM lo refina.
    """
    items = []
    vistos = set()
    for raw in texto.splitlines():
        linea = raw.split("#", 1)[0].strip()
        if not linea:
            continue
        dominio = extract_domain(linea)
        if not dominio or dominio in vistos:
            continue
        vistos.add(dominio)
        items.append({"name": dominio, "website": dominio})
    return items


# ─── UTILIDADES DE DOMINIO / EMAIL ──────────────────────────────────────────
EMAIL_RE = re.compile(r"[A-Za-z0-9._%+\-]+@[A-Za-z0-9.\-]+\.[A-Za-z]{2,}")
_BAD_EMAIL_EXT = ("png", "jpg", "jpeg", "gif", "webp", "svg", "css", "js",
                  "bmp", "ico", "woff", "woff2", "ttf")


def _ensure_url(url: str) -> str:
    url = (url or "").strip()
    if url and not re.match(r"^https?://", url, re.I):
        url = "http://" + url
    return url


def extract_domain(url: str) -> str:
    """Dominio raIz a partir de una URL o dominio suelto ('' si no es valido)."""
    if not url:
        return ""
    host = urlparse(_ensure_url(url)).netloc.lower()
    host = host.split("@")[-1].split(":")[0]
    if host.startswith("www."):
        host = host[4:]
    return host if "." in host and " " not in host else ""


def _clean_domain(value: str) -> str:
    return extract_domain(value)


def extract_emails(text: str) -> list:
    """Emails plausibles dentro de un texto, sin duplicados ni rutas de assets."""
    out = []
    for e in EMAIL_RE.findall(text or ""):
        el = e.lower()
        if el.rsplit(".", 1)[-1] in _BAD_EMAIL_EXT:
            continue
        if el not in out:
            out.append(el)
    return out


def _is_email(value: str) -> bool:
    return bool(EMAIL_RE.fullmatch((value or "").strip()))


def _reconcile_email(desc_email: str, encontrados: list, texto: str) -> str:
    """Antialucinacion: solo acepta el email del LLM si aparece en el sitio."""
    desc_email = (desc_email or "").strip().lower()
    encontrados_lower = [e.lower() for e in encontrados]
    if desc_email and _is_email(desc_email):
        if desc_email in encontrados_lower or desc_email in (texto or "").lower():
            return desc_email
    return encontrados_lower[0] if encontrados_lower else ""


# ─── EMAILS DEL SITIO: mailto: + regex sobre el HTML CRUDO ──────────────────
# Crawl4AI pierde los enlaces <a href="mailto:..."> al convertir el HTML a
# markdown. Por eso los emails se sacan del HTML crudo (mailto: con
# BeautifulSoup + regex) y se complementan con el texto. Luego se descartan los
# emails de plataformas/herramientas y se priorizan los del dominio del target.
STRICT_EMAIL_RE = re.compile(
    r"^[A-Za-z0-9._%+\-]+@[A-Za-z0-9.\-]+\.[A-Za-z]{2,}$")

# Dominios de plataformas, CDNs y librerias: nunca son el contacto del target.
_JUNK_EMAIL_DOMAINS = {
    "example.com", "example.org", "example.net", "domain.com", "email.com",
    "yourdomain.com", "tudominio.com", "sentry.io", "wixpress.com",
    "sentry.wixpress.com", "sentry-next.wixpress.com", "wix.com",
    "wordpress.com", "wordpress.org", "w3.org", "schema.org",
    "googleapis.com", "gstatic.com", "google.com", "jquery.com",
    "cloudflare.com", "elementor.com", "automattic.com",
}
# Partes locales de buzones automaticos o de herramientas (sin valor comercial).
_JUNK_EMAIL_LOCALS = {
    "noreply", "no-reply", "donotreply", "do-not-reply", "mailer-daemon",
    "postmaster", "hostmaster", "abuse", "jquery", "wordpress", "sentry",
    "you", "youremail", "your-email", "name", "nombre", "ejemplo", "example",
}
# Buzones genericos del propio dominio: validos, pero peor candidato que un
# email con nombre de persona — bajan en la priorizacion, no se descartan.
_GENERIC_EMAIL_LOCALS = {
    "info", "contacto", "contact", "ventas", "venta", "hola", "hello",
    "admin", "administracion", "soporte", "support", "mail", "correo",
    "gerencia", "recepcion", "atencion", "comercial", "consultas",
}


def _email_domain(email: str) -> str:
    return email.rsplit("@", 1)[-1] if "@" in email else ""


def _email_local(email: str) -> str:
    return email.split("@", 1)[0] if "@" in email else email


def _is_junk_email(email: str) -> bool:
    """True si el email es de una plataforma/herramienta, no un contacto real."""
    dom = _email_domain(email)
    if dom in _JUNK_EMAIL_DOMAINS:
        return True
    if dom.rsplit(".", 1)[-1] in _BAD_EMAIL_EXT:    # logo@2x.png y similares
        return True
    if _email_local(email) in _JUNK_EMAIL_LOCALS:
        return True
    return False


def _is_domain_email(email: str, dominio: str) -> bool:
    """True si el email pertenece al dominio del target (o un subdominio)."""
    dom = _email_domain(email)
    return bool(dominio) and (dom == dominio or dom.endswith("." + dominio))


def _mailto_emails(html: str) -> list:
    """Emails de los enlaces <a href="mailto:...">, que se pierden en el markdown."""
    if not html:
        return []
    try:
        from bs4 import BeautifulSoup
    except Exception:  # noqa: BLE001
        # Sin BeautifulSoup: rescatar los mailto: con regex sobre el HTML.
        return [m.lower() for m in re.findall(
            r'mailto:([^"\'?>\s]+)', html, flags=re.I)]
    out = []
    for a in BeautifulSoup(html, "html.parser").find_all("a", href=True):
        href = a["href"].strip()
        if not href.lower().startswith("mailto:"):
            continue
        cuerpo = href[7:].split("?", 1)[0]          # quita ?subject=...&body=...
        for addr in cuerpo.split(","):              # mailto: admite varios
            addr = unquote(addr).strip().lower()
            if addr:
                out.append(addr)
    return out


def _cf_decoded_emails(html: str) -> list:
    """Decodifica los emails ofuscados por Cloudflare (__cf_email__/data-cfemail).

    Cloudflare oculta el email tras un <a> con el texto cifrado en hex: el
    primer byte es la clave XOR y el resto, los caracteres del email. Tambien
    aparece como fragmento en href="/cdn-cgi/l/email-protection#<hex>". Sin
    decodificarlo, sitios como ejemplo.cl no exponen ningun email.
    """
    if not html:
        return []
    hexes = re.findall(r'data-cfemail="([0-9a-fA-F]{4,})"', html)
    hexes += re.findall(r'/cdn-cgi/l/email-protection#([0-9a-fA-F]{4,})', html)
    out = []
    for hx in hexes:
        if len(hx) % 2:                                # debe ser pares de hex
            continue
        try:
            key = int(hx[:2], 16)
            dec = "".join(chr(int(hx[i:i + 2], 16) ^ key)
                          for i in range(2, len(hx), 2))
        except ValueError:
            continue
        if "@" in dec:
            out.append(dec.lower())
    return out


def extract_site_emails(html: str, texto: str, prospect_domain: str) -> list:
    """Lista priorizada de emails publicados en el sitio.

    Une los mailto: del HTML (que Crawl4AI pierde al pasar a markdown), los
    emails ofuscados por Cloudflare, el regex sobre el HTML crudo y el regex
    sobre el texto. Descarta emails de plataformas/herramientas y ordena:
    primero los del dominio del target, luego el resto (incluye
    gmail/personales).
    """
    dominio = (prospect_domain or "").strip().lower()
    html_dec = _html_entities.unescape(html or "")     # &#64; -> @
    crudos = _mailto_emails(html)
    crudos += _cf_decoded_emails(html)
    crudos += [m.lower() for m in EMAIL_RE.findall(html_dec)]
    crudos += extract_emails(texto)                    # ya viene saneado

    validos, vistos = [], set()
    for e in crudos:
        e = e.strip().strip(".").lower()
        if not e or e in vistos or not STRICT_EMAIL_RE.match(e):
            continue
        vistos.add(e)
        if not _is_junk_email(e):
            validos.append(e)

    def _orden(e):
        propio = 0 if _is_domain_email(e, dominio) else 1
        generico = 1 if _email_local(e) in _GENERIC_EMAIL_LOCALS else 0
        return (propio, generico)

    return sorted(validos, key=_orden)        # estable: respeta orden de hallazgo


# ─── SCRAPING DEL SITIO DEL TARGET (Crawl4AI + fallback) ────────────────────
def _crawl_text(result) -> str:
    """Extrae texto de un CrawlResult de forma tolerante a versiones de Crawl4AI."""
    md = getattr(result, "markdown", None)
    if md is not None:
        raw = getattr(md, "raw_markdown", None) or getattr(md, "fit_markdown", None)
        if raw:
            return raw
        if isinstance(md, str):
            return md
    html = getattr(result, "cleaned_html", None) or getattr(result, "html", None)
    if html:
        try:
            from bs4 import BeautifulSoup
            return BeautifulSoup(html, "html.parser").get_text(" ")
        except Exception:  # noqa: BLE001
            return re.sub(r"<[^>]+>", " ", html)
    return ""


# ─── SUBPAGINAS: enlaces a /contacto, /equipo, /nosotros... ──────────────────
# El email del decisor suele vivir en una subpagina, no en la home. Estos slugs
# (en orden de prioridad) son las paginas tipicas donde aparece.
_SUBPAGE_SLUGS = [
    "contacto", "contact", "equipo", "team", "nosotros", "about",
    "quienes-somos", "quiénes-somos", "staff", "directorio",
]
# Extensiones de assets/descargas: nunca son una subpagina de contacto.
_SUBPAGE_BAD_EXT = (
    ".jpg", ".jpeg", ".png", ".gif", ".webp", ".svg", ".css", ".js", ".pdf",
    ".zip", ".rar", ".doc", ".docx", ".xls", ".xlsx", ".ppt", ".pptx", ".mp4",
    ".mp3", ".ico", ".woff", ".woff2", ".ttf", ".rss", ".xml", ".json",
)


def get_subpage_urls(texto: str, base_url: str) -> list:
    """URLs de subpaginas candidatas (contacto/equipo/nosotros...) desde la home.

    Funcion PURA (sin I/O), testeable de forma aislada: parsea los enlaces de
    `texto` (HTML o markdown), los resuelve contra `base_url` y devuelve hasta
    3 URLs absolutas del mismo dominio cuyo path coincide con un slug
    prioritario, ordenadas por prioridad del slug. Si no hay coincidencias
    exactas devuelve [] (no se scrapea a ciegas).
    """
    if not texto or not base_url:
        return []
    base_dom = extract_domain(base_url)
    if not base_dom:
        return []
    base_abs = _ensure_url(base_url)
    home_path = urlparse(base_abs).path.strip("/").lower()

    # href="..." (HTML) + ](...)  (markdown de Crawl4AI).
    hrefs = re.findall(r'href\s*=\s*["\']([^"\']+)["\']', texto, flags=re.I)
    hrefs += [m.split()[0] for m in re.findall(r'\]\(([^)\s]+)', texto) if m.strip()]

    por_slug = {}                              # indice_slug -> primera URL hallada
    vistos = set()
    for href in hrefs:
        href = href.strip()
        if not href or href.startswith("#") or href.lower().startswith(
                ("mailto:", "tel:", "javascript:", "data:")):
            continue
        parsed = urlparse(urljoin(base_abs, href))
        if parsed.scheme not in ("http", "https"):
            continue
        dom = parsed.netloc.lower().split("@")[-1].split(":")[0]
        if dom.startswith("www."):
            dom = dom[4:]
        if dom != base_dom and not dom.endswith("." + base_dom):
            continue                           # otro dominio
        path = parsed.path.strip("/").lower()
        if not path or path == home_path:      # raiz o la propia home
            continue
        if path.endswith(_SUBPAGE_BAD_EXT):    # asset, no pagina
            continue
        clean = urljoin(base_abs, href).split("#")[0]
        if clean in vistos:
            continue
        path_norm = "/" + path + "/"
        for i, slug in enumerate(_SUBPAGE_SLUGS):
            if f"/{slug}/" in path_norm or f"/{slug}." in path_norm:
                if i not in por_slug:
                    por_slug[i] = clean
                    vistos.add(clean)
                break
    return [por_slug[i] for i in sorted(por_slug)][:3]


class SiteScraper:
    """Scraper del sitio del target. Usa Crawl4AI; cae a requests + BeautifulSoup."""

    def __init__(self, cfg: dict):
        self.cfg = cfg or {}
        self.max_chars = int(self.cfg.get("max_chars", 6000))
        self.wct = int(self.cfg.get("word_count_threshold", 15))
        self.timeout_ms = int(self.cfg.get("page_timeout_ms", 30000))
        self.ua = self.cfg.get("user_agent", "Crowsnest-OpenClaw/1.0")
        self.subpages_enabled = bool(self.cfg.get("scrape_subpages", True))
        self._crawler = None

    async def __aenter__(self):
        if self.cfg.get("enabled", True):
            try:
                from crawl4ai import AsyncWebCrawler
                try:
                    self._crawler = AsyncWebCrawler(verbose=False)
                except TypeError:
                    self._crawler = AsyncWebCrawler()
                await self._crawler.__aenter__()
                info("Crawl4AI activo para el scraping de sitios.")
            except Exception as e:  # noqa: BLE001
                warn(f"Crawl4AI no disponible ({e}); usando fallback requests.")
                self._crawler = None
        return self

    async def __aexit__(self, *exc):
        if self._crawler is not None:
            try:
                await self._crawler.__aexit__(*exc)
            except Exception:  # noqa: BLE001
                pass

    async def fetch(self, url: str):
        """Home + subpaginas. Devuelve (texto, metodo, html).

        Scrapea la home y, si `scrape_subpages` esta activo, hasta 3 subpaginas
        prioritarias (contacto/equipo/nosotros...). Combina texto Y HTML crudo
        de todas para que extract_site_emails encuentre tambien los emails
        (mailto:/Cloudflare) que viven en esas subpaginas, no solo en la home.
        El texto combinado se acota a max_chars*2 para no saturar al LLM.
        """
        texto_home, metodo, html_home = await self.fetch_one(url)
        if not texto_home or not self.subpages_enabled:
            return texto_home, metodo, html_home

        subpage_urls = get_subpage_urls(html_home or texto_home, url)
        textos_extra, htmls_extra = [], []
        for sub_url in subpage_urls:
            texto_sub, _metodo_sub, html_sub = await self.fetch_one(sub_url)
            if texto_sub:
                textos_extra.append(f"\n\n--- {sub_url} ---\n{texto_sub}")
            if html_sub:
                htmls_extra.append(html_sub)
            if texto_sub or html_sub:
                info(f"  + subpagina scrapeada: {sub_url}")

        if not textos_extra and not htmls_extra:
            return texto_home, metodo, html_home
        texto_combinado = (texto_home + "".join(textos_extra))[:self.max_chars * 2]
        return texto_combinado, metodo, html_home + "".join(htmls_extra)

    async def fetch_one(self, url: str):
        """Scrapea UNA pagina. Devuelve (texto, metodo, html) con metodo en
        {'crawl4ai','requests','none'}.

        `html` es el HTML crudo de la pagina (sin truncar): se conserva aparte
        del texto porque los enlaces mailto: se pierden al convertir a markdown
        (ver extract_site_emails).
        """
        url = _ensure_url(url)
        if not url:
            return "", "none", ""
        if self._crawler is not None:
            try:
                try:
                    result = await self._crawler.arun(
                        url=url, word_count_threshold=self.wct,
                        page_timeout=self.timeout_ms)
                except TypeError:
                    result = await self._crawler.arun(url=url)
                texto = _crawl_text(result).strip()
                if len(texto) > 40:
                    html = (getattr(result, "html", None)
                            or getattr(result, "cleaned_html", None) or "")
                    return texto[:self.max_chars], "crawl4ai", html
            except Exception as e:  # noqa: BLE001
                warn(f"Crawl4AI fallo en {url}: {e}")
        return self._fetch_requests(url)

    def _http_get(self, url: str):
        """GET con cabeceras de scraper. Si el certificado TLS no valida
        (cert solo para www, cadenas incompletas, etc.) reintenta una
        vez sin verificar: el objetivo es leer el sitio publico, no autenticarlo.
        """
        hdrs = {"User-Agent": self.ua, "Accept-Language": "es-CL,es;q=0.9"}
        try:
            return requests.get(url, timeout=20, allow_redirects=True, headers=hdrs)
        except requests.exceptions.SSLError:
            warn(f"Certificado TLS invalido en {url}; reintento sin verificar.")
            try:
                from urllib3.exceptions import InsecureRequestWarning
                requests.packages.urllib3.disable_warnings(InsecureRequestWarning)
            except Exception:  # noqa: BLE001
                pass
            return requests.get(url, timeout=20, allow_redirects=True,
                                headers=hdrs, verify=False)

    def _fetch_requests(self, url: str):
        try:
            r = self._http_get(url)
            if r.status_code >= 400 or not r.text:
                return "", "none", ""
            html = r.text
            try:
                from bs4 import BeautifulSoup
                soup = BeautifulSoup(html, "html.parser")
                for tag in soup(["script", "style", "noscript"]):
                    tag.decompose()
                texto = " ".join(soup.get_text(" ").split())
            except Exception:  # noqa: BLE001
                texto = " ".join(re.sub(r"<[^>]+>", " ", html).split())
            # Aun sin texto util se devuelve el HTML: puede traer mailto: validos.
            if texto:
                return texto[:self.max_chars], "requests", html
            return "", "none", html
        except Exception as e:  # noqa: BLE001
            warn(f"Fallback requests fallo en {url}: {e}")
            return "", "none", ""


# ─── PREFILTRO HTTP: DESCARTE DE DOMINIOS MUERTOS ───────────────────────────
# Antes de gastar scraping + 3 agentes Ollama en un target, una sola GET
# rapida descarta dominios caidos, parqueados o abandonados. Es sync (requests
# lo es); enrich_one la corre en un executor para no bloquear el event loop.
def check_domain_alive(url: str, cfg: dict) -> tuple[bool, str, str, bool]:
    """Prefiltro HTTP de un dominio.

    Devuelve (pasa, skip_reason, dominio_alternativo, necesita_js).

    - `pasa` es False si el dominio esta muerto/abandonado/insuficiente.
    - `skip_reason` queda en '' cuando el dominio pasa.
    - `dominio_alternativo` es '' salvo que la peticion (con allow_redirects) haya
      aterrizado en otro dominio: en ese caso es el dominio destino (el target pudo
      migrar) y solo se calcula si cfg["detectar_migracion"] esta activo.
    - `necesita_js` es True cuando el servidor respondio 2xx pero el contenido
      crudo es menor que cfg["min_content_chars"]. Indica al caller que el sitio
      esta vivo pero requiere renderizado JS (Crawl4AI) en vez de descartar.
      Todos los demas casos devuelven necesita_js=False.

    `cfg` es config["prefiltro"].
    """
    if not (url or "").strip():
        return False, "sin_website", "", False
    dom_original = extract_domain(url)
    try:
        r = requests.get(_ensure_url(url), timeout=cfg.get("timeout_seg", 8),
                         allow_redirects=True)
    except requests.exceptions.Timeout:
        return False, "timeout", "", False
    except requests.exceptions.ConnectionError:
        return False, "conexion_fallida", "", False
    except Exception:  # noqa: BLE001
        return False, "error_http", "", False

    # Dominio destino tras seguir redirecciones: si difiere del original (y no es
    # un subdominio suyo ni viceversa) puede ser el dominio nuevo del target.
    dom_alt = ""
    if cfg.get("detectar_migracion", False):
        dom_final = extract_domain(getattr(r, "url", "") or "")
        if (dom_final and dom_original and dom_final != dom_original
                and not dom_final.endswith("." + dom_original)
                and not dom_original.endswith("." + dom_final)):
            dom_alt = dom_final

    # Algunos servidores responden 403/406/429 a un scraper (rechazan el
    # user-agent o estan rate-limiting) pero el sitio esta vivo. Esos codigos
    # (config["prefiltro"]["ignorar_status_codes"]) no descartan: el servidor
    # respondio, asi que seguimos evaluando contenido/antiguedad.
    ignorar_status = cfg.get("ignorar_status_codes", [])
    if r.status_code >= 400 and r.status_code not in ignorar_status:
        return False, f"http_{r.status_code}", dom_alt, False

    text = r.text or ""
    if len(text.strip()) < cfg.get("min_content_chars", 300):
        # El servidor respondió 2xx pero el HTML crudo es esqueleto — típico de
        # sitios que cargan contenido vía JavaScript. No descartar: dejar
        # que Crawl4AI renderice y reintente.
        return False, "contenido_insuficiente", dom_alt, True

    low = text.lower()
    for senal in cfg.get("señales_muerto", []):
        if senal.lower() in low:
            return False, f"dominio_abandonado:{senal}", dom_alt, False

    last_mod = r.headers.get("Last-Modified")
    max_anios = cfg.get("max_antiguedad_años")
    if last_mod and max_anios:
        try:                                   # parseo best-effort: si falla, no descarta
            dt = parsedate_to_datetime(last_mod)
            if dt is not None:
                anios = (datetime.now(dt.tzinfo) - dt).days / 365.25
                if anios > max_anios:
                    return False, f"desactualizado:{int(anios)}años", dom_alt, False
        except (TypeError, ValueError):
            pass

    return True, "", "", False


# ─── PARSEO DE SALIDA LLM ───────────────────────────────────────────────────
def _extract_json(text: str) -> dict:
    """Extrae el primer objeto JSON de la respuesta del modelo."""
    text = (text or "").strip()
    if text.startswith("```"):
        text = text.strip("`")
        text = re.sub(r"^json\s*", "", text, flags=re.I).strip()
    s, e = text.find("{"), text.rfind("}")
    if s != -1 and e != -1 and e > s:
        try:
            return json.loads(text[s:e + 1])
        except json.JSONDecodeError:
            pass
    try:
        return json.loads(text)
    except json.JSONDecodeError:
        return {}


def _clean_message(text: str) -> str:
    """Limpia texto del LLM: fences, 'Asunto:', comillas envolventes."""
    text = (text or "").strip()
    if text.startswith("```"):
        text = text.strip("`").strip()
    lineas = text.splitlines()
    if lineas and lineas[0].strip().lower().startswith(("asunto:", "subject:")):
        lineas = lineas[1:]
    text = "\n".join(lineas).strip()
    if len(text) > 1 and text[0] in "\"'“" and text[-1] in "\"'”":
        text = text[1:-1].strip()
    return text


# ─── HALLAZGOS REALES DESDE EL FLASH JSON ───────────────────────────────────
# Los informes Flash viven en reportes/<slug>_<YYYYMMDD>_<HHMMSS>/ y guardan el
# JSON flash_<slug>.json, donde <slug> es el dominio con los puntos convertidos
# en guion bajo (ejemplo.cl -> ejemplo_cl).
def _resolve_reportes_dir() -> Path:
    """Carpeta de informes Flash, valida tanto en el host como en el contenedor.

    En el host es <repo>/reportes/. En Docker, `crowsnest.sh batch` monta esa misma
    carpeta en /home/work/results (ver los -v de crowsnest.sh), de modo que aqui se
    ve como un hermano `results` de openclaw/, no `reportes`. Probamos ambos
    nombres y devolvemos el primero que exista; CROWSNEST_REPORTS_DIR manda si
    esta definido.
    """
    env = os.environ.get("CROWSNEST_REPORTS_DIR")
    if env:
        return Path(env)
    for nombre in ("reportes", "results"):
        cand = MODULE_DIR.parent / nombre
        if cand.is_dir():
            return cand
    return MODULE_DIR.parent / "reportes"


REPORTES_DIR = _resolve_reportes_dir()

_DIR_SUFFIX_RE = re.compile(r"_\d{8}_\d{6}$")


def _domain_slug(domain: str) -> str:
    """Dominio -> slug de carpeta/archivo (los puntos pasan a guion bajo)."""
    return (domain or "").strip().lower().replace(".", "_")


def find_flash_json(domain: str, reportes_dir: Path = REPORTES_DIR):
    """Ruta al Flash JSON mas reciente de `domain`, o None si no existe.

    Recorre reportes/<slug>_<YYYYMMDD>_<HHMMSS>/ y devuelve el flash_<slug>.json
    de la carpeta con el timestamp mas alto.
    """
    slug = _domain_slug(domain)
    if not slug or not reportes_dir.is_dir():
        return None
    candidatos = []
    for d in reportes_dir.iterdir():
        if not d.is_dir() or not d.name.startswith(slug + "_"):
            continue
        if not _DIR_SUFFIX_RE.fullmatch(d.name[len(slug):]):
            continue
        flash = d / f"flash_{slug}.json"
        if not flash.is_file():
            otros = sorted(d.glob("flash_*.json"))
            flash = otros[0] if otros else None
        if flash is not None:
            candidatos.append((d.name, flash))
    if not candidatos:
        return None
    candidatos.sort(key=lambda c: c[0], reverse=True)
    return candidatos[0][1]


def _truncar(texto, limite: int = 120) -> str:
    """Recorta `texto` a <= `limite` chars sin partir palabras.

    Prefiere cortar al final de una oracion dentro del limite; si no hay,
    corta en un limite de palabra y agrega elipsis. Asi el LLM recibe
    un fragmento que se lee completo y no intenta inventar el final.
    """
    texto = str(texto or "").strip()
    if len(texto) <= limite:
        return texto
    frag = texto[:limite]
    fin_oracion = max(frag.rfind(". "), frag.rfind("; "))
    if fin_oracion >= 60:
        return frag[:fin_oracion + 1]
    corte = frag.rsplit(" ", 1)[0].rstrip(" ,.;:—-")
    return f"{corte}…"


def _finding_signature(f: dict) -> str:
    """Firma de un hallazgo ignorando el host entre parentesis (mx1/mx2 -> igual)."""
    nombre = re.sub(r"\s*\([^)]*\)", "", str(f.get("name", ""))).strip().lower()
    return f"{nombre}|{f.get('severity', '')}"


def _dedup_findings(findings: list) -> list:
    """Colapsa hallazgos casi identicos (mismo nombre base + severidad)."""
    vistos, salida = set(), []
    for f in findings or []:
        sig = _finding_signature(f)
        if sig in vistos:
            continue
        vistos.add(sig)
        salida.append(f)
    return salida


def _top_hallazgos(findings: list, n: int = 3) -> list:
    """Los `n` hallazgos mas severos y distintos (severity_priority ascendente)."""
    unicos = _dedup_findings(findings)
    ordenados = sorted(unicos, key=lambda f: f.get("severity_priority", 99))
    salida = []
    for f in ordenados[:n]:
        salida.append({
            "nombre": str(f.get("name", "")).strip(),
            "severity_label": str(f.get("severity_label", "")).strip(),
            "descripcion": _truncar(f.get("description"), 120),
        })
    return salida


def extract_flash_data(flash_path) -> dict:
    """Lee un Flash JSON y extrae risk score, top-3 hallazgos y recomendacion."""
    data = json.loads(Path(flash_path).read_text(encoding="utf-8"))
    es = data.get("executive_summary", {}) or {}
    findings = data.get("findings", []) or []
    return {
        "risk_score": es.get("risk_score"),
        "risk_level": str(es.get("risk_level") or "").strip(),
        "total_hallazgos": es.get("total_findings") or len(findings),
        "key_recommendation": str(es.get("key_recommendation") or "")[:200].strip(),
        "hallazgos": _top_hallazgos(findings, 3),
        "es_fallback": False,
    }


def fallback_flash_data() -> dict:
    """Hallazgos genericos de DMARC/SPF cuando el dominio no tiene Flash JSON."""
    return {
        "risk_score": None,
        "risk_level": "no evaluado",
        "total_hallazgos": 2,
        "key_recommendation": (
            "Implementar DMARC con politica p=reject y endurecer el registro SPF "
            "a -all para impedir la suplantacion del dominio en el correo."),
        "hallazgos": [
            {"nombre": "DMARC sin politica de rechazo (p=none o ausente)",
             "severity_label": "Alta",
             "descripcion": ("El dominio no rechaza correos fraudulentos: un "
                             "tercero puede suplantar la identidad corporativa "
                             "en el correo.")},
            {"nombre": "SPF permisivo o ausente",
             "severity_label": "Media",
             "descripcion": ("El registro SPF no restringe que servidores estan "
                             "autorizados a enviar correo en nombre del dominio.")},
        ],
        "es_fallback": True,
    }


def load_hallazgos(domain: str):
    """Devuelve (flash_data, ruta_usada). Cae al fallback DMARC/SPF si no hay JSON."""
    flash_path = find_flash_json(domain) if domain else None
    if flash_path is not None:
        try:
            return extract_flash_data(flash_path), str(flash_path)
        except (json.JSONDecodeError, OSError, ValueError) as e:  # noqa: BLE001
            warn(f"No se pudo leer {flash_path}: {e}; uso hallazgos genericos.")
    return fallback_flash_data(), ""


# ─── AGENTES ────────────────────────────────────────────────────────────────
def run_orquestador(client: OllamaClient, cfg: dict, place: dict, *,
                    dominio_original: str = "", dominio_alternativo: str = "") -> dict:
    # Si el target migro de dominio, se lo decimos al orquestador para que lo
    # incorpore al angulo (ver instruccion de migracion en su system_prompt).
    migracion = ""
    if dominio_original and dominio_alternativo:
        migracion = (f"- dominio_original: {dominio_original}\n"
                     f"- dominio_alternativo: {dominio_alternativo}\n")
    user = (
        "Datos del target:\n"
        f"- Nombre: {place['name']}\n"
        f"- Sitio web: {place['website'] or '(no informado)'}\n"
        f"{migracion}\n"
        "Evalua el target y define el angulo de analisis."
    )
    raw = client.chat(cfg["model"], cfg["system_prompt"], user,
                      temperature=cfg.get("temperature", 0.15),
                      num_predict=cfg.get("num_predict", 400), json_mode=True)
    d = _extract_json(raw)
    return {
        "viable": bool(d.get("viable", True)),
        "cargo_objetivo": str(d.get("cargo_objetivo") or d.get("cargo") or "").strip(),
        "prioridad": str(d.get("prioridad", "media")).strip().lower(),
        "angulo": str(d.get("angulo", "")).strip(),
    }


def run_descubridor(client: OllamaClient, cfg: dict, place: dict, plan: dict,
                    sitio_texto: str, emails_encontrados: list) -> dict:
    bloque = sitio_texto.strip()[:5000] if sitio_texto.strip() \
        else "(no se pudo obtener contenido del sitio)"
    user = (
        "NEGOCIO\n"
        f"- Nombre: {place['name']}\n"
        f"- Sitio web: {place['website'] or '(no informado)'}\n"
        f"- Cargo sugerido (orquestador): {plan.get('cargo_objetivo', '')}\n\n"
        "EMAILS ENCONTRADOS EN EL SITIO (usa SOLO uno de estos, no inventes "
        "ninguno; elige el mas apropiado para el decisor segun su cargo y el "
        "contexto del negocio):\n"
        f"{', '.join(emails_encontrados) or '(ninguno)'}\n\n"
        f"CONTENIDO DEL SITIO WEB:\n{bloque}\n\n"
        "Extrae la informacion de contacto en JSON."
    )
    raw = client.chat(cfg["model"], cfg["system_prompt"], user,
                      temperature=cfg.get("temperature", 0.1),
                      num_predict=cfg.get("num_predict", 700), json_mode=True)
    d = _extract_json(raw)
    senales = d.get("senales") or d.get("señales") or []
    if isinstance(senales, str):
        senales = [senales]
    return {
        "dominio": str(d.get("dominio", "")).strip().lower(),
        "email": str(d.get("email", "")).strip().lower(),
        "cargo_objetivo": str(d.get("cargo_objetivo") or d.get("cargo") or "").strip(),
        "nombre_contacto": str(d.get("nombre_contacto", "")).strip(),
        "resumen_empresa": str(d.get("resumen_empresa", "")).strip(),
        "senales": [str(s).strip() for s in senales if str(s).strip()][:6],
    }


# ─── SUMMARIZER — RESUMEN EJECUTIVO DEL INFORME ─────────────────────────────
# Toma los hallazgos tecnicos del scan y produce el resumen ejecutivo en
# ingles. Su salida es OPCIONAL: el motor de informes la consume si esta y la
# omite si no, de modo que el informe se genera igual sin backend LLM.

# Resultado de la etapa del summarizer. NO son estados del target: el ciclo de
# vida del target vive en lib/states.py y no guarda relacion con esto. Se nombran
# aparte para que "skipped" no se confunda con lib.states.SKIPPED.
SUMMARY_OK       = "ok"
SUMMARY_RETRY_OK = "retry_ok"
SUMMARY_FAILED   = "failed"
SUMMARY_SKIPPED  = "not_requested"

def _finding_line(n: int, hallazgos: list) -> str:
    if n - 1 < len(hallazgos):
        h = hallazgos[n - 1]
        return f"- [{h['severity_label']}] {h['nombre']}: {h['descripcion']}"
    return ""


def build_summarizer_prompt(dominio: str, scan: dict) -> str:
    """Arma el prompt del summarizer con los hallazgos reales del scan."""
    hallazgos = scan.get("hallazgos", [])
    lineas = [l for l in (_finding_line(i, hallazgos) for i in range(1, 6)) if l]
    return (
        "TARGET\n"
        f"- Domain: {dominio}\n"
        f"- Total findings: {scan.get('total_hallazgos', len(hallazgos))}\n\n"
        "FINDINGS\n"
        + ("\n".join(lineas) if lineas else "(no significant findings)")
        + "\n\nWrite the executive summary."
    )


def run_summarizer(client: OllamaClient, cfg: dict, dominio: str,
                   scan: dict) -> str:
    """Una pasada del summarizer; devuelve el resumen en ingles ya limpio."""
    prompt = build_summarizer_prompt(dominio, scan)
    raw = client.chat(cfg["model"], cfg["system_prompt"], prompt,
                      temperature=cfg.get("temperature", 0.3),
                      num_predict=cfg.get("num_predict", 400))
    return _limpiar_texto(raw)


def _limpiar_texto(txt: str) -> str:
    """Quita fences, comillas envolventes y prefacios del modelo."""
    t = (txt or "").strip()
    if t.startswith("```"):
        t = re.sub(r"^```[a-zA-Z]*\n?", "", t)
        t = re.sub(r"\n?```$", "", t).strip()
    if len(t) >= 2 and t[0] == t[-1] and t[0] in "\"'":
        t = t[1:-1].strip()
    return t


def _valid_summary(txt: str) -> bool:
    """Rechaza respuestas vacias, meta-respuestas o plantillas sin rellenar."""
    if not txt or len(txt) < 80:
        return False
    low = txt.lower()
    if low.startswith(("here is", "here's", "sure", "certainly")):
        return False
    if re.search(r"\{[^}\n]*\}", txt):          # llaves sin rellenar
        return False
    return True


def summarize_con_verificacion(client: OllamaClient, cfg: dict, dominio: str,
                               scan: dict) -> tuple:
    """Devuelve (resumen, status). Ver las constantes SUMMARY_*."""
    try:
        txt = run_summarizer(client, cfg, dominio, scan)
    except Exception as e:                                       # noqa: BLE001
        warn(f"summarizer fallo en {dominio}: {e}")
        return None, SUMMARY_FAILED
    if _valid_summary(txt):
        return txt, SUMMARY_OK
    try:
        txt2 = run_summarizer(client, cfg, dominio, scan)
    except Exception:                                            # noqa: BLE001
        return None, SUMMARY_FAILED
    if _valid_summary(txt2):
        return txt2, SUMMARY_RETRY_OK
    return None, SUMMARY_FAILED


# ─── VALIDACION MX + SCORE DE CALIDAD DEL EMAIL ─────────────────────────────
# Locales genericos que NO identifican a un decisor (penalizan el score).
_EMAIL_SCORE_GENERICOS = (
    "contacto", "info", "admin", "hola", "ventas", "soporte",
    "webmaster", "no-reply", "noreply", "mail", "correo",
)
# Webmail publico: el email no es del dominio propio del target.
_FREE_EMAIL_PROVIDERS = {
    "gmail.com", "googlemail.com", "hotmail.com", "hotmail.cl", "hotmail.es",
    "outlook.com", "outlook.cl", "outlook.es", "live.com", "live.cl",
    "yahoo.com", "yahoo.es", "yahoo.cl", "icloud.com", "me.com", "aol.com",
    "gmx.com", "protonmail.com", "proton.me", "zoho.com", "msn.com",
}


def validate_email_mx(email: str) -> tuple[bool, str]:
    """Verifica que el dominio del email tenga registro MX valido.

    Devuelve (valido, razon). Solo hace un lookup DNS de MX, sin handshake SMTP.
    Es sync: enrich_one la corre en un executor para no bloquear el event loop.
    Si dnspython no esta instalado degrada con (False, "dns_no_disponible").
    """
    email = (email or "").strip().lower()
    if not email or "@" not in email:
        return False, "sin_email"
    if dns is None:
        return False, "dns_no_disponible"
    dominio = email.rsplit("@", 1)[-1]
    if not dominio:
        return False, "sin_email"
    try:
        answers = dns.resolver.resolve(dominio, "MX", lifetime=5)
        return (True, "") if len(answers) >= 1 else (False, "sin_registro_mx")
    except dns.resolver.NXDOMAIN:
        return False, "dominio_inexistente"
    except dns.resolver.NoAnswer:
        return False, "sin_registro_mx"
    except dns.exception.Timeout:
        return False, "timeout_dns"
    except Exception:  # noqa: BLE001
        return False, "error_dns"


def email_quality_score(email: str, mx_valido: bool) -> int:
    """Puntua la calidad de un email para priorizar el envio (0-100, funcion pura).

    +40 MX valido · +30 local no generico · +20 dominio propio (no webmail) ·
    +10 parece nombre de persona (tiene punto, o >5 chars y no generico).
    """
    email = (email or "").strip().lower()
    if not email or "@" not in email:
        return 0
    local, dominio = email.rsplit("@", 1)
    es_generico = any(g in local for g in _EMAIL_SCORE_GENERICOS)
    score = 0
    if mx_valido:
        score += 40
    if not es_generico:
        score += 30
    if dominio and dominio not in _FREE_EMAIL_PROVIDERS:
        score += 20
    if ("." in local) or (len(local) > 5 and not es_generico):
        score += 10
    return min(score, 100)


# ─── CONFIANZA ──────────────────────────────────────────────────────────────
_CARGO_GENERICO = {"", "desconocido", "contacto", "responsable del negocio", "n/a"}


def compute_confianza(dominio: str, email: str, metodo: str, cargo: str,
                      viable: bool, eq_score: int = 0) -> float:
    """Confianza objetiva del enriquecimiento (0.0 - 1.0), por senales concretas."""
    score = 0.0
    if dominio:
        score += 0.30
    if metodo == "crawl4ai":
        score += 0.25
    elif metodo == "requests":
        score += 0.15
    score += round((eq_score / 100) * 0.25, 4)
    if cargo and cargo.strip().lower() not in _CARGO_GENERICO:
        score += 0.20
    if not viable:
        score *= 0.5
    return round(min(score, 1.0), 2)


# ─── PIPELINE POR TARGET ─────────────────────────────────────────────────
def _safe(label: str, fn, fallback):
    try:
        return fn()
    except Exception as e:  # noqa: BLE001
        warn(f"Agente {label} fallo: {e}")
        return fallback


async def enrich_one(idx: int, total: int, place: dict, agentes: dict,
                     client: OllamaClient, scraper: SiteScraper,
                     batch_cfg: dict, full_config: dict, *,
                     sin_summary: bool = False) -> dict:
    empresa = place["name"] or "(sin nombre)"
    website = place["website"]
    migracion_detectada = False
    dominio_original = ""
    dominio_alternativo = ""

    # 0. Prefiltro HTTP: descartar dominios muertos antes de scraping + LLM.
    # Compat: si la seccion "prefiltro" no existe en config.json, queda
    # desactivado (dict vacio es falsy); si existe, "enabled" manda (default True).
    prefiltro_cfg = full_config.get("prefiltro", {})
    if prefiltro_cfg and prefiltro_cfg.get("enabled", True) and website:
        loop = asyncio.get_event_loop()
        vivo, razon, dom_alt, necesita_js = await loop.run_in_executor(
            None, check_domain_alive, website, prefiltro_cfg)
        if not vivo and dom_alt:
            # Dominio original muerto pero redirige a otro activo: el target migro.
            # No se descarta; el pipeline sigue con el dominio nuevo.
            dominio_original = extract_domain(website)
            dominio_alternativo = dom_alt
            migracion_detectada = True
            warn(f"[{idx}/{total}] MIGRADO {empresa[:32]:<32} "
                 f"{dominio_original or '-'} → {dom_alt}")
            website = _ensure_url(dom_alt)
            place = {**place, "website": website}
        elif not vivo and necesita_js:
            # 2xx con HTML esqueleto: el sitio carga contenido vía JS. No
            # descartar — el SiteScraper usará Crawl4AI y obtendrá el render
            # completo. Si después tampoco encuentra nada, el flujo normal de
            # confianza/email se encargará de bajar el score.
            warn(f"[{idx}/{total}] JS-SITE {empresa[:32]:<32} — intentando Crawl4AI...")
        elif not vivo:
            warn(f"[{idx}/{total}] SKIP {empresa[:36]:<36} razón={razon}")
            return {
                "name": empresa,
                "dominio": extract_domain(website) or "",
                "cargo_objetivo": "",
                "email": "",
                "summary": None,
                "confianza": 0.0,
                "descartado": True,
                "skip_reason": razon,
            }

    # 1. Scraping del sitio del target (Crawl4AI / requests)
    sitio_texto, metodo, sitio_html = ("", "none", "")
    if website:
        sitio_texto, metodo, sitio_html = await scraper.fetch(website)
    # Emails del sitio: mailto: + regex sobre el HTML crudo, no solo el markdown.
    emails_encontrados = extract_site_emails(sitio_html, sitio_texto,
                                             extract_domain(website))

    # 2. ORQUESTADOR — triage del negocio (con señal de migracion si la hubo)
    plan = _safe("orquestador",
                 lambda: run_orquestador(client, agentes["orquestador"], place,
                                         dominio_original=dominio_original,
                                         dominio_alternativo=dominio_alternativo),
                 {"viable": True, "cargo_objetivo": "",
                  "prioridad": "media", "angulo": ""})

    # 3. DESCUBRIDOR — extraccion de contacto
    desc = _safe("descubridor",
                 lambda: run_descubridor(client, agentes["descubridor"], place,
                                         plan, sitio_texto, emails_encontrados),
                 {"dominio": "", "email": "", "cargo_objetivo": "",
                  "nombre_contacto": "", "resumen_empresa": "", "senales": []})

    dominio = extract_domain(website) or _clean_domain(desc["dominio"])
    email = _reconcile_email(desc["email"], emails_encontrados, sitio_texto)
    cargo = (desc["cargo_objetivo"] or plan["cargo_objetivo"]
             or "Responsable del negocio")

    # 3.6 VALIDACION MX + SCORE DE CALIDAD DEL EMAIL (DNS, sin SMTP).
    if email:
        loop = asyncio.get_event_loop()
        mx_valido, mx_razon = await loop.run_in_executor(
            None, validate_email_mx, email)
    else:
        mx_valido, mx_razon = False, "sin_email"
    eq_score = email_quality_score(email, mx_valido)

    # 3.5 HALLAZGOS REALES — Flash JSON del dominio (o fallback DMARC/SPF).
    flash_data, flash_json_usado = load_hallazgos(dominio)
    tipo = ""

    # 4. SUMMARIZER — resumen ejecutivo del informe, a partir de los hallazgos.
    # --no-summary: batches de solo enriquecimiento (dominio/email/MX) sin
    # gastar tokens en el LLM. El campo summary queda en null.
    if sin_summary:
        summary, summary_status = None, SUMMARY_SKIPPED
    else:
        summary, summary_status = summarize_con_verificacion(
            client, agentes["summarizer"], dominio, flash_data)

    confianza = compute_confianza(dominio, email, metodo, cargo,
                                  plan.get("viable", True), eq_score)

    marca = (f"{BG}OK{NC}" if confianza >= batch_cfg.get("confianza_minima", 0.35)
             else f"{YL}~~{NC}")
    info(f"[{idx}/{total}] {marca} {empresa[:32]:<32} "
         f"dom={dominio or '-':<22} conf={confianza} sum={summary_status}")

    return {
        "name": empresa,
        "dominio": dominio,
        "cargo_objetivo": cargo,
        "email": email,
        "emails_encontrados": emails_encontrados,
        "summary": summary,
        "summary_status": summary_status,
        "confianza": confianza,
        "email_mx_valido": mx_valido,
        "email_mx_razon": mx_razon,
        "email_quality": eq_score,
        "flash_json_usado": flash_json_usado,
        "hallazgos_usados": flash_data["hallazgos"],
        "migracion_detectada": migracion_detectada,
        "dominio_original": dominio_original,
        "dominio_alternativo": dominio_alternativo,
    }


async def run_batch(places: list, config: dict, client: OllamaClient, *,
                    sin_summary: bool = False) -> list:
    agentes = config["agentes"]
    batch_cfg = config.get("batch", {})
    pausa = float(batch_cfg.get("pausa_entre_targets_seg", 0))
    resultados = []
    async with SiteScraper(config.get("crawl4ai", {})) as scraper:
        for i, place in enumerate(places, 1):
            resultados.append(
                await enrich_one(i, len(places), place, agentes, client,
                                 scraper, batch_cfg, config,
                                 sin_summary=sin_summary))
            if pausa and i < len(places):
                await asyncio.sleep(pausa)
    return resultados


# ─── PERSISTENCIA EN db/targets.json ─────────────────────────────────────
# Los emails que descubre el batch viven en el JSON de salida; aqui se escriben
# tambien de vuelta a la base maestra db/targets.json para que no dependan de
# un paso manual. Es best-effort: si la DB no esta (p.ej. dentro del contenedor,
# donde db/ no se monta) se avisa y el batch continua sin abortar.
def _resolve_targets_db() -> Path:
    """Ruta de la base maestra de targets. CROWSNEST_TARGETS_DB manda."""
    env = os.environ.get("CROWSNEST_TARGETS_DB")
    if env:
        return Path(env)
    return MODULE_DIR.parent / "db" / "targets.json"


TARGETS_DB = _resolve_targets_db()


def persist_emails_to_db(targets: list, db_path=None, *,
                         email_fecha: str | None = None,
                         backup: bool = True) -> dict:
    """Escribe los emails encontrados de vuelta a db/targets.json.

    Por cada target con email no vacio busca su dominio como llave en
    .targets y agrega/actualiza email_contacto, emails_encontrados y
    email_fecha, preservando el resto del registro y la estructura
    envoltorio ({targets, version}). Hace un backup
    db/targets.json.backup_email_<timestamp> antes de tocar el archivo.

    Devuelve {actualizados, no_encontrados, db_path, ok}. Nunca lanza por
    causas operativas (DB ausente, estructura inesperada): avisa y devuelve
    ok=False para no tumbar el batch.
    """
    db_path = Path(db_path) if db_path else TARGETS_DB
    base = {"actualizados": [], "no_encontrados": [], "db_path": str(db_path)}
    if not db_path.is_file():
        warn(f"DB de targets no encontrada ({db_path}); no se persisten emails.")
        return {**base, "ok": False}

    con_email = [p for p in targets if (p.get("email") or "").strip()]
    descartados = [p for p in targets if p.get("descartado")]
    migrados = [p for p in targets if p.get("migracion_detectada")]
    if not con_email and not descartados and not migrados:
        info("Ningun target trae email, descarte ni migracion; nada que persistir.")
        return {**base, "ok": True}

    try:
        db = json.loads(db_path.read_text(encoding="utf-8"))
    except (json.JSONDecodeError, OSError) as e:  # noqa: BLE001
        error(f"No se pudo leer la DB {db_path}: {e}; no se persisten emails.")
        return {**base, "ok": False}

    registros = db.get("targets")
    if not isinstance(registros, dict):
        warn(f"Estructura inesperada en {db_path} (.targets no es objeto); "
             "no se persiste.")
        return {**base, "ok": False}

    fecha = email_fecha or datetime.now().isoformat(timespec="seconds")

    # Backup solo cuando de verdad hay algo que escribir.
    if backup:
        stamp = time.strftime("%Y%m%d_%H%M%S")
        bak = db_path.with_name(f"{db_path.name}.backup_email_{stamp}")
        bak.write_text(db_path.read_text(encoding="utf-8"), encoding="utf-8")
        info(f"Backup de la DB: {bak.name}")

    actualizados, no_encontrados, marcados_descarte, migraciones = [], [], [], []
    for target in targets:
        dominio = (target.get("dominio") or "").strip().lower()
        # Descartados por el prefiltro: marcar estado y saltar (no llevan email).
        if target.get("descartado"):
            if dominio:                       # sin dominio no hay llave que tocar
                razon = target.get("skip_reason", "")
                entry = registros.setdefault(dominio, {})
                # conexion_fallida/timeout son errores de red transitorios, no un
                # dominio muerto: dejar como flash_listo (pendiente) para que el
                # proximo batch lo reintente. Se anota el fallo y NO se toca el
                # outreach (el envio sigue vigente si ya estaba).
                if razon in ("conexion_fallida", "timeout"):
                    entry["status"] = QUEUED
                    entry["skip_reason"] = razon
                else:
                    entry["status"] = SKIPPED
                    entry["skip_reason"] = razon
                    marcados_descarte.append((dominio, razon))
            continue
        email = (target.get("email") or "").strip()
        # Migracion: la entrada se mantiene bajo el dominio ORIGINAL (no romper
        # referencias); se anotan el dominio nuevo y el original, y el email del
        # nuevo sitio se guarda en esa misma entrada.
        if target.get("migracion_detectada"):
            original = (target.get("dominio_original") or "").strip().lower()
            alt = (target.get("dominio_alternativo") or dominio).strip().lower()
            clave = original or dominio        # la entrada vive bajo el original
            if clave and clave in registros:
                reg = registros[clave]
                reg["dominio_alternativo"] = alt
                reg["dominio_original"] = original
                if email:
                    reg["emails_found"] = target.get("emails_encontrados") or [email]
                    reg["emails_found_at"] = fecha
                    reg["email_mx_valid"] = target.get("email_mx_valido", False)
                    actualizados.append((clave, email))
                migraciones.append((original, alt))
            else:
                no_encontrados.append((clave or "(sin dominio)", email))
            continue
        if not email:
            continue
        if dominio and dominio in registros:
            reg = registros[dominio]
            reg["emails_found"] = target.get("emails_encontrados") or [email]
            reg["emails_found_at"] = fecha
            reg["email_mx_valid"] = target.get("email_mx_valido", False)
            actualizados.append((dominio, email))
        else:
            no_encontrados.append((dominio or "(sin dominio)", email))

    db_path.write_text(json.dumps(db, ensure_ascii=False, indent=2) + "\n",
                       encoding="utf-8")
    log(f"DB actualizada: {len(actualizados)} target(s) con email persistido.")
    if marcados_descarte:
        info(f"{len(marcados_descarte)} dominio(s) marcados como descartados en la DB.")
    if migraciones:
        info(f"{len(migraciones)} migracion(es) anotadas en la DB: "
             + ", ".join(f"{o}→{a}" for o, a in migraciones))
    if no_encontrados:
        warn(f"{len(no_encontrados)} dominio(s) con email no estaban en la DB "
             "(omitidos, no se crean entradas nuevas): "
             + ", ".join(d for d, _ in no_encontrados))
    return {"actualizados": actualizados, "no_encontrados": no_encontrados,
            "descartados": marcados_descarte, "migraciones": migraciones,
            "db_path": str(db_path), "ok": True}


# ─── ENTRADA / SALIDA ───────────────────────────────────────────────────────
def read_input(path: str | None) -> str:
    if path:
        p = Path(path)
        if not p.is_file():
            error(f"No existe el archivo de entrada: {path}")
            sys.exit(1)
        return p.read_text(encoding="utf-8")
    if not sys.stdin.isatty():
        data = sys.stdin.read()
        if data.strip():
            return data
    error("No se indico entrada. Usa --input <dominios.txt> o pasa la lista por stdin.")
    sys.exit(1)


def print_summary(targets: list, config: dict) -> None:
    # Recibe la lista COMPLETA (utiles + descartados) para poder contar ambos.
    descartados = [p for p in targets if p.get("descartado")]
    utiles = [p for p in targets if not p.get("descartado")]
    cmin = config.get("batch", {}).get("confianza_minima", 0.0)
    altos = [p for p in utiles if p.get("confianza", 0.0) >= cmin]
    step("Resumen del enriquecimiento")
    info(f"Targets procesados : {len(targets)}")
    info(f"Descartados prefiltro : {len(descartados)}")
    info(f"Migraciones detectadas: {sum(1 for p in targets if p.get('migracion_detectada'))}")
    info(f"Confianza >= {cmin}      : {len(altos)}")
    info(f"Con dominio           : {sum(1 for p in utiles if p['dominio'])}")
    info(f"Con email             : {sum(1 for p in utiles if p['email'])}")
    info(f"Email MX válido       : {sum(1 for p in utiles if p.get('email_mx_valido'))}")
    info(f"Email score promedio  : {round(sum(p.get('email_quality', 0) for p in utiles if p.get('email')) / max(1, sum(1 for p in utiles if p.get('email'))), 1)}")
    info(f"Con emails en sitio   : {sum(1 for p in utiles if p.get('emails_encontrados'))}")
    info(f"Con Flash JSON real   : {sum(1 for p in utiles if p.get('flash_json_usado'))}")
    estados = {}
    for p in utiles:
        estado = p.get("summary_status", "?")
        estados[estado] = estados.get(estado, 0) + 1
    info("Estado del resumen    : "
         + ", ".join(f"{k}={v}" for k, v in sorted(estados.items())))


def main(argv=None) -> int:
    ap = argparse.ArgumentParser(
        description="OpenClaw Orchestrator - enriquece una lista de dominios objetivo.")
    ap.add_argument("input_pos", nargs="?",
                    help="Lista de dominios objetivo, uno por linea (posicional).")
    ap.add_argument("-i", "--input",
                    help="Lista de dominios objetivo, uno por linea. '#' comenta.")
    ap.add_argument("-o", "--output", help="Archivo JSON de salida (si se omite, stdout).")
    ap.add_argument("-c", "--config", default=str(DEFAULT_CONFIG),
                    help="Ruta de config.json.")
    ap.add_argument("-n", "--limit", type=int, default=0,
                    help="Procesar como maximo N targets.")
    ap.add_argument("--skip-preflight", action="store_true",
                    help="Omitir la verificacion de modelos Ollama.")
    ap.add_argument("--db",
                    help="Ruta de db/targets.json donde persistir los emails "
                         "(por defecto <repo>/db/targets.json o "
                         "CROWSNEST_TARGETS_DB).")
    ap.add_argument("--no-db-sync", action="store_true",
                    help="No escribir los emails encontrados de vuelta a "
                         "db/targets.json al terminar el batch.")
    ap.add_argument("--include-discarded", action="store_true",
                    help="Incluir en la salida los dominios descartados por el "
                         "prefiltro (por defecto solo se escriben los utiles).")
    ap.add_argument("--no-summary", action="store_true",
                    help="Omitir la etapa del summarizer. El campo summary queda "
                         "en null y summary_status='not_requested'. Util para "
                         "batches de solo enriquecimiento.")
    args = ap.parse_args(argv)

    try:
        config = load_config(args.config)
    except (FileNotFoundError, ValueError, json.JSONDecodeError) as e:
        error(f"Configuracion invalida: {e}")
        return 1

    client = OllamaClient.from_config(config)

    # Preflight: verificar que los modelos esten disponibles antes del batch.
    if not args.skip_preflight:
        ok, report = verify_models(config, client)
        print_preflight(report, config["agentes"])
        if not ok:
            error("Preflight fallido. Aborta el batch (usa --skip-preflight para forzar).")
            return 2

    # Leer la lista de dominios objetivo (texto plano, uno por linea).
    places = parse_target_list(read_input(args.input or args.input_pos))
    if not places:
        error("La lista de entrada no contiene dominios validos.")
        return 1

    cap = int(config.get("batch", {}).get("max_targets", 60))
    if args.limit > 0:
        places = places[:args.limit]
    if len(places) > cap:
        warn(f"Entrada con {len(places)} dominios; se limita a {cap} (batch.max_targets).")
        places = places[:cap]

    step(f"Enriqueciendo {len(places)} target(s)")
    t0 = time.time()
    targets = asyncio.run(run_batch(places, config, client,
                                       sin_summary=args.no_summary))

    descartados = [p for p in targets if p.get("descartado")]
    utiles = [p for p in targets if not p.get("descartado")]

    if descartados:
        step("Dominios descartados por prefiltro")
        for d in descartados:
            warn(f"  {d['name'][:40]:<40} {d['skip_reason']}")

    # La salida solo incluye targets utiles, salvo --include-discarded (debug).
    salida_items = targets if args.include_discarded else utiles
    salida_items.sort(key=lambda p: p.get("confianza", 0.0), reverse=True)

    salida = json.dumps(salida_items, ensure_ascii=False, indent=2)
    if args.output:
        Path(args.output).write_text(salida + "\n", encoding="utf-8")
        log(f"Escrito: {args.output}")
    else:
        print(salida)

    print_summary(targets, config)

    # Persistir los emails encontrados de vuelta a la base maestra (best-effort).
    if not args.no_db_sync:
        step("Persistencia de emails en db/targets.json")
        persist_emails_to_db(targets, args.db or None)

    info(f"Tiempo total: {time.time() - t0:.1f}s")
    return 0


if __name__ == "__main__":
    sys.exit(main())
