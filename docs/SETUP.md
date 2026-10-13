# Setup guide

## Requirements

| | Minimum |
| --- | --- |
| Python | 3.10 or newer |
| Ollama | 0.9 or newer (older versions work but may print qwen3's `<think>` reasoning slowly) |
| RAM | 8 GB (`qwen3:4b` uses about 3–4 GB) |
| Disk | about 3 GB for the model |

A GPU makes generation much faster but is not required. On a CPU a full paper can take
5–20 minutes.

## 1. Install Ollama and the model

1. Download and install Ollama from <https://ollama.com/download>.
2. Open a terminal and run:
   ```bash
   ollama pull qwen3:4b
   ollama run qwen3:4b "Say hello"     # quick test, then press Ctrl+D to exit
   ```
3. Ollama runs in the background (the menu-bar or tray app, or `ollama serve`). The program
   connects to it at `http://localhost:11434`.

## 2. Get the code

```bash
git clone https://github.com/evillwb/Easy-Note-AI---Project.git
cd Easy-Note-AI---Project
```

## 3. Install the Python dependency

**Windows (PowerShell)**
```powershell
python -m venv .venv
.venv\Scripts\Activate.ps1
pip install -r requirements.txt
```
If PowerShell blocks the activate script, run
`Set-ExecutionPolicy -Scope CurrentUser RemoteSigned` once.

**macOS / Linux**
```bash
python3 -m venv .venv
source .venv/bin/activate
pip install -r requirements.txt
```

## 4. Add past papers and run

1. Copy your past-paper PDFs into the `past_papers/` folder. Papers from the same subject
   and level give the best results.
2. Run:
   ```bash
   python -m exam_gen
   ```
3. Open the new file in `output/`. Any Markdown viewer works, including VS Code
   (`Ctrl+Shift+V` for preview), Obsidian or Typora.

To turn it into a PDF or Word document you can use [Pandoc](https://pandoc.org):
`pandoc output/practice_exam_....md -o exam.docx`

## Troubleshooting

| Message | Fix |
| --- | --- |
| `Cannot reach Ollama at http://localhost:11434` | Start the Ollama app, or run `ollama serve` in another terminal. |
| `Model 'qwen3:4b' is not installed` | `ollama pull qwen3:4b` |
| `little or no text found (scanned image PDF?)` | The PDF is a scan. OCR it first: `ocrmypdf in.pdf out.pdf` |
| `0 questions detected` | The numbering style was not recognised. Generation still works, but run with `--dump-extracted` to see the text, then adjust the patterns in `exam_gen/pdf_extract.py`. |
| Out of memory / very slow | Lower `--num-ctx 8192` and `--max-chars 8000`. |
| Questions are repetitive or off-topic | Add `--subject`, `--level` and `--instructions "..."`, or try a lower `--temperature`. |
| Ollama on another machine | `--host http://192.168.1.20:11434`, or set the `OLLAMA_HOST` environment variable. |
