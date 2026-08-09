#!/usr/bin/env bash
# =============================================================================
# crowsnest.sh — CLI unificado de Crowsnest
# Uso:
#   ./crowsnest.sh targets enriquecer → enriquece targets con OpenClaw (LLM)
#   ./crowsnest.sh recon        → recon pasivo de targets (sin Docker, ~10 seg/dominio)
#   ./crowsnest.sh report       → genera informe completo (con Docker, ~20 min)
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
REPORTS_DIR="${SCRIPT_DIR}/reports"
TARGETS_DIR="${SCRIPT_DIR}/targets"
TARGETS_FILE="${TARGETS_DIR}/domains.txt"
IMAGE_NAME="crowsnest:latest"
DB_FILE="${SCRIPT_DIR}/db/targets.json"

# ── HELPERS ──────────────────────────────────────────────────────────────────
header() {
    clear
    echo -e "${RED}┌─────────────────────────────────────────────────────────┐${NC}"
    echo -e "${RED}│${NC}  ${WHITE}Crowsnest${NC} ${GRAY}— passive reconnaissance${NC}             ${RED}│${NC}"
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
        error "Missing: $1"
        echo -e "    Install with: ${GRAY}$2${NC}"
        return 1
    fi
    return 0
}

check_docker_running() {
    if ! docker info &>/dev/null; then
        error "Docker is not running."
        echo -e "    Start Docker Desktop (Windows) or: ${GRAY}sudo systemctl start docker${NC}"
        exit 1
    fi
}

check_container_built() {
    if ! docker image inspect "${IMAGE_NAME}" &>/dev/null; then
        error "Image '${IMAGE_NAME}' is not built."
        echo -e "    Build it first: ${GRAY}docker compose build${NC}"
        exit 1
    fi
}

score_color() {
    local score=$1
    if   [[ $score -ge 80 ]]; then echo -e "${BRED}${score}/100 — Critical${NC}"
    elif [[ $score -ge 50 ]]; then echo -e "${YELLOW}${score}/100 — High${NC}"
    elif [[ $score -ge 25 ]]; then echo -e "${YELLOW}${score}/100 — Medium${NC}"
    elif [[ $score -gt 0  ]]; then echo -e "${GREEN}${score}/100 — Low${NC}"
    else                           echo -e "${GRAY}0/100 — No findings${NC}"
    fi
}

# ejemplo-legal.example → Ejemplo Legal | estudio-ejemplo.example → Estudio Ejemplo
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
    local DOMINIO="$1" NOMBRE="$2" TIPO="$3" RUTA_PDF="$4"
    python3 - <<PYEOF
import json, sys
from pathlib import Path
from datetime import datetime

sys.path.insert(0, "${SCRIPT_DIR}")
from lib.states import QUEUED, REPORTED

db_path = Path("${DB_FILE}")
db = json.loads(db_path.read_text()) if db_path.exists() else {"version": 1, "targets": {}}

d = db["targets"].setdefault("${DOMINIO}", {
    "name": "${NOMBRE}",
    "report_at": None, "report_pdf": None,
    "detailed_report_pdf": None,
    "remediation_at": None, "remediation_pdf": None,
    "skip_reason": "",
    "status": QUEUED
})

d["name"] = "${NOMBRE}"
now = datetime.now().isoformat(timespec="seconds")

if "${TIPO}" == "report_pdf":
    d["report_at"] = now
    d["report_pdf"] = "${RUTA_PDF}"
    d["status"] = REPORTED
elif "${TIPO}" == "detailed_report_pdf":
    d["detailed_report_pdf"] = "${RUTA_PDF}"
elif "${TIPO}" == "remediation_pdf":
    d["remediation_at"] = now
    d["remediation_pdf"] = "${RUTA_PDF}"
    d["status"] = REPORTED

db_path.parent.mkdir(parents=True, exist_ok=True)
db_path.write_text(json.dumps(db, ensure_ascii=False, indent=2))
print(f"[✓] DB updated: ${DOMINIO} → ${TIPO}")
PYEOF
}

# _db_update_scan — registra scan_data + session_folder tras un escaneo.
# A diferencia de _db_update, NO toca report_pdf/detailed_report_pdf: los PDFs
# se generan aparte desde el JSON que deja este paso.
_db_update_scan() {
    local DOMINIO="$1" NOMBRE="$2" REPORT_JSON="$3" SESSION_FOLDER="$4"
    python3 - "${DB_FILE}" "${DOMINIO}" "${NOMBRE}" "${REPORT_JSON}" "${SESSION_FOLDER}" "${SCRIPT_DIR}" <<'PYEOF'
import json, sys
from pathlib import Path
from datetime import datetime

sys.path.insert(0, sys.argv[6])
from lib.states import QUEUED, RECON

db_path        = Path(sys.argv[1])
dominio        = sys.argv[2]
nombre         = sys.argv[3]
report_json    = Path(sys.argv[4])
session_folder = sys.argv[5]

db = json.loads(db_path.read_text()) if db_path.exists() else {"version": 1, "targets": {}}

d = db["targets"].setdefault(dominio, {
    "name": nombre,
    "report_at": None, "report_pdf": None,
    "detailed_report_pdf": None,
    "remediation_at": None, "remediation_pdf": None,
    "skip_reason": "",
    "status": QUEUED,
})

d["name"] = nombre
d["report_at"] = datetime.now().isoformat(timespec="seconds")

sev_rank = {"critical": 0, "high": 1, "medium": 2, "low": 3, "info": 4}
try:
    rep = json.loads(report_json.read_text())
    es = rep.get("executive_summary", {}) or {}
    by_sev = es.get("findings_by_severity", {}) or {}
    findings = rep.get("findings", []) or []
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
except Exception as e:
    # Si falla la extracción, al menos persiste session_folder
    d.setdefault("scan_data", {})["session_folder"] = session_folder
    print(f"[!] Could not fully extract scan_data from {report_json.name}: {e}")

if d.get("status") in (None, QUEUED):
    d["status"] = RECON

db_path.parent.mkdir(parents=True, exist_ok=True)
db_path.write_text(json.dumps(db, ensure_ascii=False, indent=2))
print(f"[✓] DB updated: {dominio} → scan_data + session_folder")
PYEOF
}

# =============================================================================
# MODO 0: TARGETS — enriquecimiento de la lista de dominios objetivo
# =============================================================================
# =============================================================================
# MODO 0.5: ENRIQUECER — OpenClaw Orchestrator (Ollama + Crawl4AI)
# =============================================================================
cmd_targets_enriquecer() {
    header "Stage 0.5 · Target enrichment — OpenClaw"

    local OPENCLAW_DIR="${SCRIPT_DIR}/openclaw"
    if [[ ! -f "${OPENCLAW_DIR}/run_batch.py" ]]; then
        error "openclaw/run_batch.py not found"
        echo -e "  The openclaw_orchestrator module is not installed."
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

    # ── Localizar la lista de dominios objetivo ──────────────────────────────
    local INPUT="${1:-}"
    if [[ -z "${INPUT}" ]]; then
        INPUT="${TARGETS_FILE}"
    fi
    if [[ -z "${INPUT}" || ! -f "${INPUT}" ]]; then
        error "No target domain list found."
        echo -e "  Usage: ${GRAY}./crowsnest.sh targets enriquecer <path/domains.txt>${NC}"
        echo -e "  Default: ${GRAY}${TARGETS_FILE}${NC}"
        exit 1
    fi
    INPUT="$(cd "$(dirname "${INPUT}")" && pwd)/$(basename "${INPUT}")"

    mkdir -p "${REPORTS_DIR}"
    local TS OUT_NAME OUT_HOST
    TS="$(date +%Y%m%d_%H%M%S)"
    OUT_NAME="targets_enriquecidos_${TS}.json"
    OUT_HOST="${REPORTS_DIR}/${OUT_NAME}"

    info "Environment: ${GRAY}${ENTORNO}${NC}"
    info "Input:       ${GRAY}${INPUT}${NC}"
    info "Output:      ${GRAY}${OUT_HOST}${NC}"
    info "LLM:         ${GRAY}${OLLAMA_HOST_URL}${NC}"
    echo ""

    # ── Ejecutar: preferir el contenedor (trae Crawl4AI + cliente Ollama) ─────
    if command -v "${DOCKER_BIN%% *}" &>/dev/null \
       && ${DOCKER_BIN} info &>/dev/null \
       && ${DOCKER_BIN} image inspect "${IMAGE_NAME}" &>/dev/null; then
        info "Running in a ${GRAY}${IMAGE_NAME}${NC} container…"
        ${DOCKER_BIN} run --rm \
            --network host \
            -e OLLAMA_HOST="${OLLAMA_HOST_URL}" \
            -v "${OPENCLAW_DIR}:/home/work/openclaw${ZFLAG}" \
            -v "${INPUT}:/home/work/input/domains.txt:${RO_OPT}" \
            -v "${REPORTS_DIR}:/home/work/results${ZFLAG}" \
            -v "${SCRIPT_DIR}/db:/home/work/db${ZFLAG}" \
            "${IMAGE_NAME}" \
            python3 /home/work/openclaw/run_batch.py \
                --config /home/work/openclaw/config.json \
                --input  /home/work/input/domains.txt \
                --output "/home/work/results/${OUT_NAME}"
    else
        warn "Docker image unavailable — falling back to the host Python."
        warn "Requires: ${GRAY}pip install -r openclaw/requirements.txt${NC}"
        OLLAMA_HOST="${OLLAMA_HOST_URL}" python3 "${OPENCLAW_DIR}/run_batch.py" \
            --config "${OPENCLAW_DIR}/config.json" \
            --input  "${INPUT}" \
            --output "${OUT_HOST}"
    fi

    echo ""
    if [[ -s "${OUT_HOST}" ]]; then
        log "Enriched targets written to: ${GRAY}${OUT_HOST}${NC}"
    else
        error "No output file was produced."
        exit 1
    fi
}

# =============================================================================
# MODO 1: RECON — califica targets rápido (sin Docker)
# =============================================================================
cmd_recon() {
    header "Stage 1 · Target recon"

    # Verificar checkdmarc instalado
    if ! check_dep "checkdmarc" "pip install checkdmarc --break-system-packages"; then
        exit 1
    fi
    if ! check_dep "python3" ""; then exit 1; fi

    mkdir -p "$(dirname "${TARGETS_FILE}")"
    mkdir -p "${REPORTS_DIR}"

    step "How do you want to enter the domains?"
    echo "  1) A single domain (type it now)"
    echo "  2) A list from a file  [${TARGETS_FILE}]"
    echo "  3) Type several now (one per line, blank line to finish)"
    echo ""
    ask "Option [1/2/3]:"
    read -r opcion

    declare -a DOMINIOS=()

    case "$opcion" in
        1)
            ask "Domain to analyse (e.g. example.com):"
            read -r dom
            dom="${dom#https://}"; dom="${dom#http://}"; dom="${dom%%/*}"
            DOMINIOS=("$dom")
            ;;
        2)
            if [[ ! -f "${TARGETS_FILE}" ]]; then
                error "${TARGETS_FILE} does not exist"
                info  "Create it with one domain per line and run again."
                exit 1
            fi
            mapfile -t DOMINIOS < <(grep -v '^\s*#' "${TARGETS_FILE}" | grep -v '^\s*$')
            info "Analysing ${#DOMINIOS[@]} domains from the file."
            ;;
        3)
            ask "Enter domains (one per line, blank line to finish):"
            while true; do
                read -r dom
                [[ -z "$dom" ]] && break
                dom="${dom#https://}"; dom="${dom#http://}"; dom="${dom%%/*}"
                DOMINIOS+=("$dom")
            done
            ;;
        *)
            error "Invalid option."; exit 1 ;;
    esac

    if [[ ${#DOMINIOS[@]} -eq 0 ]]; then
        error "No domains entered."; exit 1
    fi

    # Filtrar dominios ya registrados en DB
    if [[ -f "${DB_FILE}" ]]; then
        YA_EN_DB=$(python3 - <<PYEOF
import json
from pathlib import Path
try:
    db = json.loads(Path("${DB_FILE}").read_text())
    print("\n".join(db.get("targets", {}).keys()))
except Exception:
    pass
PYEOF
        )
        if [[ -n "$YA_EN_DB" ]]; then
            declare -a _DOM_NUEVOS=()
            for _d in "${DOMINIOS[@]}"; do
                if echo "$YA_EN_DB" | grep -qx "$_d"; then
                    warn "Skipping '${_d}' — already in the database"
                else
                    _DOM_NUEVOS+=("$_d")
                fi
            done
            DOMINIOS=("${_DOM_NUEVOS[@]+"${_DOM_NUEVOS[@]}"}")
            [[ ${#DOMINIOS[@]} -eq 0 ]] && { warn "Every domain is already in the database."; exit 0; }
        fi
    fi

    step "Analysing ${#DOMINIOS[@]} domain(s)…"
    echo ""

    # Archivo de resultados de sesión
    SESSION_DATE=$(date +"%Y%m%d_%H%M%S")
    RESULTS_FILE="${REPORTS_DIR}/recon_${SESSION_DATE}.txt"
    PRIORITY_FILE="${REPORTS_DIR}/recon_priority_${SESSION_DATE}.txt"

    declare -a PRIORITY=()
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
    issues.append('SPF invalid or missing')
elif '-all' not in spf.get('record', ''):
    score += 20
    issues.append('SPF softfail (~all)')

# DMARC
dmarc = data.get('dmarc', {})
if not dmarc.get('valid', False):
    score += 45
    issues.append('DMARC missing')
else:
    policy = dmarc.get('tags', {}).get('p', {}).get('value', 'none')
    if policy == 'none':
        score += 30
        issues.append('DMARC p=none (no effect)')
    elif policy == 'quarantine':
        score += 15
        issues.append('DMARC p=quarantine (incomplete)')

score = min(score, 100)

priority = score >= 50
print(f"SCORE:{score}")
print(f"PRIORITY_HIT:{'YES' if priority else 'NO'}")
print(f"ISSUES:{' | '.join(issues) if issues else 'None relevant'}")
PYEOF
        )

        SCORE=$(echo "$RESULTADO" | grep "SCORE:" | cut -d: -f2)
        PRIORITY_HIT=$(echo "$RESULTADO" | grep "PRIORITY_HIT:" | cut -d: -f2)
        ISSUES=$(echo "$RESULTADO" | grep "ISSUES:" | cut -d: -f2-)

        # Mostrar resultado
        printf "  Score:   "; score_color "${SCORE:-0}"
        echo -e "  Issues:  ${GRAY}${ISSUES}${NC}"

        if [[ "$PRIORITY_HIT" == "YES" ]]; then
            echo -e "  Status:  ${BRED}● PRIORITY TARGET — worth a full scan${NC}"
            PRIORITY+=("$dominio")
        else
            echo -e "  Status:  ${GREEN}● Low priority — well configured${NC}"
        fi
        echo ""

        TODOS+=("${SCORE}|${PRIORITY_HIT}|${dominio}|${ISSUES}")
    done

    # ── RESUMEN ──────────────────────────────────────────────────────────────
    step "Session summary"

    echo -e "  Domains analysed    : ${WHITE}${#DOMINIOS[@]}${NC}"
    echo -e "  Priority targets    : ${BRED}${#PRIORITY[@]}${NC}"
    echo -e "  Low priority        : ${GREEN}$(( ${#DOMINIOS[@]} - ${#PRIORITY[@]} ))${NC}"
    echo ""

    # Guardar resultados
    {
        echo "# Crowsnest — recon results ${SESSION_DATE}"
        echo "# Format: SCORE | PRIORITY_HIT | DOMAIN | ISSUES"
        for r in "${TODOS[@]}"; do echo "$r"; done
    } > "${RESULTS_FILE}"

    if [[ ${#PRIORITY[@]} -gt 0 ]]; then
        printf '%s\n' "${PRIORITY[@]}" > "${PRIORITY_FILE}"
        echo -e "${BGREEN}Priority targets saved to:${NC}"
        echo -e "  ${GRAY}${PRIORITY_FILE}${NC}"
        echo ""

        ask "Generate a report now for the first priority target? [y/N]"
        read -r resp
        if [[ "${resp,,}" == "y" || "${resp,,}" == "s" ]]; then
            PRIMER="${PRIORITY[0]}"
            ask "Target name for '${PRIMER}' (e.g. Example Ltd):"
            read -r nombre_cliente
            _run_report "$PRIMER" "$nombre_cliente"
        else
            info "When you want the report, run:"
            echo -e "  ${GRAY}./crowsnest.sh report${NC}"
        fi
    else
        warn "No priority targets in this session."
    fi

    echo ""
    log "Full results saved to: ${GRAY}${RESULTS_FILE}${NC}"
}

# =============================================================================
# MODO 2: FLASH — informe completo con Docker
# =============================================================================
cmd_report() {
    header "Stage 1 · Report (Docker)"

    check_docker_running
    check_container_built

    # ── Modo directo (no-interactivo) ─────────────────────────────────────────
    # ./crowsnest.sh report dominio.example "Nombre Empresa"  → salta el menú de prioritarios
    if [[ -n "${1:-}" ]]; then
        _run_report "$1" "${2:-$1}"
        return
    fi

    # ── INPUT ─────────────────────────────────────────────────────────────────
    step "Target details"

    # ¿Hay prioritarios del día?
    LATEST_PRIORITY=$(ls -t "${REPORTS_DIR}"/recon_priority_*.txt 2>/dev/null | head -1 || echo "")

    if [[ -n "$LATEST_PRIORITY" ]]; then
        info "Priority targets available:"
        # Excluir dominios ya procesados (cualquier status distinto de queued)
        mapfile -t LISTA < <(python3 - "$LATEST_PRIORITY" <<PYEOF
import json, sys
from pathlib import Path

sys.path.insert(0, "${SCRIPT_DIR}")
from lib.states import is_pending

excluidos = set()
try:
    db = json.loads(Path("${DB_FILE}").read_text())
    for dom, info in db.get("targets", {}).items():
        if not is_pending(info.get("status")):
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
        echo "  m) Enter manually"
        echo ""
        ask "Choose [number or m]:"
        read -r sel

        if [[ "$sel" == "m" ]] || [[ -z "$sel" ]]; then
            ask "Domain:"
            read -r DOMINIO
        elif [[ "$sel" =~ ^[0-9]+$ ]] && [[ "$sel" -le "${#LISTA[@]}" ]]; then
            DOMINIO="${LISTA[$((sel-1))]}"
        else
            ask "Domain:"
            read -r DOMINIO
        fi
    else
        ask "Target domain (e.g. example.com):"
        read -r DOMINIO
    fi

    DOMINIO="${DOMINIO#https://}"; DOMINIO="${DOMINIO#http://}"; DOMINIO="${DOMINIO%%/*}"

    ask "Target name (e.g. Example Ltd):"
    read -r CLIENTE

    echo ""
    info "Domain : ${WHITE}${DOMINIO}${NC}"
    info "Name   : ${WHITE}${CLIENTE}${NC}"
    echo ""
    ask "Confirm and run? [y/N]"
    read -r confirm
    [[ "${confirm,,}" != "y" && "${confirm,,}" != "s" ]] && { warn "Cancelled."; exit 0; }

    _run_report "$DOMINIO" "$CLIENTE"
}

_run_report() {
    local DOMINIO="$1"
    local CLIENTE="$2"
    local TIMESTAMP; TIMESTAMP=$(date +"%Y%m%d_%H%M%S")
    local SAFE_DOM="${DOMINIO//./_}"
    local SESSION_DIR="${REPORTS_DIR}/${SAFE_DOM}_${TIMESTAMP}"

    # El encuadre de cumplimiento lo elige el motor desde config/compliance/;
    # aqui solo se nombran los artefactos.
    local DB_REPORT_KEY="report_pdf"
    local DB_DETAIL_KEY="detailed_report_pdf"
    local REPORT_BASE="Crowsnest_Report"
    local DETAIL_BASE="Crowsnest_Detailed"
    local JSON_REPORT="report_${SAFE_DOM}.json"
    local JSON_DETAIL="detailed_${SAFE_DOM}.json"

    mkdir -p "${SESSION_DIR}"/{subdomains,email,nuclei,technologies,http}

    step "Running the OSINT scan in Docker (~15 min)"
    info "Live progress below ↓"
    echo ""

    docker run --rm \
        --user $(id -u):$(id -g) \
        --name "crowsnest_report_${SAFE_DOM}" \
        --env-file "${SCRIPT_DIR}/.env" \
        --network bridge \
        -v "${REPORTS_DIR}:/home/work/results:z" \
        -v "${SCRIPT_DIR}/config:/root/.config/subfinder:z" \
        -v "${SCRIPT_DIR}/scripts:/home/work/scripts:ro,z" \
        "${IMAGE_NAME}" \
        bash /home/work/scripts/audit.sh "${DOMINIO}" "/home/work/results/${SAFE_DOM}_${TIMESTAMP}" 2>&1 | \
        grep -E "^\[|subfinder|httpx|checkdmarc|whatweb|nuclei|Total|✓" || true

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

    # Resumen del summarizer: opcional. Si el pipeline LLM no corrio, el
    # informe se genera igual sin esa seccion.
    local SUMMARY_TXT="${SESSION_DIR}/summary_${SAFE_DOM}.txt"
    if [[ -s "${SUMMARY_TXT}" ]]; then
        info "Summarizer output: ${GRAY}$(basename "${SUMMARY_TXT}")${NC}"
        COMMON_ARGS+=("--summary" "${SUMMARY_TXT}")
    fi
    [[ -n "$DMARC_JSON" ]] && COMMON_ARGS+=("--dmarc" "${DMARC_JSON}")
    [[ -n "$TECH_JSON"  ]] && COMMON_ARGS+=("--tech"  "${TECH_JSON}")

    # ── Report JSON ───────────────────────────────────────────────────────────
    step "Building the summary report JSON"
    local REPORT_JSON="${AUDIT_DIR}/${JSON_REPORT}"

    python3 "${SCRIPT_DIR}/scripts/nuclei_to_report.py" "${COMMON_ARGS[@]}" \
        --report-type "summary" \
        --output "${REPORT_JSON}"

    # ── Diagnóstico JSON ──────────────────────────────────────────────────────
    step "Building the detailed report JSON"
    local DETAIL_JSON="${AUDIT_DIR}/${JSON_DETAIL}"

    python3 "${SCRIPT_DIR}/scripts/nuclei_to_report.py" "${COMMON_ARGS[@]}" \
        --report-type "detailed" \
        --output "${DETAIL_JSON}"

    # ── PDFs ──────────────────────────────────────────────────────────────────
    # El estado del target solo avanza a "reported" cuando existe al menos un
    # PDF (ver _db_update); dejar esto como sugerencia manual significaba que
    # el flujo principal del dashboard nunca completaba el ciclo de estados.
    step "Rendering the report PDFs"
    local REPORT_PDF="${AUDIT_DIR}/${REPORT_BASE}_${SAFE_DOM}_${TIMESTAMP}.pdf"
    local DETAIL_PDF="${AUDIT_DIR}/${DETAIL_BASE}_${SAFE_DOM}_${TIMESTAMP}.pdf"

    python3 "${SCRIPT_DIR}/scripts/generate_pdf.py" \
        --input  "${REPORT_JSON}" \
        --output "${REPORT_PDF}"
    python3 "${SCRIPT_DIR}/scripts/generate_pdf.py" \
        --input  "${DETAIL_JSON}" \
        --output "${DETAIL_PDF}"

    # Registrar scan_data + session_folder en la DB
    _db_update_scan "${DOMINIO}" "${CLIENTE}" "${REPORT_JSON}" "$(basename "${SESSION_DIR}")"
    _db_update "${DOMINIO}" "${CLIENTE}" "${DB_REPORT_KEY}" "${DOMINIO}/$(basename "${REPORT_PDF}")"
    _db_update "${DOMINIO}" "${CLIENTE}" "${DB_DETAIL_KEY}" "${DOMINIO}/$(basename "${DETAIL_PDF}")"

    # ── RESULTADO ─────────────────────────────────────────────────────────────
    echo ""
    echo -e "${RED}┌─────────────────────────────────────────────────────────┐${NC}"
    echo -e "${RED}│${NC}  ${BGREEN}✓ Scan complete — report ready${NC}                          ${RED}│${NC}"
    echo -e "${RED}│${NC}  ${GRAY}${CLIENTE}${NC}"
    echo -e "${RED}├─────────────────────────────────────────────────────────┤${NC}"
    echo -e "${RED}│${NC}  Summary PDF  : ${GRAY}$(basename "${REPORT_PDF}")${NC}"
    echo -e "${RED}│${NC}  Detailed PDF : ${GRAY}$(basename "${DETAIL_PDF}")${NC}"
    echo -e "${RED}├─────────────────────────────────────────────────────────┤${NC}"
    echo -e "${RED}│${NC}  Dir: ${GRAY}${AUDIT_DIR}${NC}"
    echo -e "${RED}└─────────────────────────────────────────────────────────┘${NC}"
    echo ""

    # Sin prompt de "abrir el PDF" a proposito: _run_report corre tambien en
    # batch (subshells en paralelo, sin stdin) y desde el wrapper de la webapp,
    # que escribe una cantidad fija de lineas. Un `read` de mas aqui haria
    # fallar cada worker del batch y romperia el boton del dashboard.
    info "Report ready."
}

# =============================================================================
# MODO 2b: DIAGNÓSTICO — regenera PDF desde sesión existente (sin nuevo escaneo)
# =============================================================================
cmd_diagnostico() {
    header "Re-render · Detailed report from an existing session"

    if ! check_dep "python3" ""; then exit 1; fi

    step "Domain to re-render"
    ask "Domain (e.g. example.com):"
    read -r DOMINIO
    DOMINIO="${DOMINIO#https://}"; DOMINIO="${DOMINIO#http://}"; DOMINIO="${DOMINIO%%/*}"

    local SAFE_DOM="${DOMINIO//./_}"

    # Buscar sesión más reciente para este dominio
    local SESSION_DIR
    SESSION_DIR=$(ls -td "${REPORTS_DIR}/${SAFE_DOM}_"* 2>/dev/null | head -1 || echo "")

    if [[ -z "$SESSION_DIR" ]] || [[ ! -d "$SESSION_DIR" ]]; then
        error "No previous session for '${DOMINIO}' under ${REPORTS_DIR}/"
        info "Run a scan first: ${GRAY}./crowsnest.sh report${NC}"
        exit 1
    fi

    info "Session: ${GRAY}${SESSION_DIR}${NC}"
    echo ""

    # Detectar nombre del cliente desde JSON existente
    local EXISTING_JSON CLIENTE
    EXISTING_JSON=$(find "${SESSION_DIR}" \
        \( -name "report_${SAFE_DOM}.json" -o -name "detailed_${SAFE_DOM}.json" \) \
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
        info "Name detected: ${WHITE}${CLIENTE}${NC}"
        ask "Use this name? [Y/n]"
        read -r use_it
        if [[ "${use_it,,}" == "n" ]]; then
            ask "Target name:"
            read -r CLIENTE
        fi
    else
        ask "Target name (e.g. Example Ltd):"
        read -r CLIENTE
    fi

    echo ""
    info "Domain : ${WHITE}${DOMINIO}${NC}"
    info "Name   : ${WHITE}${CLIENTE}${NC}"
    echo ""
    ask "Re-render the detailed PDF without a new scan? [y/N]"
    read -r confirm
    [[ "${confirm,,}" != "y" && "${confirm,,}" != "s" ]] && { warn "Cancelled."; exit 0; }

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

    local DETAIL_JSON="${SESSION_DIR}/detailed_${SAFE_DOM}.json"
    local DIAG_PDF="${SESSION_DIR}/Crowsnest_Detailed_${SAFE_DOM}_${TIMESTAMP}.pdf"

    step "Re-rendering the detailed report PDF (no new scan)"

    local -a ARGS=("--client" "${CLIENTE}" "--domain" "${DOMINIO}" \
                   "--output" "${DETAIL_JSON}" "--report-type" "detailed")
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
        --input  "${DETAIL_JSON}" \
        --output "${DIAG_PDF}"

    RESUMEN=$(python3 - <<PYEOF
import json
try:
    data = json.load(open('${DETAIL_JSON}'))
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
    echo -e "${RED}│${NC}  ${BGREEN}✓ Detailed report re-rendered (no new scan)${NC}          ${RED}│${NC}"
    echo -e "${RED}│${NC}  ${GRAY}${CLIENTE}${NC}"
    echo -e "${RED}│${NC}  Risk      : $(score_color "${R_SCORE:-0}") — ${R_LEVEL}"
    echo -e "${RED}│${NC}  Scenarios : ${WHITE}${R_SCEN:-0}${NC} business-impact scenarios identified"
    echo -e "${RED}├─────────────────────────────────────────────────────────┤${NC}"
    echo -e "${RED}│${NC}  PDF: ${GRAY}${DIAG_PDF}${NC}"
    echo -e "${RED}└─────────────────────────────────────────────────────────┘${NC}"
    echo ""

    ask "Open the PDF now? [y/N]"
    read -r abrir
    [[ "${abrir,,}" == "y" || "${abrir,,}" == "s" ]] && _open_pdf "${DIAG_PDF}"

    info "Detailed report ready."
}

# =============================================================================
# MODO 3: TRABAJO — pipeline completo para cliente autorizado
# =============================================================================
cmd_trabajo() {
    header "Stage 2 · Remediation pipeline (authorised target)"

    check_docker_running
    check_container_built

    step "Target details"

    ask "Target domain (e.g. example.com):"
    read -r DOMINIO
    DOMINIO="${DOMINIO#https://}"; DOMINIO="${DOMINIO#http://}"; DOMINIO="${DOMINIO%%/*}"

    ask "Target name (e.g. Example Ltd):"
    read -r CLIENTE

    ask "Authorisation reference (e.g. AUTH-2026-001):"
    read -r AUTH_REF

    echo ""
    warn "This runs a FULL scan (~35 min)."
    warn "Only proceed with written authorisation from the system owner."
    echo ""
    info "Domain      : ${WHITE}${DOMINIO}${NC}"
    info "Name        : ${WHITE}${CLIENTE}${NC}"
    info "Authorisation: ${WHITE}${AUTH_REF}${NC}"
    echo ""
    ask "Confirm and run the full scan? [y/N]"
    read -r confirm
    [[ "${confirm,,}" != "y" && "${confirm,,}" != "s" ]] && { warn "Cancelled."; exit 0; }

    _run_trabajo "$DOMINIO" "$CLIENTE" "$AUTH_REF"
}

_run_trabajo() {
    local DOMINIO="$1"
    local CLIENTE="$2"
    local AUTH_REF="$3"
    local TIMESTAMP; TIMESTAMP=$(date +"%Y%m%d_%H%M%S")
    local SAFE_DOM="${DOMINIO//./_}"
    local SESSION_DIR="${REPORTS_DIR}/${SAFE_DOM}_${TIMESTAMP}"

    mkdir -p "${SESSION_DIR}"/{subdomains,email,nuclei,technologies,http}

    # Registrar autorizacion para trazabilidad
    {
        echo "# Crowsnest — scan authorisation record"
        echo "Date        : $(date)"
        echo "Name        : ${CLIENTE}"
        echo "Domain      : ${DOMINIO}"
        echo "Authorisation: ${AUTH_REF}"
        echo "Operator    : $(whoami)@$(hostname)"
    } > "${SESSION_DIR}/authorisation_${SAFE_DOM}.txt"
    log "Authorisation recorded at: ${GRAY}${SESSION_DIR}/authorisation_${SAFE_DOM}.txt${NC}"

    step "Running the full pipeline in Docker (~35 min)"
    info "Live progress below ↓"
    echo ""

    docker run --rm \
        --user "$(id -u):$(id -g)" \
        --name "crowsnest_remediation_${SAFE_DOM}" \
        --env-file "${SCRIPT_DIR}/.env" \
        --network bridge \
        -v "${REPORTS_DIR}:/home/work/results:z" \
        -v "${SCRIPT_DIR}/config:/root/.config/subfinder:z" \
        -v "${SCRIPT_DIR}/scripts:/home/work/scripts:ro,z" \
        "${IMAGE_NAME}" \
        bash /home/work/scripts/audit.sh "${DOMINIO}" "/home/work/results/${SAFE_DOM}_${TIMESTAMP}" --full

    echo ""
    step "Rendering the remediation report PDF"

    AUDIT_DIR="${SESSION_DIR}"

    NUCLEI_JSON=$(find "${AUDIT_DIR}" -name "nuclei_${DOMINIO}.json"     2>/dev/null | head -1 || echo "")
    DMARC_JSON=$(find  "${AUDIT_DIR}" -name "checkdmarc_${DOMINIO}.json" 2>/dev/null | head -1 || echo "")
    TECH_JSON=$(find   "${AUDIT_DIR}" -name "whatweb_${DOMINIO}.json"    2>/dev/null | head -1 || echo "")
    NMAP_JSON=$(find   "${AUDIT_DIR}" -path "*/nmap/nmap_${DOMINIO}.json" 2>/dev/null | head -1 || echo "")

    INFORME_JSON="${AUDIT_DIR}/remediation_${SAFE_DOM}.json"
    PDF_OUT="${AUDIT_DIR}/Crowsnest_Remediation_${SAFE_DOM}_${TIMESTAMP}.pdf"

    ARGS=("--client" "${CLIENTE}" "--domain" "${DOMINIO}" "--output" "${INFORME_JSON}")
    [[ -n "$NUCLEI_JSON" ]] && ARGS+=("--input" "${NUCLEI_JSON}") || {
        echo "" > /tmp/empty.jsonl
        ARGS+=("--input" "/tmp/empty.jsonl")
    }
    [[ -n "$DMARC_JSON" ]] && ARGS+=("--dmarc" "${DMARC_JSON}")
    [[ -n "$TECH_JSON"  ]] && ARGS+=("--tech"  "${TECH_JSON}")
    [[ -n "$NMAP_JSON"  ]] && ARGS+=("--nmap"  "${NMAP_JSON}")
    ARGS+=(--report-type remediation)

    python3 "${SCRIPT_DIR}/scripts/nuclei_to_report.py" "${ARGS[@]}"
    python3 "${SCRIPT_DIR}/scripts/generate_pdf.py" \
        --input  "${INFORME_JSON}" \
        --output "${PDF_OUT}"

    local REL_TRABAJO="${DOMINIO}/$(basename "${PDF_OUT}")"
    _db_update "${DOMINIO}" "${CLIENTE}" "remediation_pdf" "${REL_TRABAJO}"

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
    echo -e "${RED}│${NC}  ${BGREEN}✓ Remediation report generated${NC}                         ${RED}│${NC}"
    echo -e "${RED}│${NC}  ${GRAY}${CLIENTE}${NC}"
    echo -e "${RED}│${NC}  ${GRAY}Authorisation: ${AUTH_REF}${NC}"
    echo -e "${RED}├─────────────────────────────────────────────────────────┤${NC}"
    echo -e "${RED}│${NC}  Risk    : $(score_color "${R_SCORE:-0}") — ${R_LEVEL}"
    echo -e "${RED}│${NC}  Findings: ${WHITE}${R_TOTAL:-0}${NC} total  ${BRED}Critical:${R_CRIT:-0}${NC}  ${YELLOW}High:${R_HIGH:-0}${NC}  Med:${R_MED:-0}  Low:${R_LOW:-0}"
    echo -e "${RED}├─────────────────────────────────────────────────────────┤${NC}"
    echo -e "${RED}│${NC}  PDF : ${GRAY}${PDF_OUT}${NC}"
    echo -e "${RED}│${NC}  JSON: ${GRAY}${INFORME_JSON}${NC}"
    echo -e "${RED}└─────────────────────────────────────────────────────────┘${NC}"
    echo ""

    ask "Open the PDF now? [y/N]"
    read -r abrir
    [[ "${abrir,,}" == "y" || "${abrir,,}" == "s" ]] && _open_pdf "${PDF_OUT}"

    info "Report ready to deliver to the client."
}

# =============================================================================
# MODO BATCH — procesar lista de targets prioritarios en paralelo
# =============================================================================
cmd_batch() {
    header "Batch · Targets prioritarios en paralelo"

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
        TARGET_FILE=$(ls -t "${TARGETS_DIR}"/recon_priority_*.txt 2>/dev/null | head -1 || true)
    fi
    if [[ -z "$TARGET_FILE" ]]; then
        TARGET_FILE=$(ls -t "${REPORTS_DIR}"/recon_priority_*.txt 2>/dev/null | head -1 || true)
    fi

    if [[ -z "$TARGET_FILE" ]] || [[ ! -f "$TARGET_FILE" ]]; then
        error "No priority target list found."
        info "Generate one with: ${GRAY}./crowsnest.sh recon${NC}"
        info "Or provide a path: ${GRAY}./crowsnest.sh batch targets/mi_lista.txt${NC}"
        exit 1
    fi

    declare -a DOMINIOS=()
    mapfile -t DOMINIOS < <(grep -v '^\s*#' "$TARGET_FILE" | grep -v '^\s*$')
    local TOTAL="${#DOMINIOS[@]}"

    if [[ $TOTAL -eq 0 ]]; then
        error "'${TARGET_FILE}' contains no domains."
        exit 1
    fi

    info "Lista   : ${GRAY}${TARGET_FILE}${NC}"
    info "Domains: ${WHITE}${TOTAL}${NC}"
    echo ""

    # ── Número de workers ────────────────────────────────────────────────────
    local N_WORKERS
    if [[ -n "$FLAG_WORKERS" ]]; then
        N_WORKERS="$FLAG_WORKERS"
    else
        ask "How many parallel workers? [1-5, default 3]:"
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
        echo "  a) Automatic — derive from the domain  (example-corp.example → Example Corp)"
        echo "  m) Manual — pedir nombre por cada dominio"
        echo ""
        ask "Naming mode [a/m, default a]:"
        read -r modo_nombres
        modo_nombres="${modo_nombres:-a}"
        echo ""
    fi

    declare -a NOMBRES=()
    local auto_name nombre dom
    if [[ "${modo_nombres,,}" == "m" ]]; then
        step "Client names"
        for dom in "${DOMINIOS[@]}"; do
            auto_name=$(domain_to_name "$dom")
            ask "Name for '${dom}' [Enter = ${auto_name}]:"
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
    step "Execution plan"
    local i
    for i in "${!DOMINIOS[@]}"; do
        printf "  %2d) %-40s → %s\n" "$((i+1))" "${DOMINIOS[$i]}" "${NOMBRES[$i]}"
    done
    echo ""
    info "Parallel workers  : ${WHITE}${N_WORKERS}${NC}"
    info "Total domains     : ${WHITE}${TOTAL}${NC}"
    echo ""
    if [[ $FLAG_CONFIRM -eq 1 ]]; then
        info "Auto-confirmed (--confirm)"
    else
        ask "Start the batch? [y/N]"
        read -r confirm
        [[ "${confirm,,}" != "y" && "${confirm,,}" != "s" ]] && { warn "Cancelled."; exit 0; }
    fi

    # ── Ejecución en paralelo ─────────────────────────────────────────────────
    local BATCH_TS; BATCH_TS=$(date +"%Y%m%d_%H%M%S")
    local BATCH_LOG_DIR="${REPORTS_DIR}/batch_${BATCH_TS}_logs"
    mkdir -p "$BATCH_LOG_DIR"

    declare -a PIDS=()
    declare -a PID_IDX=()
    local completed=0 failed=0
    local -a np=() ni=()
    local j pid pidx ex d

    step "Running..."
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
                        echo -e "${BGREEN}[✓ $((pidx+1))/${TOTAL}]${NC} ${WHITE}${d}${NC} — done"
                        completed=$((completed + 1))
                    else
                        echo -e "${BRED}[✗ $((pidx+1))/${TOTAL}]${NC} ${WHITE}${d}${NC} — FAILED  (log: ${safe}.log)"
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
        echo -e "${CYAN}[→ ${num}/${TOTAL}]${NC} ${WHITE}${dom}${NC} — starting..."
        ( _run_report "$dom" "$nombre" ) > "${BATCH_LOG_DIR}/${safe}.log" 2>&1 &
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
                    echo -e "${BGREEN}[✓ $((pidx+1))/${TOTAL}]${NC} ${WHITE}${d}${NC} — done"
                    completed=$((completed + 1))
                else
                    local fs="${d//./_}"
                    echo -e "${BRED}[✗ $((pidx+1))/${TOTAL}]${NC} ${WHITE}${d}${NC} — FAILED  (log: ${fs}.log)"
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

    # ── Resumen ───────────────────────────────────────────────────────────────
    echo ""
    echo -e "${RED}┌─────────────────────────────────────────────────────────┐${NC}"
    echo -e "${RED}│${NC}  ${BGREEN}✓ Batch complete${NC}                                       ${RED}│${NC}"
    echo -e "${RED}├─────────────────────────────────────────────────────────┤${NC}"
    echo -e "${RED}│${NC}  Total       : ${WHITE}${TOTAL}${NC}"
    echo -e "${RED}│${NC}  Completed   : ${BGREEN}${completed}${NC}"
    echo -e "${RED}│${NC}  Failed      : ${BRED}${failed}${NC}"
    echo -e "${RED}├─────────────────────────────────────────────────────────┤${NC}"
    echo -e "${RED}│${NC}  Logs        : ${GRAY}${BATCH_LOG_DIR}${NC}"
    echo -e "${RED}│${NC}  Reports     : ${GRAY}${REPORTS_DIR}${NC}"
    echo -e "${RED}└─────────────────────────────────────────────────────────┘${NC}"
    echo ""
}

# =============================================================================
# AYUDA
# =============================================================================
cmd_help() {
    header "Help"
    echo -e "  ${WHITE}./crowsnest.sh targets enriquecer${NC}  ${GRAY}[path/domains.txt]${NC}"
    echo -e "  ${GRAY}Enrich a domain list with the OpenClaw LLM agents.${NC}"
    echo -e "  ${GRAY}Returns {name, domain, email, confidence} per target.${NC}"
    echo ""
    echo -e "  ${WHITE}./crowsnest.sh recon${NC}"
    echo -e "  ${GRAY}Score domains with checkdmarc. No Docker required.${NC}"
    echo -e "  ${GRAY}Identifies which domains have DMARC/SPF misconfigured.${NC}"
    echo ""
    echo -e "  ${WHITE}./crowsnest.sh report${NC}  ${GRAY}[domain] [\"Name\"]${NC}"
    echo -e "  ${GRAY}Full containerised scan → summary + detailed report JSON.${NC}"
    echo -e "  ${GRAY}The compliance framework is selected in config/compliance/.${NC}"
    echo ""
    echo -e "  ${WHITE}./crowsnest.sh diagnostico${NC}"
    echo -e "  ${GRAY}Re-renders the detailed report PDF from the latest session.${NC}"
    echo -e "  ${GRAY}No new scan — reuses the session artefacts.${NC}"
    echo ""
    echo -e "  ${WHITE}./crowsnest.sh trabajo${NC}"
    echo -e "  ${GRAY}Full pipeline against an authorised target (~35 min).${NC}"
    echo -e "  ${GRAY}Requires written authorisation. Produces the remediation PDF.${NC}"
    echo ""
    echo -e "  ${WHITE}./crowsnest.sh batch${NC}  ${GRAY}[path/list.txt]${NC}"
    echo -e "  ${GRAY}Scans a domain list in parallel (up to 5 workers).${NC}"
    echo -e "  ${GRAY}Uses the newest file in targets/ or a path given as argument.${NC}"
    echo -e "  ${GRAY}Produces the summary and detailed report for each domain.${NC}"
    echo ""
    echo -e "  ${WHITE}./crowsnest.sh webapp${NC}"
    echo -e "  ${GRAY}Starts the Flask dashboard on http://0.0.0.0:5000${NC}"
    echo -e "  ${GRAY}Manage targets, launch commands, watch output live.${NC}"
    echo ""
    echo -e "  ${GRAY}Planned: ./crowsnest.sh monitoreo${NC}"
    echo ""
}

# =============================================================================
# ENTRADA PRINCIPAL
# =============================================================================
case "${1:-help}" in
    targets)
        case "${2:-}" in
            enriquecer) cmd_targets_enriquecer "${@:3}" ;;
            *)
                error "Unknown subcommand: 'targets ${2:-}'"
                echo -e "  Usage: ${GRAY}./crowsnest.sh targets enriquecer [file]${NC}"
                exit 1 ;;
        esac ;;
    recon)       cmd_recon ;;
    report)      cmd_report "${@:2}" ;;
    diagnostico) cmd_diagnostico ;;
    trabajo)     cmd_trabajo ;;
    batch)       cmd_batch "${@:2}" ;;
    webapp)      bash "${SCRIPT_DIR}/webapp/run.sh" ;;
    help|--help|-h) cmd_help ;;
    *)
        error "Unknown command: '${1}'"
        echo ""
        cmd_help
        exit 1
        ;;
esac
