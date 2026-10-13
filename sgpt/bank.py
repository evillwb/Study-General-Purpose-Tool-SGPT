"""Question bank: every question from your past papers, sorted by chapter and difficulty."""

from __future__ import annotations

import uuid
from collections import defaultdict
from datetime import datetime
from pathlib import Path

from . import i18n, prompts
from .generator import (QUESTION_TYPES, Progress, _as_int, _text, pictures, solve_questions,
                        verify_questions)
from .ollama_client import Cancelled, parse_json
from .sources import Source

CLASSIFY_BATCH = 8


def _extract(client, paper: Source, progress: Progress) -> list[dict]:
    """Questions of one paper: the detected numbering, or the AI when that finds too few."""
    found = [{"number": q.number, "text": q.text.strip(), "marks": q.marks,
              "section": q.section, "page": q.page}
             for q in paper.paper.questions if len(q.text.strip()) > 10]
    # Trust the detected numbering unless it found very few questions for a long file.
    if len(found) >= 3 and len(found) * 2500 >= len(paper.text):
        return found
    questions = []
    text = paper.text
    chunks = range(0, len(text), 12000)
    for n, start in enumerate(chunks, 1):
        progress.step(0, 1, f"Finding the questions in {paper.title} (part {n} of {len(chunks)})")
        reply = client.chat(prompts.BANK_EXTRACT_SYSTEM,
                            prompts.BANK_EXTRACT_PROMPT.format(name=paper.title,
                                                               text=text[start:start + 12000]),
                            json_mode=True, max_tokens=8192, should_stop=progress.cancelled)
        try:
            data = parse_json(reply)
        except ValueError:
            continue
        for q in data.get("questions") or []:
            if isinstance(q, dict) and len(_text(q.get("text"))) > 10:
                questions.append({"number": _text(q.get("number")) or str(len(questions) + 1),
                                  "text": _text(q.get("text")), "marks": _as_int(q.get("marks")),
                                  "section": _text(q.get("chapter")), "page": 0})
    return questions if len(questions) > len(found) else found


def _snippet(q: dict, length: int) -> str:
    text = " ".join(q["text"].split())
    return text[:length] + ("…" if len(text) > length else "")


def _picture(image_dir: Path | None, q: dict) -> bytes | None:
    if image_dir and q.get("image"):
        try:
            return (image_dir / q["image"]).read_bytes()
        except OSError:
            return None
    return None


def build_bank(client, papers: list[Source], *, subject: str = "", topics: list[str] = (),
               progress: Progress | None = None, image_dir: Path | None = None,
               language: str = "") -> dict:
    """Every question of the past papers, sorted into chapters with a difficulty rating.

    With image_dir, a picture of each question (cut from its page) is saved there, shown
    in the bank, and given to the AI when the model can see images.
    """
    progress = progress or Progress()
    rule = i18n.describe_rule(language) if language else ""
    done, total = 0, len(papers) * (2 if image_dir else 1) + 2

    questions: list[dict] = []
    for paper in papers:
        progress.step(done, total, f"Finding the questions in {paper.title}")
        sections: list[str] = []
        for q in _extract(client, paper, progress):
            if q.get("section") and q["section"] not in sections:
                sections.append(q["section"])
            part = f"-s{sections.index(q['section']) + 1}" if q.get("section") else ""
            questions.append({"id": f"p{papers.index(paper) + 1}{part}-q{q['number']}",
                              "paper": paper.title, **q})
        done += 1
    if not questions:
        raise RuntimeError("No questions were found in the past papers.")
    if image_dir:
        from .snapshots import snapshot_questions

        for i, paper in enumerate(papers, 1):
            if progress.cancelled():
                raise Cancelled()
            progress.step(done, total, f"Taking pictures of the questions in {paper.title}")
            mine = [q for q in questions if q["paper"] == paper.title]
            if paper.paper and paper.paper.path.suffix.lower() == ".pdf":
                try:
                    snapshot_questions(paper.paper.path, mine, image_dir, f"p{i}-")
                except (RuntimeError, ValueError, OSError) as exc:
                    progress.warn(f"could not take pictures of {paper.title}: {exc}")
            done += 1
    # Make ids unique even if a paper repeats a number.
    seen: dict[str, int] = {}
    for q in questions:
        seen[q["id"]] = seen.get(q["id"], 0) + 1
        if seen[q["id"]] > 1:
            q["id"] += f"-{seen[q['id']]}"

    total = done + 1 + -(-len(questions) // CLASSIFY_BATCH)
    progress.step(done, total, "Working out the chapters")
    hint = f"Topics seen in these papers: {', '.join(topics[:30])}" if topics else ""
    listing = "\n".join(f"- {_snippet(q, 160)}" for q in questions[:120])
    chapters: list[str] = []
    for _ in range(2):
        reply = client.chat(prompts.BANK_CHAPTERS_SYSTEM + rule,
                            prompts.BANK_CHAPTERS_PROMPT.format(subject=subject or "school",
                                                                hint=hint, questions=listing),
                            json_mode=True, max_tokens=2048, should_stop=progress.cancelled)
        try:
            chapters = [c for c in (_text(x) for x in parse_json(reply).get("chapters") or []) if c][:15]
        except (ValueError, AttributeError):
            continue
        if chapters:
            break
    chapters = chapters or list(topics[:12]) or ["General"]
    done += 1

    lookup = {c.lower(): c for c in chapters}
    for start in range(0, len(questions), CLASSIFY_BATCH):
        batch = questions[start:start + CLASSIFY_BATCH]
        progress.step(done, total, f"Sorting questions {start + 1}–{start + len(batch)} of {len(questions)}")
        items = "\n\n".join(f"[id: {q['id']}] ({q['marks'] or '?'} marks)\n{_snippet(q, 1500)}" for q in batch)
        images, note = pictures(client, [{"id": q["id"], "picture": _picture(image_dir, q)} for q in batch],
                                "the question with id")
        for _ in range(2):
            reply = client.chat(prompts.BANK_CLASSIFY_SYSTEM + rule,
                                prompts.BANK_CLASSIFY_PROMPT.format(chapters="; ".join(chapters),
                                                                    questions=items) + note,
                                json_mode=True, max_tokens=4096, should_stop=progress.cancelled,
                                **({"images": images} if images else {}))
            try:
                rows = parse_json(reply).get("questions") or []
            except (ValueError, AttributeError):
                continue
            by_id = {_text(r.get("id")): r for r in rows if isinstance(r, dict)}
            for i, q in enumerate(batch):
                r = by_id.get(q["id"]) or (rows[i] if i < len(rows) and isinstance(rows[i], dict) else {})
                chapter = _text(r.get("chapter"))
                q["chapter"] = lookup.get(chapter.lower(), chapter or "Other")
                q["topic"] = _text(r.get("topic"))
                qtype = _text(r.get("type")).lower()
                q["type"] = qtype if qtype in QUESTION_TYPES else "short"
                q["difficulty"] = min(max(_as_int(r.get("difficulty")) or 5, 1), 10)
                q["reason"] = _text(r.get("reason"))
            break
        for q in batch:  # anything the AI skipped
            q.setdefault("chapter", "Other")
            q.setdefault("topic", "")
            q.setdefault("type", "short")
            q.setdefault("difficulty", 5)
            q.setdefault("reason", "")
        done += 1
    progress.step(total, total, "Done")

    order = chapters + sorted({q["chapter"] for q in questions} - set(chapters))
    return {
        "id": uuid.uuid4().hex[:10],
        "created": datetime.now().isoformat(timespec="seconds"),
        "model": getattr(client, "model", ""),
        "subject": subject,
        "language": language,
        "papers": [p.title for p in papers],
        "chapters": [c for c in order if any(q["chapter"] == c for q in questions)],
        "questions": questions,
    }


def hardest(bank: dict, per_chapter: int = 10) -> dict[str, list[dict]]:
    """The hardest questions in each chapter, hardest first (ties: more marks first)."""
    groups: dict[str, list[dict]] = defaultdict(list)
    for q in bank["questions"]:
        groups[q["chapter"]].append(q)
    return {c: sorted(groups[c], key=lambda q: (-q["difficulty"], -(q["marks"] or 0)))[:per_chapter]
            for c in bank["chapters"] if groups.get(c)}


def solve_bank_questions(client, bank: dict, ids: list[str], language: str = "en",
                         progress: Progress | None = None, image_dir: Path | None = None) -> None:
    """Write (and double-check) answers for chosen past-paper questions."""
    progress = progress or Progress()
    chosen = [q for q in bank["questions"] if q["id"] in set(ids) and not q.get("answer")]
    ctx = {"level": "", "subject": bank.get("subject") or "", "notes": "", "language": language,
           "source_language": "auto"}
    for start in range(0, len(chosen), 4):
        batch = chosen[start:start + 4]
        progress.step(start // 4, -(-len(chosen) // 4), f"Answering questions {start + 1}–{start + len(batch)}")
        work = [{"number": i + 1, "marks": q["marks"] or 1, "type": q["type"], "question": q["text"],
                 "options": [], "parts": [], "answer": "", "final_answer": "", "marking_points": [],
                 "accept": "", "picture": _picture(image_dir, q)} for i, q in enumerate(batch)]
        solve_questions(client, ctx, work, progress)
        verify_questions(client, ctx, work, progress)
        for q, w in zip(batch, work):
            for key in ("answer", "final_answer", "marking_points", "accept", "check", "check_note"):
                if w.get(key):
                    q[key] = w[key]


def render_bank(bank: dict, view: str = "chapters", per_chapter: int = 10,
                language: str = "en", pictures: bool = False) -> str:
    """Markdown of the bank: all questions by chapter, or the hardest per chapter.

    With pictures, a question that has one is shown as its picture (file name relative to
    the bank's image folder) instead of its extracted text."""
    title = ("Hardest past-year questions" if view == "hardest" else "Past-year questions by chapter")
    out = [f"# {title}", "", f"*From: {', '.join(bank['papers'])}*", ""]
    groups = hardest(bank, per_chapter) if view == "hardest" else {
        c: [q for q in bank["questions"] if q["chapter"] == c] for c in bank["chapters"]}
    for chapter, qs in groups.items():
        if not qs:
            continue
        out += [f"## {chapter}", ""]
        for n, q in enumerate(qs, 1):
            marks = f" [{i18n.marks(language, q['marks'])}]" if q.get("marks") else ""
            where = f"{q['paper']} — " + (f"{q['section']}, " if q.get("section") else "") + f"Q{q['number']}"
            out += [f"### {n}. {where}{marks} · difficulty {q['difficulty']}/10", ""]
            if pictures and q.get("image"):
                out += [f"![Question {q['number']}]({q['image']})", ""]
            else:
                out += ["  \n".join(q["text"].split("\n")), ""]
            if view == "hardest" and q.get("reason"):
                out += [f"*Why it's hard: {q['reason']}*", ""]
            if q.get("answer"):
                out += ["**Answer:**", "", "  \n".join(q["answer"].split("\n")), ""]
                if q.get("marking_points"):
                    out += [f"- {p['point']} ({p['marks']})" for p in q["marking_points"]] + [""]
    return "\n".join(out)
