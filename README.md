# Study General Purpose Tool (SGPT)

Make a **practice exam paper** with a **model answer paper** and a **step-by-step marking
scheme** in a few minutes. Give it your past papers, notes, links or pasted text, or just
type a topic and let it search the internet.

- **Runs on your computer** with [Ollama](https://ollama.com) (default model `qwen3:4b`), so
  nothing leaves your machine. You can also use **OpenAI, Anthropic Claude, Google Gemini,
  Groq, OpenRouter, DeepSeek** or any OpenAI-compatible server.
- **Any sources:** PDF past papers and notes, `.txt` and `.md` files, photos of pages, web
  links and pasted text. Scanned PDFs and photos are read with built-in **OCR** (offline).
- **Internet search** when you have no sources: DuckDuckGo and Wikipedia work with no
  account; Brave and Tavily are optional.
- **Your choice of questions:** multiple choice, true/false, fill in the blank, short
  answer, calculation, structured and essay, with counts, marks and difficulty. Or copy the
  layout of your past papers.
- **English, Chinese (中文) and Malay (Bahasa Melayu)** for both the exam and the sources.
  It can also translate, for example English notes into a Malay paper.
- **Review and edit:** reveal answers, edit any question, regenerate or delete one, then
  print, save as PDF or export as Markdown.

## Quick start

1. Install [Python 3.10+](https://www.python.org/downloads/) and
   [Ollama](https://ollama.com/download), then get the model:
   ```bash
   ollama pull qwen3:4b
   ```
2. Get this project (`git clone` or **Code → Download ZIP** on GitHub).
3. Start the app:
   - **Windows:** double-click `start-sgpt.bat`
   - **macOS / Linux:** double-click `start-sgpt.command` (or run it in a terminal)

   The first run installs everything into a `.venv` folder. After that, the app opens in
   your browser at <http://127.0.0.1:8765>.

To use a cloud AI instead of Ollama, click the status pill at the top right of the app,
choose a provider and paste your API key.

## Command line

The same generator also runs from the terminal:

```bash
python -m sgpt --topic "Photosynthesis" --level GCSE --plan "mcq:10,short:4,essay:1:12"
python -m sgpt library --structure match              # copy the layout of the PDFs in library/
python -m sgpt --url https://en.wikipedia.org/wiki/Cell_cycle --topic "Cell cycle"
python -m sgpt --topic "Persamaan kuadratik" --language ms
python -m sgpt --topic "Gravity" -p anthropic          # uses ANTHROPIC_API_KEY
python -m sgpt --help
```

Each run saves `output/<date>_<title>.md` (paper, model answers and marking scheme) and a
`.json` copy that the app can open.

## Documentation

| Guide | What it covers |
| --- | --- |
| [docs/SETUP.md](docs/SETUP.md) | Installing, AI providers and API keys, OCR, search, troubleshooting |
| [docs/HOW_IT_WORKS.md](docs/HOW_IT_WORKS.md) | The pipeline, and which file to change for what |
| [docs/EDITING_IN_VSCODE.md](docs/EDITING_IN_VSCODE.md) | Editing, running, debugging and pushing changes from VS Code |

## Good to know

- AI makes mistakes, especially small local models. **Check the answers before you rely
  on them.** A bigger model gives better questions and answers, for example
  `qwen3:8b` on Ollama or any cloud model.
- With a cloud provider, or with internet search, your source text and topic are sent to
  that service. With Ollama and no internet search, everything stays on your computer.
- Diagrams and graphs in your sources are not understood. Only the text is used.
