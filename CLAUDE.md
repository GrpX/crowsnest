# Working on Crowsnest

Notes for anyone — human or agent — picking this repo up. Most of what
follows is not style preference: it records decisions that were made
deliberately, cost effort to make, and are easy to undo by accident.

## What this is

A passive reconnaissance orchestrator. Domains in, containerised OSINT
tooling over them, optional LLM enrichment, a technical assessment report
out, with a Flask dashboard streaming job output live.

## What this is not, on purpose

This started as internal tooling at a small infosec company. The entire
commercial layer was removed in a deliberate refactor — roughly 2,000 lines
across nine stages. **Do not re-add any of it**, even if a feature seems to
"want" it:

- **No email sending.** The Brevo client, templates, bounce sync and every
  wrapper are gone. The LLM agent that wrote cold outreach now writes report
  summaries instead.
- **No company scraping.** `scripts/scraper.py` (Google Places, Brave,
  Apollo) is gone. The pipeline takes a plain domain list as input, one per
  line, `#` comments a line. It does not discover its own targets.
- **No pricing.** Remediation is estimated in effort (`low`/`medium`/`high`),
  never in currency. There is a smoke test asserting no monetary fields
  reach the report JSON. If you find yourself adding `cost_uf` back, stop.
- **No conversion tracking.** No outreach state machine, no follow-up
  cadence, no lead qualification. A classifier whose whole purpose was
  ideal-customer profiling was deleted at the end of the refactor — it had
  survived four earlier sweeps because it never used the word "prospecto".
- **No quoting.** No proposal generator, no client management.

The dashboard shows targets and findings, not a funnel.

## The passive-only constraint is legal, not technical

Crowsnest never touches the target. Collection resolves against public
records, third-party indexes and DNS — never against the target's own
infrastructure. No port scans, no fuzzing, no authentication attempts, no
takeover verification.

**Do not add active probing against third-party infrastructure.** This is
not a missing feature. The reasoning is in the README's "Design constraints
— why passive-only" section, written by the repo owner from primary
sources, and the concrete tooling decisions are in
[`docs/tooling-decisions.md`](docs/tooling-decisions.md) — including two
cases worth knowing before proposing a tool:

- **subjack** was not adopted as-is. It reads the CNAME *and then requests
  the host* to fingerprint the response. That second step is a probe.
- **GitMiner** was rejected because it requires an authenticated session
  cookie, which ties recon to a real identifiable account.

If a tool sends a request to the target and interprets the response, it does
not belong here regardless of how gentle the request is.

**Do not write legal content.** The repo owner drafts anything about
regulation from primary sources. If a task seems to need statutory text,
leave a `TODO` marker and move on. Do not invent articles, laws or
citations.

## The LLM backend is swappable — keep it that way

**No model name may appear in code, tests or docs** — this file included,
which is why none is named here as an example. `openclaw/config.json` is the
only place one is written down. Local models age fast; the whole point is
that swapping one is a config edit.

Resolution order, all implemented in `openclaw/run_batch.py`:

| Thing | Order |
|---|---|
| Model | `CROWSNEST_MODEL_<AGENT>` → `CROWSNEST_MODEL` → `openclaw/config.json` |
| Endpoint | `LLM_BASE_URL` → `OLLAMA_HOST` → `llm.base_url` in config |

There is **no localhost fallback in code**. If none of the three is set the
client refuses to construct — a config error up front beats a network
timeout halfway through a batch.

`openclaw/tests/test_models.py` asserts that each agent resolves to *some*
model available in the configured backend, never that it is a particular
one. If you add an assertion naming a model, you have reintroduced the
problem the test exists to prevent.

Three agents: `orquestador`, `descubridor`, `summarizer`.

## The report generates without an LLM backend

This is load-bearing. `scripts/nuclei_to_report.py` has no LLM dependency at
all. The summarizer's output reaches it through an optional `--summary` file
and lands in `executive_summary.narrative`; the template renders that
section only `{% if executive_summary.narrative %}`.

With no backend, no summary file, or a missing summary file, the PDF still
renders. A smoke test covers exactly this. Do not make the report engine
call an LLM.

## Yes/no prompts accept both "y" and "s"

`webapp/wrappers/*.py` drive `crowsnest.sh`'s interactive flows by writing
keystrokes to stdin — `stdin = f"{dominio}\n{nombre}\ny\n"`.

The prompts read `[y/N]` and the comparisons are
`[[ "${resp,,}" == "y" || "${resp,,}" == "s" ]]`. Both letters are accepted
deliberately, so a wrapper that was not updated still works.

**Changing a prompt without its comparison and the wrappers breaks every
dashboard button silently** — no error, the flow just cancels. If you touch
one of the three, touch all three.

## Single sources of truth

Three things are declared exactly once. Each was duplicated before and drifted.

- **`lib/states.py`** — the target lifecycle
  (`queued → recon → enriched → reported`, plus `skipped` as a branch).
  Every Python consumer imports it, including the heredocs inside
  `crowsnest.sh`, which insert the repo root into `sys.path`. The frontend
  does **not** redeclare them: `webapp/app.py` passes them to the template,
  which publishes `window.TARGET_STATES` and renders the filter buttons in a
  Jinja loop. Adding a state means editing one file.
- **`templates/crowsnest_logo.svg`** (wordmark) and **`templates/crowsnest_mark.svg`**
  (compact mark) — `lib/branding.py` reads both; `generate_pdf.py` takes the
  data URIs, the webapp injects the raw wordmark markup through a context
  processor and uses the mark's data URI as favicon. There is no embedded
  fallback copy of either on purpose — a second declaration is what this
  replaced. A smoke test derives a structural signature from each SVG at
  run time (its longest `<path d>`, or its longest `<text>` if that's more
  distinctive) and fails if that signature appears in any other file.
- **`lib/version.py`** — the running revision, derived from git. There is no
  `VERSION` file and no tags, so any hardcoded version number would be
  fiction. Renders nothing outside a git checkout.

## CI

`.github/workflows/ci.yml`, three jobs: ruff, pytest, and a shell job.
Everything is pinned — actions, Python, ruff, every pip dependency. No
floating refs.

CI runs with **no LLM backend, no Docker and no API keys**. Backend tests
must therefore skip, and a dedicated step **asserts that the skip actually
happened**. If those tests pass in CI, either an endpoint leaked in or they
stopped checking one — both make the test decorative, and the build fails to
say so. `pytest` runs with `-r a` so every skip prints its reason.

Ruff's rule selection lives in `pyproject.toml` rather than relying on the
tool's default, which changes between releases.

## Code comments stay in Spanish

The interface, docs, console output and commit messages are in English. The
code comments are in Spanish and were deliberately left that way. Do not
translate them.

## Still open

- **Logo.** The current wordmark is plain typography, a placeholder for a
  real one. Replacing it is a single file — see the branding note above.
- **Final security grep.** Run before publishing, over the whole tree.
- **Visual PDF review.** `examples/sample_report.pdf` has been checked by
  text extraction, not read page by page.
- **Create the remote and push.** Not done. See below.

## No remote, no push

**The repository has no remote configured and nothing has been pushed.**
Do not create a remote, add one, or push, until the owner authorises it
explicitly. Local commits are fine.

One reason this matters concretely: the private repo this was derived from
has real API credentials in its git history, on a remote. That is exactly
the mistake this repo exists to avoid repeating.
