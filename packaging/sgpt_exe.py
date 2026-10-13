"""Entry point of the Windows .exe (built with PyInstaller, see packaging/README.md).

Keeps your files in Documents\\SGPT, picks a free port, opens the browser, and keeps the
window open on errors so you can read them.
"""

from __future__ import annotations

import socket
import sys
import threading
import traceback
import webbrowser
from pathlib import Path


def data_folder() -> Path:
    docs = Path.home() / "Documents"
    folder = (docs if docs.is_dir() else Path.home()) / "SGPT"
    folder.mkdir(parents=True, exist_ok=True)
    return folder


def free_port(start: int = 8765, tries: int = 20) -> int:
    for port in range(start, start + tries):
        with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as s:
            try:
                s.bind(("127.0.0.1", port))
                return port
            except OSError:
                continue
    raise SystemExit(f"No free port between {start} and {start + tries - 1}.")


def run() -> None:
    from sgpt.app import create_app

    folder = data_folder()
    app = create_app(folder / "library", folder / "output")
    port = free_port()
    url = f"http://127.0.0.1:{port}"
    print("SGPT (Study General Purpose Tool)")
    print(f"  Running at  {url}")
    print(f"  Your files  {folder}")
    print("  Keep this window open while you use SGPT. Close it to quit.\n")
    if "--no-browser" not in sys.argv:
        threading.Timer(1.5, webbrowser.open, [url]).start()
    app.run(host="127.0.0.1", port=port, threaded=True)


if __name__ == "__main__":
    try:
        run()
    except KeyboardInterrupt:
        pass
    except BaseException:  # noqa: BLE001 - show the error instead of closing the window
        traceback.print_exc()
        try:
            input("\nSGPT stopped because of the error above. Press Enter to close.")
        except EOFError:
            pass
        sys.exit(1)
