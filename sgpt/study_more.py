"""More study tools: chat with your sources, essay checker, reading comprehension,
study planner and step-by-step tutor. Every tool writes in the chosen output language."""

from __future__ import annotations

import math
import re
from collections import Counter
from datetime import date, datetime, timedelta, timezone
from pathlib import Path

from . import i18n
from .generator import Progress, _as_int, _text
from .ollama_client import parse_json

_SYSTEM = ("You are an expert, encouraging teacher. You are accurate and specific. "
           "Reply with JSON only when asked for JSON.")


def _rule(o: dict) -> str:
    return i18n.write_rule(o.get("language", "en"), o.get("source_languages"))


def _json(client, system: str, prompt: str, progress: Progress, *, think: bool = False,
          max_tokens: int = 6144) -> dict:
    for _ in range(2):
        reply = client.chat(system, prompt, json_mode=True, max_tokens=max_tokens,
                            should_stop=progress.cancelled, think=think)
        try:
            data = parse_json(reply)
        except ValueError:
            continue
        if isinstance(data, dict) and data:
            return data
    return {}


# --- Essay checker ----------------------------------------------------------------------
# Marking criteria follow each exam's usual scheme (approximate; check the current format).
ESSAY_TYPES = {
    "spm_english": ("SPM English (1119) · Writing", "English",
                    [("Content", 5), ("Communicative achievement", 5), ("Organisation", 5), ("Language", 5)]),
    "spm_bm": ("SPM Bahasa Melayu · Karangan", "Malay",
               [("Isi dan huraian", 12), ("Bahasa (tatabahasa, kosa kata)", 12), ("Penyusunan dan gaya", 6)]),
    "uec_chinese": ("UEC 华文 · 作文", "Simplified Chinese",
                    [("内容", 20), ("结构", 10), ("语言", 15), ("标点与书写", 5)]),
    "igcse_english": ("IGCSE English · Composition", "English",
                      [("Content and structure", 16), ("Style and accuracy", 24)]),
    "general": ("Any essay", "", [("Ideas and content", 10), ("Organisation", 10), ("Language", 10)]),
}


def make_essay(client, material: str, o: dict, steps, progress) -> dict:
    essay = (o.get("essay") or "").strip()
    if len(essay) < 40:
        raise RuntimeError("Paste the essay to check (at least a few sentences).")
    kind = o.get("essay_type") if o.get("essay_type") in ESSAY_TYPES else "general"
    label, essay_lang, criteria = ESSAY_TYPES[kind]
    total = sum(m for _, m in criteria)
    steps("Reading and marking the essay")
    rubric = "\n".join(f"- {name}: 0–{m}" for name, m in criteria)
    prompt = (f"Mark this essay as an experienced {label} examiner. Task/title: "
              f"{o.get('topic') or '(not given)'}. Level: {o.get('level') or 'secondary school'}.\n"
              f"Criteria:\n{rubric}\nTotal: {total}.\n"
              f"{'The essay should be written in ' + essay_lang + '. ' if essay_lang else ''}"
              "Find every language error (grammar, spelling, word choice, punctuation): quote the "
              "exact original words, the correction and a short reason. Then write an improved "
              f"version of the whole essay in the essay's own language, keeping the student's ideas.\n"
              f"{_extra(o)}\nReply with JSON: "
              '{"criteria": [{"name": "...", "score": 3, "max": 5, "comment": "..."}], '
              '"band": "short overall level, e.g. B2 / Cemerlang / 良", "summary": "two or three sentences", '
              '"strengths": ["..."], "improvements": ["specific advice"], '
              '"corrections": [{"original": "exact words", "corrected": "...", "reason": "..."}], '
              '"improved": "the full improved essay"}'
              f"\n\nESSAY:\n{essay[:12000]}")
    data = _json(client, _SYSTEM + " You mark essays fairly and consistently." + _rule(o), prompt,
                 progress, think=True, max_tokens=12000)
    if not data:
        raise RuntimeError("The AI did not return a marking. Try again or another model.")
    names = {n.lower(): (n, m) for n, m in criteria}
    rows = []
    for c in data.get("criteria") or []:
        if not isinstance(c, dict):
            continue
        name, top = names.get(_text(c.get("name")).lower(), (_text(c.get("name")), _as_int(c.get("max")) or 0))
        top = top or _as_int(c.get("max")) or 0
        score = min(max(_as_int(c.get("score")) or 0, 0), top) if top else _as_int(c.get("score")) or 0
        rows.append({"name": name, "score": score, "max": top, "comment": _text(c.get("comment"))})
    if not rows:
        rows = [{"name": n, "score": 0, "max": m, "comment": ""} for n, m in criteria]
    corrections = [{"original": _text(x.get("original")), "corrected": _text(x.get("corrected")),
                    "reason": _text(x.get("reason"))}
                   for x in data.get("corrections") or []
                   if isinstance(x, dict) and _text(x.get("original")) and _text(x.get("corrected"))]
    # Only keep corrections that quote words really in the essay.
    corrections = [x for x in corrections if x["original"] in essay][:80]
    return {"title": f"Essay check · {label}", "essay_type": kind, "essay": essay,
            "score": sum(r["score"] for r in rows), "out_of": sum(r["max"] for r in rows) or total,
            "band": _text(data.get("band")), "summary": _text(data.get("summary")),
            "criteria": rows, "strengths": [_text(x) for x in data.get("strengths") or [] if _text(x)],
            "improvements": [_text(x) for x in data.get("improvements") or [] if _text(x)],
            "corrections": corrections, "improved": _text(data.get("improved"))}


# --- Reading comprehension -------------------------------------------------------------

def make_reading(client, material: str, o: dict, steps, progress) -> dict:
    count = min(max(_as_int(o.get("count")) or 8, 3), 20)
    lang = i18n.LANGUAGES[i18n.lang(o.get("language"))]["prompt"]
    length = {"short": "about 250 words", "medium": "about 450 words", "long": "about 700 words"}.get(
        o.get("length") or "medium", "about 450 words")
    steps("Writing the passage and questions")
    base = (f"Use this material as the content of the passage:\n{material[:6000]}\n" if material
            else f"Topic: {o.get('topic') or 'a topic suitable for students'}.\n")
    prompt = (f"Write a reading comprehension exercise in {lang} for {o.get('level') or 'secondary school'} "
              f"students: an original passage of {length} with numbered paragraphs, then {count} "
              "questions that test understanding: about half multiple choice (4 options, one correct) "
              "and half short answer (literal, inference, vocabulary in context, writer's purpose). "
              f"{base}{_extra(o)}\nReply with JSON: "
              '{"title": "...", "passage": "paragraphs separated by blank lines", "questions": ['
              '{"type": "mcq", "question": "...", "options": ["...", "...", "...", "..."], "answer": 0, '
              '"explanation": "..."}, {"type": "short", "question": "...", "answer": "model answer", '
              '"marks": 2}]}')
    data = _json(client, _SYSTEM + _rule(o), prompt, progress, max_tokens=8192)
    passage = _text(data.get("passage"))
    if len(passage) < 200:
        raise RuntimeError("The AI did not return a usable passage. Try again or another model.")
    questions = []
    for q in data.get("questions") or []:
        if not isinstance(q, dict) or not _text(q.get("question")):
            continue
        options = [_text(x) for x in q.get("options") or [] if _text(x)]
        answer = q.get("answer")
        if len(options) == 4 and isinstance(_as_int(answer), int) and 0 <= _as_int(answer) < 4:
            questions.append({"type": "mcq", "question": _text(q["question"]), "options": options,
                              "answer": _as_int(answer), "explanation": _text(q.get("explanation"))})
        elif _text(answer):
            questions.append({"type": "short", "question": _text(q["question"]), "answer": _text(answer),
                              "marks": max(_as_int(q.get("marks")) or 2, 1)})
    if not questions:
        raise RuntimeError("The AI did not return usable questions. Try again or another model.")
    return {"title": _text(data.get("title")) or f"Reading: {o.get('topic') or 'comprehension'}",
            "passage": passage, "questions": questions}


# --- Step-by-step tutor ------------------------------------------------------------------

def make_tutor(client, material: str, o: dict, steps, progress) -> dict:
    question = (o.get("question") or "").strip()
    if len(question) < 5:
        raise RuntimeError("Type or paste the question you need help with.")
    steps("Working out the hints and the solution")
    prompt = (f"A {o.get('level') or 'secondary school'} student is stuck on this question. Solve it "
              "carefully yourself first. Then write 3 hints that lead the student towards the answer "
              "without giving it away (each hint a little more specific), the full worked solution "
              "as numbered steps, the final answer, common mistakes, and one similar practice "
              f"question with its answer.\n{_extra(o)}\nReply with JSON: "
              '{"topic": "...", "hints": ["...", "...", "..."], "steps": ["...", "..."], '
              '"answer": "...", "mistakes": ["..."], "similar": {"question": "...", "answer": "..."}}'
              f"\n\nQUESTION:\n{question[:4000]}")
    data = _json(client, _SYSTEM + " You are a patient one-to-one tutor." + _rule(o), prompt, progress,
                 think=True, max_tokens=8192)
    hints = [_text(x) for x in data.get("hints") or [] if _text(x)][:5]
    solution = [_text(x) for x in data.get("steps") or [] if _text(x)]
    if not hints or not (solution or _text(data.get("answer"))):
        raise RuntimeError("The AI did not return usable hints. Try again or another model.")
    similar = data.get("similar") if isinstance(data.get("similar"), dict) else {}
    return {"title": f"Tutor: {question[:60]}" + ("…" if len(question) > 60 else ""),
            "question": question, "topic": _text(data.get("topic")), "hints": hints,
            "steps": solution, "answer": _text(data.get("answer")),
            "mistakes": [_text(x) for x in data.get("mistakes") or [] if _text(x)],
            "similar": {"question": _text(similar.get("question")), "answer": _text(similar.get("answer"))}}


# --- Study planner ----------------------------------------------------------------------

def _date(value, default: date) -> date:
    try:
        return datetime.strptime(str(value)[:10], "%Y-%m-%d").date()
    except ValueError:
        return default


def plan_days(chapters: list[str], weak: list[str], start: date, exam: date, hours: float,
              rest_days: list[int] = ()) -> list[dict]:
    """A day-by-day timetable: learn each chapter (weak ones get twice the time), short
    spaced reviews 1, 3 and 7 days later, then a final stretch of past papers and revision."""
    days = [start + timedelta(d) for d in range((exam - start).days)]
    days = [d for d in days if d.weekday() not in set(rest_days)]
    if not days or not chapters:
        return []
    minutes_a_day = max(int(hours * 60), 30)
    final = min(max(round(len(days) * 0.15), 1), 7) if len(days) > 3 else 0
    learn_days, final_days = days[:len(days) - final], days[len(days) - final:]
    learning = set(learn_days)
    weights = {c: 2 if c in weak else 1 for c in chapters}
    budget = len(learn_days) * minutes_a_day * 0.8  # 20% kept for reviews
    need = {c: max(30, int(budget * w / sum(weights.values()) // 15 * 15)) for c, w in weights.items()}
    plan = {d: [] for d in days}
    queue = list(chapters)
    i = 0
    for d in learn_days:
        left = minutes_a_day - sum(t["minutes"] for t in plan[d])
        while left >= 15 and i < len(queue):
            chapter = queue[i]
            take = min(need[chapter], left)
            plan[d].append({"chapter": chapter, "kind": "learn", "minutes": take})
            need[chapter] -= take
            left -= take
            if need[chapter] <= 0:
                for gap in (1, 3, 7):  # short spaced reviews on later learning days
                    review_day = d + timedelta(gap)
                    if review_day in learning:
                        plan[review_day].append({"chapter": chapter, "kind": "review", "minutes": 15})
                i += 1
    if i < len(queue):  # not enough days: squeeze the rest into the last learning days
        for k, chapter in enumerate(queue[i:]):
            plan[learn_days[-1 - k % len(learn_days)]].append({"chapter": chapter, "kind": "learn", "minutes": 30})
    order = sorted(chapters, key=lambda c: -weights[c])
    spare = 0
    for d in learn_days:  # time left over once every chapter is learnt: past-year practice
        left = minutes_a_day - sum(t["minutes"] for t in plan[d])
        if left >= minutes_a_day * 0.5:
            plan[d].append({"chapter": f"{order[spare % len(order)]}: past-year questions", "kind": "practice",
                            "minutes": left // 15 * 15})
            spare += 1
    for n, d in enumerate(final_days):
        if n % 2 == 0:
            plan[d].append({"chapter": "Past paper (timed, full)", "kind": "mock", "minutes": minutes_a_day})
        else:
            focus = order[n // 2 % len(order)]
            plan[d].append({"chapter": f"{focus} + your mistakes from the past paper", "kind": "practice",
                            "minutes": minutes_a_day})
    return [{"date": d.isoformat(), "weekday": d.strftime("%a"), "tasks": plan[d]} for d in days]


def make_planner(client, material: str, o: dict, steps, progress) -> dict:
    today = date.today()
    start = _date(o.get("start_date"), today)
    exam = _date(o.get("exam_date"), start + timedelta(28))
    if exam <= start:
        raise RuntimeError("The exam date must be after the start date.")
    chapters = [c.strip(" -•\t") for c in re.split(r"[\n;,]", o.get("chapters") or "") if c.strip(" -•\t")]
    chapters = chapters or list(o.get("bank_chapters") or [])
    if not chapters:
        raise RuntimeError("List your chapters (one per line), or build the question bank first.")
    weak = [c for c in chapters if c.lower() in {w.strip().lower() for w in re.split(r"[\n;,]", o.get("weak") or "")}]
    hours = min(max(float(o.get("hours") or 2), 0.5), 12)
    rest = [int(x) for x in o.get("rest_days") or [] if str(x).isdigit()]
    steps("Planning your days")
    days = plan_days(chapters, weak, start, exam, hours, rest)
    if not days:
        raise RuntimeError("There are no study days between the start date and the exam.")
    tips = ""
    try:
        steps("Writing study tips")
        tips = client.chat(_SYSTEM + _rule(o),
                           f"Give 5 short, practical study tips (Markdown bullet list) for a student with "
                           f"{len(days)} study days and about {hours:g} hours a day before a "
                           f"{o.get('topic') or 'school'} exam. Weak chapters: {', '.join(weak) or 'none given'}.",
                           max_tokens=800, should_stop=progress.cancelled).strip()
    except Exception:  # noqa: BLE001 - tips are optional; the timetable is what matters
        if progress.cancelled():
            raise
    return {"title": f"Study plan · {o.get('topic') or 'exam'} on {exam.isoformat()}",
            "start": start.isoformat(), "exam_date": exam.isoformat(), "hours": hours,
            "chapters": chapters, "weak": weak, "days": days, "tips": tips}


def plan_ics(s: dict) -> str:
    """The plan as a calendar file (one all-day event per study day)."""
    def esc(t):
        return str(t).replace("\\", "\\\\").replace(";", "\\;").replace(",", "\\,").replace("\n", "\\n")
    lines = ["BEGIN:VCALENDAR", "VERSION:2.0", "PRODID:-//SGPT//Study planner//EN", "CALSCALE:GREGORIAN"]
    stamp = datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%SZ")
    for day in s["days"]:
        if not day["tasks"]:
            continue
        d = day["date"].replace("-", "")
        nxt = (date.fromisoformat(day["date"]) + timedelta(1)).isoformat().replace("-", "")
        summary = " · ".join(f"{t['chapter']}" for t in day["tasks"])[:180]
        desc = "\n".join(f"{t['kind']}: {t['chapter']} ({t['minutes']} min)" for t in day["tasks"])
        lines += ["BEGIN:VEVENT", f"UID:sgpt-{s.get('id', 'plan')}-{d}@sgpt", f"DTSTAMP:{stamp}",
                  f"DTSTART;VALUE=DATE:{d}", f"DTEND;VALUE=DATE:{nxt}", f"SUMMARY:{esc('Study: ' + summary)}",
                  f"DESCRIPTION:{esc(desc)}", "END:VEVENT"]
    exam = s["exam_date"].replace("-", "")
    lines += ["BEGIN:VEVENT", f"UID:sgpt-{s.get('id', 'plan')}-exam@sgpt", f"DTSTAMP:{stamp}",
              f"DTSTART;VALUE=DATE:{exam}", f"SUMMARY:{esc('Exam: ' + s['title'])}", "END:VEVENT", "END:VCALENDAR"]
    return "\r\n".join(lines) + "\r\n"


# --- Chat with your sources ----------------------------------------------------------------
_STOP = set("""the a an and or of to in on for is are was were be by with as at from this that it its
which what who how why when where do does did can could should would will your you yang dan di ke dari
untuk dengan ini itu ialah adalah""".split())
_CJK = re.compile(r"[\u3400-\u9fff]")


def _tokens(text: str) -> list[str]:
    words = [w for w in re.findall(r"[a-z0-9]+", text.lower()) if len(w) > 1 and w not in _STOP]
    cjk = "".join(_CJK.findall(text))
    return words + [cjk[i:i + 2] for i in range(len(cjk) - 1)]


def source_chunks(files: list[tuple[str, list[str]]], size: int = 1400) -> list[dict]:
    """Searchable pieces: [(file name, [text of page 1, page 2, …])] -> chunks with page numbers."""
    chunks = []
    for name, pages in files:
        for number, page in enumerate(pages, 1):
            page = re.sub(r"[ \t]+", " ", page).strip()
            for start in range(0, len(page), size):
                piece = page[start:start + size + 200]  # overlap a little
                if len(piece.strip()) > 40:
                    chunks.append({"file": name, "page": number if len(pages) > 1 else None, "text": piece})
    return chunks


def retrieve(chunks: list[dict], question: str, k: int = 6) -> list[dict]:
    """The k pieces most relevant to the question (BM25)."""
    if not chunks:
        return []
    docs = [Counter(_tokens(c["text"])) for c in chunks]
    avg = sum(sum(d.values()) for d in docs) / len(docs) or 1
    df = Counter(t for d in docs for t in d)
    q = _tokens(question)
    scores = []
    for i, d in enumerate(docs):
        length = sum(d.values()) or 1
        score = 0.0
        for t in q:
            if t in d:
                idf = math.log(1 + (len(docs) - df[t] + 0.5) / (df[t] + 0.5))
                score += idf * d[t] * 2.2 / (d[t] + 1.2 * (0.25 + 0.75 * length / avg))
        scores.append((score, i))
    best = [chunks[i] for s, i in sorted(scores, reverse=True)[:k] if s > 0]
    return best or chunks[:min(k, 3)]


def chat_answer(client, chat: dict, question: str, chunks: list[dict], progress: Progress) -> dict:
    """Answer from the sources, citing them as [1], [2]…; returns {"answer", "citations"}."""
    found = retrieve(chunks, question)
    excerpts = "\n\n".join(f"[{i}] ({c['file']}{', page ' + str(c['page']) if c['page'] else ''})\n{c['text']}"
                           for i, c in enumerate(found, 1))
    history = "".join(f"Student: {m['question']}\nTeacher: {m['answer'][:600]}\n\n"
                      for m in (chat.get("messages") or [])[-3:])
    prompt = (("Earlier in this conversation:\n" + history if history else "")
              + "Answer the student's question using the excerpts from their own study material below. "
              "After each fact you take from an excerpt, cite it like [1] or [2]. If the excerpts don't "
              "contain the answer, say so in one sentence, then answer from general knowledge and mark "
              "that part \"(not from your sources)\". Be clear and concise; use Markdown."
              f"\n\nEXCERPTS:\n{excerpts or '(no sources)'}\n\nQUESTION: {question}")
    answer = client.chat(_SYSTEM + _rule(chat), prompt, max_tokens=2048, should_stop=progress.cancelled)
    used = sorted({int(n) for n in re.findall(r"\[(\d+)\]", answer) if 0 < int(n) <= len(found)})
    citations = [{"n": n, "file": found[n - 1]["file"], "page": found[n - 1]["page"],
                  "text": found[n - 1]["text"][:400]} for n in used]
    return {"answer": answer.strip(), "citations": citations}


def make_chat(client, material: str, o: dict, steps, progress) -> dict:
    steps("Getting your sources ready")
    return {"title": f"Chat: {o.get('topic') or 'my study material'}", "messages": []}


def _extra(o: dict) -> str:
    return f"\nExtra instructions: {o['instructions']}\n" if o.get("instructions") else ""


KINDS = {"chat": "Chat with sources", "essay": "Essay checker", "reading": "Reading comprehension",
         "planner": "Study planner", "tutor": "Tutor"}
MAKERS = {"chat": make_chat, "essay": make_essay, "reading": make_reading, "planner": make_planner,
          "tutor": make_tutor}
# Tools that don't read sources (they get the essay, question or chapters from the form).
NO_SOURCES = {"chat", "essay", "planner", "tutor", "grammar"}


def as_markdown(s: dict) -> str:
    kind = s["kind"]
    out = [f"# {s['title']}", ""]
    if kind == "essay":
        out += [f"**Score: {s['score']} / {s['out_of']}**" + (f" · {s['band']}" if s.get("band") else ""), "",
                s.get("summary", ""), "", "| Criterion | Score | Comment |", "|---|---|---|"]
        out += [f"| {c['name']} | {c['score']}/{c['max']} | {c['comment'].replace('|', '/')} |" for c in s["criteria"]]
        out += ["", "## Strengths", ""] + [f"- {x}" for x in s["strengths"]]
        out += ["", "## How to improve", ""] + [f"- {x}" for x in s["improvements"]]
        out += ["", "## Corrections", "", "| Original | Correction | Why |", "|---|---|---|"]
        out += [f"| {c['original']} | {c['corrected']} | {c['reason']} |".replace("\n", " ") for c in s["corrections"]]
        out += ["", "## Improved version", "", s.get("improved", ""), "", "## Your essay", "", s["essay"]]
    elif kind == "reading":
        out += [s["passage"], "", "## Questions", ""]
        for i, q in enumerate(s["questions"], 1):
            out.append(f"**{i}.** {q['question']}" + (f" [{q['marks']}]" if q.get("marks") else ""))
            if q["type"] == "mcq":
                out += [""] + ["  \n".join(f"{chr(65 + j)}. {o}" for j, o in enumerate(q["options"]))]
            out.append("")
        out += ["---", "", "## Answers", ""]
        for i, q in enumerate(s["questions"], 1):
            key = f"{chr(65 + q['answer'])}. {q['options'][q['answer']]}" if q["type"] == "mcq" else q["answer"]
            out.append(f"{i}. {key}" + (f" — {q['explanation']}" if q.get("explanation") else ""))
    elif kind == "tutor":
        out += ["**Question:**", "", s["question"], ""]
        out += ["## Hints", ""] + [f"{i}. {h}" for i, h in enumerate(s["hints"], 1)]
        out += ["", "## Solution", ""] + [f"{i}. {x}" for i, x in enumerate(s["steps"], 1)]
        out += ["", f"**Answer:** {s['answer']}", ""]
        if s.get("mistakes"):
            out += ["## Common mistakes", ""] + [f"- {x}" for x in s["mistakes"]] + [""]
        if s.get("similar", {}).get("question"):
            out += ["## Try a similar one", "", s["similar"]["question"], "",
                    f"*Answer: {s['similar']['answer']}*", ""]
    elif kind == "planner":
        out += [f"From {s['start']} to the exam on **{s['exam_date']}**, about {s['hours']:g} h a day.", ""]
        if s.get("weak"):
            out += [f"Weak chapters (given extra time): {', '.join(s['weak'])}", ""]
        out += ["| Date | Plan |", "|---|---|"]
        icons = {"learn": "📖", "review": "🔁", "mock": "📝", "practice": "🎯"}
        for d in s["days"]:
            tasks = "; ".join(f"{icons.get(t['kind'], '')} {t['chapter']} ({t['minutes']} min)" for t in d["tasks"]) or "rest"
            out.append(f"| {d['weekday']} {d['date']} | {tasks.replace('|', '/')} |")
        if s.get("tips"):
            out += ["", "## Tips", "", s["tips"]]
    elif kind == "chat":
        for m in s.get("messages") or []:
            out += [f"**Q: {m['question']}**", "", m["answer"], ""]
            if m.get("citations"):
                out += ["Sources: " + "; ".join(f"[{c['n']}] {c['file']}" + (f" p.{c['page']}" if c['page'] else "")
                                                for c in m["citations"]), ""]
    return "\n".join(out)
