# /// script
# requires-python = ">=3.12"
# ///
# Convert SEC filing HTML in data/downloads to Markdown with Docling.
# Run from backend/: uv run python ../data/convert_html_to_markdown.py

from __future__ import annotations

import json
import shutil
from pathlib import Path

from docling.document_converter import DocumentConverter

DATA_DIR = Path(__file__).resolve().parent
SOURCE_DIR = DATA_DIR / "downloads"
OUTPUT_DIR = DATA_DIR / "markdown"
HTML_SUFFIXES = {".htm", ".html"}


def convert_downloads() -> int:
    sources = sorted(
        path for path in SOURCE_DIR.rglob("*") if path.suffix.lower() in HTML_SUFFIXES
    )
    manifest = json.loads((SOURCE_DIR / "manifest.json").read_text(encoding="utf-8"))

    if OUTPUT_DIR.exists():
        shutil.rmtree(OUTPUT_DIR)
    OUTPUT_DIR.mkdir()

    converter = DocumentConverter()
    for source in sources:
        output = OUTPUT_DIR / source.relative_to(SOURCE_DIR).with_suffix(".md")
        output.parent.mkdir(parents=True, exist_ok=True)
        output.write_text(
            converter.convert(source).document.export_to_markdown(), encoding="utf-8"
        )

    for filing in manifest["filings"]:
        filing["local_path"] = str(Path(filing["local_path"]).with_suffix(".md"))
    (OUTPUT_DIR / "manifest.json").write_text(
        json.dumps(manifest, indent=2) + "\n", encoding="utf-8"
    )

    assert len(sources) == manifest["downloaded_count"]
    return len(sources)


if __name__ == "__main__":
    count = convert_downloads()
    print(f"Converted {count} HTML file(s) to {OUTPUT_DIR}")
    print(f"Manifest: {OUTPUT_DIR / 'manifest.json'}")
