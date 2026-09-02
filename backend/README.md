# Backend

```bash
cp .env.example .env  # fill in the required values
uv sync
uv run uvicorn app.main:app --reload
```

The API is available at `http://localhost:8000`; check `GET /health`.

```bash
uv run pytest
uv run ruff check .
```

Keep routes in `app/`, add configuration only in `app/config.py`, and manage dependencies with `uv add` / `uv remove`.
