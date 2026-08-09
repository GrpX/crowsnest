# OpenClaw Orchestrator

The LLM agent layer of Crowsnest. It takes a list of target domains, scrapes
each site with Crawl4AI, and runs three agents over the result to enrich the
target record and draft the report's executive summary.

```
domains.txt ──► [orquestador] ──► [descubridor] ──► [summarizer] ──► enriched targets
                    triage          scrape +          executive
                                    extraction         summary
```

This layer is **optional**. If no LLM endpoint is reachable, the recon and
report stages still run — the report is simply generated without its
narrative summary.

## The backend is swappable

No model name exists anywhere in the code. Each agent resolves its model at
runtime, in this order:

1. `CROWSNEST_MODEL_<AGENT>` — e.g. `CROWSNEST_MODEL_SUMMARIZER`
2. `CROWSNEST_MODEL` — applies to every agent
3. the `model` field of that agent in [`config.json`](config.json)

If an agent resolves to nothing, startup fails with a configuration error
rather than a confusing runtime one.

The endpoint follows the same principle:

1. `LLM_BASE_URL`
2. `OLLAMA_HOST`
3. `llm.base_url` in [`config.json`](config.json)

There is no hardcoded localhost fallback. With none of the three set, the
client refuses to construct — guessing an endpoint turns a config mistake
into a network timeout halfway through a batch.

Local models age quickly, so nothing here commits to one. Point
`LLM_BASE_URL` at any Ollama-compatible server and set the model names in
config; the pipeline neither knows nor cares which models they are.

## Agents

| Agent | Role | Output format |
|---|---|---|
| `orquestador` | Triage: is the target analysable, what is the angle | JSON |
| `descubridor` | Extracts domain and published contact addresses from the site | JSON |
| `summarizer` | Writes the report's executive summary in English from the findings | text |

Models, prompts, temperatures and token budgets all live in
[`config.json`](config.json). Adding or retuning an agent is a config edit.

## Output

A JSON list ordered by descending confidence. One entry per target:

```json
{
  "name": "example.com",
  "dominio": "example.com",
  "email": "contact@example.com",
  "emails_encontrados": ["contact@example.com"],
  "summary": "The assessment of example.com revealed …",
  "summary_status": "ok",
  "confianza": 0.85
}
```

`confianza` (0.0–1.0) is computed from concrete signals, not from the model:
domain resolved (+0.30), site scraped with Crawl4AI (+0.25) or the requests
fallback (+0.15), a valid address found on the site (+0.25), a specific
target role identified (+0.20). If the orquestador marks the target as not
viable, the score is halved.

`summary_status` is one of `ok`, `retry_ok`, `failed` or `not_requested`.
These are **not** target lifecycle states — those live in `lib/states.py` and
are unrelated.

## Prerequisites

Whatever your backend needs. For a local Ollama server:

```bash
ollama serve                       # if not already running as a service
ollama pull <model>                # the models named in config.json
```

Running 7–8B models locally wants roughly 16 GB of RAM and a few GB of disk
per model. A remote endpoint has no such requirement on this machine.

Python dependencies, only when running outside the container:

```bash
pip install -r openclaw/requirements.txt
crawl4ai-setup                     # fetches Crawl4AI's headless browser
```

The `crowsnest:latest` image already ships the client, Crawl4AI and the
headless browser — see [`../Dockerfile`](../Dockerfile).

## Usage

### Through `crowsnest.sh` (recommended)

```bash
./crowsnest.sh targets enriquecer targets/domains.txt
```

Without an argument it uses `targets/domains.txt`. Output is written to
`reports/targets_enriquecidos_<date>.json`.

The wrapper runs the batch **inside the container** when the image is built,
and falls back to the host Python otherwise.

### Directly

```bash
python3 openclaw/run_batch.py --input targets/domains.txt --output enriched.json
cat targets/domains.txt | python3 openclaw/run_batch.py
```

The input is plain text: one domain per line, `#` comments a line, duplicates
and URL forms are normalised away.

Options: `--config`, `--limit N`, `--skip-preflight`, `--no-summary`,
`--no-db-sync`, `--include-discarded`. Logs go to `stderr`; without
`--output` the JSON goes to `stdout`, so it pipes.

## Preflight and tests

Before each batch, `run_batch.py` runs a preflight that checks the backend
responds and that every model declared by an agent is available there. A
missing model aborts with exit code `2`, naming it.

```bash
pytest openclaw/tests/                      # with pytest
python3 openclaw/tests/test_models.py       # standalone runner
```

The tests know no model names. They assert that every agent resolves to
*some* model, that the environment can override both model and endpoint, and
that whatever is declared exists in the configured backend. Configuration
tests always run; backend tests **skip** when nothing is reachable and
**fail** only when the backend answers and a declared model is absent.

## Environment differences

`crowsnest.sh targets enriquecer` detects the environment from `/proc/version`
and adjusts volume mounts and the Docker binary automatically.

**SELinux hosts (Fedora)** need the `:z` suffix on mounts. Run by hand:

```bash
docker run --rm --network host \
  -e LLM_BASE_URL=http://localhost:11434 \
  -v "$PWD/openclaw:/home/work/openclaw:z" \
  -v "$PWD/reports:/home/work/results:z" \
  -v "$PWD/targets/domains.txt:/home/work/input/domains.txt:ro,z" \
  crowsnest:latest \
  python3 /home/work/openclaw/run_batch.py \
    --input /home/work/input/domains.txt \
    --output /home/work/results/targets_enriquecidos.json
```

`--network host` lets the container reach a backend on the host's localhost.

**WSL2** does not use SELinux, so drop `:z`; Docker there usually needs
`sudo`. Both are handled automatically, or force it:

```bash
DOCKER_BIN="sudo docker" ./crowsnest.sh targets enriquecer targets/domains.txt
```

## Environment variables

| Variable | Purpose |
|---|---|
| `LLM_BASE_URL` | Backend endpoint. Takes precedence over everything else. |
| `OLLAMA_HOST` | Same, kept for compatibility with the Ollama convention. |
| `CROWSNEST_MODEL_<AGENT>` | Override one agent's model. |
| `CROWSNEST_MODEL` | Override every agent's model. |
| `CROWSNEST_TARGETS_DB` | Path to the target database for the write-back step. |
| `CROWSNEST_REPORTS_DIR` | Where results are written. |
| `DOCKER_BIN` | Docker invocation used by `crowsnest.sh`. |

## Files

```
openclaw/
├── config.json          agents, models, endpoint, Crawl4AI and batch settings
├── run_batch.py         orchestrator: preflight, pipeline, I/O
├── enrich_targets.py    backfills scan_data into the target database
├── requirements.txt
├── README.md            this file
└── tests/
    └── test_models.py   config coherence and backend availability
```
