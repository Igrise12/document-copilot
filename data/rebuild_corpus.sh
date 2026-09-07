#!/usr/bin/env bash
set -euo pipefail

if [ "$#" -ne 1 ]; then
  echo "Usage: bash data/rebuild_corpus.sh <supabase-user-email>" >&2
  exit 2
fi

project_dir=$(cd -- "$(dirname -- "${BASH_SOURCE[0]}")/.." && pwd)
cd "$project_dir/backend"

uv run alembic upgrade head
PYTHONPATH=. uv run python ../data/import_markdown_to_supabase.py \
  --owner-email "$1" --all --confirm-all --reindex --resume
