"""Commands kept separate from provider credentials and the future web app."""

import argparse
import json
from pathlib import Path


def main():
    parser = argparse.ArgumentParser(prog="gst-rag")
    commands = parser.add_subparsers(dest="command", required=True)
    convert = commands.add_parser("parse", help="Convert a PDF once with Docling")
    convert.add_argument("pdf", type=Path)
    convert.add_argument("--output", type=Path, default=Path("data/processed/chapter7"))
    convert.add_argument("--source-type", choices=["firm_book", "icai_book", "notification"], default="firm_book")
    convert.add_argument("--ocr", action="store_true", help="Enable OCR for scanned PDFs")
    convert.add_argument("--force", action="store_true", help="Recompute an existing parse")
    chunks = commands.add_parser("chunk", help="Build all three variants and parent records")
    chunks.add_argument("directory", type=Path)
    chunks.add_argument("--max-tokens", type=int, default=512)
    chunks.add_argument("--overlap", type=int, default=64)
    chunks.add_argument("--tokenizer", default="jinaai/jina-embeddings-v3")
    chunks.add_argument("--picture-transcriptions", type=Path, help="Optional source-reviewed, PDF-bound picture text JSON")
    chunks.add_argument("--outline-review", type=Path, help="Optional PDF/parse-bound reviewed heading levels and reading-order corrections")
    bench = commands.add_parser("benchmark", help="Run retrieval with source-quote evidence checks")
    bench.add_argument("directory", type=Path)
    bench.add_argument("questions", type=Path)
    bench.add_argument("--retriever", choices=["bm25", "jina"], default="bm25")
    bench.add_argument("--split", choices=["dev", "heldout"], default="dev")
    bench.add_argument("--context-mode", choices=["child", "neighbors", "parent"], default="child")
    bench.add_argument("--context-budget", type=int, default=2048)
    bench.add_argument("--top-k", type=int, default=10)
    bench.add_argument("--plan", choices=["plus", "pro"], default="pro")
    bench.add_argument("--variant", choices=["all", "fixed", "hierarchical", "hybrid"], default="all")
    bench.add_argument("--allow-draft-labels", action="store_true", help="Diagnostic runs only; not a validated benchmark")
    bench.add_argument("--output-tag", default="", help="Separate result filenames for different question sets")
    args = parser.parse_args()
    if args.command == "parse":
        from .ingestion import parse_pdf
        result = parse_pdf(args.pdf, args.output, args.source_type, args.ocr, args.force)
    elif args.command == "chunk":
        from .chunking import build_variants
        result = build_variants(args.directory, args.max_tokens, args.overlap, args.tokenizer, args.picture_transcriptions, args.outline_review)
    else:
        from .benchmark import run_benchmark
        result = run_benchmark(args)
    print(json.dumps(result, indent=2, ensure_ascii=True))


if __name__ == "__main__":
    main()
