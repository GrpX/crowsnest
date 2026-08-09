# Setup

Linux and WSL2. Native Windows is not supported: WeasyPrint depends on GTK
libraries that are painful to obtain on Windows, and the recon container
expects a Linux host. Under WSL2 everything runs inside the Linux
filesystem, so the same instructions apply.

---

## 1. System dependencies

### Fedora

```bash
sudo dnf install -y docker docker-compose python3 python3-pip
sudo systemctl enable --now docker
sudo usermod -aG docker "$USER"      # log out and back in for the group to apply
```

### Debian / Ubuntu

```bash
sudo apt update
sudo apt install -y docker.io docker-compose-v2 python3 python3-pip
sudo systemctl enable --now docker
sudo usermod -aG docker "$USER"      # log out and back in
```

### WSL2 (Windows 11)

Install the distro from an elevated PowerShell:

```powershell
wsl --install -d Ubuntu-24.04
```

Then install Docker Desktop, tick **"Use WSL2 instead of Hyper-V"** during
setup, and enable your distro under *Settings → Resources → WSL Integration*.
Docker Desktop provides the daemon, so skip the `docker.io` package above and
run only the Python part.

**Work inside the Linux filesystem** (`~/crowsnest`), never under `/mnt/c/`.
Windows-mounted paths are slow and break container file permissions.

### checkdmarc

The `recon` command runs on the host without Docker, so it needs checkdmarc:

```bash
pip install --user checkdmarc            # Fedora
pip install --user --break-system-packages checkdmarc   # Debian/Ubuntu/WSL2

checkdmarc --version
```

---

## 2. Get the project

```bash
git clone <this-repo> crowsnest
cd crowsnest
chmod +x crowsnest.sh
```

## 3. Configure

```bash
cp .env.example .env
$EDITOR .env
```

Every key is optional. Without them the recon stage queries fewer sources;
nothing fails.

Subfinder reads its providers from a separate file, which is git-ignored so
your keys never end up in a commit:

```bash
cp config/provider-config.example.yaml config/provider-config.yaml
$EDITOR config/provider-config.yaml
```

### Environment variables

| Variable | Purpose |
|---|---|
| `LLM_BASE_URL` | LLM endpoint. Falls back to `OLLAMA_HOST`, then `llm.base_url` in `openclaw/config.json`. |
| `CROWSNEST_MODEL_<AGENT>` | Override one agent's model (`ORQUESTADOR`, `DESCUBRIDOR`, `SUMMARIZER`). |
| `CROWSNEST_MODEL` | Override every agent's model at once. |
| `CROWSNEST_COMPLIANCE_FRAMEWORK` | Active compliance framework id. |
| `CROWSNEST_TARGETS_DB` | Path to the target database. Defaults to `db/targets.json`. |
| `CROWSNEST_REPORTS_DIR` | Where reports are written. |
| `CROWSNEST_WEBAPP_PASSWORD` | Dashboard password. Generated and written to `.env` if unset. |
| `CROWSNEST_WEBAPP_SECRET_KEY` | Flask session key. Generated if unset. |
| `DOCKER_BIN` | Docker invocation, e.g. `sudo docker` on a locked-down host. |

## 4. Build the container

```bash
docker compose build     # ~10 min the first time
```

This produces the image `crowsnest:latest`. The name is pinned in
`docker-compose.yml` so it does not depend on the directory name.

## 5. Verify

```bash
./crowsnest.sh help

mkdir -p targets
printf 'example.com\n' > targets/domains.txt
./crowsnest.sh recon                      # host-only, no Docker

./crowsnest.sh report example.com "Example"   # containerised scan
```

If you also want the LLM enrichment stage, check the agent layer separately:

```bash
python3 openclaw/tests/test_models.py
```

The configuration tests always run. The backend tests **skip** — they do not
fail — when no LLM endpoint is reachable, so a machine without one still
gets a green suite.

---

## 6. Daily use

```bash
# 1. put the domains you are authorised to scan in a list
$EDITOR targets/domains.txt        # one per line, '#' comments a line

# 2. cheap pass: DMARC/SPF/TLS scoring, no container
./crowsnest.sh recon

# 3. full scan and report for one domain
./crowsnest.sh report example.com "Example"

# 4. or process the whole list in parallel
./crowsnest.sh batch targets/domains.txt

# 5. dashboard, with live log streaming
./crowsnest.sh webapp        # http://0.0.0.0:5000
```

Reports land in `reports/<domain>_<timestamp>/`. That directory is
git-ignored.

### Opening a report from WSL2

```bash
explorer.exe .
# or browse to:
# \\wsl.localhost\Ubuntu-24.04\home\<user>\crowsnest\reports\
```

---

## 7. Layout

```
crowsnest/
├── crowsnest.sh                 CLI entry point
├── docker-compose.yml           builds crowsnest:latest
├── Dockerfile
├── .env                         your keys — git-ignored
├── .env.example
├── lib/                         states, branding, revision
├── config/
│   ├── compliance/              one file per compliance framework
│   ├── config.yaml              subfinder flags
│   ├── provider-config.example.yaml
│   └── provider-config.yaml     your provider keys — git-ignored
├── scripts/
│   ├── audit.sh                 recon, runs inside the container
│   ├── nuclei_to_report.py      findings → report JSON
│   └── generate_pdf.py          report JSON → PDF
├── openclaw/                    LLM agent layer
├── templates/                   report template + wordmark
├── webapp/                      Flask dashboard
├── examples/                    sample report and target schema
├── targets/                     your domain lists — git-ignored
├── db/                          target database — git-ignored
└── reports/                     scan output — git-ignored
```

## Troubleshooting

**`La imagen 'crowsnest:latest' no está construida`** — run
`docker compose build`. The image name is pinned in `docker-compose.yml`; if
an earlier build left images under a different name, `docker images` will
show them and `docker rmi` removes them.

**Docker needs sudo** — either add yourself to the `docker` group and
re-login, or run with `DOCKER_BIN="sudo docker" ./crowsnest.sh ...`.

**WeasyPrint fails to import** — the GTK/Pango libraries are missing.
`sudo dnf install pango cairo` on Fedora, `sudo apt install libpango-1.0-0
libpangoft2-1.0-0` on Debian/Ubuntu.

**The report generates with no summary paragraph** — expected when no LLM
backend is reachable. The narrative section is optional by design.
