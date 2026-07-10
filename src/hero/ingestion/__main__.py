"""CLI entry point: uv run python -m hero.ingestion ingest <pdf> ..."""

from __future__ import annotations

import argparse
import sys

from qdrant_client import QdrantClient

from hero.config import get_settings
from hero.ingestion.ingest import ingest_pdf
from hero.interfaces.embedder import Embedder


def main() -> int:
    parser = argparse.ArgumentParser(description="Hero.AI ingestion CLI")
    sub = parser.add_subparsers(dest="command")

    ingest_p = sub.add_parser("ingest", help="Ingest a PDF into Qdrant")
    ingest_p.add_argument("pdf", help="Path to PDF file")
    ingest_p.add_argument("--doc-id", help="Document ID (default: filename)")
    ingest_p.add_argument("--manufacturer", required=True, help="Manufacturer name")
    ingest_p.add_argument("--model-codes", required=True, help="Comma-separated model codes")
    ingest_p.add_argument("--embedder", default="stub", choices=["stub", "colmodernvbert"])
    ingest_p.add_argument("--qdrant-url", default=None, help="Qdrant URL (default: from config)")
    ingest_p.add_argument("--batch-size", type=int, default=4)

    args = parser.parse_args()
    if args.command != "ingest":
        parser.print_help()
        return 1

    # Resolve embedder
    resolved_embedder: Embedder
    if args.embedder == "colmodernvbert":
        from hero.adapters.colmodernvbert import ColModernVBertEmbedder

        resolved_embedder = ColModernVBertEmbedder()
    else:
        from hero.adapters.stub_embedder import StubEmbedder

        resolved_embedder = StubEmbedder()

    # Resolve Qdrant client
    settings = get_settings()
    qdrant_url = args.qdrant_url or settings.qdrant_url
    client = QdrantClient(url=qdrant_url)

    doc_id = args.doc_id or args.pdf.rsplit("/", 1)[-1].rsplit(".", 1)[0]
    model_codes = [c.strip() for c in args.model_codes.split(",")]

    print(f"Ingesting {args.pdf} as doc_id={doc_id}")
    print(f"  manufacturer={args.manufacturer}, model_codes={model_codes}")
    print(f"  embedder={args.embedder}, qdrant={qdrant_url}")

    count = ingest_pdf(
        pdf_path=args.pdf,
        doc_id=doc_id,
        manufacturer=args.manufacturer,
        model_codes=model_codes,
        embedder=resolved_embedder,
        client=client,
        batch_size=args.batch_size,
    )

    print(f"Ingested {count} pages successfully.")
    return 0


if __name__ == "__main__":
    sys.exit(main())
