"""The generation pipeline.

    sources ──► (past papers) analyse structure ──┐
            └─► (notes, links, web) study notes ──┴─► write questions ──► answers + marking scheme

The result is an "exam" dict (saved as JSON). render_markdown() turns it into the paper,
model answers and marking scheme.
"""

from __future__ import annotations

import random
import re
import uuid
from collections import Counter
from dataclasses import dataclass, field
from datetime import datetime

from . import i18n, prompts
from .ollama_client import parse_json
from .pdf_extract import ExamPaper
from .sources import Source

QUESTION_TYPES = {
    "mcq": {"label": "Multiple choice", "marks": 1,
            "instructions": "Choose the one correct answer for each question."},
    "true_false": {"label": "True / false", "marks": 1,
                   "instructions": "State whether each statement is true or false."},
    "fill_blank": {"label": "Fill in the blank", "marks": 1,
                   "instructions": "Write the missing word or value in each gap."},
    "short": {"label": "Short answer", "marks": 3,
              "instructions": "Answer each question in a few sentences or lines of working."},
    "calculation": {"label": "Calculation", "marks": 4,
                    "instructions": "Show all your working."},
    "structured": {"label": "Structured", "marks": 8,
                   "instructions": "Answer all parts of each question."},
    "essay": {"label": "Essay / long answer", "marks": 12,
              "instructions": "Write in full sentences and organise your answer clearly."},
}
LEVELS = ("easy", "medium", "hard")
LEVEL_TEXT = {
    "easy": "easy = recall or a single step, in a familiar context",
    "medium": "medium = standard exam application, two or three steps",
    "hard": "hard = multi-step, unfamiliar context, analysis or evaluation",
}
# Share of questions at each level for the difficulty presets.
DIFFICULTY_MIX = {
    "easy": {"easy": 70, "medium": 25, "hard": 5},
    "medium": {"easy": 20, "medium": 60, "hard": 20},
    "hard": {"easy": 5, "medium": 35, "hard": 60},
    "mixed": {"easy": 30, "medium": 50, "hard": 20},
}
DIFFICULTY_TEXT = {**{k: k for k in DIFFICULTY_MIX}, "past": "past", "custom": "custom"}
CHALLENGE_TEXT = {
    -2: "Make every question clearly easier than usual for this level: fewer steps, familiar "
        "contexts, more guidance in the wording.",
    -1: "Make the questions slightly easier than usual for this level.",
    0: "",
    1: "Make the questions slightly harder than usual for this level: an extra step or a less "
       "familiar context.",
    2: "Make the questions much harder than usual for this level: multi-step reasoning, "
       "unfamiliar contexts, and questions that combine topics.",
}
DEFAULT_PLAN = [{"type": "mcq", "count": 5, "marks": 1},
                {"type": "short", "count": 4, "marks": 3},
                {"type": "structured", "count": 2, "marks": 8}]
WRITE_BATCH = 5   # questions per writing call (small models stay accurate on short tasks)
SOLVE_BATCH = 4   # questions per answer/marking call
NOTES_LIMIT = 10000


class Progress:
    """Receives progress updates. The CLI prints them; the web app shows them in the UI."""

    def step(self, done: int, total: int, message: str) -> None:
        print(f"[{done}/{total}] {message}")

    def warn(self, message: str) -> None:
        print(f"  ! {message}")

    def cancelled(self) -> bool:
        return False


@dataclass
class ExamRequest:
    topic: str = ""                 # what the exam is about, e.g. "Cell biology"
    subject: str = ""
    level: str = ""
    structure: str = "auto"         # "auto" | "match" (copy past papers) | "custom" (use plan)
    plan: list[dict] = field(default_factory=lambda: [dict(p) for p in DEFAULT_PLAN])
    difficulty: str = "mixed"
    instructions: str = ""          # extra instructions for the question writer
    duration_minutes: int | None = None
    max_chars: int = 12000
    seed: int | None = None
    language: str = "en"            # language of the exam: "en", "zh", "ms"
    source_language: str = "auto"   # language of the sources, or "auto"
    difficulty_mix: dict | None = None  # {"easy": 30, "medium": 50, "hard": 20} for "custom"
    challenge: int = 0              # -2 (much easier) … +2 (much harder), on top of the mix
    analysis: dict | None = None    # a saved past-paper analysis, so it is not redone


# --- Helpers -----------------------------------------------------------------------------

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


def _text(value) -> str:
    return str(value).strip() if value is not None else ""


class _Steps:
    def __init__(self, progress: Progress, total: int):
        self.progress, self.total, self.done = progress, total, 0

    def __call__(self, message: str) -> None:
        self.progress.step(self.done, self.total, message)
        self.done += 1


# --- Past-paper analysis ------------------------------------------------------------------

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
        "difficulty": normalise_mix(data.get("difficulty")),
        "difficulty_notes": str(data.get("difficulty_notes") or ""),
        "command_words": _as_list(data.get("command_words"))[:20],
        "sections": sections,
    }


def normalise_mix(value) -> dict | None:
    """Turn {"easy": 1, "medium": 2, "hard": 1} (any scale) into whole percentages."""
    if not isinstance(value, dict):
        return None
    raw = {k: max(float(value.get(k) or 0), 0) for k in LEVELS}
    total = sum(raw.values())
    if total <= 0:
        return None
    mix = {k: round(v * 100 / total) for k, v in raw.items()}
    mix["medium"] += 100 - sum(mix.values())
    return mix


def analyse_paper(client, paper: ExamPaper, max_chars: int, progress: Progress) -> dict:
    prompt = prompts.ANALYSE_PROMPT.format(name=paper.path.name, text=paper.text[:max_chars])
    for _ in range(2):
        reply = client.chat(prompts.ANALYSE_SYSTEM, prompt, json_mode=True, max_tokens=2048,
                            should_stop=progress.cancelled)
        try:
            return normalise_blueprint(parse_json(reply), paper)
        except ValueError:
            continue
    progress.warn(f"could not parse analysis of {paper.path.name}; using detected structure")
    return fallback_blueprint(paper)


def merge_blueprints(blueprints: list[dict]) -> dict:
    """Combine per-paper blueprints: the usual layout (latest paper wins), every paper's topics."""
    def most_common(key):
        values = [b[key] for b in blueprints if b.get(key)]
        return Counter(values).most_common(1)[0][0] if values else None

    usual = Counter(len(b["sections"]) for b in blueprints).most_common(1)[0][0]
    layout = [b for b in blueprints if len(b["sections"]) == usual][-1]
    topics = Counter(t for b in blueprints for t in b["topics"])
    mixes = [b["difficulty"] for b in blueprints if b.get("difficulty")]
    words = Counter(w.strip().capitalize() for b in blueprints for w in b.get("command_words", []))
    return {
        "difficulty": normalise_mix({k: sum(m[k] for m in mixes) for k in LEVELS}) if mixes else None,
        "difficulty_notes": " ".join(dict.fromkeys(b["difficulty_notes"] for b in blueprints
                                                   if b.get("difficulty_notes")))[:1200],
        "command_words": [w for w, _ in words.most_common(15)],
        "topic_counts": dict(topics.most_common()),
        "subject": most_common("subject") or "",
        "level": most_common("level") or "",
        "duration_minutes": most_common("duration_minutes"),
        "instructions": layout["instructions"],
        "topics": [t for t, _ in topics.most_common()],
        "style_notes": next((b["style_notes"] for b in reversed(blueprints) if b["style_notes"]), ""),
        "sections": layout["sections"],
    }


def analyse_papers(client, papers: list[Source], max_chars: int = 12000,
                   progress: Progress | None = None, steps: "_Steps | None" = None) -> dict:
    """Analyse past papers one by one; returns {"merged": blueprint, "papers": [...]}."""
    progress = progress or Progress()
    steps = steps or _Steps(progress, len(papers))
    per_paper = []
    for s in papers:
        steps(f"Analysing {s.title}")
        per_paper.append({"name": s.title, **analyse_paper(client, s.paper, max_chars, progress)})
    return {"merged": merge_blueprints(per_paper), "papers": per_paper}


# --- Source notes --------------------------------------------------------------------------

def _chunks(text: str, size: int, limit: int = 3) -> list[str]:
    return [text[i:i + size] for i in range(0, min(len(text), size * limit), size)] or [""]


def summarise_source(client, source: Source, topic: str, max_chars: int,
                     steps: _Steps, progress: Progress, language: str = "en",
                     source_language: str = "auto") -> str:
    notes = []
    for i, chunk in enumerate(_chunks(source.text, max_chars)):
        steps(f"Reading {source.title}" + (f" (part {i + 1})" if i else ""))
        reply = client.chat(prompts.NOTES_SYSTEM + i18n.write_rule(language, source_language),
                            prompts.NOTES_PROMPT.format(topic=topic or "as in the source",
                                                        title=source.title, text=chunk),
                            max_tokens=2048, should_stop=progress.cancelled)
        if reply and "NOT RELEVANT" not in reply[:40]:
            notes.append(reply)
    return "\n".join(notes)


# --- Questions ----------------------------------------------------------------------------

_OPTION_PREFIX = re.compile(r"^\s*(?:\(?[A-Ha-h][).:]|[A-Ha-h]\s*-)\s+")


def normalise_question(data: dict, want_type: str | None, want_marks: int | None,
                       language: str = "en") -> dict | None:
    if not isinstance(data, dict) or not _text(data.get("question")):
        return None
    qtype = want_type or _text(data.get("type")).lower().replace(" ", "_").replace("/", "_")
    if qtype not in QUESTION_TYPES:
        qtype = "structured" if data.get("parts") else "short"
    options = [_OPTION_PREFIX.sub("", _text(o)) for o in data.get("options") or [] if _text(o)]
    if qtype == "true_false":
        options = list(i18n.label(language, "true_false"))
    elif qtype == "mcq" and len(options) < 2:
        qtype, options = "short", []
    elif qtype != "mcq":
        options = []
    parts = []
    for i, part in enumerate(data.get("parts") or []):
        if isinstance(part, dict) and _text(part.get("text")):
            parts.append({"label": _text(part.get("label")).strip("()") or chr(97 + i),
                          "text": _text(part.get("text")),
                          "marks": max(_as_int(part.get("marks")) or 1, 1)})
    marks = sum(p["marks"] for p in parts) if parts else (
        want_marks or _as_int(data.get("marks")) or QUESTION_TYPES[qtype]["marks"])
    difficulty = _text(data.get("difficulty")).lower()
    return {
        "type": qtype,
        "topic": _text(data.get("topic")),
        "difficulty": difficulty if difficulty in ("easy", "medium", "hard") else "medium",
        "marks": max(marks, 1),
        "question": _text(data.get("question")),
        "options": options,
        "parts": parts,
        "answer": "", "final_answer": "", "marking_points": [], "accept": "",
    }


def difficulty_mix(request: ExamRequest, blueprint: dict | None) -> dict:
    if request.difficulty == "custom":
        return normalise_mix(request.difficulty_mix) or DIFFICULTY_MIX["mixed"]
    if request.difficulty == "past":
        return (blueprint or {}).get("difficulty") or DIFFICULTY_MIX["mixed"]
    return DIFFICULTY_MIX.get(request.difficulty, DIFFICULTY_MIX["mixed"])


def difficulty_targets(count: int, mix: dict) -> list[str]:
    """Spread `count` questions over the levels in `mix`, easiest first."""
    exact = {k: count * mix[k] / 100 for k in LEVELS}
    counts = {k: int(v) for k, v in exact.items()}
    for k in sorted(LEVELS, key=lambda k: exact[k] - counts[k], reverse=True)[:count - sum(counts.values())]:
        counts[k] += 1
    return [k for k in LEVELS for _ in range(counts[k])]


def _difficulty_text(mix: dict, challenge: int, blueprint: dict | None) -> str:
    text = (f"overall about {mix['easy']}% easy, {mix['medium']}% medium, {mix['hard']}% hard "
            f"({'; '.join(LEVEL_TEXT.values())}).")
    if blueprint and blueprint.get("difficulty_notes"):
        text += f" In the past papers: {blueprint['difficulty_notes']}"
    if CHALLENGE_TEXT.get(challenge):
        text += " " + CHALLENGE_TEXT[challenge]
    return text


def _context(request: ExamRequest, info: dict, notes: str, papers: list[Source],
             rng: random.Random) -> dict:
    pool = [q for s in papers for q in s.paper.questions if len(q.text) > 40]
    examples = ""
    if pool:
        picks = rng.sample(pool, min(3, len(pool)))
        examples = ("\nExample past questions, for STYLE AND DIFFICULTY ONLY (do not reuse them):\n"
                    + "\n\n".join(q.text[:600] for q in picks) + "\n")
    return {
        "subject": info["subject"] or "general knowledge",
        "level": info["level"] or "secondary school",
        "topic": request.topic or info["subject"] or "the syllabus",
        "difficulty": info["difficulty_text"],
        "topics": info["topics"],
        "style": f"House style from past papers: {info['style_notes']}\n" if info["style_notes"] else "",
        "examples": examples,
        "notes": (f"\nBase the questions on this source material:\n{notes}\n") if notes else "",
        "extra": f"\nAdditional instructions from the teacher: {request.instructions}\n"
                 if request.instructions else "",
        "language": i18n.lang(request.language),
        "source_language": request.source_language,
    }


def write_questions(client, ctx: dict, batch: dict, avoid: list[str], rng: random.Random,
                    progress: Progress) -> list[dict]:
    topics = batch.get("topics") or ctx["topics"]
    topics = rng.sample(topics, len(topics)) if topics else [ctx["topic"]]
    items = batch["description"]
    if batch.get("targets"):
        items += "\n- Difficulty of each question, in order: " + ", ".join(batch["targets"])
    prompt = prompts.WRITE_PROMPT.format(
        count=batch["count"], items=items, topics=", ".join(topics[:15]),
        avoid=("\nDo not repeat these existing questions:\n- "
               + "\n- ".join(a[:150] for a in avoid[-15:]) + "\n") if avoid else "",
        **{k: ctx[k] for k in ("level", "subject", "topic", "difficulty", "style", "examples",
                               "notes", "extra")})
    for _ in range(2):
        system = prompts.WRITE_SYSTEM + i18n.write_rule(ctx.get("language"), ctx.get("source_language"))
        reply = client.chat(system, prompt, json_mode=True, max_tokens=6144,
                            should_stop=progress.cancelled)
        try:
            data = parse_json(reply)
        except ValueError:
            continue
        items = data.get("questions") if isinstance(data, dict) else None
        if isinstance(data, dict) and items is None and data.get("question"):
            items = [data]  # a single question instead of a list
        questions = [q for q in (normalise_question(d, batch.get("type"), batch.get("marks"),
                                                    ctx.get("language", "en"))
                                 for d in items or []) if q]
        if questions:
            questions = questions[:batch["count"]]
            for q, target in zip(questions, batch.get("targets") or []):
                q["difficulty"] = target  # we asked for this level, so label it as such
            return questions
    progress.warn(f"could not write: {batch['description'].strip()}")
    return []


def _question_text(q: dict) -> str:
    lines = [f"Question {q['number']} [{q['marks']} marks] ({QUESTION_TYPES[q['type']]['label']})",
             q["question"]]
    lines += [f"{chr(65 + i)}. {o}" for i, o in enumerate(q["options"])]
    lines += [f"({p['label']}) {p['text']} [{p['marks']}]" for p in q["parts"]]
    return "\n".join(lines)


def solve_questions(client, ctx: dict, questions: list[dict], progress: Progress) -> None:
    prompt = prompts.SOLVE_PROMPT.format(
        level=ctx["level"], subject=ctx["subject"], notes=ctx["notes"][:6000],
        questions="\n\n".join(_question_text(q) for q in questions))
    for _ in range(2):
        system = prompts.SOLVE_SYSTEM + i18n.write_rule(ctx.get("language"), ctx.get("source_language"))
        reply = client.chat(system, prompt, json_mode=True, max_tokens=8192,
                            should_stop=progress.cancelled)
        try:
            data = parse_json(reply)
        except ValueError:
            continue
        solutions = data.get("solutions") if isinstance(data, dict) else None
        if not isinstance(solutions, list) or not solutions:
            continue
        by_number = {_as_int(s.get("number")): s for s in solutions if isinstance(s, dict)}
        for i, q in enumerate(questions):
            s = by_number.get(q["number"]) or (solutions[i] if i < len(solutions) else None)
            if not isinstance(s, dict):
                continue
            q["answer"] = _text(s.get("answer"))
            q["final_answer"] = _text(s.get("final_answer"))
            q["accept"] = _text(s.get("accept"))
            q["marking_points"] = [
                {"point": _text(p.get("point")), "marks": max(_as_int(p.get("marks")) or 1, 1)}
                for p in s.get("marking_points") or []
                if isinstance(p, dict) and _text(p.get("point"))]
        return
    progress.warn("could not write answers for questions "
                  + ", ".join(str(q["number"]) for q in questions))


# --- The whole exam -----------------------------------------------------------------------

def _plan_sections(request: ExamRequest, blueprint: dict | None) -> list[dict]:
    """Turn the past-paper blueprint or the custom plan into sections of writing batches."""
    sections = []
    if blueprint:
        for sec in blueprint["sections"]:
            types = ", ".join(sec["question_types"]) or "the same styles as the past papers"
            remaining, batches = sec["question_count"], []
            per_q = (sec["marks"] / sec["question_count"]) if sec["marks"] else None
            while remaining > 0:
                n = min(WRITE_BATCH, remaining)
                marks = f", worth about {round(per_q * n)} marks in total" if per_q else ""
                batches.append({"count": n, "type": None, "marks": None, "topics": sec["topics"],
                                "description": f"- {n} question(s) in these styles: {types}{marks}"})
                remaining -= n
            sections.append({"name": sec["name"], "instructions": sec["instructions"],
                             "batches": batches})
        return sections
    for item in request.plan:
        qtype, count = item.get("type"), min(_as_int(item.get("count")) or 0, 50)
        if qtype not in QUESTION_TYPES or count <= 0:
            continue
        info = QUESTION_TYPES[qtype]
        marks = max(_as_int(item.get("marks")) or info["marks"], 1)
        batches = []
        for start in range(0, count, WRITE_BATCH):
            n = min(WRITE_BATCH, count - start)
            batches.append({"count": n, "type": qtype, "marks": marks, "topics": [],
                            "description": f"- {n} × {info['label']} question(s), "
                                           f"{marks} mark(s) each"})
        language = request.language
        sections.append({"name": i18n.label(language, "section", letter=chr(65 + len(sections)),
                                            label=i18n.type_label(language, qtype)),
                         "instructions": i18n.type_instructions(language, qtype),
                         "batches": batches})
    return sections


def generate_exam(client, sources: list[Source], request: ExamRequest | None = None,
                  progress: Progress | None = None) -> dict:
    request = request or ExamRequest()
    progress = progress or Progress()
    rng = random.Random(request.seed)
    papers = [s for s in sources if s.kind == "paper" and s.paper]
    use_papers = bool(papers) and request.structure in ("match", "auto")
    # Past papers set the layout in "match" mode; otherwise their content is read like notes.
    materials = [s for s in sources if (s not in papers or not use_papers) and s.text.strip()]
    analysis = request.analysis
    need_analysis = bool(papers) and not analysis and (use_papers or request.difficulty == "past")
    if request.structure == "match" and not papers:
        progress.warn("No past papers found, so the custom question plan is used instead")

    note_steps = sum(len(_chunks(s.text, request.max_chars)) for s in materials)
    steps = _Steps(progress, len(papers) * need_analysis + note_steps + 2)

    if need_analysis:
        analysis = analyse_papers(client, papers, request.max_chars, progress, steps)
    blueprint = (analysis or {}).get("merged")

    notes = [summarise_source(client, s, request.topic or request.subject, request.max_chars,
                              steps, progress, request.language, request.source_language)
             for s in materials]
    notes_text = "\n\n".join(n for n in notes if n)[:NOTES_LIMIT]

    info = {
        "subject": request.subject or (blueprint or {}).get("subject") or request.topic,
        "level": request.level or (blueprint or {}).get("level") or "",
        "topics": (blueprint or {}).get("topics") or ([request.topic] if request.topic else []),
        "style_notes": (blueprint or {}).get("style_notes") or "",
    }
    mix = difficulty_mix(request, blueprint)
    info["difficulty_text"] = _difficulty_text(mix, request.challenge, blueprint)
    ctx = _context(request, info, notes_text, papers, rng)
    sections = (_plan_sections(request, blueprint if use_papers else None)
                or _plan_sections(ExamRequest(), None))
    # Give every question a target level, easiest first within each section.
    for sec in sections:
        targets = difficulty_targets(sum(b["count"] for b in sec["batches"]), mix)
        for b in sec["batches"]:
            b["targets"], targets = targets[:b["count"]], targets[b["count"]:]
    n_questions = sum(b["count"] for s in sections for b in s["batches"])
    steps.total = (steps.done + sum(len(s["batches"]) for s in sections)
                   + -(-n_questions // SOLVE_BATCH))

    questions: list[dict] = []
    for index, sec in enumerate(sections):
        for batch in sec["batches"]:
            steps(f"Writing {sec['name']}")
            for q in write_questions(client, ctx, batch, [q["question"] for q in questions], rng,
                                     progress):
                q["section"] = index
                q["number"] = len(questions) + 1
                questions.append(q)
    if not questions:
        raise RuntimeError("The AI did not return any usable questions. Try again, or try a "
                           "different model.")
    for start in range(0, len(questions), SOLVE_BATCH):
        batch = questions[start:start + SOLVE_BATCH]
        steps(f"Writing answers for questions {batch[0]['number']}–{batch[-1]['number']}")
        solve_questions(client, ctx, batch, progress)
    progress.step(steps.total, steps.total, "Done")

    total = sum(q["marks"] for q in questions)
    duration = (request.duration_minutes or (blueprint or {}).get("duration_minutes")
                or max(15, round(total * 1.2 / 5) * 5))
    language = i18n.lang(request.language)
    name = " ".join(x for x in (info["level"], info["subject"]) if x)
    practice = i18n.label(language, "practice_exam")
    return {
        "version": 1,
        "id": uuid.uuid4().hex[:10],
        "title": f"{name} — {practice}" if name else practice,
        "language": language,
        "subject": info["subject"], "level": info["level"], "topic": request.topic,
        "difficulty": request.difficulty,
        "difficulty_mix": mix,
        "challenge": request.challenge,
        "analysis": analysis,
        "duration_minutes": duration,
        "instructions": ((blueprint or {}).get("instructions") if language == "en" else None)
        or list(i18n.label(language, "default_instructions")),
        "created": datetime.now().isoformat(timespec="seconds"),
        "model": getattr(client, "model", ""),
        "sources": [s.citation() for s in sources],
        "sections": [{"name": s["name"], "instructions": s["instructions"]} for s in sections],
        "questions": questions,
        "context": {k: ctx[k] for k in ("subject", "level", "topic", "difficulty", "topics",
                                        "style", "notes", "extra", "language",
                                        "source_language")},
    }


def regenerate_question(client, exam: dict, number: int, progress: Progress | None = None,
                        seed: int | None = None) -> dict:
    """Replace one question with a new one of the same type, marks and section."""
    progress = progress or Progress()
    old = next(q for q in exam["questions"] if q["number"] == number)
    ctx = {"examples": "", **exam["context"]}
    label = QUESTION_TYPES[old["type"]]["label"]
    batch = {"count": 1, "type": old["type"], "marks": old["marks"],
             "topics": [old["topic"]] if old["topic"] else [], "targets": [old["difficulty"]],
             "description": f"- 1 × {label} question, {old['marks']} mark(s)"
                            + (" with sub-parts" if old["parts"] else "")}
    others = [q["question"] for q in exam["questions"]]
    new = write_questions(client, ctx, batch, others, random.Random(seed), progress)
    if not new:
        raise RuntimeError("The AI did not return a usable question. Try again.")
    q = new[0]
    q["section"], q["number"] = old["section"], number
    solve_questions(client, ctx, [q], progress)
    exam["questions"] = [q if x["number"] == number else x for x in exam["questions"]]
    return q


def renumber(exam: dict) -> None:
    exam["questions"].sort(key=lambda q: (q["section"], q["number"]))
    for i, q in enumerate(exam["questions"], 1):
        q["number"] = i


# --- Markdown output ----------------------------------------------------------------------

def _br(text: str) -> str:
    """Keep the model's single line breaks in every Markdown viewer."""
    return "  \n".join(text.strip().split("\n"))


def _paper_question(q: dict) -> list[str]:
    out = [f"**{q['number']}.** {_br(q['question'])} **[{q['marks']}]**", ""]
    if q["options"]:
        out += ["  \n".join(f"{chr(65 + i)}. {o}" for i, o in enumerate(q["options"])), ""]
    for p in q["parts"]:
        out += [f"({p['label']}) {_br(p['text'])} **[{p['marks']}]**", ""]
    return out


def render_markdown(exam: dict, part: str = "all") -> str:
    """part: "all", "paper", "answers" or "scheme"."""
    lang = i18n.lang(exam.get("language"))
    t = lambda key, **kw: i18n.label(lang, key, **kw)  # noqa: E731
    qs = exam["questions"]
    total = sum(q["marks"] for q in qs)
    out: list[str] = []
    if part in ("all", "paper"):
        out += [f"# {exam['title']}", "",
                f"**{t('time_allowed')}:** {exam['duration_minutes']} {t('minutes')}  \n"
                f"**{t('total_marks')}:** {total}", "",
                f"**{t('name')}:** ……………………………………………  **{t('class')}:** ……………………", "",
                f"### {t('instructions')}",
                *[f"- {line}" for line in exam["instructions"]], "", "---", ""]
        for index, sec in enumerate(exam["sections"]):
            section_qs = [q for q in qs if q["section"] == index]
            if not section_qs:
                continue
            out += [f"## {sec['name']}", "", f"*{sec['instructions']}*", ""]
            for q in section_qs:
                out += _paper_question(q)
            out += ["---", ""]
    if part in ("all", "answers"):
        out += [f"# {t('model_answers')}", "", f"> {t('answers_blurb')}", ""]
        for q in qs:
            out += [f"### {t('question', n=q['number'])}", "",
                    _br(q["answer"] or f"*{t('no_answer')}*"), ""]
            if q["final_answer"]:
                out += [f"**{t('final_answer')}:** {q['final_answer']}", ""]
        out += ["---", ""]
    if part in ("all", "scheme"):
        out += [f"# {t('marking_scheme')}", "", f"> {t('scheme_blurb')}", ""]
        for q in qs:
            out += [f"### {t('question', n=q['number'])} — {i18n.marks(lang, q['marks'])}", ""]
            if q["final_answer"]:
                out += [f"**{t('answer')}:** {q['final_answer']}", ""]
            out += [f"- {p['point']} — **{i18n.marks(lang, p['marks'])}**"
                    for p in q["marking_points"]] or [f"- *{t('no_points')}*"]
            if q["accept"]:
                out += ["", f"*{t('accept')}:* {q['accept']}"]
            out.append("")
        if exam["sources"]:
            out += ["---", "", f"**{t('sources')}:** " + "; ".join(
                f"[{s['title']}]({s['url']})" if s.get("url") else s["title"]
                for s in exam["sources"]), ""]
        model = t("with_model", model=exam["model"]) if exam.get("model") else ""
        out += [f"*{t('generated', date=exam['created'][:16].replace('T', ' '), model=model)}*", ""]
    return "\n".join(out)
