"""Prompt templates. Edit these to change the tone, format or rules of generated papers."""

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
  "style_notes": "how questions are worded, use of sub-parts (a)(b)(c), mark allocation style, command words"
}}

If the paper has no named sections, use a single section called "Questions".
Use null for anything the paper does not state.

PAPER: {name}
--------------------------------------------------
{text}
--------------------------------------------------"""

WRITE_SYSTEM = (
    "You are an experienced exam setter writing a brand-new practice paper. "
    "Your questions are original: never copy or lightly reword a past question. "
    "Questions must be accurate, unambiguous and answerable, with marks shown in square "
    "brackets like [3]. Write in Markdown. Do not include answers."
)

WRITE_SECTION_PROMPT = """Write {section_name} of a new {level} {subject} practice exam.

Section requirements:
- Instructions: {instructions}
- Number of questions: {question_count} (number them starting at {first_number})
- Total marks for this section: {marks}
- Question types: {question_types}
- Topics to cover (spread across questions): {topics}

House style taken from past papers: {style_notes}

Example past questions, for STYLE AND DIFFICULTY ONLY (do not reuse them):
{examples}

{extra}
Output format:
- Start with "## {section_name}" and an italic line with the section instructions.
- Each question as "**Question N**" followed by the question text.
- Use sub-parts (a), (b), (c) where the past papers do, each with its own mark in [brackets].
- For multiple choice give options A-D on separate lines.
- End each question with its total marks, e.g. "*(Total: 6 marks)*".
Output only the section in Markdown."""

MARK_SYSTEM = (
    "You are a senior examiner writing a detailed marking scheme for teachers and students. "
    "You solve every question carefully and check your arithmetic. Write in Markdown."
)

MARK_SECTION_PROMPT = """Write the marking scheme for this section of a {level} {subject} exam.

For EVERY question and sub-part give:
1. **Answer**: the final correct answer.
2. **Step-by-step working**: numbered steps showing how to reach the answer.
3. **Mark allocation**: which step or point earns each mark (e.g. "M1 for correct method",
   "A1 for correct answer", "B1 for each valid point"), adding up exactly to the marks shown.
4. **Accept / Do not accept**: acceptable alternatives and common mistakes that score no marks.

Use headings "### Question N" to match the paper.

SECTION:
--------------------------------------------------
{section}
--------------------------------------------------"""
