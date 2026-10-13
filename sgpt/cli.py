"""Command-line entry point: python -m sgpt [options]"""

from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

from .i18n import LANGUAGES
from .generator import DIFFICULTY_TEXT, QUESTION_TYPES, ExamRequest, Progress, generate_exam, render_markdown
from .ollama_client import Cancelled, LLMError
from .providers import PROVIDERS, make_client, search_settings
from .sources import SourceError, gather_sources


class _QuietProgress(Progress):
    def step(self, done: int, total: int, message: str) -> None:
        pass


def parse_plan(text: str) -> list[dict]:
    """'mcq:10,short:5:3' -> [{"type": "mcq", "count": 10}, {"type": "short", "count": 5, "marks": 3}]"""
    plan = []
    for item in filter(None, (x.strip() for x in text.split(","))):
        bits = item.split(":")
        if bits[0] not in QUESTION_TYPES or len(bits) < 2:
            raise argparse.ArgumentTypeError(
                f"bad plan item '{item}'. Use type:count[:marks] with type one of "
                + ", ".join(QUESTION_TYPES))
        entry = {"type": bits[0], "count": int(bits[1])}
        if len(bits) > 2:
            entry["marks"] = int(bits[2])
        plan.append(entry)
    return plan


def build_parser() -> argparse.ArgumentParser:
    p = argparse.ArgumentParser(
        prog="sgpt",
        description="Generate a practice exam with model answers and a marking scheme from your "
                    "sources (past papers, notes, links) or from an internet search.")
    p.add_argument("input", nargs="?", default="library",
                   help="folder of source files: PDF past papers/notes, .txt, .md (default: library)")
    p.add_argument("-o", "--output", help="output Markdown file (default: output/<date>_<title>.md); "
                   "a .json copy is saved next to it")
    p.add_argument("-t", "--topic", default="", help="what the exam is about, e.g. 'photosynthesis'")
    p.add_argument("--subject", default="", help="subject, e.g. 'Biology'")
    p.add_argument("--level", default="", help="level, e.g. 'GCSE' or 'Year 9'")
    p.add_argument("-l", "--language", choices=list(LANGUAGES), default="en",
                   help="language of the exam: en (English), zh (Chinese), ms (Malay)")
    p.add_argument("--source-language", choices=["auto", *LANGUAGES], default="auto",
                   help="language of your sources (default: auto). Internet search uses this, "
                        "or the exam language when auto")
    p.add_argument("--url", action="append", default=[], help="web page or PDF link to use (repeatable)")
    p.add_argument("--text-file", help="text file with extra notes to use")
    p.add_argument("--web", choices=["auto", "on", "off"], default="auto",
                   help="search the internet for the topic: auto = only when no other sources (default)")
    p.add_argument("--structure", choices=["match", "custom"],
                   help="match = copy the layout of your past papers; custom = use --plan "
                        "(default: match if past papers are found)")
    p.add_argument("--plan", type=parse_plan, help="questions to write, e.g. 'mcq:10,short:5,essay:1:15' "
                   "(type:count[:marks each]). Types: " + ", ".join(QUESTION_TYPES))
    p.add_argument("--difficulty", choices=list(DIFFICULTY_TEXT), default="mixed",
                   help="easy, medium, hard, mixed (default), past (same mix as your past papers) "
                        "or custom (use --mix)")
    p.add_argument("--mix", help="custom difficulty mix as easy,medium,hard percentages, e.g. 20,50,30")
    p.add_argument("--challenge", type=int, choices=range(-2, 3), default=0, metavar="{-2..2}",
                   help="fine-tune: -2 much easier … 2 much harder (default 0)")
    p.add_argument("--no-verify", action="store_true",
                   help="skip the double-check of every answer (faster, less accurate)")
    p.add_argument("--instructions", default="", help="extra instructions for the question writer")
    p.add_argument("--minutes", type=int, help="time allowed (default: estimated from marks)")
    p.add_argument("-p", "--provider", default="ollama", choices=list(PROVIDERS),
                   help="AI provider (default: ollama)")
    p.add_argument("-m", "--model", help="model name (default depends on provider: "
                   + ", ".join(f"{k}={v.default_model}" for k, v in PROVIDERS.items()
                               if v.default_model) + ")")
    p.add_argument("--api-key", help="API key for cloud providers "
                   "(default: the key saved in the app, or the provider's environment variable)")
    p.add_argument("--base-url", "--host", dest="base_url",
                   help="Ollama URL or OpenAI-compatible /v1 URL")
    p.add_argument("--temperature", type=float, default=0.7, help="creativity, 0.0-1.0 (default: 0.7)")
    p.add_argument("--num-ctx", type=int, default=16384, help="Ollama context window (default: 16384)")
    p.add_argument("--max-chars", type=int, default=12000,
                   help="characters of each source sent per AI call (default: 12000)")
    p.add_argument("--seed", type=int, help="random seed for reproducible output")
    p.add_argument("-q", "--quiet", action="store_true", help="less progress output")
    return p


def main(argv: list[str] | None = None) -> int:
    args = build_parser().parse_args(argv)
    folder = Path(args.input)
    warn = lambda msg: print(f"  ! {msg}")  # noqa: E731
    try:
        text = Path(args.text_file).read_text(encoding="utf-8") if args.text_file else ""
        engine, engine_key = search_settings()
        sources = gather_sources(folder=folder if folder.is_dir() else None, text=text,
                                 urls=args.url, topic=args.topic or args.subject, web=args.web,
                                 engine=engine, engine_key=engine_key,
                                 language=args.language if args.source_language == "auto"
                                 else args.source_language,
                                 step=lambda m: print(m), warn=warn)
    except (OSError, SourceError) as exc:
        print(f"Error: {exc}", file=sys.stderr)
        return 1
    if not sources:
        print("No sources. Put PDFs or notes in the folder, use --url/--text-file, "
              "or give a --topic to search the internet.", file=sys.stderr)
        return 1
    for s in sources:
        extra = f", {len(s.paper.questions)} questions" if s.paper else ""
        print(f"  - [{s.kind}] {s.title}{extra}")

    structure = args.structure or ("custom" if args.plan else "auto")
    if args.mix and args.difficulty == "mixed":
        args.difficulty = "custom"
    request = ExamRequest(topic=args.topic, subject=args.subject, level=args.level,
                          structure=structure, difficulty=args.difficulty,
                          instructions=args.instructions, duration_minutes=args.minutes,
                          max_chars=args.max_chars, seed=args.seed, language=args.language,
                          challenge=args.challenge, verify=not args.no_verify,
                          difficulty_mix=dict(zip(("easy", "medium", "hard"),
                                                  (float(x) for x in args.mix.split(","))))
                          if args.mix else None,
                          source_language=args.source_language)
    if args.plan:
        request.plan = args.plan
    try:
        client = make_client(args.provider, args.model, api_key=args.api_key,
                             base_url=args.base_url, temperature=args.temperature,
                             seed=args.seed, num_ctx=args.num_ctx, verbose=not args.quiet)
        if args.provider != "ollama":
            print(f"Using {PROVIDERS[args.provider].label} ({client.model}): "
                  "the text of your sources is sent to this provider.")
        client.check_model()
        exam = generate_exam(client, sources, request,
                             progress=_QuietProgress() if args.quiet else None)
    except (LLMError, RuntimeError) as exc:
        print(f"\nError: {exc}", file=sys.stderr)
        return 2
    except (KeyboardInterrupt, Cancelled):
        print("\nCancelled.", file=sys.stderr)
        return 130

    if args.output:
        output = Path(args.output)
    else:
        slug = "".join(c if c.isalnum() else "_" for c in exam["title"]).strip("_")[:50]
        output = Path("output") / f"{exam['created'].replace(':', '').replace('-', '')}_{slug}.md"
    output.parent.mkdir(parents=True, exist_ok=True)
    output.write_text(render_markdown(exam), encoding="utf-8")
    output.with_suffix(".json").write_text(json.dumps(exam, indent=2, ensure_ascii=False),
                                           encoding="utf-8")
    print(f"\nSaved {len(exam['questions'])} questions with model answers and marking scheme "
          f"to {output}")
    return 0
