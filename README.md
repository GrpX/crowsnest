# Crowsnest

Passive reconnaissance orchestrator. It takes a list of domains, runs
containerised OSINT tooling against them, enriches the findings with LLM
agents, and renders a technical assessment report — with a web dashboard that
streams every job's output live.

Nothing it does touches the target: no exploitation, no authentication
attempts, no traffic beyond what an ordinary visitor generates.

## Pipeline

```
domains.txt
    │
    ▼
┌─────────────┐   subfinder · httpx · nuclei · checkdmarc · whatweb · nmap
│    recon    │   containerised, results written per session
└──────┬──────┘
       ▼
┌─────────────┐   3 LLM agents: triage, discovery, summary
│  enrichment │   optional — the pipeline runs without a backend
└──────┬──────┘
       ▼
┌─────────────┐   findings → severity → compliance controls → effort
│   report    │   Jinja2 + WeasyPrint → PDF
└──────┬──────┘
       ▼
┌─────────────┐   job lifecycle, findings by severity, live log stream
│  dashboard  │   Flask + SSE
└─────────────┘
```

A target moves through `queued → recon → enriched → reported`, with `skipped`
as the branch for domains the prefilter rejects. Those five states are
declared once, in `lib/states.py`, and every consumer — shell heredocs,
Python modules, the web API and the frontend — reads them from there.

## Pluggable by design

Three unrelated concerns follow the same pattern: a directory of declarative
config, selected at runtime, with nothing about the choice compiled in.

| Concern | Declared in | Selected by |
|---|---|---|
| OSINT providers | `config/provider-config.example.yaml` | copy to `config/provider-config.yaml`, add keys |
| LLM backend | `openclaw/config.json` → `llm` | `LLM_BASE_URL`, `CROWSNEST_MODEL_<AGENT>` |
| Compliance mapping | `config/compliance/*.yaml` | `--compliance <id>` or `CROWSNEST_COMPLIANCE_FRAMEWORK` |

**No model name appears anywhere in the code.** Agents resolve their model
from config with an environment override, and the test suite asserts that
each agent declares *some* model available in the configured backend — never
that it is a particular one. Local models age fast; swapping one is a config
edit, not a patch.

The same holds for compliance. A framework file declares an id, a name and a
mapping from finding tag to control; the report renders whatever it declares.
The bundled example is OWASP Top 10 because it is a public taxonomy that
needs no legal interpretation. If several frameworks are present and none is
selected, the engine exits and lists them rather than guessing which one a
report was written against.

That indirection exists for a concrete reason. The pipeline was originally
built against one jurisdiction's regulation, hardcoded through the report
templates — two near-duplicate templates whose only real difference was
which statute they cited. Making the mapping a config file collapsed them
into one and removed the assumption that the reader's obligations are
knowable from the code. Jurisdiction is an input here, not a scope.

## Design constraints — why passive-only

<!-- TODO: passive-only rationale -->

## Stack

Python · Docker Compose · Flask + SSE · Jinja2 + WeasyPrint · Crawl4AI ·
an Ollama-compatible LLM endpoint.

Recon tooling runs inside the container: subfinder, httpx, nuclei,
checkdmarc, whatweb, nmap, amass.

## Example output

[`examples/sample_report.pdf`](examples/sample_report.pdf) — a full report
generated against a fictitious target with the OWASP Top 10 framework active:
executive summary, risk scenarios, findings table with severity, per-finding
evidence, prioritised remediation plan with effort estimates, and the
compliance control mapping.

[`examples/sample_target.json`](examples/sample_target.json) — the target
schema, with entirely fictitious entries.

## Quick start

```bash
git clone <this-repo> crowsnest && cd crowsnest

cp .env.example .env                                    # API keys, all optional
cp config/provider-config.example.yaml \
   config/provider-config.yaml                          # subfinder providers

docker compose build                                    # builds crowsnest:latest

mkdir -p targets && printf 'example.com\nexample.org\n' > targets/domains.txt
./crowsnest.sh recon                                    # score domains, no Docker
./crowsnest.sh report example.com "Example"             # full scan → report JSON
./crowsnest.sh webapp                                   # dashboard on :5000
```

Every API key is optional: without them the recon stage simply queries fewer
sources. Without an LLM backend the enrichment stage is skipped and the
report is generated without its narrative summary — the PDF still renders.

Full install in [`SETUP.md`](SETUP.md); the agent layer in
[`openclaw/README.md`](openclaw/README.md); adding a compliance framework in
[`config/compliance/README.md`](config/compliance/README.md).

## Commands

| Command | What it does |
|---|---|
| `./crowsnest.sh recon` | Score domains with checkdmarc. No Docker required. |
| `./crowsnest.sh report <domain> "<name>"` | Full containerised scan → report JSON |
| `./crowsnest.sh diagnostico` | Re-render the detailed report from the latest session |
| `./crowsnest.sh trabajo` | Full pipeline against an authorised target |
| `./crowsnest.sh batch [list.txt]` | Process a domain list in parallel |
| `./crowsnest.sh targets enriquecer [list.txt]` | Run the LLM enrichment agents |
| `./crowsnest.sh webapp` | Start the dashboard |

## Layout

```
crowsnest.sh            CLI entry point
lib/                    states, branding, revision — shared by every consumer
config/
  compliance/           one file per compliance framework
  provider-config.example.yaml
scripts/
  audit.sh              recon inside the container
  nuclei_to_report.py   findings → structured report JSON
  generate_pdf.py       report JSON → PDF
openclaw/               LLM agent layer (see its README)
templates/              report template + wordmark
webapp/                 Flask dashboard, SSE log streaming
examples/               sample report and target schema
```

## What is not in this repository

Real target data, scan results and generated reports stay out: `db/`,
`targets/` and `reportes/` are ignored, as is any provider config holding
real keys. The tracked provider config is an empty `.example` template.

## License

MIT — see [`LICENSE`](LICENSE).
