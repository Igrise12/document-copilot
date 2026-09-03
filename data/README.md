# Data

Local data artifacts for development live here.

- `downloads/` holds raw source files fetched from SEC EDGAR, grouped by year.
- `markdown/` holds the Docling-generated Markdown mirror, using the same folders and manifest.
- Downloaded payloads are gitignored because the corpus can get large.
- Fetch a sample corpus with `uv run data/download.py` 
- Convert it from `backend/` with `uv run python ../data/convert_html_to_markdown.py`.
- Chunking is fully local: Docling uses a conservative 512 UTF-8-byte budget, safely
  below EmbeddingGemma's 2K-token context window.
- Pilot one chunk from `backend/` with `PYTHONPATH=. uv run python ../data/import_markdown_to_supabase.py --owner-email <driftwood-user-email> --accession-number <accession-number> --max-chunks 1`.
- After inspecting that pilot, process the corpus with `PYTHONPATH=. uv run python ../data/import_markdown_to_supabase.py --owner-email <driftwood-user-email> --all --confirm-all`.

After the full import, manually run [`evaluation_questions.json`](evaluation_questions.json).
Each filing has a revenue and a heading/table question; the 2026 prediction must return
the insufficient-evidence message exactly.
