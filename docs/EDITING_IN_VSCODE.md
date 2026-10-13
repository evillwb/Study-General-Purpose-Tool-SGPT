# Editing the program in VS Code

You don't need Claude Code to work on this project. It is plain Python, and VS Code is
all you need to edit, run, debug and push changes.

## 1. One-time setup

1. Install [VS Code](https://code.visualstudio.com/), [Python 3.10+](https://www.python.org/downloads/)
   and [Git](https://git-scm.com/downloads).
2. In VS Code open the Command Palette (`Ctrl+Shift+P`, or `Cmd+Shift+P` on Mac), run
   **Git: Clone**, and paste:
   `https://github.com/evillwb/Easy-Note-AI---Project.git`
3. When the folder opens, accept the prompt to install the **recommended extensions**
   (Python and Python Debugger).
4. Open the terminal (`` Ctrl+` ``) and create the virtual environment:
   ```bash
   python -m venv .venv
   # Windows:  .venv\Scripts\activate
   # Mac/Linux: source .venv/bin/activate
   pip install -r requirements-dev.txt
   ```
5. `Ctrl+Shift+P` → **Python: Select Interpreter** → choose the one in `.venv`.

## 2. Run the program

- **From the Run and Debug panel** (`Ctrl+Shift+D`): pick **Generate practice exam** and
  press ▶ (or `F5`). These configurations are in `.vscode/launch.json`, where you can change
  the arguments, for example `["past_papers", "--subject", "Biology"]`.
- **From the terminal**: `python -m exam_gen --help`

Make sure Ollama is running first (see [SETUP.md](SETUP.md)).

## 3. Debug

Click left of a line number to set a red breakpoint, for example inside `generate_exam` in
`exam_gen/generator.py`, then press `F5`. You can step through the code and inspect
variables such as `bp` (the merged blueprint) or the model's replies.

## 4. Run the tests

Open the **Testing** panel (flask icon) and click ▶, or run `python -m pytest` in the
terminal. The tests use a fake Ollama server, so they run in about a second and need
neither Ollama nor the model.

## 5. Save your changes to GitHub

1. Open **Source Control** (`Ctrl+Shift+G`).
2. Review the changed files, type a message such as "Make questions harder", and click
   **Commit**.
3. Click **Sync Changes** (or **Push**). The first time, VS Code asks you to sign in to
   GitHub.

The terminal equivalent is:
```bash
git add -A
git commit -m "Describe your change"
git push
```

## Where to start editing

See the "Where to change things" table in [HOW_IT_WORKS.md](HOW_IT_WORKS.md). The easiest
and most effective change is the prompt text in `exam_gen/prompts.py`. Leave the
`{placeholders}` in place, and use double braces `{{ }}` for literal braces.
