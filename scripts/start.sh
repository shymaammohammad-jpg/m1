#!/usr/bin/env bash
set -euo pipefail
cd "$(dirname "$0")/.."
export AUDIT_TESSDATA_DIR="${AUDIT_TESSDATA_DIR:-${PWD}/data/tessdata}"
export XDG_CACHE_HOME="${PWD}/.cache"
export OMP_THREAD_LIMIT=1
# OCR remains opt-in; originals are reviewable even when the text is partial.
export AUDIT_OCR_ON_UPLOAD="${AUDIT_OCR_ON_UPLOAD:-0}"
exec .venv/bin/python -m uvicorn backend.app:app --host "${AUDIT_HOST:-127.0.0.1}" --port "${AUDIT_PORT:-8000}"
