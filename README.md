# S.I.N.S. — Pipeline OSINT de auditoría de seguridad web

Sistema de reconocimiento de superficie de ataque y generación de informes
de ciberseguridad, diseñado para operar con mínima intervención humana:
desde el descubrimiento de objetivos hasta el informe ejecutivo en PDF.

![Dashboard](docs/screenshots/dashboard.png)

*Los campos de dominio/identificador/email están anonimizados a propósito
para esta versión de portfolio — el sistema opera con datos reales.*

## Qué hace

1. **Descubrimiento** — scraping multi-fuente de objetivos potenciales
   (`scripts/scraper.py`)
2. **Reconocimiento pasivo** — orquesta subfinder, nuclei, httpx, whatweb y
   checkdmarc sobre el objetivo, todo containerizado
3. **Enriquecimiento con IA** — 3 agentes LLM locales (Ollama, qwen2.5 +
   llama3.1) orquestados para clasificar hallazgos, descubrir contactos y
   validar resultados sin depender de APIs pagas (`openclaw/`)
4. **Generación de informes** — motor Jinja2 + WeasyPrint que convierte
   hallazgos técnicos en informes ejecutivos en PDF, con distintos frameworks
   legales según el caso de uso (Ley 21.719 / Ley 21.663, Chile)
5. **Dashboard web** — Flask, con streaming de logs en vivo del pipeline
   corriendo (`webapp/`)

## Ejemplo de output

[`examples/sample_report.pdf`](examples/sample_report.pdf) — informe completo
generado por el pipeline sobre un objetivo ficticio, mostrando el formato de
salida: resumen ejecutivo, análisis de impacto de negocio, plan de
remediación con costos, tabla de hallazgos y marco legal aplicable.

## Stack técnico

Python · Docker/Docker Compose · Ollama (LLMs locales) · Flask ·
WeasyPrint + Jinja2 · subfinder/nuclei/httpx/whatweb (ProjectDiscovery) ·
Brevo API (transaccional) · Crawl4AI

## Uso rápido

```bash
cp .env.example .env && nano .env
docker-compose build
./sins.sh captacion
./sins.sh flash
```

## Documentación
- `SETUP.md`             — Instalación en Fedora KDE y Windows 11 WSL2
- `openclaw/README.md`   — OpenClaw Orchestrator: enriquecimiento de prospectos
  con agentes Ollama + Crawl4AI (configuración Docker para Fedora y WSL2)
- `docs/base_legal_oiv.md` — Ejemplo de análisis legal aplicado (Ley 21.663,
  Marco de Ciberseguridad de Chile) integrado al framework de informes

## Datos

Este repositorio contiene **solo código**. La base de datos de prospectos
(`db/prospectos.json`) y los objetivos de escaneo (`targets/`) quedan fuera
por contener datos reales de terceros.

`examples/sample_prospecto.json` documenta el esquema de datos con entradas
**ficticias**, para poder ejecutar el pipeline sin datos reales.
