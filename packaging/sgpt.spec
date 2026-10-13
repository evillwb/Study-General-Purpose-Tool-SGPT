# PyInstaller spec for SGPT.exe. Build from the project folder:
#   pyinstaller packaging/sgpt.spec --noconfirm
# The result is dist/SGPT.exe (one file, nothing else to install).
import os
import sys

from PyInstaller.utils.hooks import collect_all, collect_submodules

ROOT = os.path.dirname(SPECPATH)  # the project folder, so "sgpt" can be found
sys.path.insert(0, ROOT)

datas = [(os.path.join(ROOT, "sgpt", "web"), "sgpt/web")]
binaries = []
hiddenimports = collect_submodules("sgpt") + collect_submodules("markdown")
for package in ("rapidocr", "onnxruntime", "docx", "pdf2docx", "fitz", "pymupdf", "anthropic"):
    d, b, h = collect_all(package)
    datas += d
    binaries += b
    hiddenimports += h

a = Analysis(
    [os.path.join(SPECPATH, "sgpt_exe.py")],
    pathex=[ROOT],
    datas=datas,
    binaries=binaries,
    hiddenimports=hiddenimports,
    excludes=["tkinter", "matplotlib", "IPython", "pytest"],
)
pyz = PYZ(a.pure)
exe = EXE(
    pyz,
    a.scripts,
    a.binaries,
    a.datas,
    name="SGPT",
    icon=os.path.join(SPECPATH, "sgpt.ico"),
    console=True,
    upx=False,
)
