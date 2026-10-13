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
