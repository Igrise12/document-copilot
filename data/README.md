# Data

Local data artifacts for development live here.

- `downloads/` holds raw source files fetched from SEC EDGAR, grouped by year.
- `markdown/` holds the Docling-generated Markdown mirror, using the same folders and manifest.
- Downloaded payloads are gitignored because the corpus can get large.
- Fetch a sample corpus with `uv run data/download.py` 
- Convert it from `backend/` with `uv run python ../data/convert_html_to_markdown.py`.
- Import it from `backend/` with `PYTHONPATH=. uv run python ../data/import_markdown_to_supabase.py --owner-email <driftwood-user-email>`.
