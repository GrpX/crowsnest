# =============================================================================
# CIBER-WORKSTATION — Imagen OSINT S.I.N.S.
# Usa binarios precompilados de ProjectDiscovery (versiones fijas)
# =============================================================================
FROM ubuntu:24.04

LABEL maintainer="S.I.N.S. SpA"

ENV DEBIAN_FRONTEND=noninteractive
ENV PYTHONDONTWRITEBYTECODE=1
ENV PYTHONUNBUFFERED=1
WORKDIR /home/work

# 1. DEPENDENCIAS DEL SISTEMA
RUN apt-get update -y && apt-get install -y --no-install-recommends \
    curl wget git unzip zip \
    python3 python3-pip python3-venv \
    dnsutils whois nmap \
    jq vim nano less ca-certificates \
    && apt-get clean && rm -rf /var/lib/apt/lists/*

# 2. HERRAMIENTAS PROJECTDISCOVERY — binarios precompilados
RUN mkdir -p /usr/local/bin

# subfinder v2.14.0
RUN wget -q "https://github.com/projectdiscovery/subfinder/releases/download/v2.14.0/subfinder_2.14.0_linux_amd64.zip" \
    && unzip -q subfinder_2.14.0_linux_amd64.zip subfinder \
    && mv subfinder /usr/local/bin/ \
    && rm subfinder_2.14.0_linux_amd64.zip

# httpx v1.9.0
RUN wget -q "https://github.com/projectdiscovery/httpx/releases/download/v1.9.0/httpx_1.9.0_linux_amd64.zip" \
    && unzip -q httpx_1.9.0_linux_amd64.zip httpx \
    && mv httpx /usr/local/bin/ \
    && rm httpx_1.9.0_linux_amd64.zip

# nuclei v3.8.0
RUN wget -q "https://github.com/projectdiscovery/nuclei/releases/download/v3.8.0/nuclei_3.8.0_linux_amd64.zip" \
    && unzip -q nuclei_3.8.0_linux_amd64.zip nuclei \
    && mv nuclei /usr/local/bin/ \
    && rm nuclei_3.8.0_linux_amd64.zip

# dnsx v1.2.3
RUN wget -q "https://github.com/projectdiscovery/dnsx/releases/download/v1.2.3/dnsx_1.2.3_linux_amd64.zip" \
    && unzip -q dnsx_1.2.3_linux_amd64.zip dnsx \
    && mv dnsx /usr/local/bin/ \
    && rm dnsx_1.2.3_linux_amd64.zip

# 3. WHATWEB
RUN apt-get update -y && apt-get install -y --no-install-recommends whatweb \
    && apt-get clean && rm -rf /var/lib/apt/lists/*

# 4. HERRAMIENTAS PYTHON
RUN python3 -m venv /opt/venv
ENV PATH="/opt/venv/bin:/usr/local/bin:$PATH"
ENV VIRTUAL_ENV=/opt/venv
RUN pip install --upgrade pip && pip install \
    checkdmarc trustymail h8mail theHarvester \
    shodan requests jinja2 pandas openpyxl \
    python-dotenv rich

# 4b. OPENCLAW ORCHESTRATOR — cliente Ollama + Crawl4AI
# Enriquecimiento de targets PYME con agentes Ollama locales.
RUN pip install \
    ollama \
    crawl4ai \
    playwright \
    beautifulsoup4 lxml \
    pytest

# Navegador headless (Chromium) que usa Crawl4AI para el scraping de sitios PYME.
# --with-deps instala tambien las librerias de sistema necesarias.
RUN apt-get update -y \
    && playwright install --with-deps chromium \
    && (crawl4ai-setup || true) \
    && apt-get clean && rm -rf /var/lib/apt/lists/*

# 5. CONFIGURACION
RUN mkdir -p /root/.config/subfinder /root/.config/amass /root/.nuclei-templates
RUN echo "# Subfinder provider config" > /root/.config/subfinder/provider-config.yaml
RUN echo "# Amass config" > /root/.config/amass/config.ini

# 6. ACTUALIZAR TEMPLATES NUCLEI
RUN nuclei -update-templates -silent || true

# 7. SCRIPTS Y DIRECTORIOS
COPY scripts/ /home/work/scripts/
COPY openclaw/ /home/work/openclaw/
RUN chmod +x /home/work/scripts/*.sh /home/work/openclaw/run_batch.py 2>/dev/null || true
RUN mkdir -p \
    /home/work/results/subdomains \
    /home/work/results/email \
    /home/work/results/nuclei \
    /home/work/results/technologies \
    /home/work/results/http \
    /home/work/results/reports \
    /home/work/targets

RUN chmod -R 777 /home/work
CMD ["/bin/bash"]
