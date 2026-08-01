#!/usr/bin/env bash
# =============================================================================
# sins.sh — CLI unificado de S.I.N.S.
# Uso:
#   ./sins.sh prospectos   → scraping multi-fuente de PYMES chilenas
#   ./sins.sh prospectos enriquecer → enriquece prospectos con OpenClaw (Ollama)
#   ./sins.sh captacion    → califica prospectos (sin Docker, ~10 seg/dominio)
#   ./sins.sh flash        → genera informe flash completo (con Docker, ~20 min)
#   ./sins.sh flash --ciber → informes con marco Ley 21.663 (Ley Marco de Ciberseguridad)
#
# Compatibilidad: Fedora KDE · Ubuntu · WSL2 (Windows 11)
# =============================================================================

set -euo pipefail

# ── COLORES ──────────────────────────────────────────────────────────────────
RED='\033[0;31m'; BRED='\033[1;31m'
GREEN='\033[0;32m'; BGREEN='\033[1;32m'
YELLOW='\033[1;33m'; CYAN='\033[0;36m'
WHITE='\033[1;37m'; GRAY='\033[0;37m'
NC='\033[0m'

# ── PATHS ────────────────────────────────────────────────────────────────────
SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
REPORTES_DIR="${SCRIPT_DIR}/reportes"
TARGETS_DIR="${SCRIPT_DIR}/targets"
PROSPECTOS_FILE="${TARGETS_DIR}/prospectos.txt"
CONTAINER_NAME="sins-workstation-ciber-workstation"
DB_FILE="${SCRIPT_DIR}/db/prospectos.json"

# ── HELPERS ──────────────────────────────────────────────────────────────────
header() {
    clear
    echo -e "${RED}┌─────────────────────────────────────────────────────────┐${NC}"
    echo -e "${RED}│${NC}  ${WHITE}S.I.N.S.${NC} ${GRAY}— SINS Is Not Static SpA${NC}                      ${RED}│${NC}"
    echo -e "${RED}│${NC}  ${GRAY}$1${NC}"
    echo -e "${RED}└─────────────────────────────────────────────────────────┘${NC}"
    echo ""
}

log()     { echo -e "${GREEN}[✓]${NC} $1"; }
info()    { echo -e "${CYAN}[→]${NC} $1"; }
warn()    { echo -e "${YELLOW}[!]${NC} $1"; }
error()   { echo -e "${BRED}[✗]${NC} $1"; }
step()    { echo -e "\n${WHITE}$1${NC}"; echo -e "${GRAY}$(printf '─%.0s' {1..55})${NC}"; }
ask()     { echo -e "${CYAN}[?]${NC} $1"; }

check_dep() {
    if ! command -v "$1" &>/dev/null; then
        error "Falta: $1"
        echo -e "    Instala con: ${GRAY}$2${NC}"
        return 1
    fi
    return 0
}

check_docker_running() {
    if ! docker info &>/dev/null; then
        error "Docker no está corriendo."
        echo -e "    Inicia Docker Desktop (Windows) o: ${GRAY}sudo systemctl start docker${NC}"
        exit 1
    fi
}

check_container_built() {
    if ! docker image inspect "${CONTAINER_NAME}" &>/dev/null; then
        error "La imagen '${CONTAINER_NAME}' no está construida."
        echo -e "    Ejecuta primero: ${GRAY}docker-compose build${NC}"
        exit 1
    fi
}

score_color() {
    local score=$1
    if   [[ $score -ge 80 ]]; then echo -e "${BRED}${score}/100 — Crítico${NC}"
    elif [[ $score -ge 50 ]]; then echo -e "${YELLOW}${score}/100 — Alto${NC}"
    elif [[ $score -ge 25 ]]; then echo -e "${YELLOW}${score}/100 — Medio${NC}"
    elif [[ $score -gt 0  ]]; then echo -e "${GREEN}${score}/100 — Bajo${NC}"
    else                           echo -e "${GRAY}0/100 — Sin hallazgos${NC}"
    fi
}

# ejemplo-legal.cl → Ejemplo Legal | estudio-ejemplo.com → Estudio Ejemplo
domain_to_name() {
    local domain="$1"
    domain="${domain#https://}"; domain="${domain#http://}"; domain="${domain%%/*}"
    local base="${domain%.*}"
    base="${base//-/ }"
    python3 -c "import sys; print(' '.join(w.capitalize() for w in sys.argv[1].split()))" "$base"
}

_open_pdf() {
    local FILE="$1"
    if grep -qi microsoft /proc/version 2>/dev/null; then
        explorer.exe "$(wslpath -w "${FILE}")"
    elif command -v xdg-open &>/dev/null; then
        xdg-open "${FILE}" &
    fi
}

_db_update() {
    local DOMINIO="$1" NOMBRE="$2" TIPO="$3" RUTA_PDF="$4" SCORE="${5:-null}"
    python3 - <<PYEOF
import json, sys
from pathlib import Path
from datetime import datetime

db_path = Path("${DB_FILE}")
db = json.loads(db_path.read_text()) if db_path.exists() else {"version": 1, "prospectos": {}}

d = db["prospectos"].setdefault("${DOMINIO}", {
    "nombre": "${NOMBRE}",
    "flash_fecha": None, "flash_pdf": None,
    "diagnostico_pdf": None,
    "flash_ciber_pdf": None, "diagnostico_ciber_pdf": None,
    "trabajo_fecha": None, "trabajo_pdf": None,
    "score_captacion": None,
    "estado": "nuevo"
})

d["nombre"] = "${NOMBRE}"
now = datetime.now().isoformat(timespec="seconds")

if "${TIPO}" == "flash_pdf":
    d["flash_fecha"] = now
    d["flash_pdf"] = "${RUTA_PDF}"
    d["estado"] = "flash_listo"
elif "${TIPO}" == "diagnostico_pdf":
    d["diagnostico_pdf"] = "${RUTA_PDF}"
elif "${TIPO}" == "flash_ciber_pdf":
    d["flash_ciber_pdf"] = "${RUTA_PDF}"
elif "${TIPO}" == "diagnostico_ciber_pdf":
    d["diagnostico_ciber_pdf"] = "${RUTA_PDF}"
elif "${TIPO}" == "trabajo_pdf":
    d["trabajo_fecha"] = now
    d["trabajo_pdf"] = "${RUTA_PDF}"
    d["estado"] = "trabajo_entregado"

if "${SCORE}" != "null":
    d["score_captacion"] = int("${SCORE}")

db_path.parent.mkdir(parents=True, exist_ok=True)
db_path.write_text(json.dumps(db, ensure_ascii=False, indent=2))
print(f"[✓] DB actualizada: ${DOMINIO} → ${TIPO}")
PYEOF
}

# _db_update_scan — registra scan_data + session_folder tras un escaneo Flash.
# A diferencia de _db_update, NO toca flash_pdf/diagnostico_pdf: el PDF se
# genera bajo demanda cuando el prospecto responde (scripts/enviar_flash.py).
_db_update_scan() {
    local DOMINIO="$1" NOMBRE="$2" FLASH_JSON="$3" SESSION_FOLDER="$4"
    python3 - "${DB_FILE}" "${DOMINIO}" "${NOMBRE}" "${FLASH_JSON}" "${SESSION_FOLDER}" <<'PYEOF'
import json, sys
from pathlib import Path
from datetime import datetime

db_path        = Path(sys.argv[1])
dominio        = sys.argv[2]
nombre         = sys.argv[3]
flash_json     = Path(sys.argv[4])
session_folder = sys.argv[5]

db = json.loads(db_path.read_text()) if db_path.exists() else {"version": 1, "prospectos": {}}

d = db["prospectos"].setdefault(dominio, {
    "nombre": nombre,
    "flash_fecha": None, "flash_pdf": None,
    "diagnostico_pdf": None,
    "flash_ciber_pdf": None, "diagnostico_ciber_pdf": None,
    "trabajo_fecha": None, "trabajo_pdf": None,
    "score_captacion": None,
    "estado": "nuevo",
})

d["nombre"] = nombre
d["flash_fecha"] = datetime.now().isoformat(timespec="seconds")

sev_rank = {"critical": 0, "high": 1, "medium": 2, "low": 3, "info": 4}
try:
    flash = json.loads(flash_json.read_text())
    es = flash.get("executive_summary", {}) or {}
    by_sev = es.get("findings_by_severity", {}) or {}
    findings = flash.get("findings", []) or []
    ordered = sorted(findings, key=lambda f: (
        f.get("severity_priority", sev_rank.get(f.get("severity"), 99)),
        str(f.get("id", "")),
    ))
    top = [
        {"id": f.get("id"), "name": f.get("name"),
         "severity": f.get("severity"), "category": f.get("category")}
        for f in ordered[:3]
    ]
    rec = es.get("key_recommendation")
    if isinstance(rec, str):
        rec = rec[:150]
    scan = {
        "risk_score": es.get("risk_score"),
        "risk_level": es.get("risk_level"),
        "total_findings": es.get("total_findings"),
        "high_findings": by_sev.get("high"),
        "medium_findings": by_sev.get("medium"),
        "email_security_status": es.get("email_security_status"),
        "key_recommendation": rec,
        "top_findings": top,
        "session_folder": session_folder,
    }
    d["scan_data"] = scan
    if scan["risk_score"] is not None:
        d["score_captacion"] = scan["risk_score"]
except Exception as e:
    # Si falla la extracción, al menos persiste session_folder
    d.setdefault("scan_data", {})["session_folder"] = session_folder
    print(f"[!] No se pudo extraer scan_data completo de {flash_json.name}: {e}")

if d.get("estado") in (None, "nuevo"):
    d["estado"] = "flash_listo"

db_path.parent.mkdir(parents=True, exist_ok=True)
db_path.write_text(json.dumps(db, ensure_ascii=False, indent=2))
print(f"[✓] DB actualizada: {dominio} → scan_data + session_folder")
PYEOF
}

# =============================================================================
# MODO 0: PROSPECTOS — scraping multi-fuente de PYMES chilenas
# =============================================================================
# =============================================================================
# MODO 0.5: ENRIQUECER — OpenClaw Orchestrator (Ollama + Crawl4AI)
# =============================================================================
cmd_prospectos_enriquecer() {
    header "Fase 0.5 · Enriquecimiento de prospectos — OpenClaw"

    local OPENCLAW_DIR="${SCRIPT_DIR}/openclaw"
    if [[ ! -f "${OPENCLAW_DIR}/run_batch.py" ]]; then
        error "No se encontró openclaw/run_batch.py"
        echo -e "  El módulo openclaw_orchestrator no está instalado."
        exit 1
    fi
    if ! check_dep "python3" ""; then exit 1; fi

    # ── Detección de entorno: Fedora (SELinux, :z) vs WSL2 (sudo docker) ──────
    local DOCKER_BIN="${DOCKER_BIN:-}"
    local ZFLAG ENTORNO
    if grep -qiE '(microsoft|wsl)' /proc/version 2>/dev/null; then
        ZFLAG=""
        DOCKER_BIN="${DOCKER_BIN:-sudo docker}"
        ENTORNO="WSL2"
    else
        ZFLAG=":z"
        DOCKER_BIN="${DOCKER_BIN:-docker}"
        ENTORNO="Fedora/Linux"
    fi
    local RO_OPT="ro${ZFLAG:+,z}"
    local OLLAMA_HOST_URL="${OLLAMA_HOST:-http://localhost:11434}"

    # ── Localizar el JSON de Google Places ───────────────────────────────────
    local INPUT="${1:-}"
    if [[ -z "${INPUT}" ]]; then
        INPUT=$(ls -t "${TARGETS_DIR}"/google_places*.json \
                       "${REPORTES_DIR}"/google_places*.json 2>/dev/null | head -1 || echo "")
    fi
    if [[ -z "${INPUT}" || ! -f "${INPUT}" ]]; then
        error "No se encontró un JSON de Google Places."
        echo -e "  Uso: ${GRAY}./sins.sh prospectos enriquecer <ruta/google_places.json>${NC}"
        exit 1
    fi
    INPUT="$(cd "$(dirname "${INPUT}")" && pwd)/$(basename "${INPUT}")"

    mkdir -p "${REPORTES_DIR}"
    local TS OUT_NAME OUT_HOST
    TS="$(date +%Y%m%d_%H%M%S)"
    OUT_NAME="prospectos_enriquecidos_${TS}.json"
    OUT_HOST="${REPORTES_DIR}/${OUT_NAME}"

    info "Entorno:  ${GRAY}${ENTORNO}${NC}"
    info "Entrada:  ${GRAY}${INPUT}${NC}"
    info "Salida:   ${GRAY}${OUT_HOST}${NC}"
    info "Ollama:   ${GRAY}${OLLAMA_HOST_URL}${NC}"
    echo ""

    # ── Ejecutar: preferir el contenedor (trae Crawl4AI + cliente Ollama) ─────
    if command -v "${DOCKER_BIN%% *}" &>/dev/null \
       && ${DOCKER_BIN} info &>/dev/null \
       && ${DOCKER_BIN} image inspect "${CONTAINER_NAME}" &>/dev/null; then
        info "Ejecutando dentro del contenedor ${GRAY}${CONTAINER_NAME}${NC}..."
        ${DOCKER_BIN} run --rm \
            --network host \
            -e OLLAMA_HOST="${OLLAMA_HOST_URL}" \
            -v "${OPENCLAW_DIR}:/home/work/openclaw${ZFLAG}" \
            -v "${INPUT}:/home/work/input/places.json:${RO_OPT}" \
            -v "${REPORTES_DIR}:/home/work/results${ZFLAG}" \
            -v "${SCRIPT_DIR}/db:/home/work/db${ZFLAG}" \
            "${CONTAINER_NAME}" \
            python3 /home/work/openclaw/run_batch.py \
                --config /home/work/openclaw/config.json \
                --input  /home/work/input/places.json \
                --output "/home/work/results/${OUT_NAME}"
    else
        warn "Imagen Docker no disponible — usando el Python del host."
        warn "Requiere: ${GRAY}pip install -r openclaw/requirements.txt${NC}"
        OLLAMA_HOST="${OLLAMA_HOST_URL}" python3 "${OPENCLAW_DIR}/run_batch.py" \
            --config "${OPENCLAW_DIR}/config.json" \
            --input  "${INPUT}" \
            --output "${OUT_HOST}"
    fi

    echo ""
    if [[ -s "${OUT_HOST}" ]]; then
        log "Prospectos enriquecidos en: ${GRAY}${OUT_HOST}${NC}"
    else
        error "No se generó el archivo de salida."
        exit 1
    fi
}

# =============================================================================
# MODO 1: CAPTACIÓN — califica prospectos rápido (sin Docker)
# =============================================================================
cmd_captacion() {
    header "Fase 1 · Captación de prospectos"

    # Verificar checkdmarc instalado
    if ! check_dep "checkdmarc" "pip install checkdmarc --break-system-packages"; then
        exit 1
    fi
    if ! check_dep "python3" ""; then exit 1; fi

    mkdir -p "$(dirname "${PROSPECTOS_FILE}")"
    mkdir -p "${REPORTES_DIR}"

    step "¿Cómo quieres ingresar los dominios?"
    echo "  1) Un solo dominio (escribirlo ahora)"
    echo "  2) Lista desde archivo  [${PROSPECTOS_FILE}]"
    echo "  3) Escribir varios ahora (uno por línea, línea vacía para terminar)"
    echo ""
    ask "Opción [1/2/3]:"
    read -r opcion

    declare -a DOMINIOS=()

    case "$opcion" in
        1)
            ask "Dominio a analizar (ej: estudiojuridico.cl):"
            read -r dom
            dom="${dom#https://}"; dom="${dom#http://}"; dom="${dom%%/*}"
            DOMINIOS=("$dom")
            ;;
        2)
            if [[ ! -f "${PROSPECTOS_FILE}" ]]; then
                error "No existe ${PROSPECTOS_FILE}"
                info  "Crea el archivo con un dominio por línea y vuelve a correr."
                exit 1
            fi
            mapfile -t DOMINIOS < <(grep -v '^\s*#' "${PROSPECTOS_FILE}" | grep -v '^\s*$')
            info "Se analizarán ${#DOMINIOS[@]} dominios desde el archivo."
            ;;
        3)
            ask "Ingresa dominios (uno por línea, Enter en blanco para terminar):"
            while true; do
                read -r dom
                [[ -z "$dom" ]] && break
                dom="${dom#https://}"; dom="${dom#http://}"; dom="${dom%%/*}"
                DOMINIOS+=("$dom")
            done
            ;;
        *)
            error "Opción inválida."; exit 1 ;;
    esac

    if [[ ${#DOMINIOS[@]} -eq 0 ]]; then
        error "No se ingresaron dominios."; exit 1
    fi

    # Filtrar dominios ya registrados en DB
    if [[ -f "${DB_FILE}" ]]; then
        YA_EN_DB=$(python3 - <<PYEOF
import json
from pathlib import Path
try:
    db = json.loads(Path("${DB_FILE}").read_text())
    print("\n".join(db.get("prospectos", {}).keys()))
except Exception:
    pass
PYEOF
        )
        if [[ -n "$YA_EN_DB" ]]; then
            declare -a _DOM_NUEVOS=()
            for _d in "${DOMINIOS[@]}"; do
                if echo "$YA_EN_DB" | grep -qx "$_d"; then
                    warn "Ignorando '${_d}' — ya existe en DB"
                else
                    _DOM_NUEVOS+=("$_d")
                fi
            done
            DOMINIOS=("${_DOM_NUEVOS[@]+"${_DOM_NUEVOS[@]}"}")
            [[ ${#DOMINIOS[@]} -eq 0 ]] && { warn "Todos los dominios ya están en DB."; exit 0; }
        fi
    fi

    step "Analizando ${#DOMINIOS[@]} dominio(s)..."
    echo ""

    # Archivo de resultados de sesión
    SESSION_DATE=$(date +"%Y%m%d_%H%M%S")
    RESULTS_FILE="${REPORTES_DIR}/captacion_${SESSION_DATE}.txt"
    CALIENTES_FILE="${REPORTES_DIR}/prospectos_calientes_${SESSION_DATE}.txt"

    declare -a CALIENTES=()
    declare -a TODOS=()

    for dominio in "${DOMINIOS[@]}"; do
        echo -e "${WHITE}▸ ${dominio}${NC}"

        # Correr checkdmarc y capturar JSON
        RAW=$(checkdmarc "$dominio" --output-format json 2>/dev/null || echo '{}')

        # Parsear con Python inline
        RESULTADO=$(python3 - <<PYEOF
import json, sys

raw = '''${RAW}'''
try:
    data = json.loads(raw)
except:
    data = {}

score = 0
issues = []

# SPF
spf = data.get('spf', {})
if not spf.get('valid', False):
    score += 35
    issues.append('SPF inválido o ausente')
elif '-all' not in spf.get('record', ''):
    score += 20
    issues.append('SPF con softfail (~all)')

# DMARC
dmarc = data.get('dmarc', {})
if not dmarc.get('valid', False):
    score += 45
    issues.append('DMARC ausente')
else:
    policy = dmarc.get('tags', {}).get('p', {}).get('value', 'none')
    if policy == 'none':
        score += 30
        issues.append('DMARC p=none (sin efecto)')
    elif policy == 'quarantine':
        score += 15
        issues.append('DMARC p=quarantine (incompleto)')

score = min(score, 100)

caliente = score >= 50
print(f"SCORE:{score}")
print(f"CALIENTE:{'SI' if caliente else 'NO'}")
print(f"ISSUES:{' | '.join(issues) if issues else 'Ninguno relevante'}")
PYEOF
        )

        SCORE=$(echo "$RESULTADO" | grep "SCORE:" | cut -d: -f2)
        CALIENTE=$(echo "$RESULTADO" | grep "CALIENTE:" | cut -d: -f2)
        ISSUES=$(echo "$RESULTADO" | grep "ISSUES:" | cut -d: -f2-)

        # Mostrar resultado
        printf "  Puntaje:  "; score_color "${SCORE:-0}"
        echo -e "  Problemas: ${GRAY}${ISSUES}${NC}"

        if [[ "$CALIENTE" == "SI" ]]; then
            echo -e "  Estado:   ${BRED}● PROSPECTO CALIENTE — enviar informe flash${NC}"
            CALIENTES+=("$dominio")
        else
            echo -e "  Estado:   ${GREEN}● Descartado — buena configuración${NC}"
        fi
        echo ""

        TODOS+=("${SCORE}|${CALIENTE}|${dominio}|${ISSUES}")
    done

    # ── RESUMEN ──────────────────────────────────────────────────────────────
    step "Resumen de sesión"

    echo -e "  Dominios analizados : ${WHITE}${#DOMINIOS[@]}${NC}"
    echo -e "  Prospectos calientes: ${BRED}${#CALIENTES[@]}${NC}"
    echo -e "  Descartados         : ${GREEN}$(( ${#DOMINIOS[@]} - ${#CALIENTES[@]} ))${NC}"
    echo ""

    # Guardar resultados
    {
        echo "# S.I.N.S. — Resultados de captación ${SESSION_DATE}"
        echo "# Formato: SCORE | CALIENTE | DOMINIO | PROBLEMAS"
        for r in "${TODOS[@]}"; do echo "$r"; done
    } > "${RESULTS_FILE}"

    if [[ ${#CALIENTES[@]} -gt 0 ]]; then
        printf '%s\n' "${CALIENTES[@]}" > "${CALIENTES_FILE}"
        echo -e "${BGREEN}Prospectos calientes guardados en:${NC}"
        echo -e "  ${GRAY}${CALIENTES_FILE}${NC}"
        echo ""

        ask "¿Generar informe flash ahora para el primer prospecto caliente? [s/N]"
        read -r resp
        if [[ "${resp,,}" == "s" ]]; then
            PRIMER="${CALIENTES[0]}"
            ask "Nombre del cliente para '${PRIMER}' (ej: Estudio Jurídico González):"
            read -r nombre_cliente
            _run_flash "$PRIMER" "$nombre_cliente"
        else
            info "Cuando quieras el flash, ejecuta:"
            echo -e "  ${GRAY}./sins.sh flash${NC}"
        fi
    else
        warn "Ningún prospecto caliente en esta sesión. Busca más dominios."
    fi

    echo ""
    log "Resultados completos guardados en: ${GRAY}${RESULTS_FILE}${NC}"
}

# =============================================================================
# MODO 2: FLASH — informe flash completo con Docker
# =============================================================================
cmd_flash() {
    header "Fase 1 · Informe Flash (con Docker)"

    check_docker_running
    check_container_built

    # ── Flag --ciber: informes con marco Ley 21.663 (Ley Marco de Ciberseguridad) ─
    # ./sins.sh flash --ciber dominio.cl  → 2 PDF orientados a proveedores de
    # operadores de servicios esenciales (en vez del marco Ley 21.719 por defecto).
    local FRAMEWORK="datos"
    local -a _FARGS=()
    for _a in "$@"; do
        case "$_a" in
            --ciber) FRAMEWORK="ciber" ;;
            *)       _FARGS+=("$_a") ;;
        esac
    done
    set -- "${_FARGS[@]+"${_FARGS[@]}"}"

    # ── Modo directo (no-interactivo) ─────────────────────────────────────────
    # ./sins.sh flash dominio.cl "Nombre Empresa"  → salta el menú de calientes
    if [[ -n "${1:-}" ]]; then
        _run_flash "$1" "${2:-$1}" "$FRAMEWORK"
        return
    fi

    # ── INPUT ─────────────────────────────────────────────────────────────────
    step "Datos del prospecto"

    # ¿Hay calientes del día?
    LATEST_CALIENTES=$(ls -t "${REPORTES_DIR}"/prospectos_calientes_*.txt 2>/dev/null | head -1 || echo "")

    if [[ -n "$LATEST_CALIENTES" ]]; then
        info "Prospectos calientes disponibles:"
        # Excluir dominios ya procesados (estado flash_listo o descartado en DB)
        mapfile -t LISTA < <(python3 - "$LATEST_CALIENTES" <<PYEOF
import json, sys
from pathlib import Path
excluidos = set()
try:
    db = json.loads(Path("${DB_FILE}").read_text())
    for dom, info in db.get("prospectos", {}).items():
        if info.get("estado") in ("flash_listo", "descartado"):
            excluidos.add(dom)
except Exception:
    pass
for line in Path(sys.argv[1]).read_text().splitlines():
    dom = line.strip()
    if dom and dom not in excluidos:
        print(dom)
PYEOF
        )
        for i in "${!LISTA[@]}"; do
            echo "  $((i+1))) ${LISTA[$i]}"
        done
        echo "  m) Ingresar manualmente"
        echo ""
        ask "Elige [número o m]:"
        read -r sel

        if [[ "$sel" == "m" ]] || [[ -z "$sel" ]]; then
            ask "Dominio:"
            read -r DOMINIO
        elif [[ "$sel" =~ ^[0-9]+$ ]] && [[ "$sel" -le "${#LISTA[@]}" ]]; then
            DOMINIO="${LISTA[$((sel-1))]}"
        else
            ask "Dominio:"
            read -r DOMINIO
        fi
    else
        ask "Dominio del prospecto (ej: estudiojuridico.cl):"
        read -r DOMINIO
    fi

    DOMINIO="${DOMINIO#https://}"; DOMINIO="${DOMINIO#http://}"; DOMINIO="${DOMINIO%%/*}"

    ask "Nombre del cliente (ej: Estudio Jurídico González Ltda.):"
    read -r CLIENTE

    echo ""
    info "Dominio : ${WHITE}${DOMINIO}${NC}"
    info "Cliente : ${WHITE}${CLIENTE}${NC}"
    echo ""
    ask "¿Confirmar y ejecutar? [s/N]"
    read -r confirm
    [[ "${confirm,,}" != "s" ]] && { warn "Cancelado."; exit 0; }

    _run_flash "$DOMINIO" "$CLIENTE" "$FRAMEWORK"
}

_run_flash() {
    local DOMINIO="$1"
    local CLIENTE="$2"
    local FRAMEWORK="${3:-datos}"
    local TIMESTAMP; TIMESTAMP=$(date +"%Y%m%d_%H%M%S")
    local SAFE_DOM="${DOMINIO//./_}"
    local SESSION_DIR="${REPORTES_DIR}/${SAFE_DOM}_${TIMESTAMP}"

    # ── Variantes según el marco legal del informe ───────────────────────────
    # datos → Ley 21.719 (Protección de Datos)  ·  ciber → Ley 21.663 (Ciberseguridad)
    local FW_LABEL DB_FLASH_KEY DB_DIAG_KEY FLASH_BASE DIAG_BASE
    local JSON_FLASH JSON_DIAG COMMIT_MSG
    if [[ "${FRAMEWORK}" == "ciber" ]]; then
        FW_LABEL="Ley 21.663 — Ley Marco de Ciberseguridad"
        DB_FLASH_KEY="flash_ciber_pdf";  DB_DIAG_KEY="diagnostico_ciber_pdf"
        FLASH_BASE="SINS_Flash_Ciber";   DIAG_BASE="SINS_Diagnostico_Ciber"
        JSON_FLASH="flash_ciber_${SAFE_DOM}.json"
        JSON_DIAG="diagnostico_ciber_${SAFE_DOM}.json"
        COMMIT_MSG="db: flash ciber ${DOMINIO}"
    else
        FW_LABEL="Ley 21.719 — Protección de Datos Personales"
        DB_FLASH_KEY="flash_pdf";  DB_DIAG_KEY="diagnostico_pdf"
        FLASH_BASE="SINS_Flash";   DIAG_BASE="SINS_Diagnostico"
        JSON_FLASH="flash_${SAFE_DOM}.json"
        JSON_DIAG="diagnostico_${SAFE_DOM}.json"
        COMMIT_MSG="db: flash ${DOMINIO}"
    fi

    mkdir -p "${SESSION_DIR}"/{subdomains,email,nuclei,technologies,http}

    step "Ejecutando escaneo OSINT en Docker (~15 min)"
    info "Puedes seguir el progreso en tiempo real abajo ↓"
    echo ""

    docker run --rm \
        --user $(id -u):$(id -g) \
        --name "sins_flash_${SAFE_DOM}" \
        --env-file "${SCRIPT_DIR}/.env" \
        --network bridge \
        -v "${REPORTES_DIR}:/home/work/results:z" \
        -v "${SCRIPT_DIR}/config:/root/.config/subfinder:z" \
        -v "${SCRIPT_DIR}/scripts:/home/work/scripts:ro,z" \
        "${CONTAINER_NAME}" \
        bash /home/work/scripts/audit.sh "${DOMINIO}" "/home/work/results/${SAFE_DOM}_${TIMESTAMP}" 2>&1 | \
        grep -E "^\[|subfinder|httpx|checkdmarc|whatweb|nuclei|encontró|Total|✓" || true

    echo ""

    local AUDIT_DIR="${SESSION_DIR}"
    local NUCLEI_JSON DMARC_JSON TECH_JSON
    NUCLEI_JSON=$(find "${AUDIT_DIR}" -name "nuclei_${DOMINIO}.json"     2>/dev/null | head -1 || echo "")
    DMARC_JSON=$(find  "${AUDIT_DIR}" -name "checkdmarc_${DOMINIO}.json" 2>/dev/null | head -1 || echo "")
    TECH_JSON=$(find   "${AUDIT_DIR}" -name "whatweb_${DOMINIO}.json"    2>/dev/null | head -1 || echo "")

    # Argumentos comunes a ambos informes
    local -a COMMON_ARGS=("--client" "${CLIENTE}" "--domain" "${DOMINIO}")
    if [[ -n "$NUCLEI_JSON" ]]; then
        COMMON_ARGS+=("--input" "${NUCLEI_JSON}")
    else
        echo "" > /tmp/empty.jsonl
        COMMON_ARGS+=("--input" "/tmp/empty.jsonl")
    fi
    [[ -n "$DMARC_JSON" ]] && COMMON_ARGS+=("--dmarc" "${DMARC_JSON}")
    [[ -n "$TECH_JSON"  ]] && COMMON_ARGS+=("--tech"  "${TECH_JSON}")

    # ── Flash JSON ────────────────────────────────────────────────────────────
    # El PDF NO se genera aquí — se produce bajo demanda cuando el prospecto
    # responde (scripts/enviar_flash.py lo arma desde este JSON).
    step "Generando JSON Flash (${FW_LABEL})"
    local FLASH_JSON="${AUDIT_DIR}/${JSON_FLASH}"

    python3 "${SCRIPT_DIR}/scripts/nuclei_to_report.py" "${COMMON_ARGS[@]}" \
        --report-type "flash" \
        --framework   "${FRAMEWORK}" \
        --output "${FLASH_JSON}"

    # ── Diagnóstico JSON ──────────────────────────────────────────────────────
    step "Generando JSON Diagnóstico (${FW_LABEL})"
    local DIAG_JSON="${AUDIT_DIR}/${JSON_DIAG}"

    python3 "${SCRIPT_DIR}/scripts/nuclei_to_report.py" "${COMMON_ARGS[@]}" \
        --report-type "diagnostico" \
        --framework   "${FRAMEWORK}" \
        --output "${DIAG_JSON}"

    # Registrar scan_data + session_folder en la DB (sin PDFs)
    _db_update_scan "${DOMINIO}" "${CLIENTE}" "${FLASH_JSON}" "$(basename "${SESSION_DIR}")"


    # ── RESULTADO ─────────────────────────────────────────────────────────────
    echo ""
    echo -e "${RED}┌─────────────────────────────────────────────────────────┐${NC}"
    echo -e "${RED}│${NC}  ${BGREEN}✓ Escaneo completado — JSONs listos${NC}                     ${RED}│${NC}"
    echo -e "${RED}│${NC}  ${GRAY}${CLIENTE}${NC}"
    echo -e "${RED}│${NC}  ${GRAY}Marco: ${FW_LABEL}${NC}"
    echo -e "${RED}├─────────────────────────────────────────────────────────┤${NC}"
    echo -e "${RED}│${NC}  Flash JSON      : ${GRAY}$(basename "${FLASH_JSON}")${NC}"
    echo -e "${RED}│${NC}  Diagnóstico JSON: ${GRAY}$(basename "${DIAG_JSON}")${NC}"
    echo -e "${RED}├─────────────────────────────────────────────────────────┤${NC}"
    echo -e "${RED}│${NC}  Dir: ${GRAY}${AUDIT_DIR}${NC}"
    echo -e "${RED}└─────────────────────────────────────────────────────────┘${NC}"
    echo ""

    info "PDF se generará cuando el prospecto responda."
    info "Desde la webapp: [ENVIAR FLASH] en DATA_ASSETS."
    info "Desde la CLI:    python3 scripts/enviar_flash.py --dominio ${DOMINIO}"
}

# =============================================================================
# MODO 2b: DIAGNÓSTICO — regenera PDF desde sesión existente (sin nuevo escaneo)
# =============================================================================
cmd_diagnostico() {
    header "Diagnóstico · Regenerar desde sesión existente"

    if ! check_dep "python3" ""; then exit 1; fi

    step "Dominio a regenerar"
    ask "Dominio (ej: empresa-ejemplo.cl):"
    read -r DOMINIO
    DOMINIO="${DOMINIO#https://}"; DOMINIO="${DOMINIO#http://}"; DOMINIO="${DOMINIO%%/*}"

    local SAFE_DOM="${DOMINIO//./_}"

    # Buscar sesión más reciente para este dominio
    local SESSION_DIR
    SESSION_DIR=$(ls -td "${REPORTES_DIR}/${SAFE_DOM}_"* 2>/dev/null | head -1 || echo "")

    if [[ -z "$SESSION_DIR" ]] || [[ ! -d "$SESSION_DIR" ]]; then
        error "No se encontró sesión previa para '${DOMINIO}' en ${REPORTES_DIR}/"
        info "Genera un escaneo primero con: ${GRAY}./sins.sh flash${NC}"
        exit 1
    fi

    info "Sesión: ${GRAY}${SESSION_DIR}${NC}"
    echo ""

    # Detectar nombre del cliente desde JSON existente
    local EXISTING_JSON CLIENTE
    EXISTING_JSON=$(find "${SESSION_DIR}" \
        \( -name "flash_${SAFE_DOM}.json" -o -name "diagnostico_${SAFE_DOM}.json" \) \
        2>/dev/null | head -1 || echo "")
    CLIENTE=""
    if [[ -n "$EXISTING_JSON" ]]; then
        CLIENTE=$(python3 -c "
import json, sys
try:
    d = json.load(open('${EXISTING_JSON}'))
    c = d.get('client', {})
    print(c.get('name', '') if isinstance(c, dict) else str(c))
except: pass
" 2>/dev/null || echo "")
    fi

    if [[ -n "$CLIENTE" ]]; then
        info "Cliente detectado: ${WHITE}${CLIENTE}${NC}"
        ask "¿Usar este nombre? [S/n]"
        read -r use_it
        if [[ "${use_it,,}" == "n" ]]; then
            ask "Nombre del cliente:"
            read -r CLIENTE
        fi
    else
        ask "Nombre del cliente (ej: Estudio Jurídico González Ltda.):"
        read -r CLIENTE
    fi

    echo ""
    info "Dominio : ${WHITE}${DOMINIO}${NC}"
    info "Cliente : ${WHITE}${CLIENTE}${NC}"
    echo ""
    ask "¿Regenerar PDF de diagnóstico sin nuevo escaneo? [s/N]"
    read -r confirm
    [[ "${confirm,,}" != "s" ]] && { warn "Cancelado."; exit 0; }

    _regen_diagnostico "${DOMINIO}" "${CLIENTE}" "${SESSION_DIR}"
}

_regen_diagnostico() {
    local DOMINIO="$1"
    local CLIENTE="$2"
    local SESSION_DIR="$3"
    local SAFE_DOM="${DOMINIO//./_}"
    local TIMESTAMP; TIMESTAMP=$(date +"%Y%m%d_%H%M%S")

    local NUCLEI_JSON DMARC_JSON TECH_JSON
    NUCLEI_JSON=$(find "${SESSION_DIR}" -name "nuclei_${DOMINIO}.json"     2>/dev/null | head -1 || echo "")
    DMARC_JSON=$(find  "${SESSION_DIR}" -name "checkdmarc_${DOMINIO}.json" 2>/dev/null | head -1 || echo "")
    TECH_JSON=$(find   "${SESSION_DIR}" -name "whatweb_${DOMINIO}.json"    2>/dev/null | head -1 || echo "")

    local DIAG_JSON="${SESSION_DIR}/diagnostico_${SAFE_DOM}.json"
    local DIAG_PDF="${SESSION_DIR}/SINS_Diagnostico_${SAFE_DOM}_${TIMESTAMP}.pdf"

    step "Regenerando diagnóstico de impacto PDF (sin nuevo escaneo)"

    local -a ARGS=("--client" "${CLIENTE}" "--domain" "${DOMINIO}" \
                   "--output" "${DIAG_JSON}" "--report-type" "diagnostico")
    if [[ -n "$NUCLEI_JSON" ]]; then
        ARGS+=("--input" "${NUCLEI_JSON}")
    else
        echo "" > /tmp/empty_diag.jsonl
        ARGS+=("--input" "/tmp/empty_diag.jsonl")
    fi
    [[ -n "$DMARC_JSON" ]] && ARGS+=("--dmarc" "${DMARC_JSON}")
    [[ -n "$TECH_JSON"  ]] && ARGS+=("--tech"  "${TECH_JSON}")

    python3 "${SCRIPT_DIR}/scripts/nuclei_to_report.py" "${ARGS[@]}"
    python3 "${SCRIPT_DIR}/scripts/generate_pdf.py" \
        --input  "${DIAG_JSON}" \
        --output "${DIAG_PDF}"

    RESUMEN=$(python3 - <<PYEOF
import json
try:
    data = json.load(open('${DIAG_JSON}'))
    es = data.get('executive_summary', {})
    bi = data.get('business_impact', {})
    print(f"SCORE:{es.get('risk_score', 0)}")
    print(f"LEVEL:{es.get('risk_level', 'N/A')}")
    print(f"SCENARIOS:{len(bi.get('scenarios', []))}")
except Exception:
    print("SCORE:0\nLEVEL:N/A\nSCENARIOS:0")
PYEOF
    )

    R_SCORE=$(echo "$RESUMEN" | grep "SCORE:" | cut -d: -f2)
    R_LEVEL=$(echo "$RESUMEN" | grep "LEVEL:" | cut -d: -f2)
    R_SCEN=$(echo  "$RESUMEN" | grep "SCENARIOS:" | cut -d: -f2)

    echo ""
    echo -e "${RED}┌─────────────────────────────────────────────────────────┐${NC}"
    echo -e "${RED}│${NC}  ${BGREEN}✓ Diagnóstico regenerado (sin nuevo escaneo)${NC}           ${RED}│${NC}"
    echo -e "${RED}│${NC}  ${GRAY}${CLIENTE}${NC}"
    echo -e "${RED}│${NC}  Riesgo    : $(score_color "${R_SCORE:-0}") — ${R_LEVEL}"
    echo -e "${RED}│${NC}  Escenarios: ${WHITE}${R_SCEN:-0}${NC} de impacto en el negocio identificados"
    echo -e "${RED}├─────────────────────────────────────────────────────────┤${NC}"
    echo -e "${RED}│${NC}  PDF: ${GRAY}${DIAG_PDF}${NC}"
    echo -e "${RED}└─────────────────────────────────────────────────────────┘${NC}"
    echo ""

    ask "¿Abrir el PDF ahora? [s/N]"
    read -r abrir
    [[ "${abrir,,}" == "s" ]] && _open_pdf "${DIAG_PDF}"

    info "Diagnóstico listo para adjuntar a la propuesta comercial."
}

# =============================================================================
# MODO 3: TRABAJO — pipeline completo para cliente autorizado
# =============================================================================
cmd_trabajo() {
    header "Fase 2 · Trabajo Técnico (cliente autorizado)"

    check_docker_running
    check_container_built

    step "Datos del cliente"

    ask "Dominio del cliente (ej: empresa.cl):"
    read -r DOMINIO
    DOMINIO="${DOMINIO#https://}"; DOMINIO="${DOMINIO#http://}"; DOMINIO="${DOMINIO%%/*}"

    ask "Nombre del cliente (ej: Empresa Jurídica González Ltda.):"
    read -r CLIENTE

    ask "N° de autorización / referencia del contrato (ej: AUTH-2025-001):"
    read -r AUTH_REF

    echo ""
    warn "Este comando ejecuta un escaneo COMPLETO (~35 min)."
    warn "Solo proceder con autorización firmada del cliente."
    echo ""
    info "Dominio     : ${WHITE}${DOMINIO}${NC}"
    info "Cliente     : ${WHITE}${CLIENTE}${NC}"
    info "Autorización: ${WHITE}${AUTH_REF}${NC}"
    echo ""
    ask "¿Confirmar y ejecutar escaneo completo? [s/N]"
    read -r confirm
    [[ "${confirm,,}" != "s" ]] && { warn "Cancelado."; exit 0; }

    _run_trabajo "$DOMINIO" "$CLIENTE" "$AUTH_REF"
}

_run_trabajo() {
    local DOMINIO="$1"
    local CLIENTE="$2"
    local AUTH_REF="$3"
    local TIMESTAMP; TIMESTAMP=$(date +"%Y%m%d_%H%M%S")
    local SAFE_DOM="${DOMINIO//./_}"
    local SESSION_DIR="${REPORTES_DIR}/${SAFE_DOM}_${TIMESTAMP}"

    mkdir -p "${SESSION_DIR}"/{subdomains,email,nuclei,technologies,http}

    # Registrar autorización para trazabilidad
    {
        echo "# S.I.N.S. — Registro de autorización de escaneo"
        echo "Fecha       : $(date)"
        echo "Cliente     : ${CLIENTE}"
        echo "Dominio     : ${DOMINIO}"
        echo "Autorización: ${AUTH_REF}"
        echo "Operador    : $(whoami)@$(hostname)"
    } > "${SESSION_DIR}/autorizacion_${SAFE_DOM}.txt"
    log "Autorización registrada en: ${GRAY}${SESSION_DIR}/autorizacion_${SAFE_DOM}.txt${NC}"

    step "Ejecutando pipeline completo en Docker (~35 min)"
    info "Puedes seguir el progreso en tiempo real abajo ↓"
    echo ""

    docker run --rm \
        --user "$(id -u):$(id -g)" \
        --name "sins_trabajo_${SAFE_DOM}" \
        --env-file "${SCRIPT_DIR}/.env" \
        --network bridge \
        -v "${REPORTES_DIR}:/home/work/results:z" \
        -v "${SCRIPT_DIR}/config:/root/.config/subfinder:z" \
        -v "${SCRIPT_DIR}/scripts:/home/work/scripts:ro,z" \
        "${CONTAINER_NAME}" \
        bash /home/work/scripts/audit.sh "${DOMINIO}" "/home/work/results/${SAFE_DOM}_${TIMESTAMP}" --full

    echo ""
    step "Generando informe técnico PDF"

    AUDIT_DIR="${SESSION_DIR}"

    NUCLEI_JSON=$(find "${AUDIT_DIR}" -name "nuclei_${DOMINIO}.json"     2>/dev/null | head -1 || echo "")
    DMARC_JSON=$(find  "${AUDIT_DIR}" -name "checkdmarc_${DOMINIO}.json" 2>/dev/null | head -1 || echo "")
    TECH_JSON=$(find   "${AUDIT_DIR}" -name "whatweb_${DOMINIO}.json"    2>/dev/null | head -1 || echo "")
    NMAP_JSON=$(find   "${AUDIT_DIR}" -path "*/nmap/nmap_${DOMINIO}.json" 2>/dev/null | head -1 || echo "")

    INFORME_JSON="${AUDIT_DIR}/trabajo_${SAFE_DOM}.json"
    PDF_OUT="${AUDIT_DIR}/SINS_Trabajo_${SAFE_DOM}_${TIMESTAMP}.pdf"

    ARGS=("--client" "${CLIENTE}" "--domain" "${DOMINIO}" "--output" "${INFORME_JSON}")
    [[ -n "$NUCLEI_JSON" ]] && ARGS+=("--input" "${NUCLEI_JSON}") || {
        echo "" > /tmp/empty.jsonl
        ARGS+=("--input" "/tmp/empty.jsonl")
    }
    [[ -n "$DMARC_JSON" ]] && ARGS+=("--dmarc" "${DMARC_JSON}")
    [[ -n "$TECH_JSON"  ]] && ARGS+=("--tech"  "${TECH_JSON}")
    [[ -n "$NMAP_JSON"  ]] && ARGS+=("--nmap"  "${NMAP_JSON}")
    ARGS+=(--report-type trabajo)

    python3 "${SCRIPT_DIR}/scripts/nuclei_to_report.py" "${ARGS[@]}"
    python3 "${SCRIPT_DIR}/scripts/generate_pdf.py" \
        --input  "${INFORME_JSON}" \
        --output "${PDF_OUT}"

    local REL_TRABAJO="${DOMINIO}/$(basename "${PDF_OUT}")"
    _db_update "${DOMINIO}" "${CLIENTE}" "trabajo_pdf" "${REL_TRABAJO}"

    # Extraer resumen de hallazgos del JSON generado
    RESUMEN=$(python3 - <<PYEOF
import json, sys
try:
    data = json.load(open('${INFORME_JSON}'))
    es   = data.get('executive_summary', {})
    bsev = es.get('findings_by_severity', {})
    print(f"SCORE:{es.get('risk_score', 0)}")
    print(f"LEVEL:{es.get('risk_level', 'N/A')}")
    print(f"TOTAL:{es.get('total_findings', 0)}")
    print(f"CRIT:{bsev.get('critical', 0)}")
    print(f"HIGH:{bsev.get('high', 0)}")
    print(f"MED:{bsev.get('medium', 0)}")
    print(f"LOW:{bsev.get('low', 0)}")
except Exception as e:
    print("SCORE:0\nLEVEL:N/A\nTOTAL:0\nCRIT:0\nHIGH:0\nMED:0\nLOW:0")
PYEOF
    )

    R_SCORE=$(echo "$RESUMEN" | grep "SCORE:" | cut -d: -f2)
    R_LEVEL=$(echo "$RESUMEN" | grep "LEVEL:" | cut -d: -f2)
    R_TOTAL=$(echo "$RESUMEN" | grep "TOTAL:" | cut -d: -f2)
    R_CRIT=$(echo  "$RESUMEN" | grep "CRIT:"  | cut -d: -f2)
    R_HIGH=$(echo  "$RESUMEN" | grep "HIGH:"  | cut -d: -f2)
    R_MED=$(echo   "$RESUMEN" | grep "MED:"   | cut -d: -f2)
    R_LOW=$(echo   "$RESUMEN" | grep "LOW:"   | cut -d: -f2)

    echo ""
    echo -e "${RED}┌─────────────────────────────────────────────────────────┐${NC}"
    echo -e "${RED}│${NC}  ${BGREEN}✓ Informe técnico generado${NC}                             ${RED}│${NC}"
    echo -e "${RED}│${NC}  ${GRAY}${CLIENTE}${NC}"
    echo -e "${RED}│${NC}  ${GRAY}Autorización: ${AUTH_REF}${NC}"
    echo -e "${RED}├─────────────────────────────────────────────────────────┤${NC}"
    echo -e "${RED}│${NC}  Riesgo  : $(score_color "${R_SCORE:-0}") — ${R_LEVEL}"
    echo -e "${RED}│${NC}  Hallazgos: ${WHITE}${R_TOTAL:-0}${NC} total  ${BRED}Crítico:${R_CRIT:-0}${NC}  ${YELLOW}Alto:${R_HIGH:-0}${NC}  Medio:${R_MED:-0}  Bajo:${R_LOW:-0}"
    echo -e "${RED}├─────────────────────────────────────────────────────────┤${NC}"
    echo -e "${RED}│${NC}  PDF : ${GRAY}${PDF_OUT}${NC}"
    echo -e "${RED}│${NC}  JSON: ${GRAY}${INFORME_JSON}${NC}"
    echo -e "${RED}└─────────────────────────────────────────────────────────┘${NC}"
    echo ""

    ask "¿Abrir el PDF ahora? [s/N]"
    read -r abrir
    [[ "${abrir,,}" == "s" ]] && _open_pdf "${PDF_OUT}"

    info "Informe listo para entregar al cliente."
}

# =============================================================================
# MODO BATCH — procesar lista de prospectos calientes en paralelo
# =============================================================================
cmd_batch() {
    header "Batch · Prospectos calientes en paralelo"

    check_docker_running
    check_container_built

    # ── Parseo de flags opcionales ────────────────────────────────────────────
    local TARGET_FILE="" FLAG_WORKERS="" FLAG_CONFIRM=0 FLAG_AUTO_NAME=0
    while [[ $# -gt 0 ]]; do
        case "$1" in
            --workers)   FLAG_WORKERS="$2"; shift 2 ;;
            --workers=*) FLAG_WORKERS="${1#--workers=}"; shift ;;
            --confirm)   FLAG_CONFIRM=1; shift ;;
            --auto-name) FLAG_AUTO_NAME=1; shift ;;
            *)           [[ -z "$TARGET_FILE" ]] && TARGET_FILE="$1"; shift ;;
        esac
    done

    # ── Archivo de targets ────────────────────────────────────────────────────
    if [[ -z "$TARGET_FILE" ]]; then
        TARGET_FILE=$(ls -t "${TARGETS_DIR}"/prospectos_calientes_*.txt 2>/dev/null | head -1 || true)
    fi
    if [[ -z "$TARGET_FILE" ]]; then
        TARGET_FILE=$(ls -t "${REPORTES_DIR}"/prospectos_calientes_*.txt 2>/dev/null | head -1 || true)
    fi

    if [[ -z "$TARGET_FILE" ]] || [[ ! -f "$TARGET_FILE" ]]; then
        error "No se encontró lista de prospectos calientes."
        info "Genera una con: ${GRAY}./sins.sh captacion${NC}"
        info "O provee una ruta: ${GRAY}./sins.sh batch targets/mi_lista.txt${NC}"
        exit 1
    fi

    declare -a DOMINIOS=()
    mapfile -t DOMINIOS < <(grep -v '^\s*#' "$TARGET_FILE" | grep -v '^\s*$')
    local TOTAL="${#DOMINIOS[@]}"

    if [[ $TOTAL -eq 0 ]]; then
        error "El archivo '${TARGET_FILE}' no contiene dominios."
        exit 1
    fi

    info "Lista   : ${GRAY}${TARGET_FILE}${NC}"
    info "Dominios: ${WHITE}${TOTAL}${NC}"
    echo ""

    # ── Número de workers ────────────────────────────────────────────────────
    local N_WORKERS
    if [[ -n "$FLAG_WORKERS" ]]; then
        N_WORKERS="$FLAG_WORKERS"
    else
        ask "¿Cuántos workers en paralelo? [1-5, default 3]:"
        read -r N_WORKERS
        N_WORKERS="${N_WORKERS:-3}"
    fi
    if ! [[ "$N_WORKERS" =~ ^[0-9]+$ ]] || [[ $N_WORKERS -lt 1 ]]; then N_WORKERS=3; fi
    [[ $N_WORKERS -gt 5 ]] && N_WORKERS=5
    info "Workers : ${WHITE}${N_WORKERS}${NC}"
    echo ""

    # ── Modo de nombres ──────────────────────────────────────────────────────
    local modo_nombres
    if [[ $FLAG_AUTO_NAME -eq 1 || $FLAG_CONFIRM -eq 1 ]]; then
        modo_nombres="a"
    else
        echo "  a) Automático — derivar del dominio  (ejemplo-legal.cl → Ejemplo Legal)"
        echo "  m) Manual — pedir nombre por cada dominio"
        echo ""
        ask "Modo de nombres [a/m, default a]:"
        read -r modo_nombres
        modo_nombres="${modo_nombres:-a}"
        echo ""
    fi

    declare -a NOMBRES=()
    local auto_name nombre dom
    if [[ "${modo_nombres,,}" == "m" ]]; then
        step "Nombres de clientes"
        for dom in "${DOMINIOS[@]}"; do
            auto_name=$(domain_to_name "$dom")
            ask "Nombre para '${dom}' [Enter = ${auto_name}]:"
            read -r nombre
            NOMBRES+=("${nombre:-$auto_name}")
        done
        echo ""
    else
        for dom in "${DOMINIOS[@]}"; do
            NOMBRES+=("$(domain_to_name "$dom")")
        done
    fi

    # ── Confirmación inicial ──────────────────────────────────────────────────
    step "Plan de ejecución"
    local i
    for i in "${!DOMINIOS[@]}"; do
        printf "  %2d) %-40s → %s\n" "$((i+1))" "${DOMINIOS[$i]}" "${NOMBRES[$i]}"
    done
    echo ""
    info "Workers paralelos : ${WHITE}${N_WORKERS}${NC}"
    info "Total dominios    : ${WHITE}${TOTAL}${NC}"
    echo ""
    if [[ $FLAG_CONFIRM -eq 1 ]]; then
        info "Confirmación automática (--confirm)"
    else
        ask "¿Iniciar batch? [s/N]"
        read -r confirm
        [[ "${confirm,,}" != "s" ]] && { warn "Cancelado."; exit 0; }
    fi

    # ── Ejecución en paralelo ─────────────────────────────────────────────────
    local BATCH_TS; BATCH_TS=$(date +"%Y%m%d_%H%M%S")
    local BATCH_LOG_DIR="${REPORTES_DIR}/batch_${BATCH_TS}_logs"
    mkdir -p "$BATCH_LOG_DIR"

    export BATCH_MODE=1

    declare -a PIDS=()
    declare -a PID_IDX=()
    local completed=0 failed=0
    local -a np=() ni=()
    local j pid pidx ex d

    step "Ejecutando..."
    echo ""

    for i in "${!DOMINIOS[@]}"; do
        dom="${DOMINIOS[$i]}"
        nombre="${NOMBRES[$i]}"
        local num=$((i + 1))
        local safe="${dom//./_}"

        # Esperar slot libre
        while [[ ${#PIDS[@]} -ge $N_WORKERS ]]; do
            np=(); ni=()
            for j in "${!PIDS[@]}"; do
                pid="${PIDS[$j]}"; pidx="${PID_IDX[$j]}"
                if ! kill -0 "$pid" 2>/dev/null; then
                    ex=0; wait "$pid" 2>/dev/null || ex=$?
                    d="${DOMINIOS[$pidx]}"
                    if [[ $ex -eq 0 ]]; then
                        echo -e "${BGREEN}[✓ $((pidx+1))/${TOTAL}]${NC} ${WHITE}${d}${NC} — completado"
                        completed=$((completed + 1))
                    else
                        echo -e "${BRED}[✗ $((pidx+1))/${TOTAL}]${NC} ${WHITE}${d}${NC} — FALLÓ  (log: ${safe}.log)"
                        failed=$((failed + 1))
                    fi
                else
                    np+=("$pid"); ni+=("$pidx")
                fi
            done
            PIDS=(); [[ ${#np[@]} -gt 0 ]] && PIDS+=("${np[@]}")
            PID_IDX=(); [[ ${#ni[@]} -gt 0 ]] && PID_IDX+=("${ni[@]}")
            [[ ${#PIDS[@]} -ge $N_WORKERS ]] && sleep 2
        done

        # Lanzar job
        echo -e "${CYAN}[→ ${num}/${TOTAL}]${NC} ${WHITE}${dom}${NC} — iniciando..."
        ( _run_flash "$dom" "$nombre" ) > "${BATCH_LOG_DIR}/${safe}.log" 2>&1 &
        PIDS+=($!)
        PID_IDX+=($i)
    done

    # Esperar jobs restantes
    while [[ ${#PIDS[@]} -gt 0 ]]; do
        np=(); ni=()
        for j in "${!PIDS[@]}"; do
            pid="${PIDS[$j]}"; pidx="${PID_IDX[$j]}"
            if ! kill -0 "$pid" 2>/dev/null; then
                ex=0; wait "$pid" 2>/dev/null || ex=$?
                d="${DOMINIOS[$pidx]}"
                if [[ $ex -eq 0 ]]; then
                    echo -e "${BGREEN}[✓ $((pidx+1))/${TOTAL}]${NC} ${WHITE}${d}${NC} — completado"
                    completed=$((completed + 1))
                else
                    local fs="${d//./_}"
                    echo -e "${BRED}[✗ $((pidx+1))/${TOTAL}]${NC} ${WHITE}${d}${NC} — FALLÓ  (log: ${fs}.log)"
                    failed=$((failed + 1))
                fi
            else
                np+=("$pid"); ni+=("$pidx")
            fi
        done
        PIDS=(); [[ ${#np[@]} -gt 0 ]] && PIDS+=("${np[@]}")
        PID_IDX=(); [[ ${#ni[@]} -gt 0 ]] && PID_IDX+=("${ni[@]}")
        [[ ${#PIDS[@]} -gt 0 ]] && sleep 2
    done

    unset BATCH_MODE

    # ── Resumen ───────────────────────────────────────────────────────────────
    echo ""
    echo -e "${RED}┌─────────────────────────────────────────────────────────┐${NC}"
    echo -e "${RED}│${NC}  ${BGREEN}✓ Batch completado${NC}                                     ${RED}│${NC}"
    echo -e "${RED}├─────────────────────────────────────────────────────────┤${NC}"
    echo -e "${RED}│${NC}  Total       : ${WHITE}${TOTAL}${NC}"
    echo -e "${RED}│${NC}  Completados : ${BGREEN}${completed}${NC}"
    echo -e "${RED}│${NC}  Fallidos    : ${BRED}${failed}${NC}"
    echo -e "${RED}├─────────────────────────────────────────────────────────┤${NC}"
    echo -e "${RED}│${NC}  Logs        : ${GRAY}${BATCH_LOG_DIR}${NC}"
    echo -e "${RED}│${NC}  Reportes    : ${GRAY}${REPORTES_DIR}${NC}"
    echo -e "${RED}└─────────────────────────────────────────────────────────┘${NC}"
    echo ""
}

# =============================================================================
# AYUDA
# =============================================================================
cmd_help() {
    header "Ayuda"
    echo -e "  ${WHITE}./sins.sh prospectos${NC}"
    echo -e "  ${GRAY}Scraping multi-fuente de PYMES chilenas por categoría y ciudad.${NC}"
    echo -e "  ${GRAY}Fuentes: Páginas Amarillas + DuckDuckGo + Google Maps + Apollo.io${NC}"
    echo -e "  ${GRAY}Analiza DMARC/SPF/TLS y guarda calientes en targets/.${NC}"
    echo ""
    echo -e "  ${WHITE}./sins.sh prospectos enriquecer${NC}  ${GRAY}[ruta/google_places.json]${NC}"
    echo -e "  ${GRAY}Enriquece un JSON de Google Places con OpenClaw (3 agentes Ollama).${NC}"
    echo -e "  ${GRAY}Devuelve {empresa, dominio, cargo_objetivo, email, mensaje, confianza}.${NC}"
    echo ""
    echo -e "  ${WHITE}./sins.sh captacion${NC}"
    echo -e "  ${GRAY}Califica prospectos con checkdmarc (sin Docker).${NC}"
    echo -e "  ${GRAY}Identifica quién tiene DMARC/SPF mal configurado.${NC}"
    echo ""
    echo -e "  ${WHITE}./sins.sh flash${NC}  ${GRAY}[--ciber] [dominio] [\"Nombre\"]${NC}"
    echo -e "  ${GRAY}Genera Flash + Diagnóstico desde un escaneo Docker (~15 min).${NC}"
    echo -e "  ${GRAY}Produce SINS_Flash_*.pdf y SINS_Diagnostico_*.pdf en la misma sesión.${NC}"
    echo -e "  ${GRAY}--ciber: marco Ley 21.663 (Ciberseguridad) para proveedores de${NC}"
    echo -e "  ${GRAY}         operadores de servicios esenciales — SINS_*_Ciber_*.pdf.${NC}"
    echo ""
    echo -e "  ${WHITE}./sins.sh diagnostico${NC}"
    echo -e "  ${GRAY}Regenera solo el PDF de diagnóstico desde la sesión más reciente.${NC}"
    echo -e "  ${GRAY}Sin nuevo escaneo — útil para retoques o reenvíos sin costo adicional.${NC}"
    echo ""
    echo -e "  ${WHITE}./sins.sh trabajo${NC}"
    echo -e "  ${GRAY}Pipeline completo para cliente autorizado (~35 min).${NC}"
    echo -e "  ${GRAY}Requiere autorización firmada. Genera informe técnico PDF.${NC}"
    echo ""
    echo -e "  ${WHITE}./sins.sh batch${NC}  ${GRAY}[ruta/lista.txt]${NC}"
    echo -e "  ${GRAY}Procesa la lista de prospectos calientes en paralelo (hasta 5 workers).${NC}"
    echo -e "  ${GRAY}Lee el archivo más reciente de targets/ o acepta ruta como argumento.${NC}"
    echo -e "  ${GRAY}Genera Flash + Diagnóstico para cada dominio sin intervención manual.${NC}"
    echo ""
    echo -e "  ${WHITE}./sins.sh webapp${NC}"
    echo -e "  ${GRAY}Inicia la interfaz web Flask en http://0.0.0.0:5000${NC}"
    echo -e "  ${GRAY}Gestiona prospectos, lanza comandos y ve el output en tiempo real.${NC}"
    echo ""
    echo -e "  ${GRAY}Próximamente: ./sins.sh monitoreo${NC}"
    echo ""
}

# =============================================================================
# ENTRADA PRINCIPAL
# =============================================================================
case "${1:-help}" in
    prospectos)
        case "${2:-}" in
            enriquecer) cmd_prospectos_enriquecer "${@:3}" ;;
            *)
                error "Subcomando desconocido: 'prospectos ${2:-}'"
                echo -e "  Uso: ${GRAY}./sins.sh prospectos enriquecer [archivo]${NC}"
                exit 1 ;;
        esac ;;
    captacion)   cmd_captacion ;;
    flash)       cmd_flash "${@:2}" ;;
    diagnostico) cmd_diagnostico ;;
    trabajo)     cmd_trabajo ;;
    batch)       cmd_batch "${@:2}" ;;
    webapp)      bash "${SCRIPT_DIR}/webapp/run.sh" ;;
    help|--help|-h) cmd_help ;;
    *)
        error "Comando desconocido: '${1}'"
        echo ""
        cmd_help
        exit 1
        ;;
esac
