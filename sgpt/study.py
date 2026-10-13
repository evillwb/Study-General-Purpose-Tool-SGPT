"""Study tools: notes, flashcards, vocabulary, MCQ quizzes and grammar tests."""

from __future__ import annotations

import csv
import io
import json
import random
import re
import uuid
from datetime import datetime

from . import i18n
from .generator import NOTES_LIMIT, Progress, _as_int, _chunks, _text, summarise_source
from .ollama_client import parse_json
from .sources import Source, source_languages


def _rule(o: dict) -> str:
    """Write in the chosen language; the sources may be in others."""
    return i18n.write_rule(o.get("language", "en"), o.get("source_languages"))


KINDS = {"notes": "Notes", "flashcards": "Flashcards", "vocab": "Vocabulary",
         "quiz": "MCQ quiz", "grammar": "Grammar test"}
NOTE_STYLES = {
    "chapter": "Chapter notes in the style of a good revision handout: a '# ' chapter title; "
               "first a '## Key terms' table with columns 'Term', 'Definition' and 'Example'; then "
               "one '## ' section per sub-topic with short bullet points, comparison tables where "
               "things are compared, and processes written as arrow flows (A → B → C). Short "
               "phrases, not long paragraphs.",
    "detailed": "Detailed study notes: clear headings and sub-headings, short paragraphs and "
                "bullet points, key terms in **bold**, definitions, formulas, worked examples "
                "and common mistakes.",
    "summary": "A short summary: a one-paragraph overview, then the 8-15 most important key "
               "points as bullets, then a 'Remember' box (a quote block) with the must-know facts.",
    "cornell": "Cornell notes: a Markdown table with two columns, 'Cue / question' and 'Notes', "
               "one row per idea, followed by a '## Summary' paragraph.",
    "outline": "A hierarchical outline: nested bullet points (up to 4 levels), short phrases, "
               "no long paragraphs.",
    "mindmap": "A mind map written as a nested bullet list: one top-level bullet for the "
               "central topic, 4-8 main branches under it, and 2-5 short sub-branches each. "
               "Only the bullet list, a few words per bullet.",
    "key_terms": "A glossary: a Markdown table with columns 'Term', 'Meaning' and 'Example', "
                 "covering every important term.",
}
NOTE_STYLE_LABELS = {
    "guide": "Exam study guide (print edition)", "chapter": "Chapter notes with tables",
    "detailed": "Detailed notes", "summary": "Summary + key points", "cornell": "Cornell notes",
    "outline": "Outline", "mindmap": "Mind map", "key_terms": "Key terms glossary",
}
NOTE_LENGTH = {"short": "about 300 words", "medium": "about 700 words", "long": "about 1500 words"}
# Grammar tests: id -> (label, language tested, item kind, what to write).
# Kinds: "fill" (type the missing word), "error" (pick the wrong part of 4), "mcq" (choose).
_GRAMMAR = {
    "en_tenses": ("English · Tenses", "en", "fill",
                  "verb TENSES. Each sentence has a gap \"_____\" with the base verb in brackets right "
                  "after it, e.g. \"Yesterday she _____ (go) to the market.\" Mix present, past and future; "
                  "simple, continuous and perfect; and passive where suitable"),
    "en_word_form": ("English · Word form", "en", "fill",
                     "WORD FORMS. Each sentence has a gap \"_____\" and the root word in capitals in brackets "
                     "at the end, e.g. \"The scenery was _____. (BEAUTY)\". The student changes the root into "
                     "the right form (noun, verb, adjective, adverb, negative prefix, plural…)"),
    "en_error": ("English · Error identification", "en", "error",
                 "ERROR IDENTIFICATION. Each sentence is split into exactly 4 parts (A–D); exactly one part "
                 "has a grammar error (tense, agreement, preposition, article, word form, pronoun…)"),
    "en_prepositions": ("English · Prepositions", "en", "mcq",
                        "PREPOSITIONS. Each sentence has a gap \"_____\" and 4 preposition options; exactly "
                        "one is correct"),
    "en_agreement": ("English · Subject–verb agreement", "en", "mcq",
                     "SUBJECT–VERB AGREEMENT. Each sentence has a gap \"_____\" and 4 verb options "
                     "(e.g. is / are / was / were); exactly one is correct, including tricky subjects "
                     "(each, neither…nor, collective nouns, a number of…)"),
    "zh_sick": ("中文 · 病句辨析", "zh", "mcq",
                "病句辨析. Each item asks \"下列句子中，没有语病的一项是\" (or \"有语病的一项是\"), with 4 "
                "sentences as the options; exactly one fits. Errors: 搭配不当, 成分残缺或赘余, 语序不当, "
                "前后矛盾, 不合逻辑"),
    "zh_typos": ("中文 · 错别字", "zh", "error",
                 "错别字. Each sentence is split into exactly 4 parts (A–D); exactly one part contains a "
                 "wrongly written character (同音字 or 形近字). The correction is the right word"),
    "zh_measure": ("中文 · 量词", "zh", "mcq",
                   "量词. Each sentence has a gap \"_____\" where a measure word goes, and 4 measure-word "
                   "options; exactly one is correct"),
    "zh_connectives": ("中文 · 关联词", "zh", "mcq",
                       "关联词. Each sentence has one or two gaps \"_____\" for conjunctions (因为…所以, 虽然…但是, "
                       "不但…而且, 即使…也, 只要…就…), and 4 options; exactly one is correct"),
    "zh_idioms": ("中文 · 成语运用", "zh", "mcq",
                  "成语运用. Each sentence has a gap \"_____\" for an idiom (成语), and 4 idiom options; "
                  "exactly one fits the meaning and context"),
    "ms_error": ("Melayu · Kesalahan bahasa", "ms", "error",
                 "KENAL PASTI KESALAHAN (SPM style). Each sentence is split into exactly 4 parts (A–D); "
                 "exactly one part has an error (ejaan, imbuhan, kata sendi nama, penjodoh bilangan, kata "
                 "ganda, struktur ayat, istilah)"),
    "ms_affixes": ("Melayu · Imbuhan", "ms", "fill",
                   "IMBUHAN. Each sentence has a gap \"_____\" with the kata dasar in brackets right after "
                   "it, e.g. \"Dia _____ (ajar) adiknya membaca.\" The student writes the correct form with "
                   "awalan, akhiran, apitan or sisipan"),
    "ms_measure": ("Melayu · Penjodoh bilangan", "ms", "mcq",
                   "PENJODOH BILANGAN. Each sentence has a gap \"_____\" for a penjodoh bilangan (sebuah, "
                   "seekor, sebatang, sekuntum, seutas…) and 4 options; exactly one is correct"),
    "ms_prepositions": ("Melayu · Kata sendi nama", "ms", "mcq",
                        "KATA SENDI NAMA. Each sentence has a gap \"_____\" and 4 options (di, ke, dari, "
                        "daripada, pada, kepada, untuk, bagi, akan…); exactly one is correct"),
    "ms_proverbs": ("Melayu · Peribahasa", "ms", "mcq",
                    "PERIBAHASA. Each item describes a situation and asks which peribahasa fits best, with "
                    "4 peribahasa as the options; exactly one is correct"),
}
GRAMMAR_TESTS = {test: label for test, (label, *_rest) in _GRAMMAR.items()}

_GRAMMAR_SHAPES = {
    "fill": '{"items": [{"sentence": "... _____ ...", "base": "word in brackets", "answer": "...", '
            '"alternatives": ["other correct answers"], "explanation": "..."}]}',
    "error": '{"items": [{"segments": ["part A", "part B", "part C", "part D"], "error_index": 2, '
             '"correction": "the corrected part", "explanation": "..."}]}',
    "mcq": '{"items": [{"question": "the sentence with _____, or the question", '
           '"options": ["...", "...", "...", "..."], "answer": 0, "explanation": "..."}]}',
}

_SYSTEM = ("You are an expert teacher who writes accurate, clear study material for students. "
           "Reply with JSON only when asked for JSON.")


def _ask_json(client, system: str, prompt: str, key: str, progress: Progress,
              max_tokens: int = 6144, think: bool = False) -> list:
    for _ in range(2):
        reply = client.chat(system, prompt, json_mode=True, max_tokens=max_tokens,
                            should_stop=progress.cancelled, think=think)
        try:
            data = parse_json(reply)
        except ValueError:
            continue
        items = data.get(key) if isinstance(data, dict) else None
        if isinstance(items, list) and items:
            return items
    return []


def _material(client, sources: list[Source], topic: str, language: str, progress: Progress,
              steps) -> str:
    """Condense the sources into notes the tools can work from (short sources pass through)."""
    total = sum(len(s.text) for s in sources)
    if total <= 9000:
        return "\n\n".join(f"[{s.title}]\n{s.text}" for s in sources)
    notes = [summarise_source(client, s, topic, 9000, steps, progress, language)
             for s in sources]
    return "\n\n".join(n for n in notes if n)[:NOTES_LIMIT]


class _Steps:
    def __init__(self, progress: Progress, total: int):
        self.progress, self.total, self.done = progress, total, 0

    def __call__(self, message: str) -> None:
        self.progress.step(self.done, max(self.total, self.done + 1), message)
        self.done += 1


# --- Generators ------------------------------------------------------------------------

def make_notes(client, material: str, o: dict, steps, progress) -> dict:
    if o.get("style") == "guide":
        return make_guide(client, material, o, steps, progress)
    style = o.get("style") if o.get("style") in NOTE_STYLES else "detailed"
    steps("Writing your notes")
    prompt = (f"Write {NOTE_STYLES[style]}\nLength: {NOTE_LENGTH.get(o.get('length'), NOTE_LENGTH['medium'])}."
              f"\nTopic: {o['topic'] or 'as in the material'}\nLevel: {o.get('level') or 'secondary school'}"
              f"\nStart with a '# ' title. Write in Markdown only (no JSON, no code fences)."
              f"{_extra(o)}\n\nMATERIAL:\n{material or '(none: use your own accurate knowledge)'}")
    text = client.chat(_SYSTEM + _rule(o), prompt, max_tokens=8192,
                       should_stop=progress.cancelled)
    text = re.sub(r"^```(?:markdown|md)?\s*|\s*```$", "", text.strip())
    title = next((ln[2:].strip() for ln in text.splitlines() if ln.startswith("# ")), o["topic"] or "Notes")
    return {"title": title, "style": style, "markdown": text}


GUIDE_SYSTEM = (
    "You write exam study guides that top students print and revise from: exact formulas and "
    "facts, the methods examiners reward, and the traps that lose marks. Concise and accurate. "
    "Write maths as plain text (x², √, ×, π, fractions like 3/4), never LaTeX."
)


def make_guide(client, material: str, o: dict, steps, progress) -> dict:
    """A print-ready study guide built chapter by chapter (one AI call per chapter), with
    overview tables computed from the question bank and past-paper analysis when available."""
    bank, analysis = o.get("bank"), o.get("analysis") or {}
    topic = o["topic"] or analysis.get("subject") or "the course"
    system = GUIDE_SYSTEM + _rule(o)

    # 1. Chapters: from the question bank, the analysis, or the AI.
    if bank:
        chapters = list(bank["chapters"])
    else:
        steps("Planning the chapters")
        chapters = [_text(c) for c in _ask_json(
            client, _SYSTEM, f"List the chapters (4-14, teaching order, short names) a study "
            f"guide for {topic} ({o.get('level') or 'secondary school'}) should cover."
            + (f" Topics seen in past papers: {', '.join(analysis.get('topics', [])[:30])}." if analysis else "")
            + f'\nReply with JSON: {{"chapters": ["..."]}}\n\nMATERIAL:\n{material[:6000]}',
            "chapters", progress, max_tokens=1024) if _text(c)][:14]
        chapters = chapters or analysis.get("topics", [])[:10] or [topic]
    counts = {c: [q for q in (bank or {}).get("questions", []) if q["chapter"] == c] for c in chapters}

    # 2. One section per chapter.
    sections = []
    for n, chapter in enumerate(chapters, 1):
        steps(f"Writing chapter {n} of {len(chapters)}: {chapter}")
        past = sorted(counts.get(chapter, []), key=lambda q: -q["difficulty"])[:5]
        examples = "\n".join(f"- ({q['paper']} Q{q['number']}, difficulty {q['difficulty']}/10) "
                             f"{' '.join(q['text'].split())[:300]}" for q in past)
        prompt = (f"Write the study-guide section for chapter {n}: {chapter} ({topic}, "
                  f"{o.get('level') or 'secondary school'}).\n"
                  f"Format exactly:\n## {n}. {chapter}\n"
                  "> Key formulas, definitions and facts to know, one per line (this becomes a "
                  "shaded box; start every line with '> ')\n\n"
                  "Then 4-8 bullet points: the methods to use, what the exam usually asks, and "
                  "common mistakes (mark these 'Trap:'). Add a small table only if comparing things."
                  + _extra(o)
                  + (f"\n\nReal past-paper questions from this chapter (the hardest first):\n{examples}" if examples else "")
                  + f"\n\nMATERIAL:\n{material[:7000] or '(none: use your own accurate knowledge)'}")
        text = client.chat(system, prompt, max_tokens=4096, should_stop=progress.cancelled)
        text = re.sub(r"^```(?:markdown|md)?\s*|\s*```$", "", text.strip())
        if not text.lstrip().startswith("## "):
            text = f"## {n}. {chapter}\n\n{text}"
        sections.append(text)

    # 3. Overview and checklist, from real data where we have it.
    papers = (bank or {}).get("papers") or [p.get("name") for p in analysis.get("papers", [])] if (bank or analysis) else []
    out = [f"# {topic} — Study Guide", "",
           f"*{o.get('level') or ''} study notes: key facts, methods, past-paper patterns and a revision checklist*".replace("* ", "*"),
           ""]
    if papers:
        out += [f"Based on: {', '.join(papers)}", ""]
    merged = analysis.get("merged") if "merged" in analysis else analysis
    if merged and merged.get("sections"):
        out += ["## Exam overview", "", "| Section | Questions | Marks | Question types |", "|---|---|---|---|"]
        out += [f"| {sec['name']} | {sec['question_count']} | {sec.get('marks') or '–'} | "
                f"{', '.join(sec.get('question_types') or []) or '–'} |" for sec in merged["sections"]]
        if merged.get("duration_minutes"):
            out += ["", f"Time allowed: {merged['duration_minutes']} minutes."]
        if merged.get("command_words"):
            out += ["", f"Command words to know: {', '.join(merged['command_words'])}."]
        out.append("")
    if bank:
        out += ["## Past-paper patterns", "",
                "How often each chapter appears in your past papers, and how hard its questions are.", "",
                "| Chapter | Questions | Marks | Avg difficulty | Hardest |", "|---|---|---|---|---|"]
        ranked = sorted(chapters, key=lambda c: -len(counts[c]))
        for c in ranked:
            qs = counts[c]
            if not qs:
                continue
            avg = sum(q["difficulty"] for q in qs) / len(qs)
            top = max(qs, key=lambda q: q["difficulty"])
            out.append(f"| {c} | {len(qs)} | {sum(q['marks'] or 0 for q in qs) or '–'} | {avg:.1f}/10 | "
                       f"{top['paper']} Q{top['number']} ({top['difficulty']}/10) |")
        out += ["", "## Revision checklist", ""]
        for label, group in (("Priority 1: asked most often", ranked[:max(1, len(ranked) // 3)]),
                             ("Priority 2", ranked[max(1, len(ranked) // 3):2 * max(1, len(ranked) // 3)]),
                             ("Priority 3", ranked[2 * max(1, len(ranked) // 3):])):
            if group:
                out += [f"**{label}**", ""] + [f"- [ ] {c}" for c in group if counts[c]] + [""]
    out += ["## Topic notes", ""] + [s + "\n" for s in sections]

    steps("Writing the must-memorise list")
    memo = client.chat(system, "From these study notes, list the facts and formulas a student must "
                       "memorise (the ones most often needed and easiest to forget), grouped under "
                       "short '### ' headings, as bullet points. Markdown only.\n\n"
                       + "\n\n".join(sections)[:9000], max_tokens=2048, should_stop=progress.cancelled)
    out += ["## Must memorise", "", re.sub(r"^```(?:markdown|md)?\s*|\s*```$", "", memo.strip()), ""]
    return {"title": f"{topic} — Study Guide", "style": "guide", "markdown": "\n".join(out)}


def make_flashcards(client, material: str, o: dict, steps, progress) -> dict:
    count = min(max(_as_int(o.get("count")) or 20, 1), 100)
    cards: list[dict] = []
    while len(cards) < count:
        n = min(15, count - len(cards))
        steps(f"Writing flashcards {len(cards) + 1}–{len(cards) + n}")
        avoid = "; ".join(c["front"][:60] for c in cards[-30:])
        prompt = (f"Make {n} flashcards for revising: {o['topic'] or 'the material'} "
                  f"({o.get('level') or 'secondary school'}). One idea per card: a question, term or "
                  f"prompt on the front, a short accurate answer on the back (1-3 sentences).\n"
                  + (f"Do not repeat: {avoid}\n" if avoid else "") + _extra(o) +
                  '\nReply with JSON: {"cards": [{"front": "...", "back": "..."}]}'
                  f"\n\nMATERIAL:\n{material or '(none: use your own accurate knowledge)'}")
        items = _ask_json(client, _SYSTEM + _rule(o), prompt, "cards", progress)
        new = [{"front": _text(c.get("front")), "back": _text(c.get("back"))}
               for c in items if isinstance(c, dict) and _text(c.get("front")) and _text(c.get("back"))]
        if not new:
            break
        cards += new[:n]
    return {"title": f"Flashcards: {o['topic'] or 'my notes'}", "cards": cards}


def make_vocab(client, material: str, o: dict, steps, progress) -> dict:
    words = [w.strip() for w in re.split(r"[\n,;]+", o.get("words") or "") if w.strip()][:100]
    target = o.get("translate_to") if o.get("translate_to") in i18n.LANGUAGES else ""
    translation = (f"\"translation\": the word in {i18n.LANGUAGES[target]['prompt']}, "
                   if target else "\"translation\": \"\", ")
    items: list[dict] = []
    batches = [words[i:i + 12] for i in range(0, len(words), 12)] if words else [None] * max(
        1, -(-min(max(_as_int(o.get("count")) or 20, 1), 60) // 12))
    want = min(max(_as_int(o.get("count")) or 20, 1), 60)
    for batch in batches:
        n = len(batch) if batch else min(12, want - len(items))
        if n <= 0:
            break
        steps(f"Explaining words {len(items) + 1}–{len(items) + n}")
        what = ("these words: " + ", ".join(batch)) if batch else (
            f"the {n} most useful words to learn for: {o['topic'] or 'the material'}"
            + (f" (not: {', '.join(i['word'] for i in items)})" if items else ""))
        prompt = (f"Explain {what}. Level: {o.get('level') or 'secondary school'}.\n"
                  "For each word give: \"word\", \"part_of_speech\", \"meaning\" (simple, clear), "
                  "\"example\" (one natural sentence using it), " + translation +
                  "\"synonyms\" (up to 3). Explanations and examples in the requested language."
                  + _extra(o) +
                  '\nReply with JSON: {"words": [{"word": "...", "part_of_speech": "...", "meaning": "...",'
                  ' "example": "...", "translation": "...", "synonyms": ["..."]}]}'
                  + (f"\n\nMATERIAL:\n{material}" if material and not batch else ""))
        rows = _ask_json(client, _SYSTEM + _rule(o), prompt, "words", progress)
        for r in rows:
            if isinstance(r, dict) and _text(r.get("word")) and _text(r.get("meaning")):
                items.append({k: _text(r.get(k)) for k in ("word", "part_of_speech", "meaning",
                                                           "example", "translation")}
                             | {"synonyms": [_text(s) for s in (r.get("synonyms") or []) if _text(s)][:3]})
    return {"title": f"Vocabulary: {o['topic'] or ', '.join(words[:3]) or 'list'}",
            "translate_to": target, "words": items}


def make_quiz(client, material: str, o: dict, steps, progress) -> dict:
    count = min(max(_as_int(o.get("count")) or 10, 1), 60)
    difficulty = o.get("difficulty") if o.get("difficulty") in ("easy", "medium", "hard", "mixed") else "mixed"
    items: list[dict] = []
    while len(items) < count:
        n = min(8, count - len(items))
        steps(f"Writing questions {len(items) + 1}–{len(items) + n}")
        avoid = "; ".join(q["question"][:70] for q in items[-20:])
        prompt = (f"Write {n} multiple-choice questions on: {o['topic'] or 'the material'} "
                  f"({o.get('level') or 'secondary school'}), difficulty: {difficulty}. "
                  "Exactly 4 options each, one clearly correct, believable wrong options, no "
                  "'all of the above'. Vary which option is correct.\n"
                  + (f"Do not repeat: {avoid}\n" if avoid else "") + _extra(o) +
                  '\nReply with JSON: {"questions": [{"question": "...", "options": ["...", "...", "...", "..."],'
                  ' "answer": 0, "explanation": "why the answer is right"}]} where "answer" is the index 0-3.'
                  f"\n\nMATERIAL:\n{material or '(none: use your own accurate knowledge)'}")
        rows = _ask_json(client, _SYSTEM + _rule(o), prompt, "questions", progress)
        new = []
        for r in rows:
            options = [re.sub(r"^\s*\(?[A-Da-d][).:]\s+", "", _text(x)) for x in (r.get("options") or [])
                       if _text(x)] if isinstance(r, dict) else []
            answer = _as_int(r.get("answer")) if isinstance(r, dict) else None
            if len(options) == 4 and answer is not None and 0 <= answer < 4 and _text(r.get("question")):
                new.append({"type": "mcq", "question": _text(r["question"]), "options": options,
                            "answer": answer, "explanation": _text(r.get("explanation"))})
        if not new:
            break
        steps(f"Double-checking questions {len(items) + 1}–{len(items) + len(new)}")
        items += _check_items(client, new, o, progress)[:n]
    random.shuffle(items)
    return {"title": f"Quiz: {o['topic'] or 'my notes'}", "items": items}


def make_grammar(client, material: str, o: dict, steps, progress) -> dict:
    """A grammar test in English, Chinese or Malay. The sentences are in the language being
    tested; instructions and explanations are in the chosen output language (o["language"])."""
    test = o.get("test") if o.get("test") in _GRAMMAR else "en_tenses"
    label, tested, kind, what = _GRAMMAR[test]
    tested_name = i18n.LANGUAGES[tested]["prompt"]
    explain_in = i18n.LANGUAGES[i18n.lang(o.get("language") or tested)]["prompt"]
    count = min(max(_as_int(o.get("count")) or 15, 1), 60)
    system = (_SYSTEM + f" You write {tested_name} grammar test items for students. Every sentence "
              f"and option is in natural, correct {tested_name} (except the one deliberate error "
              f"where the item has one). Write each \"explanation\" (and nothing else) in {explain_in}.")
    items: list[dict] = []
    while len(items) < count:
        n = min(10, count - len(items))
        steps(f"Writing items {len(items) + 1}–{len(items) + n}")
        theme = f" Theme of the sentences: {o['topic']}." if o.get("topic") else ""
        avoid = "; ".join((i.get("sentence") or i.get("question") or " ".join(i.get("segments", [])))[:60]
                          for i in items[-20:])
        prompt = (f"Write {n} {tested_name} grammar items testing {what}. Exactly one correct answer "
                  f"per item. Level: {o.get('level') or 'secondary school'}.{theme}\n"
                  + (f"Do not repeat: {avoid}\n" if avoid else "") + _extra(o)
                  + f"\nReply with JSON: {_GRAMMAR_SHAPES[kind]}")
        rows = _ask_json(client, system, prompt, "items", progress)
        new = [item for item in (_grammar_item(kind, r) for r in rows) if item]
        if not new:
            break
        steps(f"Double-checking items {len(items) + 1}–{len(items) + len(new)}")
        items += _check_items(client, new, {**o, "language": i18n.lang(o.get("language") or tested)},
                              progress)[:n]
    return {"title": label + (f": {o['topic']}" if o.get("topic") else ""), "test": test,
            "tested_language": tested, "items": items}


def _grammar_item(kind: str, r) -> dict | None:
    """One item from the AI's reply in the shape the quiz runner uses, or None if unusable."""
    if not isinstance(r, dict):
        return None
    explanation = _text(r.get("explanation"))
    if kind == "error":
        segments = [_text(s) for s in r.get("segments") or [] if _text(s)]
        index = _as_int(r.get("error_index"))
        if len(segments) == 4 and index is not None and 0 <= index < 4 and _text(r.get("correction")):
            return {"type": "error", "segments": segments, "answer": index,
                    "correction": _text(r["correction"]), "explanation": explanation}
        return None
    if kind == "mcq":
        options = [_text(x) for x in r.get("options") or [] if _text(x)]
        answer = _as_int(r.get("answer"))
        if len(options) == 4 and answer is not None and 0 <= answer < 4 and _text(r.get("question")):
            return {"type": "mcq", "question": _text(r["question"]), "options": options,
                    "answer": answer, "explanation": explanation}
        return None
    if "_____" in _text(r.get("sentence")) and _text(r.get("answer")):
        return {"type": "fill", "sentence": _text(r["sentence"]), "base": _text(r.get("base")),
                "answer": _text(r["answer"]),
                "alternatives": [_text(a) for a in r.get("alternatives") or [] if _text(a)],
                "explanation": explanation}
    return None


def _check_items(client, items: list[dict], o: dict, progress: Progress) -> list[dict]:
    """Independent re-solve of quiz/grammar items: fix wrong keys, drop broken items."""
    numbered = [{"n": i + 1, **{k: v for k, v in it.items() if k != "type"}} for i, it in enumerate(items)]
    prompt = ("Check these test items. For each, solve it yourself first, then compare with the key.\n"
              "Return for each item: \"n\", \"ok\" (false if the item is wrong, ambiguous or has more "
              "than one correct answer), and the corrected key: \"answer\" (same format as given), "
              "plus \"correction\" for error items.\n"
              'Reply with JSON: {"checks": [{"n": 1, "ok": true, "answer": ...}]}\n\nITEMS:\n'
              + json.dumps(numbered, ensure_ascii=False, indent=1))
    system = ("You are a strict independent examiner checking test items. Reply with JSON only."
              + _rule(o))
    checks = _ask_json(client, system, prompt, "checks", progress, max_tokens=4096, think=True)
    if not checks:
        progress.warn("could not double-check some items")
        return items
    by_n = {_as_int(c.get("n")): c for c in checks if isinstance(c, dict)}
    kept = []
    for i, item in enumerate(items):
        c = by_n.get(i + 1)
        if not c:
            kept.append(item)
            continue
        if c.get("ok") is False:
            continue  # broken item: leave it out
        if item["type"] in ("mcq", "error"):
            answer = _as_int(c.get("answer"))
            limit = len(item.get("options") or item.get("segments") or [])
            if answer is not None and 0 <= answer < limit and answer != item["answer"]:
                item["answer"], item["checked"] = answer, "corrected"
            if item["type"] == "error" and _text(c.get("correction")):
                item["correction"] = _text(c["correction"])
        elif _text(c.get("answer")) and _text(c.get("answer")).lower() != item["answer"].lower():
            item["alternatives"] = list(dict.fromkeys(item.get("alternatives", []) + [item["answer"]]))
            item["answer"], item["checked"] = _text(c["answer"]), "corrected"
        item.setdefault("checked", "verified")
        kept.append(item)
    return kept


def _extra(o: dict) -> str:
    return f"\nExtra instructions: {o['instructions']}\n" if o.get("instructions") else ""


MAKERS = {"notes": make_notes, "flashcards": make_flashcards, "vocab": make_vocab,
          "quiz": make_quiz, "grammar": make_grammar}


def generate(client, kind: str, sources: list[Source], options: dict,
             progress: Progress | None = None) -> dict:
    """Make one study set. options: topic, level, language, count, style, length, words,
    translate_to, difficulty, test, instructions."""
    if kind not in MAKERS:
        raise ValueError(f"Unknown study tool: {kind}")
    progress = progress or Progress()
    o = {"topic": "", **options, "language": i18n.lang(options.get("language")),
         "source_languages": source_languages(sources)}
    big = sum(len(s.text) for s in sources) > 9000
    note_steps = sum(len(_chunks(s.text, 9000)) for s in sources) if big else 0
    steps = _Steps(progress, note_steps + 4)
    material = "" if kind == "grammar" else _material(client, sources, o["topic"], o["language"],
                                                      progress, steps)
    result = MAKERS[kind](client, material, o, steps, progress)
    progress.step(steps.done, steps.done, "Done")
    if kind != "notes" and not (result.get("cards") or result.get("words") or result.get("items")):
        raise RuntimeError("The AI did not return anything usable. Try again or another model.")
    return {"id": uuid.uuid4().hex[:10], "kind": kind,
            "created": datetime.now().isoformat(timespec="seconds"),
            "model": getattr(client, "model", ""), "language": o["language"],
            "options": {k: v for k, v in options.items()
                        if k not in ("text", "bank", "analysis", "source_languages")},
            "sources": [s.citation() for s in sources], **result}


def ask(client, study_set: dict, question: str, progress: Progress | None = None) -> str:
    """Answer a question about a notes set, using only the notes."""
    progress = progress or Progress()
    notes = study_set.get("markdown") or as_markdown(study_set)
    return client.chat(
        _SYSTEM + i18n.write_rule(study_set.get("language", "en")),
        f"Answer the student's question using these notes. If the notes don't cover it, say so "
        f"briefly and then answer from general knowledge. Be clear and concise; use Markdown.\n\n"
        f"NOTES:\n{notes[:NOTES_LIMIT]}\n\nQUESTION: {question}",
        max_tokens=2048, should_stop=progress.cancelled)


# --- Output ---------------------------------------------------------------------------

def as_markdown(s: dict) -> str:
    kind = s["kind"]
    if kind == "notes":
        return s["markdown"]
    out = [f"# {s['title']}", ""]
    if kind == "flashcards":
        for i, c in enumerate(s["cards"], 1):
            out += [f"**{i}. {c['front']}**  ", c["back"], ""]
    elif kind == "vocab":
        lang = s.get("translate_to")
        out += ["| Word | Type | Meaning | Example" + (" | Translation" if lang else "") + " |",
                "|---|---|---|---" + ("|---" if lang else "") + "|"]
        for w in s["words"]:
            cells = [w["word"], w["part_of_speech"], w["meaning"], w["example"]] + ([w["translation"]] if lang else [])
            out.append("| " + " | ".join(c.replace("|", "/") for c in cells) + " |")
        out.append("")
    else:
        for i, it in enumerate(s["items"], 1):
            if it["type"] == "mcq":
                out += [f"**{i}.** {it['question']}", "",
                        "  \n".join(f"{chr(65 + j)}. {o}" for j, o in enumerate(it["options"])), ""]
            elif it["type"] == "error":
                out += [f"**{i}.** " + " ".join(f"{seg} **({chr(65 + j)})**" for j, seg in enumerate(it["segments"])), ""]
            else:
                out += [f"**{i}.** {it['sentence']}", ""]
        out += ["---", "", "## Answers", ""]
        for i, it in enumerate(s["items"], 1):
            if it["type"] == "mcq":
                key = f"{chr(65 + it['answer'])}. {it['options'][it['answer']]}"
            elif it["type"] == "error":
                key = f"{chr(65 + it['answer'])} → {it['correction']}"
            else:
                key = it["answer"]
            out.append(f"{i}. **{key}**" + (f" — {it['explanation']}" if it.get("explanation") else ""))
        out.append("")
    return "\n".join(out)


def as_csv(s: dict) -> str:
    """Flashcards/vocabulary as CSV (front,back), ready to import into Anki or Quizlet."""
    buf = io.StringIO()
    writer = csv.writer(buf)
    if s["kind"] == "flashcards":
        writer.writerows([c["front"], c["back"]] for c in s["cards"])
    elif s["kind"] == "vocab":
        for w in s["words"]:
            back = f"({w['part_of_speech']}) {w['meaning']}" + (f" — {w['translation']}" if w.get("translation") else "")
            writer.writerow([w["word"], back + (f"\ne.g. {w['example']}" if w.get("example") else "")])
    else:
        raise ValueError("CSV export is for flashcards and vocabulary")
    return buf.getvalue()
