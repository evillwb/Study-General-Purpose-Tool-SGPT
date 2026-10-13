"""Command-line entry point: python -m exam_gen [options]"""

from __future__ import annotations

import argparse
import json
import os
import sys
from datetime import datetime
from pathlib import Path

from .generator import generate_exam
from .ollama_client import OllamaClient, OllamaError
from .pdf_extract import load_papers


def build_parser() -> argparse.ArgumentParser:
    p = argparse.ArgumentParser(
        prog="exam_gen",
        description="Generate a new practice exam + marking scheme from past-paper PDFs "
                    "using a local Ollama model.",
    )
    p.add_argument("input", nargs="?", default="past_papers",
                   help="folder containing past-paper PDFs (default: past_papers)")
    p.add_argument("-o", "--output", help="output Markdown file "
                   "(default: output/practice_exam_<date-time>.md)")
    p.add_argument("-m", "--model", default="qwen3:4b", help="Ollama model (default: qwen3:4b)")
    p.add_argument("--host", default=os.environ.get("OLLAMA_HOST", "http://localhost:11434"),
                   help="Ollama URL (default: $OLLAMA_HOST or http://localhost:11434)")
    p.add_argument("--subject", help="override the detected subject, e.g. 'Physics'")
    p.add_argument("--level", help="override the detected level, e.g. 'GCSE Higher'")
    p.add_argument("--instructions", default="",
                   help="extra instructions for the question writer, e.g. 'focus on algebra'")
    p.add_argument("--temperature", type=float, default=0.7,
                   help="creativity, 0.0-1.0 (default: 0.7)")
    p.add_argument("--num-ctx", type=int, default=16384,
                   help="model context window in tokens (default: 16384)")
    p.add_argument("--max-chars", type=int, default=12000,
                   help="max characters read from each paper (default: 12000)")
    p.add_argument("--seed", type=int, help="random seed for reproducible output")
    p.add_argument("--dump-extracted", action="store_true",
                   help="also save the extracted PDF text/questions as JSON (for debugging)")
    p.add_argument("-q", "--quiet", action="store_true", help="less progress output")
    return p


def main(argv: list[str] | None = None) -> int:
    args = build_parser().parse_args(argv)
    folder = Path(args.input)
    if not folder.is_dir():
        print(f"Folder not found: {folder}", file=sys.stderr)
        return 1

    print(f"Reading PDFs from {folder}/")
    papers = load_papers(folder)
    if not papers:
        print("No readable PDFs found. Put past-paper PDFs (with selectable text) in the folder.",
              file=sys.stderr)
        return 1
    for paper in papers:
        print(f"  - {paper.path.name}: {paper.page_count} pages, "
              f"{len(paper.questions)} questions detected")

    stamp = datetime.now().strftime("%Y%m%d_%H%M%S")
    output = Path(args.output) if args.output else Path("output") / f"practice_exam_{stamp}.md"
    output.parent.mkdir(parents=True, exist_ok=True)

    if args.dump_extracted:
        dump = output.with_suffix(".extracted.json")
        dump.write_text(json.dumps([
            {"file": p.path.name, "title": p.title, "pages": p.page_count, "text": p.text,
             "questions": [vars(q) for q in p.questions]} for p in papers
        ], indent=2, ensure_ascii=False), encoding="utf-8")
        print(f"Extracted text saved to {dump}")

    client = OllamaClient(args.host, args.model, num_ctx=args.num_ctx,
                          temperature=args.temperature, seed=args.seed, verbose=not args.quiet)
    try:
        client.check_model()
        markdown = generate_exam(client, papers, subject=args.subject, level=args.level,
                                 extra_instructions=args.instructions, max_chars=args.max_chars,
                                 seed=args.seed)
    except OllamaError as exc:
        print(f"\nError: {exc}", file=sys.stderr)
        return 2
    except KeyboardInterrupt:
        print("\nCancelled.", file=sys.stderr)
        return 130

    output.write_text(markdown, encoding="utf-8")
    print(f"\nSaved practice exam and marking scheme to {output}")
    return 0
