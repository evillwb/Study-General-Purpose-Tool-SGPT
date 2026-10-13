"""Maths formulas and diagrams for exams, drawn with matplotlib.

Formulas: the AI writes LaTeX between $...$ (e.g. $\\frac{3x+1}{2}$). They are drawn as
images, the same on screen (SVG), in PDF and in Word (PNG). matplotlib's mathtext covers
fractions, roots, powers, indices, integrals, sums, Greek letters and common symbols.

Diagrams: a question may carry a small description of a diagram ("diagram" in the JSON),
drawn here: a function graph, bar or line chart, a shape (triangle, polygon) with labelled
sides and angles, a circle, or a number line.
"""

from __future__ import annotations

import hashlib
import io
import math
import re
from functools import lru_cache
from pathlib import Path

MATH = re.compile(r"\$(?!\s)([^$\n]{1,300}?)(?<!\s)\$")
DIAGRAM_TYPES = ("graph", "bar", "line", "shape", "circle", "numberline")
DPI = 144  # PNGs at 2x print size: exports place them at width / 2 points

# JSON escapes that eat LaTeX backslashes when a model forgets to double them:
# "\frac" -> form feed + "rac", "\times" -> tab + "imes", "\beta" -> backspace + "eta" …
_EATEN = {"\x0c": "\\f", "\t": "\\t", "\x08": "\\b", "\r": "\\r", "\n": "\\n", "\x0b": "\\v", "\x07": "\\a"}


# Which LaTeX commands each eaten escape can start (so "$5\nthen $3" stays as it is).
_COMMANDS = {"\x0c": "rac|orall", "\t": "imes|heta|an|ext|riangle|frac|o\\b", "\x08": "eta|ar|egin|oxed|ig",
             "\r": "ho|ight|m|angle", "\n": "eq|abla|u\\b|ot|e\\b|ewline|eg", "\x0b": "ec|arepsilon|arphi",
             "\x07": "lpha|pprox|ngle"}


def repair_math(text: str) -> str:
    """Put back backslashes that JSON decoding turned into control characters inside $...$,
    where they start a LaTeX command ("\x0crac" -> "\\frac")."""
    if "$" not in text or not any(c in text for c in _EATEN):
        return text
    def fix(m):
        inner = m.group(1)
        for char, starts in _COMMANDS.items():
            inner = re.sub(re.escape(char) + f"(?=(?:{starts}))", lambda _: _EATEN[char], inner)
        return f"${inner}$"
    return re.sub(r"\$([^$]{1,300}?)\$", fix, text)


def _plt():
    import matplotlib
    matplotlib.use("Agg")
    import matplotlib.pyplot as plt
    return plt


@lru_cache(maxsize=512)
def math_image(tex: str, fmt: str = "png", size: float = 11) -> bytes | None:
    """A formula as an image (png or svg), or None if mathtext can't draw it."""
    from matplotlib.font_manager import FontProperties
    from matplotlib.mathtext import math_to_image

    _plt()
    buf = io.BytesIO()
    try:
        math_to_image(f"${tex}$", buf, prop=FontProperties(size=size, math_fontfamily="cm"),
                      dpi=DPI if fmt == "png" else 72, format=fmt)
    except Exception:  # noqa: BLE001 - unsupported LaTeX: shown as text instead
        return None
    return buf.getvalue()


def plain(tex: str) -> str:
    """Readable text for a formula that can't be drawn (or for .txt/.md exports)."""
    t = re.sub(r"\\frac\{([^{}]*)\}\{([^{}]*)\}", r"(\1)/(\2)", tex)
    t = re.sub(r"\\sqrt\{([^{}]*)\}", r"√(\1)", t)
    for a, b in (("\\times", "×"), ("\\div", "÷"), ("\\leq", "≤"), ("\\le", "≤"), ("\\geq", "≥"),
                 ("\\ge", "≥"), ("\\neq", "≠"), ("\\pm", "±"), ("\\pi", "π"), ("\\theta", "θ"),
                 ("\\alpha", "α"), ("\\beta", "β"), ("\\infty", "∞"), ("\\degree", "°"), ("^\\circ", "°"),
                 ("\\cdot", "·"), ("\\left", ""), ("\\right", ""), ("\\,", " ")):
        t = t.replace(a, b)
    t = re.sub(r"\^\{([^{}]*)\}", r"^(\1)", t)
    return re.sub(r"[{}]|\\(?=[a-zA-Z])", "", t)


def math_name(tex: str) -> str:
    return "m" + hashlib.sha1(tex.encode()).hexdigest()[:12] + ".png"


def markdown_with_math_images(text: str, images_dir: Path) -> str:
    """Replace $...$ with pictures of the formulas (saved in images_dir), for PDF and Word."""
    def swap(m):
        tex = m.group(1)
        png = math_image(tex)
        if not png:
            return plain(tex)
        name = math_name(tex)
        if not (images_dir / name).exists():
            (images_dir / name).write_bytes(png)
        return f"![{tex}]({name})"
    return MATH.sub(swap, text)


def markdown_plain_math(text: str) -> str:
    """$...$ as readable plain text (for .md/.txt exports and places without images)."""
    return MATH.sub(lambda m: plain(m.group(1)), text)


# --- Diagrams ---------------------------------------------------------------------------

def clean_diagram(data) -> dict | None:
    """A diagram description from the AI, checked, or None if unusable."""
    if not isinstance(data, dict) or data.get("type") not in DIAGRAM_TYPES:
        return None
    try:
        png = diagram_image(data, "png")
    except Exception:  # noqa: BLE001 - a malformed description: no diagram
        return None
    return data if png else None


def _safe_function(expr: str):
    """y = f(x) from text like "x**2 - 3*x + 2" or "sin(x)", without eval of arbitrary code."""
    import numpy as np

    expr = expr.replace("^", "**").replace("y=", "").replace("y =", "").strip()
    if not re.fullmatch(r"[0-9x+\-*/(). ,a-z]*", expr) or "__" in expr:
        raise ValueError("unsupported function")
    names = {"x", "sin", "cos", "tan", "sqrt", "exp", "log", "abs", "pi", "e"}
    if set(re.findall(r"[a-z]+", expr)) - names:
        raise ValueError("unsupported function")
    env = {"sin": np.sin, "cos": np.cos, "tan": np.tan, "sqrt": np.sqrt, "exp": np.exp,
           "log": np.log, "abs": np.abs, "pi": np.pi, "e": np.e, "__builtins__": {}}
    code = compile(expr, "<diagram>", "eval")
    return lambda x: eval(code, env, {"x": x})  # noqa: S307 - checked above: x, numbers, math names


def diagram_image(spec: dict, fmt: str = "png") -> bytes:
    """Draw a diagram description as png or svg."""
    import numpy as np

    plt = _plt()
    kind = spec["type"]
    fig, ax = plt.subplots(figsize=(4.6, 3.2) if kind not in ("shape", "circle") else (3.8, 3.4))
    try:
        if kind == "graph":
            lo, hi = (spec.get("x_range") or [-5, 5])[:2]
            xs = np.linspace(float(lo), float(hi), 400)
            for f in (spec.get("functions") or [])[:4]:
                expr = f.get("expr") if isinstance(f, dict) else str(f)
                with np.errstate(all="ignore"):
                    ys = np.asarray(_safe_function(expr)(xs), dtype=float) * np.ones_like(xs)
                ys[np.abs(ys) > 1e6] = np.nan
                label = (f.get("label") if isinstance(f, dict) else "") or f"y = {expr}"
                ax.plot(xs, ys, linewidth=1.6, label=label)
            for p in (spec.get("points") or [])[:12]:
                ax.plot(float(p["x"]), float(p["y"]), "o", color="black", markersize=4)
                if p.get("label"):
                    ax.annotate(str(p["label"]), (float(p["x"]), float(p["y"])), textcoords="offset points",
                                xytext=(5, 5), fontsize=9)
            if spec.get("y_range"):
                ax.set_ylim(*map(float, spec["y_range"][:2]))
            ax.axhline(0, color="black", linewidth=0.8)
            ax.axvline(0, color="black", linewidth=0.8)
            ax.grid(True, linewidth=0.3)
            if len(spec.get("functions") or []) > 1:
                ax.legend(fontsize=8)
        elif kind in ("bar", "line"):
            labels = [str(x) for x in spec.get("labels") or []][:20]
            series = spec.get("series") or [{"name": "", "values": spec.get("values") or []}]
            for i, s in enumerate(series[:4]):
                values = [float(v) for v in s.get("values") or []][:len(labels)]
                if kind == "bar":
                    width = 0.8 / max(len(series), 1)
                    ax.bar([j + i * width for j in range(len(values))], values, width, label=s.get("name") or None)
                    ax.set_xticks([j + width * (len(series) - 1) / 2 for j in range(len(labels))], labels,
                                  rotation=30 if len(labels) > 6 else 0, fontsize=8)
                else:
                    ax.plot(labels[:len(values)], values, marker="o", label=s.get("name") or None)
            if len(series) > 1:
                ax.legend(fontsize=8)
            ax.grid(True, axis="y", linewidth=0.3)
        elif kind == "shape":
            points = {str(k): (float(v[0]), float(v[1])) for k, v in (spec.get("points") or {}).items()}
            order = [str(p) for p in spec.get("order") or points]
            xy = [points[p] for p in order if p in points]
            if len(xy) < 2:
                raise ValueError("a shape needs points")
            ax.fill(*zip(*xy), facecolor="none", edgecolor="black", linewidth=1.6)
            cx, cy = sum(x for x, _ in xy) / len(xy), sum(y for _, y in xy) / len(xy)
            for name, (x, y) in points.items():
                dx, dy = x - cx, y - cy
                d = math.hypot(dx, dy) or 1
                ax.annotate(name, (x, y), xytext=(x + dx / d * 0.35, y + dy / d * 0.35), ha="center",
                            va="center", fontsize=11, fontweight="bold")
            for side in (spec.get("sides") or [])[:12]:
                a, b, text = str(side[0]), str(side[1]), str(side[2])
                if a in points and b in points:
                    (x1, y1), (x2, y2) = points[a], points[b]
                    mx, my = (x1 + x2) / 2, (y1 + y2) / 2
                    nx, ny = mx - cx, my - cy
                    d = math.hypot(nx, ny) or 1
                    ha = "center" if abs(nx) < abs(ny) else ("right" if nx < 0 else "left")
                    va = "center" if abs(nx) >= abs(ny) else ("top" if ny < 0 else "bottom")
                    ax.text(mx + nx / d * 0.15, my + ny / d * 0.15, text, ha=ha, va=va, fontsize=9)
            for name, text in (spec.get("angles") or {}).items():
                if str(name) in points:
                    x, y = points[str(name)]
                    ax.text(x + (cx - x) * 0.18, y + (cy - y) * 0.18, str(text), ha="center", va="center",
                            fontsize=8, color="#333")
            ax.set_aspect("equal")
            ax.axis("off")
            ax.margins(0.18)
        elif kind == "circle":
            r = float(spec.get("radius") or 1)
            ax.add_patch(plt.Circle((0, 0), r, fill=False, linewidth=1.6))
            ax.plot(0, 0, "o", color="black", markersize=3)
            ax.text(0.05 * r, -0.12 * r, spec.get("centre_label") or "O", fontsize=10)
            if spec.get("show_radius", True):
                ax.plot([0, r], [0, 0], color="black", linewidth=1)
                ax.text(r / 2, 0.06 * r, str(spec.get("radius_label") or f"{r:g}"), ha="center", fontsize=9)
            ax.set_xlim(-1.3 * r, 1.3 * r)
            ax.set_ylim(-1.3 * r, 1.3 * r)
            ax.set_aspect("equal")
            ax.axis("off")
        elif kind == "numberline":
            lo, hi = (float(v) for v in (spec.get("range") or [-5, 5])[:2])
            ax.axhline(0, color="black", linewidth=1.2)
            for t in np.arange(math.ceil(lo), math.floor(hi) + 1):
                ax.plot([t, t], [-0.08, 0.08], color="black", linewidth=1)
                ax.text(t, -0.25, f"{t:g}", ha="center", fontsize=9)
            for p in (spec.get("points") or [])[:8]:
                ax.plot(float(p["x"]), 0, "o", markersize=7, color="black",
                        markerfacecolor="white" if p.get("open") else "black")
                if p.get("label"):
                    ax.text(float(p["x"]), 0.2, str(p["label"]), ha="center", fontsize=9)
            ax.set_xlim(lo - 0.5, hi + 0.5)
            ax.set_ylim(-0.6, 0.6)
            ax.axis("off")
            fig.set_size_inches(4.6, 1.2)
        if spec.get("title"):
            ax.set_title(str(spec["title"])[:80], fontsize=10)
        for axis, key in (("x", "x_label"), ("y", "y_label")):
            if spec.get(key):
                getattr(ax, f"set_{axis}label")(str(spec[key])[:40], fontsize=9)
        buf = io.BytesIO()
        fig.savefig(buf, format=fmt, dpi=DPI, bbox_inches="tight")
        return buf.getvalue()
    finally:
        plt.close(fig)


DIAGRAM_PROMPT = """
- "diagram" (optional, null if not needed): a diagram the question needs, described as JSON.
  Only use these shapes:
  {"type": "graph", "functions": ["x**2 - 4"], "x_range": [-4, 4], "points": [{"x": 2, "y": 0, "label": "A"}]}
  {"type": "bar" or "line", "labels": ["Mon", "Tue"], "series": [{"name": "Rainfall (mm)", "values": [3, 5]}],
   "x_label": "...", "y_label": "..."}
  {"type": "shape", "points": {"A": [0, 0], "B": [4, 0], "C": [0, 3]}, "sides": [["A", "B", "4 cm"]],
   "angles": {"A": "90°"}}
  {"type": "circle", "radius": 5, "radius_label": "5 cm"}
  {"type": "numberline", "range": [-3, 5], "points": [{"x": 2, "open": true}]}
  The diagram must match the question exactly; refer to it in the question ("The diagram shows…")."""
