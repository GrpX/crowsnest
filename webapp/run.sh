#!/usr/bin/env bash
set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
REPO_DIR="$(cd "${SCRIPT_DIR}/.." && pwd)"

if [[ -f "${REPO_DIR}/.env" ]]; then
    set -a
    # shellcheck disable=SC1090
    source "${REPO_DIR}/.env"
    set +a
fi

export FLASK_APP="${SCRIPT_DIR}/app.py"
export FLASK_ENV=production

python3 -m pip install -r "${SCRIPT_DIR}/requirements-webapp.txt" \
    --quiet --break-system-packages 2>/dev/null || \
python3 -m pip install -r "${SCRIPT_DIR}/requirements-webapp.txt" \
    --quiet --user 2>/dev/null || true

exec python3 "${SCRIPT_DIR}/app.py"
