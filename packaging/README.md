# Building SGPT.exe

`SGPT.exe` is the whole app in one file (Python, the app, OCR models and libraries), made
with [PyInstaller](https://pyinstaller.org).

| File | What it is |
| --- | --- |
| `sgpt_exe.py` | What the .exe runs: keeps files in `Documents\SGPT`, picks a free port (8765 and up), opens the browser, and keeps the window open if something goes wrong. |
| `sgpt.spec` | PyInstaller settings: which packages and data files to include. |
| `sgpt.ico` | The icon. |

## Automatic builds (GitHub Actions)

`.github/workflows/build-exe.yml` runs the tests, builds the .exe on Windows and checks
that it starts.

- **Every push:** the .exe is attached to the run as the **SGPT-windows** artifact
  (Actions tab → the run → Artifacts).
- **Pushes to `main`:** the **SGPT for Windows (latest)** release is also updated, with a
  direct download link.

## Building it yourself (Windows)

PyInstaller can only build a Windows .exe on Windows.

```bat
python -m venv .venv
.venv\Scripts\activate
pip install -r requirements.txt pyinstaller
pyinstaller packaging\sgpt.spec --noconfirm
```

The result is `dist\SGPT.exe` (about 200 MB). The same command on macOS or Linux builds
an app for that system instead.

If you add a new package to `requirements.txt` and the .exe says
`No module named …`, add the package to the `collect_all` list in `sgpt.spec`.
