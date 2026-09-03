# Backend

```bash
cp .env.example .env  # fill in the required values
uv sync
uv run uvicorn app.main:app --reload --port 8001
```

The API is available at `http://localhost:8001`; check `GET /health`.

```bash
uv run pytest
uv run ruff check .
```

## Chat smoke test

Jalankan backend, lalu berikan access token Supabase aktif melalui argumen (token tidak
disimpan oleh skrip):

```bash
uv run python smoke-test.py --access-token '<Supabase access token>'
```

Gunakan dokumen siap tertentu atau pertahankan thread sementara untuk diperiksa:

```bash
uv run python smoke-test.py \
  --access-token '<Supabase access token>' \
  --document-id '<ready document UUID>' \
  --keep-thread
```

Skrip membuat thread, menjalankan stream chat, memeriksa jawaban/sitasi yang tersimpan,
dan menghapus thread secara default.

Keep routes in `app/`, add configuration only in `app/config.py`, and manage dependencies with `uv add` / `uv remove`.
