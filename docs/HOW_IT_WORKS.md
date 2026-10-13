# How it works

SGPT is a small Python package (`sgpt/`) with a local web app on top. A small model like
`qwen3:4b` does much better on many short, focused tasks than on one long one, so every
feature is split into small AI calls (batches of 4–10 items), and their JSON replies are
checked and cleaned in code.

```
 sources ─┬─ past papers (PDF/scan) ─► analyse layout & difficulty ─┐
          ├─ notes, text, links ─────► study notes ─────────────────┤
          └─ topic only ─────────────► internet search ─────────────┤
                                                                    ├─► write ─► answer ─► double-check ─► save (.json + .md)
 plan · difficulty mix · language ──────────────────────────────────┘
```

## Modules

| File | What it does |
| --- | --- |
| `sources.py` | Loads files (PDF, text, photos), web pages and internet search (DuckDuckGo + Wikipedia, or Brave/Tavily), and keeps the file library (`library/`). |
| `pdf_extract.py` | PDF text, header/footer removal and question detection (`1.`, `Question 1`, `Soalan 1`, `第1题`, `2．`, marks such as `[3]`, `(3 markah)`, `（3分）`). Scanned pages go to `ocr.py`. |
| `ocr.py` | Offline OCR with RapidOCR (Tesseract as a fallback), with a page cache in `.sgpt-cache/`. Also `python -m sgpt.ocr`. |
| `generator.py` | Exams: past-paper analysis, difficulty planning, writing, answering, **double-checking**, and Markdown output. |
| `bank.py` | Question bank: extracts every past-paper question, finds the chapters, rates difficulty 1–10, and picks the hardest per chapter. |
| `study.py` | Notes (8 styles, including the chapter-by-chapter study guide), flashcards, vocabulary, MCQ quizzes and grammar tests. |
| `convert.py` | File conversion and Word/PDF/HTML export, keeping the original look: Microsoft Office (Windows) or LibreOffice when installed, pdf2docx for PDF → Word, mammoth for Word → PDF without either. Also `python -m sgpt.convert`. |
| `figures.py` | Maths formulas ($...$ LaTeX) and question diagrams (graphs, charts, shapes, number lines) drawn with matplotlib, for the app, PDF and Word. |
| `quizapps.py` | Kahoot! spreadsheet and Quizlet import exports. |
| `media.py` | Video and audio downloads with yt-dlp and ffmpeg (imageio-ffmpeg): cobalt-style settings → yt-dlp format strings, file names, GIF conversion, subtitles as text. |
| `layout.py` | Rebuilds scanned pages with OCR text at the same place and size and diagrams cut out as pictures, so scans → Word keep their layout. |
| `snapshots.py` | Cuts a picture of each past-paper question out of its page for the question bank (diagrams and symbols exactly as printed). |
| `providers.py`, `ollama_client.py` | AI providers: Ollama, OpenAI-compatible APIs and Anthropic Claude (official SDK), behind one `chat()` interface. |
| `i18n.py` | English, Chinese and Malay labels for papers, and the language rule added to every prompt. |
| `prompts.py` | Every prompt used for exams, checks and the question bank. The study tools' prompts are in `study.py`. |
| `app.py`, `web/` | The Flask server (listens on 127.0.0.1 only) and the single-page app (`index.html`, `app.css`, `app.js`, no build step). |
| `cli.py` | `python -m sgpt`, the exam generator on the command line. |

## Exams, step by step

1. **Analyse past papers** (optional, cached in `library/.analysis.json`). The AI describes
   each paper's sections, marks, topics, command words and difficulty mix, and the results
   are merged.
2. **Study notes.** Long sources are condensed into notes about the topic.
3. **Plan.** Either the past papers' layout or your question types and counts. Every
   question gets a target level (easy, medium or hard) from the difficulty mix, easiest
   first, plus the fine-tune instruction.
4. **Write** each section in batches of 5 (JSON), cleaned by `normalise_question`.
5. **Answer**: a model answer, a final answer and marking points that add up to the marks.
6. **Double-check**: a second call with reasoning turned on (Ollama `think: true`) re-solves
   each question without looking at the answer. Wrong answers are corrected, and questions
   it rejects are rewritten and checked again. Each question is marked ✓ checked,
   ✎ corrected or ⚠ flagged.

## Question bank

The questions come from the detected numbering (or from the AI when a paper's numbering
isn't recognised). One call works out the syllabus chapters, then batches of 8 questions
are classified by chapter, topic, type and difficulty (1–10, with a reason). "Hardest per
chapter" sorts by difficulty, then by marks. The bank is cached in
`library/.question_bank.json` and is also used by the study guide.

## Study tools

Every tool shares the source picker (files, pasted text, links, internet search). The
**study guide** is written chapter by chapter: chapters come from the question bank (or
the analysis, or the AI), and the past-paper patterns table and revision checklist are
**counted from your question bank**, not guessed. Quiz and grammar items are
double-checked the same way as exam answers: wrong keys are fixed and broken items are
dropped. Sets are saved in `output/study/`.

## Where to change things

| I want to… | Edit |
| --- | --- |
| Change how questions, answers or checks are written | `sgpt/prompts.py` |
| Change a note style or add a new one | `NOTE_STYLES` and `NOTE_STYLE_LABELS` in `sgpt/study.py` |
| Change the study guide's layout | `make_guide()` in `sgpt/study.py` |
| Add a grammar test type | `GRAMMAR_TESTS` and `_GRAMMAR_PROMPTS` in `sgpt/study.py` |
| Add a question type or change default marks | `QUESTION_TYPES` and `DEFAULT_PLAN` in `generator.py`, plus labels in `i18n.py` |
| Add a language | `sgpt/i18n.py` (one entry in each dict) |
| Add an AI provider | `PROVIDERS` in `sgpt/providers.py` |
| Change how exported PDFs look | `PAGE_CSS` and `html_to_pdf()` in `sgpt/convert.py` |
| Recognise another question-numbering style | the regexes at the top of `sgpt/pdf_extract.py` |
| Change the look of the app | `sgpt/web/app.css` (colours are variables at the top) |
