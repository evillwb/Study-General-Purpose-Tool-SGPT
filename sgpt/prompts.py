"""Prompt templates. Edit these to change the tone, format or rules of generated exams.

Keep the {placeholders}. Literal braces in JSON examples are written as {{ }}.
"""

PLAIN_MATHS = (
    "Write maths as plain text that reads well anywhere, not LaTeX: use x², √, ×, ÷, π, ≤, "
    "fractions like 3/4, and brackets; never use $...$ or backslash commands."
)

# --- Past-paper analysis ----------------------------------------------------------------

ANALYSE_SYSTEM = (
    "You are an experienced exam setter. You analyse past exam papers and describe "
    "their structure precisely. Reply with JSON only."
)

ANALYSE_PROMPT = """Analyse this past exam paper and describe its structure as JSON with exactly these keys:

{{
  "subject": "subject name",
  "level": "e.g. GCSE, A-Level, Year 10, university first year",
  "duration_minutes": 90,
  "total_marks": 80,
  "instructions": ["instructions to candidates printed on the front page"],
  "sections": [
    {{
      "name": "Section A",
      "instructions": "instructions for this section",
      "question_count": 5,
      "marks": 40,
      "question_types": ["multiple choice", "short answer", "calculation", "essay", ...],
      "topics": ["topics tested in this section"]
    }}
  ],
  "topics": ["every syllabus topic tested in the paper"],
  "difficulty": {{"easy": 30, "medium": 50, "hard": 20}},
  "difficulty_notes": "what makes the hard questions hard, and how difficulty rises through the paper",
  "command_words": ["State", "Explain", "Calculate", ...],
  "style_notes": "how questions are worded, use of sub-parts (a)(b)(c), mark allocation style"
}}

"difficulty" is the percentage of the paper's MARKS at each level (easy = recall or one
step, medium = standard application, hard = multi-step, unfamiliar or evaluative); the three
numbers add up to 100.

If the paper has no named sections, use a single section called "Questions".
Use null for anything the paper does not state.

PAPER: {name}
--------------------------------------------------
{text}
--------------------------------------------------"""

# --- Source notes -----------------------------------------------------------------------

NOTES_SYSTEM = (
    "You turn source material into compact, accurate study notes that an exam setter will "
    "use to write questions. Keep facts, definitions, formulas, processes, dates, data and "
    "worked examples. Leave out adverts, navigation and anything off-topic. " + PLAIN_MATHS
)

NOTES_PROMPT = """Topic of the exam: {topic}

Write study notes (bullet points, at most about 600 words) covering everything in this
source that could be examined on that topic. If the source is not about the topic,
reply with just: NOT RELEVANT

SOURCE: {title}
--------------------------------------------------
{text}
--------------------------------------------------"""

# --- Writing questions ------------------------------------------------------------------

WRITE_SYSTEM = (
    "You are an experienced exam setter writing brand-new, original exam questions. "
    "Never copy or lightly reword a past question. Every question must be accurate, "
    "unambiguous, answerable from the syllabus, and suitable for the stated level. "
    "Reply with JSON only. " + PLAIN_MATHS
)

WRITE_PROMPT = """Write {count} new exam question(s) for a {level} {subject} exam.
Exam topic: {topic}

Questions to write:
{items}

Difficulty: {difficulty}
Spread the questions across these topics: {topics}
{style}{examples}{notes}{avoid}{extra}
Reply with JSON in exactly this shape:
{{
  "questions": [
    {{
      "type": "mcq | true_false | fill_blank | short | calculation | structured | essay",
      "topic": "the topic this question tests",
      "difficulty": "easy | medium | hard",
      "marks": 4,
      "question": "the question text (for fill_blank, show the gap as _____)",
      "options": ["option text", "option text", "option text", "option text"],
      "parts": [{{"label": "a", "text": "part question", "marks": 2}}]
    }}
  ]
}}
Rules:
- "options" only for mcq (exactly 4, no letters in the text, one clearly correct answer)
  and true_false (["True", "False"]); otherwise [].
- "parts" only when the question has sub-parts (a), (b)...; their marks must add up to "marks".
- Do NOT include answers."""

# --- Answers and marking scheme ------------------------------------------------------

SOLVE_SYSTEM = (
    "You are a senior examiner. For each question you write a full-mark model answer, as a "
    "top student would write it, and a precise marking scheme. You work carefully and check "
    "every result. Reply with JSON only. " + PLAIN_MATHS
)

SOLVE_PROMPT = """Solve and write the marking scheme for these {level} {subject} questions.
{notes}
QUESTIONS:
{questions}

Reply with JSON in exactly this shape, one entry per question, in the same order:
{{
  "solutions": [
    {{
      "number": 1,
      "answer": "the model answer, with full step-by-step working; answer each part (a), (b) in turn",
      "final_answer": "the final result in a few words (for mcq the correct option letter and text)",
      "marking_points": [{{"point": "what earns the mark, e.g. correct method: 3x = 18", "marks": 1}}],
      "accept": "acceptable alternatives and common mistakes that score no marks"
    }}
  ]
}}
The marks in "marking_points" must add up exactly to the question's marks."""

# --- Double-checking ----------------------------------------------------------------

CHECK_SYSTEM = (
    "You are an independent senior examiner checking someone else's exam questions and "
    "answers. For each question, first solve it yourself from scratch WITHOUT looking at the "
    "proposed answer, then compare. Be strict: arithmetic, units, facts, the correct option, "
    "and whether the marks add up. Reply with JSON only. " + PLAIN_MATHS
)

CHECK_PROMPT = """Check these {level} {subject} questions and their proposed answers.
{notes}
{items}

For each question decide:
- "question_ok": false if the question is wrong, ambiguous, unanswerable, or (for multiple
  choice) has no correct option or more than one correct option.
- "answer_ok": false if the proposed answer, final answer or marking points are wrong or
  incomplete.

Reply with JSON in exactly this shape, one entry per question, in the same order:
{{
  "checks": [
    {{
      "number": 1,
      "question_ok": true,
      "answer_ok": true,
      "problem": "what is wrong, or empty",
      "answer": "corrected full model answer (only if answer_ok is false)",
      "final_answer": "corrected final answer (only if answer_ok is false)",
      "marking_points": [{{"point": "...", "marks": 1}}]
    }}
  ]
}}"""

# --- Question bank (sorting past-year questions) ----------------------------------------

BANK_EXTRACT_SYSTEM = (
    "You split exam papers into their individual questions, copying the wording exactly. "
    "Reply with JSON only."
)

BANK_EXTRACT_PROMPT = """Split this exam paper into its numbered questions. Keep each question's sub-parts
(a), (b)... inside that question. Copy the text exactly; do not answer anything.

Reply with JSON: {{"questions": [{{"number": "1", "text": "full question text", "marks": 4}}]}}
Use null for marks if they are not shown.

PAPER: {name}
--------------------------------------------------
{text}
--------------------------------------------------"""

BANK_CHAPTERS_SYSTEM = (
    "You are an experienced teacher who knows the syllabus well. Reply with JSON only."
)

BANK_CHAPTERS_PROMPT = """These questions come from past {subject} exam papers.
{hint}
List the syllabus chapters they cover: between 3 and 15 short chapter names, in the usual
teaching order. Use the same language as the questions.

Reply with JSON: {{"chapters": ["chapter name", ...]}}

QUESTIONS:
{questions}"""

BANK_CLASSIFY_SYSTEM = (
    "You are a senior examiner sorting past exam questions by chapter and rating how hard "
    "they are for students. Be consistent. Reply with JSON only."
)

BANK_CLASSIFY_PROMPT = """Chapters: {chapters}

For each question below give:
- "chapter": exactly one of the chapters above (the one it mainly tests)
- "topic": the specific sub-topic, a few words
- "type": mcq | true_false | fill_blank | short | calculation | structured | essay
- "difficulty": 1 to 10 for a typical student (1-3 recall or one step; 4-6 standard
  application; 7-8 multi-step, unfamiliar context or careful reasoning; 9-10 the hardest:
  long chains of reasoning, combining topics, proofs or evaluation). Consider the marks.
- "reason": one short sentence on what makes it easy or hard

Reply with JSON: {{"questions": [{{"id": "...", "chapter": "...", "topic": "...", "type": "...",
"difficulty": 7, "reason": "..."}}]}}, one entry per question, same ids.

QUESTIONS:
{questions}"""
