# OpenClaw Orchestrator

Módulo de enriquecimiento de prospectos de **S.I.N.S.** (SINS Is Not Static SpA).

Toma un JSON de **Google Places** y devuelve prospectos PYME enriquecidos
mediante una cadena de **3 agentes Ollama** locales, con scraping de los sitios
web vía **Crawl4AI**.

```
Google Places JSON  ──►  [orquestador] ──► [descubridor] ──► [redactor]  ──►  prospectos enriquecidos
                              triage          scraping +          mensaje
                                              extracción          de abordaje
```

## Arquitectura de agentes

| Agente        | Modelo Ollama | Rol |
|---------------|---------------|-----|
| `orquestador` | `qwen2.5:7b`  | Triage del negocio: ¿es una PYME viable? Define sector, cargo objetivo y ángulo de abordaje. |
| `descubridor` | `qwen2.5:7b`  | Extrae dominio, email de contacto y cargo objetivo desde el contenido del sitio web. |
| `redactor`    | `llama3.1:8b` | Redacta el mensaje de contacto en frío en español de Chile. |

`qwen2.5:7b` se usa donde importa el seguimiento estricto de instrucciones y la
salida JSON; `llama3.1:8b` para la redacción en prosa. Los modelos, prompts y
temperaturas se ajustan en [`config.json`](config.json).

## Salida

Lista JSON ordenada por confianza descendente. Cada prospecto:

```json
{
  "empresa": "Clínica Dental Sonríe",
  "dominio": "clinicasonrie.cl",
  "cargo_objetivo": "Gerente General",
  "email": "contacto@clinicasonrie.cl",
  "mensaje": "Estimado/a Gerente General...",
  "confianza": 0.85
}
```

`confianza` (0.0–1.0) es una métrica **objetiva** según señales concretas:
dominio encontrado (+0.30), sitio scrapeado con Crawl4AI (+0.25) o con el
fallback requests (+0.15), email válido hallado en el sitio (+0.25) y cargo
objetivo específico (+0.20). Si el orquestador marca el negocio como no viable,
la confianza se reduce a la mitad.

## Requisitos previos

**Hardware mínimo:** 16 GB de RAM — los dos modelos se ejecutan localmente vía
Ollama. En disco ocupan **~9 GB combinados** (`qwen2.5:7b` ~4.7 GB +
`llama3.1:8b` ~4.9 GB).

1. **Ollama** corriendo en el host:
   ```bash
   ollama serve            # si no está como servicio
   ```
2. **Modelos descargados** (~9 GB combinados en disco):
   ```bash
   ollama pull qwen2.5:7b && ollama pull llama3.1:8b
   ```
3. **Dependencias Python** (solo si se ejecuta fuera del contenedor):
   ```bash
   pip install -r openclaw/requirements.txt
   crawl4ai-setup          # descarga el navegador headless de Crawl4AI
   ```

El contenedor Docker `sins-workstation-ciber-workstation` ya trae el cliente
Ollama, Crawl4AI y el navegador headless (ver [`../Dockerfile`](../Dockerfile)).

## Uso

### Vía `sins.sh` (recomendado)

```bash
./sins.sh prospectos enriquecer reportes/google_places.json
```

Sin argumento, busca el `google_places*.json` más reciente en `targets/` o
`reportes/`. La salida se guarda en `reportes/prospectos_enriquecidos_<fecha>.json`.

`sins.sh` ejecuta el batch **dentro del contenedor Docker** si la imagen está
construida (trae Crawl4AI + cliente Ollama); si no, cae al Python del host.

### Directo

```bash
python3 openclaw/run_batch.py --input google_places.json --output prospectos.json
cat google_places.json | python3 openclaw/run_batch.py
```

Opciones: `--config`, `--limit N`, `--skip-preflight`. El log va a `stderr`;
sin `--output`, el JSON se escribe en `stdout` (apto para piping).

## Preflight y tests

Antes de cada batch, `run_batch.py` ejecuta un **preflight** que verifica que
Ollama responda y que `qwen2.5:7b` y `llama3.1:8b` estén disponibles. Si falta
un modelo, aborta con código de salida `2` y la instrucción `ollama pull` exacta.

Los tests verifican lo mismo de forma independiente:

```bash
pytest openclaw/tests/                      # con pytest
python3 openclaw/tests/test_models.py       # sin pytest (runner propio)
```

Los tests de configuración siempre corren. Los de Ollama se **saltan** si el
servidor no responde y **fallan** si responde pero falta algún modelo.

## Configuración por entorno

El módulo se ejecuta dentro del contenedor Docker de S.I.N.S. La diferencia
entre entornos está en el montaje de volúmenes y el binario de Docker.
`sins.sh prospectos enriquecer` **detecta el entorno automáticamente**
(`/proc/version`) y aplica lo correcto.

### Fedora KDE (SELinux)

SELinux exige el sufijo `:z` en los volúmenes para que el contenedor pueda
leerlos. `sins.sh` lo añade solo. Para ejecutar `run_batch.py` a mano:

```bash
docker run --rm --network host \
  -e OLLAMA_HOST=http://localhost:11434 \
  -v "$PWD/openclaw:/home/work/openclaw:z" \
  -v "$PWD/reportes:/home/work/results:z" \
  -v "$PWD/reportes/google_places.json:/home/work/input/places.json:ro,z" \
  sins-workstation-ciber-workstation \
  python3 /home/work/openclaw/run_batch.py \
    --input /home/work/input/places.json \
    --output /home/work/results/prospectos_enriquecidos.json
```

`--network host` permite que el contenedor alcance Ollama en `localhost:11434`.

### Windows 11 + WSL2

WSL2 **no usa SELinux**: se omite el sufijo `:z`. Docker normalmente requiere
`sudo`. `sins.sh` detecta WSL2 y usa `sudo docker` sin `:z` automáticamente.
Para forzar el binario manualmente:

```bash
DOCKER_BIN="sudo docker" ./sins.sh prospectos enriquecer reportes/google_places.json
```

A mano, la misma orden que en Fedora pero con `sudo docker` y sin `:z`:

```bash
sudo docker run --rm --network host \
  -e OLLAMA_HOST=http://localhost:11434 \
  -v "$PWD/openclaw:/home/work/openclaw" \
  -v "$PWD/reportes:/home/work/results" \
  -v "$PWD/reportes/google_places.json:/home/work/input/places.json:ro" \
  sins-workstation-ciber-workstation \
  python3 /home/work/openclaw/run_batch.py \
    --input /home/work/input/places.json \
    --output /home/work/results/prospectos_enriquecidos.json
```

Ollama instalado dentro de la distro WSL2 escucha en `localhost:11434`; con
`--network host` el contenedor lo alcanza sin configuración extra.

## Variables de entorno

| Variable      | Por defecto                  | Uso |
|---------------|------------------------------|-----|
| `OLLAMA_HOST` | `http://localhost:11434`     | Sobreescribe el host de Ollama de `config.json`. |
| `DOCKER_BIN`  | `docker` / `sudo docker` (WSL2) | Binario de Docker que usa `sins.sh`. |

## Archivos

```
openclaw/
├── config.json          # agentes, modelos, parámetros de Crawl4AI y batch
├── run_batch.py          # orquestador (preflight + pipeline + I/O)
├── requirements.txt      # dependencias Python
├── README.md             # este archivo
└── tests/
    └── test_models.py    # verifica config y disponibilidad de modelos
```
