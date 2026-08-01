#!/usr/bin/env python3
# =============================================================================
# Clasificador de targets — S.I.N.S.
# =============================================================================
# Separa los targets de db/targets.json en PYMEs reales (target SINS) y
# ruido (directorios, agregadores, SaaS de agendamiento/formularios).
#
# Por cada dominio:
#   1. Heuristica previa (rapida, sin LLM) sobre el nombre del dominio.
#   2. Scraping del home con Crawl4AI (fallback requests), max 5000 chars.
#   3. Clasificacion con qwen2.5:7b (Ollama local) en 4 categorias con score.
#
# Categorias:
#   PYME_REAL      estudio/clinica/contable individual con servicios propios
#   DIRECTORIO     agregador / lista de varios profesionales o empresas
#   SAAS_TECNICO   plataforma tecnica generica (agendamiento, formularios)
#   INDETERMINADO  dudoso, requiere revision humana
#
# Salida: db/targets_clasificados.json (NO modifica db/targets.json).
#
# Uso:
#   python3 openclaw/classify_prospects.py
#   python3 openclaw/classify_prospects.py --limit 10 --workers 3
# =============================================================================
from __future__ import annotations

import argparse
import asyncio
import json
import re
import sys
import time
from datetime import datetime
from pathlib import Path

import requests

MODULE_DIR = Path(__file__).resolve().parent
REPO_ROOT = MODULE_DIR.parent
if str(MODULE_DIR) not in sys.path:                     # permite importar run_batch
    sys.path.insert(0, str(MODULE_DIR))

# Reutiliza la infraestructura del orquestador (cliente Ollama, scraper, logging).
from run_batch import (                                 # noqa: E402
    OllamaClient, SiteScraper, _extract_json, _model_present,
    log, info, warn, error, step, BG, CY, YL, BR, W, NC,
)

DEFAULT_INPUT = REPO_ROOT / "db" / "targets.json"
DEFAULT_OUTPUT = REPO_ROOT / "db" / "targets_clasificados.json"
DEFAULT_CONFIG = MODULE_DIR / "config.json"

MODEL = "qwen2.5:7b"
HTML_MAX_CHARS = 5000
NUM_CTX = 8192                     # excerpt de 5000 chars no cabe en el ctx por defecto
CATEGORIAS = ("PYME_REAL", "DIRECTORIO", "SAAS_TECNICO", "INDETERMINADO")
_COLOR_CAT = {"PYME_REAL": BG, "DIRECTORIO": YL, "SAAS_TECNICO": CY,
              "INDETERMINADO": BR}


# ─── PROMPTS ────────────────────────────────────────────────────────────────
SYSTEM_PROMPT = (
    "Eres un clasificador experto de sitios web chilenos para S.I.N.S. "
    "(SINS Is Not Static SpA), una startup de ciberseguridad que vende servicios "
    "a PYMEs reales. Tu tarea es separar las PYMEs reales (clientes potenciales) "
    "del ruido (directorios, agregadores y plataformas SaaS). Respondes SIEMPRE "
    "en JSON valido, sin texto fuera del JSON, con exactamente estas claves: "
    "categoria (uno de: PYME_REAL, DIRECTORIO, SAAS_TECNICO, INDETERMINADO), "
    "confianza (numero entre 0.0 y 1.0), razon (una frase corta en espanol). "
    "Se estricto: si el sitio lista muchos profesionales o empresas distintas es "
    "DIRECTORIO; si es una herramienta generica de agendamiento o formularios es "
    "SAAS_TECNICO; si no hay evidencia suficiente es INDETERMINADO."
)

USER_TEMPLATE = (
    "Analiza este sitio web y clasificalo. Responde SOLO con JSON: "
    "{{categoria, confianza, razon}}.\n"
    "Categorias: PYME_REAL, DIRECTORIO, SAAS_TECNICO, INDETERMINADO.\n"
    "PYME_REAL = una empresa individual ofreciendo servicios profesionales "
    "(estudio juridico, clinica, contable).\n"
    "DIRECTORIO = lista de varios profesionales/empresas (agregador).\n"
    "SAAS_TECNICO = plataforma tecnica generica (agendamiento, formularios).\n"
    "INDETERMINADO = no se puede determinar con claridad.\n"
    "Dominio: {dominio}\n"
    "Nombre: {nombre}\n"
    "Contenido HTML (primeros 5000 chars): {html_excerpt}"
)


# ─── CLIENTE OLLAMA (ctx ampliado) ──────────────────────────────────────────
class ClasificadorOllama(OllamaClient):
    """OllamaClient con `num_ctx` explicito.

    El excerpt de 5000 chars (~1700 tokens) mas el system prompt no caben en el
    contexto por defecto de Ollama; sin ampliarlo el modelo veria el HTML
    truncado. `OllamaClient.chat` no expone `num_ctx`, asi que se sobreescribe.
    """

    def chat(self, model: str, system: str, prompt: str, *,
             temperature: float = 0.1, num_predict: int = 300,
             json_mode: bool = True, num_ctx: int = NUM_CTX) -> str:
        messages = [{"role": "system", "content": system},
                    {"role": "user", "content": prompt}]
        options = {"temperature": float(temperature),
                   "num_predict": int(num_predict),
                   "num_ctx": int(num_ctx)}
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


# ─── HEURISTICA PREVIA AL SCRAPE (rapida, sin LLM) ──────────────────────────
# Plataformas SaaS: el subdominio es una pagina alojada, no un sitio propio.
SAAS_PLATFORMS = {
    "setmore.com", "agendapro.com", "softwaredentalink.com", "crmveterinario.com",
    "simplybook.me", "calendly.com", "reservo.cl", "ueniweb.com", "wixsite.com",
    "agenda.softwaredentalink.com",
}
# Agregadores conocidos (directorios de profesionales / empresas).
DIRECTORIO_PARENTS = {"justia.com", "mercantil.com"}
DIR_KEYWORDS = ("amarillas", "guia", "guía", "directorio", "paginasamarillas",
                "listado", "ranking")
SAAS_KEYWORDS = ("agenda", "agendamiento", "reserva", "booking")
# Terminos de servicio profesional propios de una PYME individual.
PYME_KEYWORDS = ("abogad", "juridic", "jurídic", "clinica", "clínica", "dental",
                 "dentista", "contad", "contab", "audit", "asesor", "vet",
                 "estudio", "consult", "salud", "medic", "médic", "legal", "lex")


def _es_label_aleatorio(label: str) -> bool:
    """True si el label parece un hash/identificador aleatorio, no un nombre."""
    l = label.lower()
    if len(l) < 12:
        return False
    if re.fullmatch(r"[0-9a-f]{16,}", l):                 # hash hexadecimal
        return True
    digitos = sum(c.isdigit() for c in l)
    return len(l) >= 16 and digitos >= 6 and "-" not in l


def _partes_dominio(dominio: str) -> tuple[str, str]:
    """Devuelve (subdominio, dominio_padre). Para .cl/.com de 2 niveles basta."""
    labels = dominio.split(".")
    if len(labels) <= 2:
        return "", dominio
    return ".".join(labels[:-2]), ".".join(labels[-2:])


def heuristica(dominio: str) -> dict:
    """Pista de clasificacion a partir del nombre del dominio (sin red, sin LLM).

    `short_circuit=True` solo en el caso 'casi seguro' (subdominio aleatorio):
    ahi se omite scrape y LLM. En el resto la pista es orientativa para el LLM.
    """
    d = dominio.strip().lower().rstrip(".")
    sub, parent = _partes_dominio(d)
    labels_sub = [x for x in sub.split(".") if x]

    if any(_es_label_aleatorio(x) for x in labels_sub):
        return {"categoria": "SAAS_TECNICO", "fuerza": "fuerte",
                "short_circuit": True,
                "razon": (f"Subdominio con identificador aleatorio sobre "
                          f"{parent}: pagina tecnica de un SaaS, sin dominio "
                          f"propio.")}

    if parent in SAAS_PLATFORMS:
        return {"categoria": "SAAS_TECNICO", "fuerza": "media",
                "short_circuit": False,
                "razon": f"Alojado en la plataforma SaaS {parent}."}

    if parent in DIRECTORIO_PARENTS or any(k in d for k in DIR_KEYWORDS):
        return {"categoria": "DIRECTORIO", "fuerza": "media",
                "short_circuit": False,
                "razon": "El nombre del dominio sugiere un agregador/directorio."}

    if any(k in d for k in SAAS_KEYWORDS):
        return {"categoria": "SAAS_TECNICO", "fuerza": "media",
                "short_circuit": False,
                "razon": "El nombre del dominio sugiere agendamiento/reservas."}

    if d.endswith(".cl") and len(d.split(".")) == 2:
        if any(k in d for k in PYME_KEYWORDS):
            return {"categoria": "PYME_REAL", "fuerza": "media",
                    "short_circuit": False,
                    "razon": "Dominio .cl con termino de servicio profesional."}
        return {"categoria": "PYME_REAL", "fuerza": "debil",
                "short_circuit": False,
                "razon": "Dominio .cl simple, posible nombre propio o empresa."}

    return {"categoria": None, "fuerza": "debil", "short_circuit": False,
            "razon": "Sin senal heuristica clara."}


# ─── CLASIFICACION CON LLM ──────────────────────────────────────────────────
def _clasificar_llm(client: ClasificadorOllama, dominio: str, nombre: str,
                    texto: str, pista: dict) -> tuple[str, float, str]:
    """Consulta a qwen2.5:7b. Devuelve (categoria, confianza, razon)."""
    excerpt = (texto or "").strip()[:HTML_MAX_CHARS]
    hay_contenido = len(excerpt) > 40

    if pista["categoria"]:
        pista_txt = (f"{pista['categoria']} (fuerza {pista['fuerza']}): "
                     f"{pista['razon']}")
    else:
        pista_txt = "ninguna"

    user = USER_TEMPLATE.format(
        dominio=dominio, nombre=nombre,
        html_excerpt=excerpt or "(no se pudo obtener contenido del sitio)")
    user += ("\nPista heuristica previa (orientativa, NO decisiva): "
             f"{pista_txt}")

    try:
        raw = client.chat(MODEL, SYSTEM_PROMPT, user,
                          temperature=0.1, num_predict=300, json_mode=True)
    except Exception as e:                                # noqa: BLE001
        return "INDETERMINADO", 0.0, f"Error consultando al modelo: {e}"

    d = _extract_json(raw)
    cat = str(d.get("categoria", "")).strip().upper()
    if cat not in CATEGORIAS:
        cat = "INDETERMINADO"
    try:
        conf = float(d.get("confianza", 0.0))
    except (TypeError, ValueError):
        conf = 0.0
    conf = max(0.0, min(1.0, conf))
    razon = str(d.get("razon", "")).strip() or "Sin justificacion del modelo."

    # Sin contenido del sitio: la decision es debil; se acota la confianza.
    if not hay_contenido:
        conf = min(conf, 0.5)
        razon = "[sin contenido del sitio] " + razon
        if conf < 0.4:
            cat = "INDETERMINADO"

    # Ajuste leve por (des)acuerdo con la heuristica.
    if pista["categoria"] and pista["fuerza"] in ("media", "fuerte"):
        conf += 0.05 if pista["categoria"] == cat else -0.05
        conf = max(0.0, min(1.0, conf))

    return cat, conf, razon


# ─── PIPELINE POR TARGET ─────────────────────────────────────────────────
async def clasificar_uno(dominio: str, datos: dict, scraper: SiteScraper,
                         client: ClasificadorOllama,
                         sem: asyncio.Semaphore) -> dict:
    """Clasifica un target y devuelve la entrada final (datos + clasificacion)."""
    nombre = (datos.get("name") or dominio).strip()
    try:
        pista = heuristica(dominio)
        if pista["short_circuit"]:
            cat, conf, razon = pista["categoria"], 0.95, pista["razon"]
        else:
            async with sem:                               # max N en vuelo
                texto, _metodo = await scraper.fetch(dominio)
                cat, conf, razon = await asyncio.to_thread(
                    _clasificar_llm, client, dominio, nombre, texto, pista)
    except Exception as e:                                # noqa: BLE001
        cat, conf, razon = "INDETERMINADO", 0.0, f"Error durante la clasificacion: {e}"

    entrada = dict(datos)                                 # datos originales intactos
    entrada["clasificacion"] = cat
    entrada["confianza_clasificacion"] = round(conf, 2)
    entrada["razon_clasificacion"] = razon
    entrada["fecha_clasificacion"] = datetime.now().isoformat(timespec="seconds")
    return entrada


# ─── SALIDA ─────────────────────────────────────────────────────────────────
def _guardar(path: Path, resultados: dict) -> None:
    payload = {"version": 1, "clasificados": resultados}
    path.write_text(json.dumps(payload, ensure_ascii=False, indent=2) + "\n",
                     encoding="utf-8")


def _print_item(n: int, total: int, dominio: str, entrada: dict) -> None:
    cat = entrada["clasificacion"]
    color = _COLOR_CAT.get(cat, W)
    info(f"[{n:>3}/{total}] {dominio[:42]:<42} -> {color}{cat:<13}{NC} "
         f"conf={entrada['confianza_clasificacion']:.2f}")


def _print_milestone(n: int, total: int, tally: dict) -> None:
    pct = 100 * n / total if total else 0
    detalle = "  ".join(f"{c}={tally[c]}" for c in CATEGORIAS)
    log(f"Progreso {n}/{total} ({pct:.0f}%) — {detalle}")


# ─── BATCH ──────────────────────────────────────────────────────────────────
async def run_batch(items: list, scraper_cfg: dict, client: ClasificadorOllama,
                    workers: int, output_path: Path) -> dict:
    sem = asyncio.Semaphore(workers)
    total = len(items)
    estado = {"n": 0, "tally": {c: 0 for c in CATEGORIAS}}
    resultados: dict = {}

    async with SiteScraper(scraper_cfg) as scraper:
        async def procesar(dominio: str, datos: dict) -> None:
            entrada = await clasificar_uno(dominio, datos, scraper, client, sem)
            resultados[dominio] = entrada
            estado["n"] += 1                              # asyncio: sin carrera
            n = estado["n"]
            estado["tally"][entrada["clasificacion"]] += 1
            _print_item(n, total, dominio, entrada)
            if n % 10 == 0 or n == total:                 # progreso cada 10
                _print_milestone(n, total, estado["tally"])
                _guardar(output_path, resultados)         # checkpoint

        await asyncio.gather(*(procesar(d, v) for d, v in items))
    return resultados


# ─── PREFLIGHT ──────────────────────────────────────────────────────────────
def preflight(client: ClasificadorOllama) -> bool:
    step("Preflight — verificacion de Ollama")
    info(f"Host Ollama: {client.host}")
    try:
        disponibles = client.list_models()
    except Exception as e:                                # noqa: BLE001
        error(f"Ollama no responde: {e}")
        warn("Arranca el servidor con: ollama serve")
        return False
    ok = _model_present(MODEL, disponibles)
    marca = f"{BG}disponible{NC}" if ok else f"{BR}FALTA{NC}"
    info(f"  modelo clasificador -> {MODEL:<16} [{marca}]")
    if not ok:
        error(f"Modelo faltante: {MODEL}")
        print(f"      ollama pull {MODEL}", file=sys.stderr)
    return ok


# ─── REPORTE FINAL ──────────────────────────────────────────────────────────
def reporte(resultados: dict, segundos: float) -> None:
    total = len(resultados)
    conteo = {c: 0 for c in CATEGORIAS}
    for e in resultados.values():
        conteo[e["clasificacion"]] = conteo.get(e["clasificacion"], 0) + 1

    step("Distribucion por categoria")
    info(f"Targets clasificados : {total}")
    info(f"Tiempo total            : {segundos:.0f}s")
    for c in CATEGORIAS:
        n = conteo[c]
        pct = 100 * n / total if total else 0
        color = _COLOR_CAT.get(c, W)
        info(f"  {color}{c:<14}{NC} {n:>3}  ({pct:5.1f}%)")

    pymes = sorted(
        ((d, e) for d, e in resultados.items()
         if e["clasificacion"] == "PYME_REAL"),
        key=lambda x: (-x[1]["confianza_clasificacion"], x[0]))
    step("Top 10 PYME_REAL — candidatos piloto")
    if not pymes:
        warn("  Ningun target se clasifico como PYME_REAL.")
    for d, e in pymes[:10]:
        log(f"  {e['confianza_clasificacion']:.2f}  {d:<34} {e.get('name', '')}")
        print(f"          {e['razon_clasificacion']}", file=sys.stderr)

    indet = sorted(d for d, e in resultados.items()
                   if e["clasificacion"] == "INDETERMINADO")
    step(f"INDETERMINADO — revision humana ({len(indet)})")
    if not indet:
        log("  Ninguno: no hay targets que requieran revision humana.")
    for d in indet:
        e = resultados[d]
        warn(f"  {d:<34} conf={e['confianza_clasificacion']:.2f}  "
             f"{e['razon_clasificacion']}")


# ─── MAIN ───────────────────────────────────────────────────────────────────
def cargar_config(path: str) -> dict:
    p = Path(path)
    if not p.is_file():
        warn(f"No se encontro {p}; se usan valores por defecto.")
        return {}
    try:
        return json.loads(p.read_text(encoding="utf-8"))
    except json.JSONDecodeError as e:
        warn(f"config.json invalido ({e}); se usan valores por defecto.")
        return {}


def main(argv=None) -> int:
    ap = argparse.ArgumentParser(
        description="Clasifica los targets de S.I.N.S. (PYME real vs. ruido).")
    ap.add_argument("-i", "--input", default=str(DEFAULT_INPUT),
                    help="db/targets.json (solo lectura).")
    ap.add_argument("-o", "--output", default=str(DEFAULT_OUTPUT),
                    help="JSON de salida con la clasificacion.")
    ap.add_argument("-c", "--config", default=str(DEFAULT_CONFIG),
                    help="Ruta de config.json (host Ollama, ajustes Crawl4AI).")
    ap.add_argument("-n", "--limit", type=int, default=0,
                    help="Procesar como maximo N targets (0 = todos).")
    ap.add_argument("-w", "--workers", type=int, default=3,
                    help="Maximo de targets en paralelo (default 3).")
    ap.add_argument("--skip-preflight", action="store_true",
                    help="Omitir la verificacion del modelo Ollama.")
    args = ap.parse_args(argv)

    input_path = Path(args.input).resolve()
    output_path = Path(args.output).resolve()
    if output_path == input_path:
        error("El archivo de salida no puede ser el de entrada (targets.json).")
        return 1
    if not input_path.is_file():
        error(f"No existe el archivo de entrada: {input_path}")
        return 1

    try:
        data = json.loads(input_path.read_text(encoding="utf-8"))
    except json.JSONDecodeError as e:
        error(f"targets.json no es JSON valido: {e}")
        return 1
    targets = data.get("targets") if isinstance(data, dict) else None
    if not isinstance(targets, dict) or not targets:
        error("targets.json no contiene la clave 'targets' con datos.")
        return 1

    config = cargar_config(args.config)
    client = ClasificadorOllama.from_config(config)

    if not args.skip_preflight:
        if not preflight(client):
            error("Preflight fallido. Aborta (usa --skip-preflight para forzar).")
            return 2

    items = list(targets.items())
    if args.limit > 0:
        items = items[:args.limit]
    workers = max(1, args.workers)

    scraper_cfg = dict(config.get("crawl4ai", {}))
    scraper_cfg["max_chars"] = HTML_MAX_CHARS             # excerpt pedido: 5000
    scraper_cfg.setdefault("enabled", True)

    step(f"Clasificando {len(items)} target(s) — {workers} workers")
    est_min = len(items) * 8 / workers / 60               # ~8 s/target efectivos
    info(f"Tiempo estimado: ~{est_min:.0f}-{est_min * 2.5:.0f} min "
         f"(5-15 s por target)")
    info(f"Salida: {output_path}")

    t0 = time.time()
    resultados = asyncio.run(
        run_batch(items, scraper_cfg, client, workers, output_path))

    # Reordena segun el orden original de targets.json antes de guardar.
    ordenado = {d: resultados[d] for d, _ in items if d in resultados}
    _guardar(output_path, ordenado)
    log(f"Escrito: {output_path} ({len(ordenado)} targets)")

    reporte(ordenado, time.time() - t0)
    return 0


if __name__ == "__main__":
    sys.exit(main())
