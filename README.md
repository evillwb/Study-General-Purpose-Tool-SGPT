# Study General Purpose Tool (SGPT)

An all-in-one study app that runs on your own computer. It makes practice exams with
model answers and marking schemes, study notes, flashcards, vocabulary lists, timed
quizzes and grammar tests. It also sorts your past-year questions by chapter, reads scans
with OCR, and converts files between Word, PDF and more.

It works offline with [Ollama](https://ollama.com) (default model `qwen3:4b`), or with
**OpenAI, Anthropic Claude, Google Gemini, Groq, OpenRouter, DeepSeek** or any
OpenAI-compatible server. Exams and notes can be in **English, Chinese (中文) or Malay
(Bahasa Melayu)**.

## What's inside

| Page | What it does |
| --- | --- |
| **Exam** | A new practice paper from your past papers, notes, links or a topic (searched online), with a **model answer paper** and a **step-by-step marking scheme**. Choose question types, marks and difficulty (presets, a custom easy/medium/hard mix, "like my past papers", and a fine-tune slider), or copy your past papers' layout. **Analyse past papers** first to see their topics, layout and difficulty. The AI **double-checks every answer** and rewrites questions that fail the check. Edit, regenerate or delete any question; print or export to Word, PDF or Markdown. |
| **Study** | **Notes** in 8 styles, including an *exam study guide* (print edition, with past-paper patterns and a revision checklist), *chapter notes with tables*, Cornell, outline, mind map and glossary, plus "ask about these notes". **Flashcards** to flip and memorise (CSV export for Anki/Quizlet). **Vocabulary** with meanings, examples and translations. **MCQ quizzes** with or without a time limit, with scoring and review. **Grammar tests**: English tenses, English word form, and Malay error identification (*kesalahan bahasa*). |
| **Question bank** | Every question from your past-year papers, sorted by chapter, with type and a 1–10 difficulty rating. Shows the **10 hardest questions per chapter**, with answers on request; export to Word or PDF. |
| **OCR** | Turns scanned PDFs and photos into text, offline. Export to Word, PDF, text or Markdown, make a **searchable PDF**, or use the text as a source. |
| **Convert** | Word ↔ PDF, images ↔ PDF, Markdown, text and HTML to PDF or Word, PDF to images, merging PDFs. Old Office files, PowerPoint and Excel are converted when LibreOffice is installed. |

## Quick start

### Windows: SGPT.exe (no Python needed)

1. Install [Ollama](https://ollama.com/download) and run `ollama pull qwen3:4b`
   (or skip this and use a cloud AI with an API key).
2. Download **SGPT.exe** from the
   [Releases page](https://github.com/evillwb/Study-General-Purpose-Tool-SGPT/releases)
   ("SGPT for Windows (latest)") and double-click it.

The app opens in your browser. Keep the black window open while you use it; close it to
quit. Your files are kept in `Documents\SGPT`. The first start takes a few seconds.

If Windows shows "Windows protected your PC", click **More info → Run anyway**. This
appears because the .exe is not code-signed.

### From the source code (Windows, macOS, Linux)

1. Install [Python 3.10+](https://www.python.org/downloads/) and
   [Ollama](https://ollama.com/download), then get the model:
   ```bash
   ollama pull qwen3:4b
   ```
2. Get this project (`git clone`, or **Code → Download ZIP** on GitHub).
3. Start the app:
   - **Windows:** double-click `start-sgpt.bat`
   - **macOS / Linux:** double-click `start-sgpt.command` (or run it in a terminal)

   The first run installs everything into a `.venv` folder. After that, the app opens at
   <http://127.0.0.1:8765>.

To use a cloud AI instead, click the status pill at the top right, choose a provider and
paste your API key.

## Command line

```bash
python -m sgpt --topic "Photosynthesis" --level GCSE --plan "mcq:10,short:4,essay:1:12"
python -m sgpt library --structure match --difficulty past --challenge 1
python -m sgpt --topic "Persamaan kuadratik" --language ms -p anthropic
python -m sgpt.ocr scan.pdf -o scan.txt
python -m sgpt.convert report.docx --to pdf
python -m sgpt.convert *.jpg --to merged-pdf
```

Add `--help` to any of them for every option.

## Documentation

| Guide | What it covers |
| --- | --- |
| [docs/SETUP.md](docs/SETUP.md) | Installing, AI providers and API keys, OCR, search, troubleshooting |
| [docs/HOW_IT_WORKS.md](docs/HOW_IT_WORKS.md) | How each feature works, and which file to change for what |
| [docs/EDITING_IN_VSCODE.md](docs/EDITING_IN_VSCODE.md) | Editing, running, debugging and pushing changes from VS Code |

## Good to know

- AI makes mistakes, especially small local models. The double-check catches many of
  them, but **check answers before you rely on them**. Bigger models give better results,
  for example `qwen3:8b` on Ollama or any cloud model.
- With a cloud provider or internet search, your source text and topic are sent to that
  service. With Ollama and no internet search, everything stays on your computer.
- Diagrams in your sources are not understood. Only the text is used.
