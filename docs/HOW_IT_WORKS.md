# How it works

The program runs in three stages. A small model like `qwen3:4b` does better on several
short, focused tasks than on one long prompt, so each stage is a separate call to the model.

## Stage 0: read the PDFs (`exam_gen/pdf_extract.py`)

- Extracts the text of every page with PyMuPDF (or pypdf if PyMuPDF is not installed).
- Removes page numbers and running headers and footers (lines repeated on most pages).
- Splits the text into questions. It recognises `1.`, `1)`, `Question 1` and `Q1`, and only
  accepts numbers in order, so a numbered list inside a question is not counted as a new
  question.
- Reads mark allocations such as `[3]`, `[3 marks]` and `(3 marks)`.

## Stage 1: analyse each paper (`analyse_paper` in `exam_gen/generator.py`)

Each paper is sent to the model with `ANALYSE_PROMPT`. The model replies in JSON (Ollama
`format: "json"`) with the subject, level, duration, sections, question types, topics and
style. If the JSON is unusable, the program retries once and then falls back to the
structure detected in Stage 0.

`merge_blueprints` then combines the papers. It keeps the most common section layout
(preferring the most recent paper) and collects topics from **all** papers.

## Stage 2: write the new paper

Each section is written separately with `WRITE_SECTION_PROMPT`. The prompt includes the
section's requirements, a shuffled topic list and three randomly chosen past questions as
style examples. The model is told not to copy those examples.

## Stage 3: write the marking scheme

Each generated section goes back to the model with `MARK_SECTION_PROMPT`. For every
question it gives the answer, numbered working steps, a mark allocation (M1/A1/B1 style)
and accept / do-not-accept notes.

## Output

`render_markdown` builds the final file: a title, time and marks, instructions, the
sections, then `# Marking Scheme`.

## Ollama settings (`exam_gen/ollama_client.py`)

- Uses `POST /api/chat` with streaming, so the dots show progress.
- `think: false` turns off qwen3's hidden reasoning, which makes it much faster. Any
  `<think>` text that still appears is removed.
- `num_ctx` defaults to 16384 tokens. Ollama's built-in default is much smaller and would
  cut off long papers.
- Only the Python standard library is used for the HTTP calls.

## Where to change things

| I want to… | Edit |
| --- | --- |
| Change question wording, format or rules | `exam_gen/prompts.py`, `WRITE_SYSTEM` / `WRITE_SECTION_PROMPT` |
| Change the marking-scheme layout | `exam_gen/prompts.py`, `MARK_SECTION_PROMPT` |
| Change the default model or settings | `exam_gen/cli.py`, `build_parser()` |
| Support another question-numbering style | `exam_gen/pdf_extract.py`, the regexes at the top |
| Change the output file layout | `exam_gen/generator.py`, `render_markdown()` |
