# Editing Study General Purpose Tool (SGPT) in VS Code

You don't need Claude Code to work on this project. It is plain Python plus one HTML page,
and VS Code is all you need to edit, run, debug and push changes.

## 1. One-time setup

1. Install [VS Code](https://code.visualstudio.com/),
   [Python 3.10+](https://www.python.org/downloads/) and [Git](https://git-scm.com/downloads).
2. In VS Code press `Ctrl+Shift+P` (`Cmd+Shift+P` on Mac), run **Git: Clone** and paste
   `https://github.com/evillwb/Easy-Note-AI---Project.git`.
3. When the folder opens, accept the prompt to install the **recommended extensions**
   (Python and Python Debugger).
4. Open the terminal (`` Ctrl+` ``) and set up the environment:
   ```bash
   python -m venv .venv
   # Windows:   .venv\Scripts\activate
   # Mac/Linux: source .venv/bin/activate
   pip install -r requirements-dev.txt
   ```
5. `Ctrl+Shift+P` → **Python: Select Interpreter** → choose the one in `.venv`.

## 2. Run it

Open **Run and Debug** (`Ctrl+Shift+D`), pick a configuration and press ▶ (or `F5`):

- **SGPT app**: starts the web app and opens it in your browser.
- **SGPT command line (…)**: example command-line runs. Change their `args` in
  `.vscode/launch.json`.

Or use the terminal: `python -m sgpt.app`, or `python -m sgpt --help`.

After you edit the Python code, stop the app (■) and start it again. After you edit only
`sgpt/web/*` files, refreshing the browser is enough.

## 3. Debug

Click left of a line number to set a breakpoint, for example in `write_questions` in
`sgpt/generator.py`, then press `F5`. When a request reaches that line, VS Code pauses
and you can inspect variables such as `prompt` or `reply`.

For the page itself, open your browser's developer tools (`F12`) and use the **Console**
and **Network** tabs.

## 4. Run the tests

Open the **Testing** panel (flask icon) and click ▶, or run `python -m pytest`. The tests
use a fake AI server, so they take seconds and need no Ollama, API key or internet.

## 5. Save your changes to GitHub

1. Open **Source Control** (`Ctrl+Shift+G`).
2. Check the changed files, type a message such as "Make essay questions longer", and
   click **Commit**.
3. Click **Sync Changes** (or **Push**). The first time, VS Code asks you to sign in to
   GitHub.

The terminal equivalent is:
```bash
git add -A
git commit -m "Describe your change"
git push
```

## Where to start

See the "Where to change things" table in [HOW_IT_WORKS.md](HOW_IT_WORKS.md). The quickest
win is the wording of the prompts in `sgpt/prompts.py`. Keep the `{placeholders}`, and
write literal braces as `{{ }}`.
