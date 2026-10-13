# Easy Note AI: Practice Exam Generator

Turn a folder of **past-year exam PDFs** into a **new practice exam paper** with a
**step-by-step marking scheme**, saved as a Markdown file. Everything runs on your own
computer with [Ollama](https://ollama.com) and the `qwen3:4b` model. Your papers are never
uploaded anywhere.

```
past_papers/*.pdf ──► extract text & questions ──► qwen3:4b analyses structure
                                                         │
output/practice_exam_<date>.md ◄── marking scheme ◄── new questions, section by section
```

## Quick start

```bash
# 1. Install Ollama from https://ollama.com/download, then get the model
ollama pull qwen3:4b

# 2. Install the Python dependency (Python 3.10+)
python -m venv .venv
source .venv/bin/activate          # Windows: .venv\Scripts\activate
pip install -r requirements.txt

# 3. Put your past papers in past_papers/ and run
python -m exam_gen
```

The result is saved to `output/practice_exam_YYYYMMDD_HHMMSS.md`.

## Common options

```bash
python -m exam_gen path/to/pdfs -o my_exam.md          # choose input folder and output file
python -m exam_gen --subject "Chemistry" --level "GCSE"   # override detected subject/level
python -m exam_gen --instructions "focus on organic chemistry, harder questions"
python -m exam_gen --temperature 0.4 --seed 42           # more predictable / reproducible
python -m exam_gen --model qwen3:8b                      # use a different Ollama model
python -m exam_gen --dump-extracted                      # also save the extracted PDF text
python -m exam_gen --help                                # all options
```

## Documentation

| Guide | What it covers |
| --- | --- |
| [docs/SETUP.md](docs/SETUP.md) | Full installation on Windows / macOS / Linux, and troubleshooting |
| [docs/HOW_IT_WORKS.md](docs/HOW_IT_WORKS.md) | The pipeline, and where each step lives in the code |
| [docs/EDITING_IN_VSCODE.md](docs/EDITING_IN_VSCODE.md) | Editing, running, debugging and pushing changes from VS Code |

## Limitations

- PDFs must contain selectable text. Scanned image-only PDFs are skipped; run them through
  OCR first (e.g. `ocrmypdf input.pdf output.pdf`).
- `qwen3:4b` is a small model. It is good at copying exam style but can make mistakes in
  answers. **Check the marking scheme before you rely on it.** Use a bigger model such as
  `--model qwen3:8b` for better accuracy if your computer can run it.
- Diagrams, graphs and images in past papers are not read. Only the text is used.
