# How it works

```
 sources ─┬─ past papers (PDF) ──► analyse layout ──┐   (only in "Match my past papers")
          └─ notes, text, links, web ─► study notes ─┤
                                                    ├─► write questions ─► answers + marking scheme ─► exam (.json / .md)
 question plan / difficulty / language ─────────────┘
```

A small model like `qwen3:4b` does much better on many short, focused tasks than on one
long one. So each step is a separate AI call, and questions are written in batches of 5.

## 1. Sources (`easy_exam/sources.py`)

- `load_file()` reads PDFs, text files and photos. PDFs go through
  `pdf_extract.extract_paper()`, which strips page numbers and headers and finds numbered
  questions and marks, in English, Malay and Chinese.
- Pages with no selectable text are OCR'd by `easy_exam/ocr.py` (RapidOCR, offline).
  Results are cached in `.easy-exam-cache/`.
- `fetch_url()` downloads a web page or PDF link and keeps the readable text.
- `web_search()` uses DuckDuckGo and Wikipedia (or Brave or Tavily with a key), in the
  chosen language.
- `gather_sources()` puts it all together. It searches the internet only when there is
  nothing else, unless told otherwise.

## 2. Generation (`easy_exam/generator.py`)

1. **Analyse past papers** (`analyse_paper`, used in *match* mode). The AI describes each
   paper's sections, question types, marks, topics and style as JSON. `merge_blueprints`
   combines them.
2. **Study notes** (`summarise_source`). Every other source, and past papers in *custom*
   mode, is condensed into notes about the topic.
3. **Write questions** (`write_questions`). Each section is written in batches. The AI
   replies in JSON (type, topic, difficulty, marks, question, options, parts), which is
   checked and cleaned by `normalise_question`.
4. **Answers and marking scheme** (`solve_questions`). For each batch of 4 questions the AI
   writes a model answer, a short final answer, marking points that add up to the marks,
   and accept/reject notes.
5. The exam is a JSON dict. `render_markdown()` turns it into the paper, the model answers
   and the marking scheme, with headings in the chosen language from `easy_exam/i18n.py`.

`regenerate_question()` rewrites one question of the same type and marks.

## 3. AI providers (`easy_exam/providers.py`, `easy_exam/ollama_client.py`)

Every provider has the same small interface: `chat()`, `list_models()`, `check_model()`.

- **Ollama** uses `/api/chat` with streaming, `think: false` (faster qwen3) and a 16k context.
- **OpenAI-compatible** APIs (OpenAI, Gemini, Groq, OpenRouter, DeepSeek, custom) use
  `/chat/completions` with streaming. If a model rejects an option such as `temperature`,
  the request is retried without it.
- **Anthropic Claude** uses the official SDK with streaming. It sends no `temperature`,
  because current models don't accept one; effort is set to "high".

## 4. The app (`easy_exam/app.py`, `easy_exam/web/`)

A small Flask server that listens only on `127.0.0.1`. Long jobs run in a background
thread, and the page checks their progress every second. Exams are saved in `output/` as
`<id>.json` plus a `.md` copy. The page is plain HTML, CSS and JavaScript with no build
step: `index.html`, `app.css`, `app.js`.

## Where to change things

| I want to… | Edit |
| --- | --- |
| Change how questions or answers are written | `easy_exam/prompts.py` |
| Add a question type or change default marks | `QUESTION_TYPES` and `DEFAULT_PLAN` in `generator.py`, plus labels in `i18n.py` |
| Add a language | `easy_exam/i18n.py` (one entry in each dict) |
| Add an AI provider | `PROVIDERS` in `easy_exam/providers.py` |
| Change the printed paper's layout | `render_markdown()` in `generator.py` and `.sheet` styles in `web/app.css` |
| Recognise another question-numbering style | the regexes at the top of `pdf_extract.py` |
| Change the look of the app | `easy_exam/web/app.css` (colours are variables at the top) |
