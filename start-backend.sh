#!/usr/bin/env sh
set -eu
cd "$(dirname "$0")/backend"
python3 -m venv .venv
. .venv/bin/activate
python -m pip install -r requirements.txt
[ -f .env ] || cp .env.example .env
python -m uvicorn app.main:app --reload --port 8000
