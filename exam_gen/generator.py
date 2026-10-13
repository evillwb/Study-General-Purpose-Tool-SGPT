"""The generation pipeline: analyse past papers -> blueprint -> new paper -> marking scheme."""

from __future__ import annotations

import random
from collections import Counter
from datetime import datetime

from . import prompts
from .ollama_client import OllamaClient, parse_json
from .pdf_extract import ExamPaper


def _as_int(value) -> int | None:
    try:
        return int(value)
    except (TypeError, ValueError):
        return None


def _as_list(value) -> list[str]:
    if isinstance(value, list):
        return [str(v).strip() for v in value if str(v).strip()]
    if isinstance(value, str) and value.strip():
        return [value.strip()]
    return []


def fallback_blueprint(paper: ExamPaper) -> dict:
    """Blueprint built from the PDF structure alone, used if the model's JSON is unusable."""
    count = len(paper.questions) or 8
    return {
        "subject": "", "level": "", "duration_minutes": None,
        "total_marks": paper.total_marks, "instructions": [], "topics": [], "style_notes": "",
        "sections": [{"name": "Questions", "instructions": "Answer all questions.",
                      "question_count": count, "marks": paper.total_marks,
                      "question_types": [], "topics": []}],
    }


def normalise_blueprint(data: dict, paper: ExamPaper) -> dict:
    sections = []
    for sec in data.get("sections") or []:
        if not isinstance(sec, dict):
            continue
        count = _as_int(sec.get("question_count")) or 0
        if count <= 0:
            continue
        sections.append({
            "name": str(sec.get("name") or f"Section {chr(65 + len(sections))}"),
            "instructions": str(sec.get("instructions") or "Answer all questions."),
            "question_count": min(count, 30),
            "marks": _as_int(sec.get("marks")),
            "question_types": _as_list(sec.get("question_types")),
            "topics": _as_list(sec.get("topics")),
        })
    if not sections:
        sections = fallback_blueprint(paper)["sections"]
    return {
        "subject": str(data.get("subject") or ""),
        "level": str(data.get("level") or ""),
        "duration_minutes": _as_int(data.get("duration_minutes")),
        "total_marks": _as_int(data.get("total_marks")) or paper.total_marks,
        "instructions": _as_list(data.get("instructions")),
        "topics": _as_list(data.get("topics")),
        "style_notes": str(data.get("style_notes") or ""),
        "sections": sections,
    }


def analyse_paper(client: OllamaClient, paper: ExamPaper, max_chars: int) -> dict:
    text = paper.text[:max_chars]
    prompt = prompts.ANALYSE_PROMPT.format(name=paper.path.name, text=text)
    for attempt in range(2):
        reply = client.chat(prompts.ANALYSE_SYSTEM, prompt, json_mode=True, max_tokens=2048,
                            label=f"analysing {paper.path.name}" + (" (retry)" if attempt else ""))
        try:
            return normalise_blueprint(parse_json(reply), paper)
        except ValueError:
            continue
    print(f"  ! could not parse analysis of {paper.path.name}; using detected structure")
    return fallback_blueprint(paper)


def merge_blueprints(blueprints: list[dict], subject: str | None, level: str | None) -> dict:
    """Combine per-paper blueprints: the latest paper's layout, every paper's topics."""
    def most_common(key):
        values = [b[key] for b in blueprints if b.get(key)]
        return Counter(values).most_common(1)[0][0] if values else None

    # Prefer the layout whose section count is most common; ties go to the latest paper.
    layout_counts = Counter(len(b["sections"]) for b in blueprints)
    usual = layout_counts.most_common(1)[0][0]
    layout = [b for b in blueprints if len(b["sections"]) == usual][-1]

    topic_counts = Counter(t for b in blueprints for t in b["topics"])
    return {
        "subject": subject or most_common("subject") or "General",
        "level": level or most_common("level") or "",
        "duration_minutes": most_common("duration_minutes"),
        "total_marks": layout["total_marks"],
        "instructions": layout["instructions"],
        "topics": [t for t, _ in topic_counts.most_common()],
        "style_notes": next((b["style_notes"] for b in reversed(blueprints) if b["style_notes"]), ""),
        "sections": layout["sections"],
    }


def _examples(papers: list[ExamPaper], rng: random.Random, n: int = 3, max_len: int = 700) -> str:
    pool = [q for p in papers for q in p.questions if len(q.text) > 40]
    if not pool:
        return "(none available)"
    picks = rng.sample(pool, min(n, len(pool)))
    return "\n\n".join(f"Example {i + 1}:\n{q.text[:max_len]}" for i, q in enumerate(picks))


def generate_exam(client: OllamaClient, papers: list[ExamPaper], *, subject: str | None = None,
                  level: str | None = None, extra_instructions: str = "",
                  max_chars: int = 12000, seed: int | None = None) -> str:
    rng = random.Random(seed)

    print("Step 1/3: analysing past papers")
    blueprints = [analyse_paper(client, p, max_chars) for p in papers]
    bp = merge_blueprints(blueprints, subject, level)
    all_topics = bp["topics"]

    print("Step 2/3: writing the new paper")
    sections_md: list[str] = []
    number = 1
    for sec in bp["sections"]:
        topics = sec["topics"] or all_topics
        # Rotate topics so the new paper does not mirror the past paper's topic order.
        topics = rng.sample(topics, len(topics)) if topics else ["any topic from the syllabus"]
        prompt = prompts.WRITE_SECTION_PROMPT.format(
            section_name=sec["name"], level=bp["level"], subject=bp["subject"],
            instructions=sec["instructions"], question_count=sec["question_count"],
            first_number=number, marks=sec["marks"] or "as appropriate",
            question_types=", ".join(sec["question_types"]) or "as in the past papers",
            topics=", ".join(topics[:15]), style_notes=bp["style_notes"] or "standard exam style",
            examples=_examples(papers, rng),
            extra=f"Additional instructions: {extra_instructions}\n" if extra_instructions else "",
        )
        md = client.chat(prompts.WRITE_SYSTEM, prompt, max_tokens=6144,
                         label=f"writing {sec['name']}")
        sections_md.append(md)
        number += sec["question_count"]

    print("Step 3/3: writing the marking scheme")
    scheme_md = [
        client.chat(prompts.MARK_SYSTEM,
                    prompts.MARK_SECTION_PROMPT.format(level=bp["level"], subject=bp["subject"],
                                                       section=md),
                    max_tokens=8192, label=f"marking {sec['name']}")
        for sec, md in zip(bp["sections"], sections_md)
    ]

    return render_markdown(bp, sections_md, scheme_md, [p.path.name for p in papers],
                           client.model)


def render_markdown(bp: dict, sections_md: list[str], scheme_md: list[str],
                    sources: list[str], model: str) -> str:
    title = " ".join(x for x in (bp["level"], bp["subject"]) if x)
    meta = []
    if bp["duration_minutes"]:
        meta.append(f"**Time allowed:** {bp['duration_minutes']} minutes")
    if bp["total_marks"]:
        meta.append(f"**Total marks:** {bp['total_marks']}")
    instructions = bp["instructions"] or ["Answer all questions.",
                                          "Show all your working.",
                                          "The marks for each question are shown in brackets [ ]."]
    out = [
        f"# {title} — Practice Exam Paper",
        "",
        "  \n".join(meta) if meta else "",
        "",
        "### Instructions to candidates",
        *[f"- {line}" for line in instructions],
        "",
        "---",
        "",
    ]
    out += [s.strip() + "\n\n---\n" for s in sections_md]
    out += ["", "# Marking Scheme", "",
            "> For teachers and self-marking. Each mark is linked to a step in the working.", ""]
    out += [s.strip() + "\n" for s in scheme_md]
    out += ["", "---", "",
            f"*Generated {datetime.now():%Y-%m-%d %H:%M} by Easy Note AI with `{model}` "
            f"from: {', '.join(sources)}. AI-generated: check answers before relying on them.*",
            ""]
    return "\n".join(out)
