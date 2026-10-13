# Setup guide

## Requirements

| | |
| --- | --- |
| Python | 3.10 or newer |
| For local AI | [Ollama](https://ollama.com/download) and about 8 GB of RAM for `qwen3:4b` |
| For cloud AI | An API key from the provider instead (no Ollama needed) |
| Disk | About 1 GB for the app's Python packages, plus about 3 GB for the Ollama model |

## 1. Install

### Windows: SGPT.exe
Download **SGPT.exe** from the repository's Releases page and double-click it. Nothing
else to install (except Ollama, if you use local AI). Files are kept in `Documents\SGPT`.
To build the .exe yourself, see [packaging/README.md](../packaging/README.md).

### The easy way (from source)
Double-click **`start-sgpt.bat`** (Windows) or **`start-sgpt.command`**
(macOS/Linux). The first run creates a `.venv` folder and installs everything listed in
`requirements.txt`, then opens the app.

On macOS, if it says the file can't be opened, right-click it, choose **Open**, then **Open**
again. You only have to do this once.

### By hand
```bash
python -m venv .venv
# Windows:      .venv\Scripts\activate
# macOS/Linux:  source .venv/bin/activate
pip install -r requirements.txt
python -m sgpt.app          # the app
python -m sgpt --help       # the command line
```

App options: `--port 8765`, `--library library` (where uploaded files are kept),
`--output output` (where exams are saved), `--host http://localhost:11434` (Ollama URL),
`--no-browser`.

## 2. Choose your AI

Open the app and click the status pill at the top right (or the ⚙ button).

| Provider | What you need | Default model |
| --- | --- | --- |
| Ollama (local, private) | `ollama pull qwen3:4b` and the Ollama app running | `qwen3:4b` |
| OpenAI | API key from platform.openai.com | `gpt-5-mini` |
| Anthropic Claude | API key from platform.claude.com | `claude-opus-5-5` |
| Google Gemini | API key from aistudio.google.com | `gemini-2.5-flash` |
| Groq | API key from console.groq.com | `llama-3.3-70b-versatile` |
| OpenRouter | API key from openrouter.ai | `openai/gpt-5-mini` |
| DeepSeek | API key from platform.deepseek.com | `deepseek-chat` |
| Custom | Any OpenAI-compatible server: LM Studio, vLLM, Mistral, Together… | your choice |

You can type any model name the provider offers; the model box suggests the ones your key
can use. Keys are saved only on your computer in `~/.sgpt/config.json`. You can also
use environment variables (`OPENAI_API_KEY`, `ANTHROPIC_API_KEY`, `GEMINI_API_KEY`,
`GROQ_API_KEY`, `OPENROUTER_API_KEY`, `DEEPSEEK_API_KEY`), which is what the command line
uses with `-p openai` and similar.

With Claude, SGPT uses the official `anthropic` SDK. Requests use the "high" effort
setting and Anthropic's automatic fallback to another model if a request is declined.

## 3. Sources, OCR and internet search

- **Files:** drop PDFs, `.txt`, `.md` or photos (`.png`, `.jpg`) into the app. A PDF with 3
  or more numbered questions is marked as a *past paper*; anything else is *notes*. You can
  change this, or switch a file off, in the file list.
- **Scanned PDFs and photos** are read with OCR. It is built in (RapidOCR, installed by
  `requirements.txt`), works offline, and reads English, Malay and Chinese. The first scan
  takes a few seconds per page; the result is cached in a hidden `.sgpt-cache` folder
  next to the file. If you prefer Tesseract, uninstall `rapidocr` and install Tesseract,
  and it is used instead.
- **Internet search** runs when you have no other sources, or always/never if you choose so
  on the **Web** tab. The free default uses DuckDuckGo plus Wikipedia, in your exam's
  language. For more reliable results add a Brave Search or Tavily API key in the settings.

## 4. Languages

Choose the **exam language** (English, 中文, Bahasa Melayu) and the language your
**sources** are in. Sources in one language can produce an exam in another. Question
numbering such as `Soalan 1`, `第1题`, `2．`, `(5 markah)` and `（5分）` is recognised in
past papers.

## 5. Converting files (optional: LibreOffice)

PDF, Word (`.docx`), images, Markdown, text and HTML convert with nothing extra
installed. To convert old Word files (`.doc`, `.rtf`, `.odt`), PowerPoint and Excel, and
to get the most faithful Word → PDF layout, install the free
[LibreOffice](https://www.libreoffice.org/download/). SGPT finds it automatically.

## Troubleshooting

| Problem | Fix |
| --- | --- |
| "Ollama is not running" | Open the Ollama app, or run `ollama serve`. |
| "… is not installed. Run: ollama pull …" | Run that command, or choose another model. |
| "rejected the API key" | Paste the key again in the settings, and check you have credit with that provider. |
| "rate limit or quota reached" | Wait a minute, or check your plan with the provider. |
| A scanned PDF says "Install OCR" | `pip install rapidocr onnxruntime` (inside `.venv`). |
| Web search finds nothing | Your network may block DuckDuckGo: add a Brave or Tavily key, or add your own sources. |
| Questions are wrong or repetitive | Use a bigger model, add better sources, lower *Creativity*, or add instructions under *More options*. |
| Very slow on Ollama | Normal on a CPU (10–30 minutes). Choose fewer questions, a smaller *Context size*, or a GPU or cloud model. |
| Port already in use | `python -m sgpt.app --port 8800` |
| "Converting .doc files needs LibreOffice" | Install LibreOffice (see section 5), or save the file as `.docx` first. |
| "The system cannot find the path specified" from `start-sgpt.bat` | Extract the ZIP first (right-click → Extract All) and run the launcher from the extracted folder. If it still happens, delete the `.venv` folder and run it again, or use SGPT.exe. |
| "Windows protected your PC" for SGPT.exe | Click **More info → Run anyway**. The .exe is not code-signed. |
| Internet search is blocked | SGPT carries on with the AI's own knowledge and shows a warning. Add your own sources for better results. |
