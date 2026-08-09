#!/usr/bin/env bash
# audit.sh — Escaneo OSINT dentro del contenedor
# Uso: bash audit.sh dominio.example

set -euo pipefail

TARGET="${1:-}"
if [[ -z "$TARGET" ]]; then
    echo "[ERROR] Specify a domain: bash audit.sh dominio.example"
    exit 1
fi

TIMESTAMP=$(date +"%Y%m%d_%H%M%S")
SAFE="${TARGET//./_}"
BASE="${2:-/home/work/results/${SAFE}_${TIMESTAMP}}"
FULL="${3:-}"

mkdir -p "${BASE}"/{subdomains,email,nuclei,technologies,http}

echo "[→] Starting OSINT scan: ${TARGET}"
echo "[→] Results in: ${BASE}"

# 1. CHECKDMARC — seguridad de correo
echo "[*] checkdmarc..."
checkdmarc "${TARGET}" -f json \
    > "${BASE}/email/checkdmarc_${TARGET}.json" 2>&1 && \
    echo "[✓] checkdmarc done" || \
    echo "[!] checkdmarc: check the results"

# 2. SUBFINDER — subdominios
echo "[*] subfinder..."
subfinder -d "${TARGET}" -all -silent \
    -o "${BASE}/subdomains/subfinder_${TARGET}.txt" 2>/dev/null && \
    echo "[✓] subfinder: $(wc -l < ${BASE}/subdomains/subfinder_${TARGET}.txt) subdomains" || \
    echo "[!] subfinder: no results"

# 3. HTTPX — hosts activos
if [[ -s "${BASE}/subdomains/subfinder_${TARGET}.txt" ]]; then
    echo "[*] httpx..."
    # Ruta absoluta: el venv (/opt/venv/bin) trae el httpx de Python (deps de
    # OpenClaw/Ollama) que eclipsa el binario de ProjectDiscovery en el PATH.
    /usr/local/bin/httpx \
        -l "${BASE}/subdomains/subfinder_${TARGET}.txt" \
        -title -tech-detect -status-code \
        -follow-redirects -timeout 10 -threads 50 \
        -json -silent \
        -o "${BASE}/http/httpx_${TARGET}.json" 2>/dev/null && \
        echo "[✓] httpx: $(wc -l < ${BASE}/http/httpx_${TARGET}.json) live hosts" || \
        echo "[!] httpx: no results"
else
    echo "[!] No subdomains, skipping httpx"
fi

# 4. WHATWEB — tecnologías
echo "[*] whatweb..."
whatweb "https://${TARGET}" \
    --log-json="${BASE}/technologies/whatweb_${TARGET}.json" \
    --aggression 1 2>/dev/null && \
    echo "[✓] whatweb done" || \
    echo "[!] whatweb: no results"

# 5. NUCLEI — vulnerabilidades (solo si hay hosts activos)
if [[ -s "${BASE}/http/httpx_${TARGET}.json" ]]; then
    echo "[*] nuclei..."
    jq -r '.url' "${BASE}/http/httpx_${TARGET}.json" 2>/dev/null \
        > "${BASE}/http/live_urls.txt"
    nuclei \
        -l "${BASE}/http/live_urls.txt" \
        -tags "exposure,misconfiguration,ssl,dns,config,headers" \
        -severity "info,low,medium,high,critical" \
        -json-export "${BASE}/nuclei/nuclei_${TARGET}.json" \
        -silent -timeout 10 2>/dev/null && \
        echo "[✓] nuclei done" || \
        echo "[!] nuclei: no results"
else
    echo "[!] No live hosts, skipping nuclei"
fi

# 6. NMAP — puertos/servicios (solo con --full, requiere hosts activos)
if [[ "$FULL" == "--full" ]] && [[ -s "${BASE}/http/httpx_${TARGET}.json" ]]; then
    echo "[*] nmap..."
    mkdir -p "${BASE}/nmap"
    # Extraer hostnames únicos de los URLs activos
    jq -r '.url // empty' "${BASE}/http/httpx_${TARGET}.json" 2>/dev/null \
        | sed 's|https\?://||' | cut -d'/' -f1 | cut -d':' -f1 | sort -u \
        > "${BASE}/nmap/live_hosts.txt"
    if [[ -s "${BASE}/nmap/live_hosts.txt" ]]; then
        nmap -sV -sC --open -T4 \
            -iL "${BASE}/nmap/live_hosts.txt" \
            -oJ "${BASE}/nmap/nmap_${TARGET}.json" \
            2>/dev/null && \
            echo "[✓] nmap done" || \
            echo "[!] nmap: no results or error"
    else
        echo "[!] No hosts for nmap"
    fi
fi

echo ""
echo "[✓] Scan complete: ${BASE}"
