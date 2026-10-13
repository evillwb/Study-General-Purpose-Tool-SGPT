"""Source material for questions: files, pasted text, web pages and internet search."""

from __future__ import annotations

import html
import json
import re
import urllib.error
import urllib.parse
import urllib.request
from dataclasses import dataclass, field
from html.parser import HTMLParser
from pathlib import Path

from .i18n import LANGUAGES
from .pdf_extract import ExamPaper, extract_paper, needs_ocr_but_unavailable, split_questions

USER_AGENT = "Mozilla/5.0 (compatible; SGPT/1.0; +https://github.com/evillwb/Easy-Note-AI---Project)"
TEXT_SUFFIXES = {".txt", ".md", ".markdown"}
IMAGE_SUFFIXES = {".png", ".jpg", ".jpeg", ".webp"}
SUPPORTED_SUFFIXES = {".pdf"} | TEXT_SUFFIXES | IMAGE_SUFFIXES
_SKIP_DOMAINS = ("youtube.com", "youtu.be", "facebook.com", "instagram.com", "tiktok.com",
                 "twitter.com", "x.com", "pinterest.", "reddit.com/r/")


class SourceError(RuntimeError):
    pass


@dataclass
class Source:
    """A piece of material the questions are based on."""
    kind: str  # "paper" (past exam paper), "notes", "text", "web"
    title: str
    text: str
    url: str = ""
    paper: ExamPaper | None = field(default=None, repr=False)
    ocr: bool = False

    def citation(self) -> dict:
        return {"kind": self.kind, "title": self.title, "url": self.url}


# --- Files -------------------------------------------------------------------------

def load_file(path: Path, role: str | None = None) -> Source:
    """Load a PDF or text file. PDFs with numbered questions count as past papers."""
    suffix = path.suffix.lower()
    if suffix in TEXT_SUFFIXES:
        return Source("notes", path.name, path.read_text(encoding="utf-8", errors="replace"))
    if suffix in IMAGE_SUFFIXES:
        from . import ocr

        if not ocr.available():
            raise SourceError(f"{path.name}: install OCR to read images: pip install rapidocr onnxruntime")
        text = ocr.ocr_image(path.read_bytes())
        paper = ExamPaper(path, path.stem, text, 1, split_questions(text), ocr_pages=1)
    elif suffix == ".pdf":
        paper = extract_paper(path)
        if len(paper.text) < 200 and needs_ocr_but_unavailable(path):
            raise SourceError(f"{path.name} is a scanned PDF. Install OCR to read it: "
                              "pip install rapidocr onnxruntime")
    else:
        raise SourceError(f"{path.name}: unsupported file type")
    if role is None:
        role = "paper" if len(paper.questions) >= 3 else "notes"
    return Source(role, path.name, paper.text, paper=paper, ocr=paper.ocr_pages > 0)


# --- Web pages ---------------------------------------------------------------------

class _TextExtractor(HTMLParser):
    _SKIP = {"script", "style", "noscript", "nav", "footer", "header", "aside", "form",
             "svg", "button", "iframe"}
    _BLOCK = {"p", "div", "li", "br", "h1", "h2", "h3", "h4", "h5", "h6", "tr", "section",
              "article", "table", "pre", "blockquote", "dd", "dt"}

    def __init__(self):
        super().__init__(convert_charrefs=True)
        self.parts: list[str] = []
        self.title = ""
        self._skip_depth = 0
        self._in_title = False

    def handle_starttag(self, tag, attrs):
        if tag in self._SKIP:
            self._skip_depth += 1
        elif tag == "title":
            self._in_title = True
        elif tag in self._BLOCK:
            self.parts.append("\n")

    def handle_endtag(self, tag):
        if tag in self._SKIP and self._skip_depth:
            self._skip_depth -= 1
        elif tag == "title":
            self._in_title = False
        elif tag in self._BLOCK:
            self.parts.append("\n")

    def handle_data(self, data):
        if self._in_title:
            self.title += data
        elif not self._skip_depth:
            self.parts.append(data)


def html_to_text(page: str) -> tuple[str, str]:
    parser = _TextExtractor()
    parser.feed(page)
    text = re.sub(r"[ \t\r\f\v]+", " ", "".join(parser.parts))
    lines = [ln.strip() for ln in text.split("\n")]
    # Drop short menu-like fragments; keep real sentences and headings.
    lines = [ln for ln in lines if len(ln) > 40 or (ln and ln[-1] in ".:?!")]
    return parser.title.strip(), "\n".join(lines)


def _get(url: str, data: bytes | None = None, headers: dict | None = None,
         timeout: float = 20) -> tuple[bytes, str]:
    req = urllib.request.Request(url, data=data, headers={"User-Agent": USER_AGENT,
                                                          **(headers or {})})
    try:
        with urllib.request.urlopen(req, timeout=timeout) as resp:
            return resp.read(5_000_000), resp.headers.get("Content-Type", "")
    except urllib.error.HTTPError as exc:
        raise SourceError(f"{url}: HTTP {exc.code}") from exc
    except (urllib.error.URLError, TimeoutError, OSError) as exc:
        raise SourceError(f"{url}: {getattr(exc, 'reason', exc)}") from exc


def fetch_url(url: str) -> Source:
    url = url.strip()
    if not re.match(r"^https?://", url, re.IGNORECASE):
        url = "https://" + url
    body, ctype = _get(url)
    if "pdf" in ctype or url.lower().endswith(".pdf"):
        import pymupdf

        with pymupdf.open(stream=body, filetype="pdf") as doc:
            text = "\n".join(page.get_text("text", sort=True) for page in doc)
        title = urllib.parse.unquote(url.rstrip("/").rsplit("/", 1)[-1])
    else:
        title, text = html_to_text(body.decode("utf-8", errors="replace"))
    if len(text) < 200:
        raise SourceError(f"{url}: no readable text found")
    return Source("web", html.unescape(title) or url, text, url=url)


# --- Internet search ---------------------------------------------------------------

def _duckduckgo(query: str, limit: int, region: str = "") -> list[tuple[str, str]]:
    params = {"q": query, **({"kl": region} if region else {})}
    body, _ = _get("https://html.duckduckgo.com/html/", data=urllib.parse.urlencode(params).encode())
    results = []
    for href, title in re.findall(r'<a[^>]+class="result__a"[^>]+href="([^"]+)"[^>]*>(.*?)</a>',
                                  body.decode("utf-8", errors="replace"), re.DOTALL):
        href = html.unescape(href)
        if "uddg=" in href:
            href = urllib.parse.unquote(urllib.parse.parse_qs(urllib.parse.urlparse(href).query)
                                        .get("uddg", [""])[0])
        if href.startswith("//"):
            href = "https:" + href
        if href.startswith("http") and "duckduckgo.com" not in href:
            results.append((html.unescape(re.sub(r"<[^>]+>", "", title)).strip(), href))
        if len(results) >= limit:
            break
    return results


def _wikipedia(query: str, limit: int, wiki: str = "en") -> list[Source]:
    api = f"https://{wiki}.wikipedia.org/w/api.php?"
    body, _ = _get(api + urllib.parse.urlencode({
        "action": "query", "list": "search", "srsearch": query, "srlimit": limit,
        "format": "json"}))
    titles = [r["title"] for r in json.loads(body).get("query", {}).get("search", [])]
    sources = []
    for title in titles:
        body, _ = _get(api + urllib.parse.urlencode({
            "action": "query", "prop": "extracts", "explaintext": 1, "titles": title,
            "format": "json", "redirects": 1}))
        for page in json.loads(body).get("query", {}).get("pages", {}).values():
            text = page.get("extract", "")
            if len(text) > 500:
                url = f"https://{wiki}.wikipedia.org/wiki/" + urllib.parse.quote(title.replace(" ", "_"))
                sources.append(Source("web", f"{title} - Wikipedia", text, url=url))
    return sources


def _brave(query: str, limit: int, key: str) -> list[tuple[str, str]]:
    body, _ = _get("https://api.search.brave.com/res/v1/web/search?"
                   + urllib.parse.urlencode({"q": query, "count": limit}),
                   headers={"X-Subscription-Token": key, "Accept": "application/json"})
    return [(r.get("title", ""), r["url"]) for r in json.loads(body).get("web", {}).get("results", [])
            if r.get("url")]


def _tavily(query: str, limit: int, key: str) -> list[Source]:
    body, _ = _get("https://api.tavily.com/search",
                   data=json.dumps({"query": query, "max_results": limit,
                                    "include_raw_content": True}).encode(),
                   headers={"Content-Type": "application/json", "Authorization": f"Bearer {key}"})
    return [Source("web", r.get("title") or r["url"], r.get("raw_content") or r.get("content", ""),
                   url=r["url"])
            for r in json.loads(body).get("results", [])
            if len(r.get("raw_content") or r.get("content") or "") > 200]


def web_search(query: str, *, limit: int = 4, engine: str = "auto", api_key: str = "",
               language: str = "en", warn=print) -> list[Source]:
    """Search the internet and return the readable text of the best pages.

    engine: "auto" (DuckDuckGo + Wikipedia, no key needed), "brave" or "tavily" (API key).
    language: "en", "zh" or "ms" - which Wikipedia and search region to use.
    """
    lang = LANGUAGES.get(language, LANGUAGES["en"])
    if engine == "tavily":
        return _tavily(query, limit, api_key)[:limit]

    sources: list[Source] = []
    try:
        links = (_brave(query, limit * 2, api_key) if engine == "brave"
                 else _duckduckgo(query, limit * 2, lang["region"]))
    except SourceError as exc:
        warn(f"Web search failed ({exc}); using Wikipedia only")
        links = []
    seen = set()
    for title, url in links:
        if len(sources) >= limit - 1 or any(d in url for d in _SKIP_DOMAINS) or url in seen:
            continue
        seen.add(url)
        try:
            sources.append(fetch_url(url))
        except SourceError as exc:
            warn(f"Skipped {title or url}: {exc}")
    # Wikipedia is a dependable baseline and fills in when general search is blocked.
    try:
        for src in _wikipedia(query, 2, lang["wiki"]):
            if len(sources) < limit and src.url not in {s.url for s in sources}:
                sources.append(src)
    except SourceError as exc:
        warn(f"Wikipedia search failed: {exc}")
    if not sources:
        raise SourceError("No web results could be read. Check your internet connection, "
                          "or add your own sources.")
    return sources


# --- The file library (folder of uploaded sources) -----------------------------------

LIBRARY_META = ".library.json"


def library_meta(folder: Path) -> dict:
    try:
        return json.loads((folder / LIBRARY_META).read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return {}


def save_library_meta(folder: Path, meta: dict) -> None:
    (folder / LIBRARY_META).write_text(json.dumps(meta, indent=2), encoding="utf-8")


def library_files(folder: Path) -> list[Path]:
    if not folder.is_dir():
        return []
    return sorted((p for p in folder.iterdir()
                   if p.is_file() and p.suffix.lower() in SUPPORTED_SUFFIXES),
                  key=lambda p: p.name.lower())


def load_library(folder: Path, warn=print, only_selected: bool = True) -> list[Source]:
    """Load every file in the folder, using the role (past paper / notes) saved for it."""
    meta = library_meta(folder)
    sources = []
    for path in library_files(folder):
        entry = meta.get(path.name, {})
        if only_selected and entry.get("use") is False:
            continue
        try:
            source = load_file(path, entry.get("role"))
        except SourceError as exc:
            warn(str(exc))
            continue
        except Exception as exc:  # one broken file should not stop the rest
            warn(f"{path.name}: could not read ({exc})")
            continue
        if len(source.text) < 200:
            warn(f"{path.name}: little or no text found - skipped")
            continue
        sources.append(source)
    return sources


def gather_sources(*, folder: Path | None = None, text: str = "", urls: list[str] = (),
                   topic: str = "", web: str = "auto", engine: str = "auto",
                   engine_key: str = "", language: str = "en", step=None,
                   warn=print) -> list[Source]:
    """Collect every source for an exam.

    web: "on" always searches the internet for the topic, "off" never does, and "auto"
    searches only when no files, text or links were given.
    """
    step = step or (lambda message: None)
    sources = load_library(folder, warn) if folder else []
    if text.strip():
        sources.append(Source("text", "Pasted text", text.strip()))
    for url in [u.strip() for u in urls if u.strip()]:
        step(f"Downloading {url}")
        try:
            sources.append(fetch_url(url))
        except SourceError as exc:
            warn(f"Skipped link: {exc}")
    if web == "on" or (web == "auto" and not sources):
        if not topic.strip():
            if not sources:
                raise SourceError("Add some sources, or type a topic so it can be searched online.")
        else:
            step(f"Searching the internet for “{topic}”")
            sources += web_search(topic, engine=engine, api_key=engine_key, language=language,
                                  warn=warn)
    return sources
