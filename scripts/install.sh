#!/usr/bin/env bash
set -euo pipefail
cd "$(dirname "$0")/.."
export PIP_CACHE_DIR="${PWD}/.cache/pip"
export npm_config_cache="${PWD}/.cache/npm"
python3 -m venv .venv
.venv/bin/python -m pip install --disable-pip-version-check -r backend/requirements.lock
.venv/bin/python scripts/sync_references.py
for tool in node npm chromium tesseract pdftoppm; do
  command -v "$tool" >/dev/null || { echo "Required system tool missing: $tool" >&2; exit 1; }
done
mkdir -p data/tessdata
ocr_model="${PWD}/data/tessdata/ara.traineddata"
ocr_digest='e3206d3dc87fd50c24a0fb9f01838615911d25168f4e64415244b67d2bb3e729'
if ! echo "$ocr_digest  $ocr_model" | sha256sum --check --status; then
  ocr_download=$(mktemp)
  trap 'rm -f "$ocr_download"' EXIT
  curl --fail --show-error --silent --location --proto '=https' --proto-redir '=https' \
    'https://raw.githubusercontent.com/tesseract-ocr/tessdata_fast/87416418657359cb625c412a48b6e1d6d41c29bd/ara.traineddata' \
    --output "$ocr_download"
  echo "$ocr_digest  $ocr_download" | sha256sum --check --status
  mv "$ocr_download" "$ocr_model"
fi
if [ -f /usr/share/tesseract-ocr/5/tessdata/eng.traineddata ] && [ ! -f data/tessdata/eng.traineddata ]; then
  cp /usr/share/tesseract-ocr/5/tessdata/eng.traineddata data/tessdata/eng.traineddata
fi
cd frontend
npm ci --no-audit --no-fund
npm run build
