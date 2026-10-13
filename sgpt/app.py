"""Local web app: python -m sgpt.app

Runs a small web server on your own computer (http://127.0.0.1:8765) and opens it in your
browser. The server only listens on this computer. With Ollama nothing leaves your machine;
with a cloud provider or internet search, the text of your sources is sent to that service.
"""

from __future__ import annotations

import argparse
import json
import re
import shutil
import threading
import time
import uuid
import webbrowser
from pathlib import Path
from urllib.parse import quote

import markdown as md
from flask import Flask, Response, abort, jsonify, request, send_file, send_from_directory

from .generator import (DEFAULT_PLAN, DIFFICULTY_MIX, DIFFICULTY_TEXT, QUESTION_TYPES,
                        ExamRequest, Progress, analyse_papers, generate_exam,
                        regenerate_question, render_markdown, renumber)
from . import bank as qbank
from . import convert, ocr, study
from .i18n import LANGUAGES
from .ollama_client import Cancelled, LLMError
from .providers import (PROVIDERS, SEARCH_ENGINES, config_path, make_client, mask_key,
                        resolve_base_url, resolve_key, save_provider_config, save_search_settings,
                        search_settings)
from .sources import (SUPPORTED_SUFFIXES, SourceError, gather_sources, library_files,
                      library_meta, load_file, load_library, save_library_meta)

WEB_DIR = Path(__file__).parent / "web"
CACHE_VERSION = 2  # bump when analysis or question-bank results change shape, to redo them
LOCAL_JOBS = {"ocr", "convert"}  # don't use the AI, so they can run alongside an AI job
_SAFE_NAME = re.compile(r"[^A-Za-z0-9._ ()-]+")
_EXAM_ID = re.compile(r"^[a-f0-9]{6,32}$")


def _safe_filename(name: str) -> str:
    """Strip any directory parts and odd characters so files stay inside their folder."""
    name = _SAFE_NAME.sub("_", Path(name).name).strip(" .")
    if Path(name).suffix.lower() not in SUPPORTED_SUFFIXES:
        abort(400, "Use PDF, TXT, Markdown or image (PNG/JPG) files")
    return name


def render_html(text: str) -> str:
    # Escape raw HTML tags the model might emit; Markdown formatting is unaffected.
    text = re.sub(r"<(?=[A-Za-z/!])", "&lt;", text)
    return md.markdown(convert.keep_box_lines(text), extensions=["extra", "sane_lists"])


class Job(Progress):
    """Work running in a background thread; the browser polls its state."""

    def __init__(self, kind: str, exam_id: str = ""):
        self.id = uuid.uuid4().hex[:12]
        self.kind = kind  # "generate" | "regenerate"
        self.state = "running"  # running | done | error | cancelled
        self.done, self.total, self.message = 0, 1, "Starting…"
        self.log: list[str] = []
        self.error = ""
        self.exam_id = exam_id
        self.result = None  # OCR output
        self.started = time.time()
        self._cancel = threading.Event()

    def step(self, done: int, total: int, message: str) -> None:
        self.done, self.total, self.message = done, total, message
        self.log.append(message)

    def note(self, message: str) -> None:
        self.message = message
        self.log.append(message)

    def warn(self, message: str) -> None:
        self.log.append("⚠ " + message)

    def cancelled(self) -> bool:
        return self._cancel.is_set()

    def cancel(self) -> None:
        self._cancel.set()

    def eta(self) -> int | None:
        """Seconds left, judged from the time the finished steps took (None until known)."""
        elapsed = time.time() - self.started
        if self.state != "running" or self.done <= 0 or self.total <= self.done or elapsed < 3:
            return None
        return round(elapsed / self.done * (self.total - self.done))

    def as_dict(self, full: bool = True) -> dict:
        data = {"id": self.id, "kind": self.kind, "state": self.state, "done": self.done,
                "total": self.total, "message": self.message, "error": self.error,
                "exam_id": self.exam_id, "elapsed": round(time.time() - self.started),
                "eta": self.eta()}
        if full:
            data.update(log=self.log, result=self.result)
        return data


def create_app(library_dir: Path, output_dir: Path, ollama_host: str | None = None) -> Flask:
    app = Flask(__name__, static_folder=None)
    app.config["MAX_CONTENT_LENGTH"] = 200 * 1024 * 1024
    library_dir.mkdir(parents=True, exist_ok=True)
    output_dir.mkdir(parents=True, exist_ok=True)
    jobs: dict[str, Job] = {}
    lock = threading.Lock()  # one exam file write at a time

    def client(provider: str, model: str | None = None, **kwargs):
        if provider not in PROVIDERS:
            abort(400, "Unknown provider")
        if provider == "ollama" and ollama_host:
            kwargs.setdefault("base_url", ollama_host)
        return make_client(provider, model, verbose=False, **kwargs)

    def client_from(s: dict):
        try:
            seed = int(s["seed"]) if str(s.get("seed") or "").strip() else None
            return client(s.get("provider") or "ollama", s.get("model") or None,
                          num_ctx=int(s.get("num_ctx") or 16384),
                          temperature=float(s.get("temperature") or 0.7), seed=seed), seed
        except (LLMError, ValueError) as exc:
            abort(400, str(exc))

    def running_job(ocr: bool = False) -> Job | None:
        """The running AI job (or OCR job): OCR can run while an exam is being written."""
        return next((j for j in jobs.values()
                     if j.state == "running" and (j.kind in LOCAL_JOBS) == ocr), None)

    def start_job(job: Job, work) -> Response:
        if running_job(job.kind in LOCAL_JOBS):
            abort(409, "Something is already running. Wait for it or stop it first.")
        jobs[job.id] = job

        def run():
            try:
                work(job)
                job.state = "done"
            except (Cancelled, InterruptedError):
                job.state, job.message = "cancelled", "Stopped"
            except Exception as exc:  # shown to the user in the progress panel
                job.state, job.error = "error", str(exc)

        threading.Thread(target=run, daemon=True).start()
        return jsonify(job.as_dict())

    @app.errorhandler(400)
    @app.errorhandler(404)
    @app.errorhandler(409)
    def json_error(exc):
        return jsonify(error=exc.description), exc.code

    @app.get("/")
    def index():
        return send_from_directory(WEB_DIR, "index.html")

    @app.get("/static/<path:name>")
    def static_file(name):
        return send_from_directory(WEB_DIR, name)

    # --- Settings ------------------------------------------------------------------
    @app.get("/api/meta")
    def meta():
        engine, key = search_settings()
        return jsonify(
            ocr=ocr.available(),
            convert={"targets": convert.TARGETS, "libreoffice": bool(convert.libreoffice()),
                     "inputs": sorted(convert.INPUTS)},
            question_types=[{"id": k, "label": v["label"], "marks": v["marks"]}
                            for k, v in QUESTION_TYPES.items()],
            default_plan=DEFAULT_PLAN,
            difficulties=list(DIFFICULTY_TEXT),
            difficulty_mix=DIFFICULTY_MIX,
            languages=[{"id": k, "label": v["label"]} for k, v in LANGUAGES.items()],
            study={"kinds": study.KINDS, "note_styles": study.NOTE_STYLE_LABELS,
                   "grammar_tests": study.GRAMMAR_TESTS},
            providers=[{
                "id": info.id, "label": info.label, "kind": info.kind,
                "default_model": info.default_model, "key_url": info.key_url,
                "needs_key": info.kind != "ollama",
                "key": mask_key(resolve_key(info.id)) if info.kind != "ollama" else "",
                "base_url": ollama_host if info.id == "ollama" and ollama_host
                else resolve_base_url(info.id),
                "editable_url": info.id in ("ollama", "custom"),
            } for info in PROVIDERS.values()],
            search={"engine": engine, "key": mask_key(key),
                    "engines": [{"id": k, "label": v[0], "needs_key": bool(v[1])}
                                for k, v in SEARCH_ENGINES.items()]},
        )

    @app.post("/api/providers/<provider>")
    def save_provider(provider):
        if provider not in PROVIDERS:
            abort(404, "Unknown provider")
        data = request.get_json(force=True) or {}
        save_provider_config(provider, api_key=data.get("api_key"), base_url=data.get("base_url"))
        return jsonify(ok=True, key=mask_key(resolve_key(provider)))

    @app.post("/api/search-settings")
    def save_search():
        data = request.get_json(force=True) or {}
        try:
            save_search_settings(data.get("engine", "auto"), data.get("api_key"))
        except LLMError as exc:
            abort(400, str(exc))
        return jsonify(ok=True, key=mask_key(search_settings()[1]))

    @app.get("/api/status")
    def status():
        provider = request.args.get("provider", "ollama")
        try:
            c = client(provider)
            c.timeout = 15
            return jsonify(ok=True, provider=provider, models=c.list_models())
        except LLMError as exc:
            return jsonify(ok=False, provider=provider, models=[], error=str(exc))

    # --- Source library ------------------------------------------------------------
    @app.get("/api/library")
    def list_library():
        meta = library_meta(library_dir)
        items = []
        for path in library_files(library_dir):
            entry = meta.get(path.name, {})
            item = {"name": path.name, "type": path.suffix.lower().lstrip("."),
                    "use": entry.get("use", True)}
            try:
                src = load_file(path, entry.get("role"))
                item.update(role=src.kind, chars=len(src.text), readable=len(src.text) >= 200,
                            ocr=src.ocr,
                            pages=src.paper.page_count if src.paper else None,
                            questions=len(src.paper.questions) if src.paper else None)
            except Exception as exc:  # a corrupt file should not break the whole list
                item.update(role=entry.get("role", "notes"), readable=False, error=str(exc))
            items.append(item)
        return jsonify(items)

    @app.post("/api/library")
    def upload():
        saved = []
        for f in request.files.getlist("files"):
            name = _safe_filename(f.filename or "")
            f.save(library_dir / name)
            saved.append(name)
        return jsonify(saved=saved)

    @app.patch("/api/library/<name>")
    def update_library_item(name):
        name = _safe_filename(name)
        if not (library_dir / name).exists():
            abort(404, "File not found")
        data = request.get_json(force=True) or {}
        meta = library_meta(library_dir)
        entry = meta.setdefault(name, {})
        if data.get("role") in ("paper", "notes"):
            entry["role"] = data["role"]
        if "use" in data:
            entry["use"] = bool(data["use"])
        save_library_meta(library_dir, meta)
        return jsonify(ok=True)

    @app.delete("/api/library/<name>")
    def delete_library_item(name):
        path = library_dir / _safe_filename(name)
        if not path.exists():
            abort(404, "File not found")
        path.unlink()
        meta = library_meta(library_dir)
        if meta.pop(path.name, None) is not None:
            save_library_meta(library_dir, meta)
        return jsonify(ok=True)

    # --- Past-paper analysis -----------------------------------------------------------
    analysis_file = library_dir / ".analysis.json"

    def selected_papers(warn=lambda m: None):
        return [s for s in load_library(library_dir, warn) if s.kind == "paper" and s.paper]

    def papers_key(papers) -> str:
        parts = [f"v{CACHE_VERSION}"]
        for s in sorted(papers, key=lambda s: s.title):
            stat = (library_dir / s.title).stat()
            parts.append(f"{s.title}|{stat.st_size}|{stat.st_mtime_ns}")
        return "\n".join(parts)

    def cached_analysis(papers) -> dict | None:
        if not papers:
            return None
        try:
            data = json.loads(analysis_file.read_text(encoding="utf-8"))
        except (OSError, ValueError):
            return None
        return data if data.get("key") == papers_key(papers) else None

    def save_analysis(papers, analysis: dict, model: str) -> dict:
        data = {"key": papers_key(papers), "model": model,
                "created": time.strftime("%Y-%m-%dT%H:%M:%S"), **analysis}
        analysis_file.write_text(json.dumps(data, indent=2, ensure_ascii=False), encoding="utf-8")
        return data

    @app.get("/api/analysis")
    def get_analysis():
        papers = selected_papers()
        data = cached_analysis(papers)
        return jsonify(papers=[s.title for s in papers],
                       analysis={k: v for k, v in data.items() if k != "key"} if data else None)

    @app.post("/api/analyse")
    def analyse():
        s = request.get_json(force=True) or {}
        c, _ = client_from(s)

        def work(job: Job):
            c.check_model()
            papers = selected_papers(job.warn)
            if not papers:
                raise RuntimeError("No past papers selected. Add a PDF and mark it as a past paper.")
            result = analyse_papers(c, papers, progress=job)
            data = save_analysis(papers, result, c.model)
            job.result = {k: v for k, v in data.items() if k != "key"}
            job.step(1, 1, "Done")

        return start_job(Job("analyse"), work)

    # --- Question bank (all past-year questions, by chapter and difficulty) -------------
    bank_file = library_dir / ".question_bank.json"
    bank_images = library_dir / ".bank_images"  # a picture of each question, cut from its page

    def cached_bank(papers) -> dict | None:
        if not papers:
            return None
        try:
            data = json.loads(bank_file.read_text(encoding="utf-8"))
        except (OSError, ValueError):
            return None
        return data if data.get("key") == papers_key(papers) else None

    def save_bank(papers, bank: dict) -> None:
        with lock:
            bank_file.write_text(json.dumps({**bank, "key": papers_key(papers)}, indent=2,
                                            ensure_ascii=False), encoding="utf-8")

    def public_bank(bank: dict | None):
        return {k: v for k, v in bank.items() if k != "key"} if bank else None

    @app.get("/api/bank")
    def get_bank():
        papers = selected_papers()
        return jsonify(papers=[s.title for s in papers], bank=public_bank(cached_bank(papers)))

    @app.post("/api/bank/build")
    def build_bank():
        s = request.get_json(force=True) or {}
        c, _ = client_from(s)

        def work(job: Job):
            c.check_model()
            papers = selected_papers(job.warn)
            if not papers:
                raise RuntimeError("No past papers selected. Add PDFs and mark them as past papers.")
            analysis = (cached_analysis(papers) or {}).get("merged") or {}
            shutil.rmtree(bank_images, ignore_errors=True)
            bank = qbank.build_bank(c, papers, subject=s.get("subject") or analysis.get("subject") or "",
                                    topics=analysis.get("topics") or [], progress=job,
                                    image_dir=bank_images)
            save_bank(papers, bank)
            job.result = bank

        return start_job(Job("bank"), work)

    @app.post("/api/bank/solve")
    def solve_bank():
        s = request.get_json(force=True) or {}
        c, _ = client_from(s)
        ids = [str(i) for i in s.get("ids") or []][:60]
        if not ids:
            abort(400, "Choose some questions")

        def work(job: Job):
            c.check_model()
            papers = selected_papers()
            bank = cached_bank(papers)
            if not bank:
                raise RuntimeError("Build the question bank first.")
            qbank.solve_bank_questions(c, bank, ids, s.get("language") or "en", progress=job,
                                       image_dir=bank_images)
            save_bank(papers, bank)
            job.result = public_bank(bank)
            job.step(1, 1, "Done")

        return start_job(Job("bank-solve"), work)

    @app.get("/api/bank/export")
    def export_bank():
        bank = cached_bank(selected_papers())
        if not bank:
            abort(404, "Build the question bank first")
        view = request.args.get("view", "chapters")
        per_chapter = max(1, min(int(request.args.get("n") or 10), 100))
        fmt = request.args.get("format", "md")
        text = qbank.render_bank(bank, "hardest" if view == "hardest" else "chapters", per_chapter,
                                 pictures=fmt in ("pdf", "docx"))
        title = f"Hardest {per_chapter} questions per chapter" if view == "hardest" else "Questions by chapter"
        return download(text, fmt, title, images_dir=bank_images)

    @app.get("/api/bank/image/<name>")
    def bank_image(name):
        if not re.fullmatch(r"[A-Za-z0-9_-]+\.png", name):
            abort(404)
        return send_from_directory(bank_images, name, max_age=3600)

    # --- Study tools (notes, flashcards, vocabulary, quiz, grammar) ---------------------
    study_dir = output_dir / "study"
    study_dir.mkdir(exist_ok=True)

    def study_path(set_id: str) -> Path:
        if not _EXAM_ID.match(set_id):
            abort(404, "Not found")
        return study_dir / f"{set_id}.json"

    def load_set(set_id: str) -> dict:
        path = study_path(set_id)
        if not path.exists():
            abort(404, "Not found")
        return json.loads(path.read_text(encoding="utf-8"))

    def save_set(data: dict) -> None:
        with lock:
            study_path(data["id"]).write_text(json.dumps(data, indent=2, ensure_ascii=False),
                                              encoding="utf-8")

    def set_payload(data: dict) -> dict:
        out = dict(data)
        if data["kind"] == "notes":
            out["html"] = render_html(data["markdown"])
        for qa in out.get("qa", []):
            qa["html"] = render_html(qa["answer"])
        return out

    @app.get("/api/study")
    def list_sets():
        items = []
        for path in sorted(study_dir.glob("*.json"), key=lambda p: p.stat().st_mtime, reverse=True):
            try:
                d = json.loads(path.read_text(encoding="utf-8"))
            except (OSError, ValueError):
                continue
            size = len(d.get("cards") or d.get("words") or d.get("items") or [])
            items.append({"id": d["id"], "kind": d["kind"], "title": d["title"],
                          "created": d["created"], "size": size})
        return jsonify(items)

    @app.post("/api/study/generate")
    def generate_set():
        s = request.get_json(force=True) or {}
        kind = s.get("kind")
        if kind not in study.KINDS:
            abort(400, "Unknown study tool")
        c, _ = client_from(s)
        options = {k: s.get(k) for k in ("topic", "level", "language", "count", "style", "length",
                                         "words", "translate_to", "difficulty", "test",
                                         "instructions") if s.get(k) not in (None, "")}

        def work(job: Job):
            c.check_model()
            sources = []
            if kind != "grammar":
                engine, engine_key = search_settings()
                has_own = s.get("use_files") or (s.get("text") or "").strip() or (s.get("urls") or "").strip() \
                    or (kind == "vocab" and (s.get("words") or "").strip())
                try:
                    sources = gather_sources(
                        folder=library_dir if s.get("use_files") else None, text=s.get("text") or "",
                        urls=str(s.get("urls") or "").splitlines(),
                        topic=options.get("topic", ""), web=s.get("web") or ("auto" if not has_own else "off"),
                        engine=engine, engine_key=engine_key,
                        language=options.get("language") or "en", step=job.note, warn=job.warn)
                except SourceError as exc:
                    if kind != "vocab":
                        raise RuntimeError(str(exc)) from None
            if kind == "notes" and options.get("style") == "guide":
                papers = selected_papers()
                options["bank"] = cached_bank(papers)
                options["analysis"] = cached_analysis(papers)
            data = study.generate(c, kind, sources, options, progress=job)
            data["provider"] = s.get("provider") or "ollama"
            save_set(data)
            job.result = {"id": data["id"]}

        return start_job(Job("study"), work)

    @app.get("/api/study/<set_id>")
    def get_set(set_id):
        return jsonify(set_payload(load_set(set_id)))

    @app.delete("/api/study/<set_id>")
    def delete_set(set_id):
        load_set(set_id)
        study_path(set_id).unlink()
        return jsonify(ok=True)

    @app.post("/api/study/<set_id>/ask")
    def ask_set(set_id):
        data = load_set(set_id)
        s = request.get_json(force=True) or {}
        question = str(s.get("question") or "").strip()
        if not question:
            abort(400, "Type a question")
        c, _ = client_from(s)

        def work(job: Job):
            job.step(0, 1, "Thinking…")
            answer = study.ask(c, data, question, progress=job)
            data.setdefault("qa", []).append({"question": question, "answer": answer})
            save_set(data)
            job.result = {"question": question, "answer": answer, "html": render_html(answer)}
            job.step(1, 1, "Done")

        return start_job(Job("ask"), work)

    @app.get("/api/study/<set_id>/export")
    def export_set(set_id):
        data = load_set(set_id)
        fmt = request.args.get("format", "md")
        if fmt == "csv":
            try:
                text = study.as_csv(data)
            except ValueError as exc:
                abort(400, str(exc))
            return Response("\ufeff" + text, mimetype="text/csv", headers={
                "Content-Disposition": f"attachment; filename*=UTF-8''{quote(data['title'][:60])}.csv"})
        return download(study.as_markdown(data), fmt, data["title"])

    # --- Exams ------------------------------------------------------------------------
    def exam_path(exam_id: str) -> Path:
        if not _EXAM_ID.match(exam_id):
            abort(404, "Exam not found")
        return output_dir / f"{exam_id}.json"

    def load_exam(exam_id: str) -> dict:
        path = exam_path(exam_id)
        if not path.exists():
            abort(404, "Exam not found")
        return json.loads(path.read_text(encoding="utf-8"))

    def save_exam(exam: dict) -> None:
        with lock:
            exam_path(exam["id"]).write_text(json.dumps(exam, indent=2, ensure_ascii=False),
                                             encoding="utf-8")
            exam_path(exam["id"]).with_suffix(".md").write_text(render_markdown(exam),
                                                                encoding="utf-8")

    def exam_payload(exam: dict) -> dict:
        public = {k: v for k, v in exam.items() if k != "context"}
        return {**public,
                "total_marks": sum(q["marks"] for q in exam["questions"]),
                "html": {part: render_html(render_markdown(exam, part))
                         for part in ("paper", "answers", "scheme")}}

    @app.post("/api/generate")
    def generate():
        s = request.get_json(force=True) or {}
        c, seed = client_from(s)
        plan = [p for p in s.get("plan") or [] if isinstance(p, dict)]
        req = ExamRequest(
            topic=(s.get("topic") or "").strip(), subject=(s.get("subject") or "").strip(),
            level=(s.get("level") or "").strip(), structure=s.get("structure") or "custom",
            plan=plan or [dict(p) for p in DEFAULT_PLAN],
            difficulty=s.get("difficulty") if s.get("difficulty") in DIFFICULTY_TEXT else "mixed",
            difficulty_mix=s.get("difficulty_mix") if isinstance(s.get("difficulty_mix"), dict) else None,
            challenge=max(-2, min(2, int(s.get("challenge") or 0))),
            verify=s.get("verify") is not False,
            instructions=(s.get("instructions") or "").strip(),
            duration_minutes=int(s["minutes"]) if str(s.get("minutes") or "").strip() else None,
            seed=seed,
            language=s.get("language") if s.get("language") in LANGUAGES else "en",
            source_language=s.get("source_language")
            if s.get("source_language") in LANGUAGES else "auto")

        def work(job: Job):
            c.check_model()
            engine, engine_key = search_settings()
            try:
                sources = gather_sources(
                    folder=library_dir, text=s.get("text") or "",
                    urls=[u for u in str(s.get("urls") or "").splitlines()],
                    topic=req.topic or req.subject, web=s.get("web") or "auto",
                    engine=engine, engine_key=engine_key,
                    language=req.language if req.source_language == "auto" else req.source_language,
                    step=job.note, warn=job.warn)
            except SourceError as exc:
                raise RuntimeError(str(exc)) from None
            papers = [x for x in sources if x.kind == "paper" and x.paper]
            cached = cached_analysis(papers)
            if cached:
                req.analysis = {"merged": cached["merged"], "papers": cached["papers"]}
                job.note("Using the saved analysis of your past papers")
            exam = generate_exam(c, sources, req, progress=job)
            if papers and exam.get("analysis") and not cached:
                save_analysis(papers, exam["analysis"], c.model)
            exam["provider"] = s.get("provider") or "ollama"
            save_exam(exam)
            job.exam_id = exam["id"]

        return start_job(Job("generate"), work)

    @app.get("/api/jobs/current")
    def current_job():
        job = running_job()
        return jsonify(job.as_dict() if job else None)

    @app.get("/api/jobs/running")
    def running_jobs():
        """Everything still running, for the Stop buttons on every page."""
        return jsonify([j.as_dict(full=False) for j in jobs.values() if j.state == "running"])

    # --- Downloads and the file converter --------------------------------------------
    def download(markdown_text: str, fmt: str, title: str, suffix: str = "",
                 images_dir: Path | None = None) -> Response:
        if fmt not in ("md", "txt", "html", "pdf", "docx"):
            abort(400, "Unknown format")
        data, mimetype = convert.export_markdown(markdown_text, fmt, title, images_dir)
        slug = re.sub(r'[\\/:*?"<>|]+', "_", title).strip(" ._")[:60] or "export"
        return Response(data, mimetype=mimetype, headers={
            "Content-Disposition": f"attachment; filename*=UTF-8''{quote(slug + suffix)}.{fmt}"})

    @app.post("/api/export")
    def export_text():
        data = request.get_json(force=True) or {}
        return download(str(data.get("markdown") or ""), str(data.get("format") or "md"),
                        str(data.get("title") or "export"))

    converted_dir = output_dir / "converted"

    @app.post("/api/convert")
    def convert_files():
        target = request.form.get("target", "pdf")
        if target not in (*convert.TARGETS, "merged-pdf", "searchable-pdf"):
            abort(400, "Unknown target format")
        uploads = request.files.getlist("files")
        if not uploads:
            abort(400, "Choose some files")
        job = Job("convert")
        work_dir = converted_dir / job.id
        in_dir = work_dir / "in"
        in_dir.mkdir(parents=True)
        files = []
        for f in uploads:
            name = _SAFE_NAME.sub("_", Path(f.filename or "file").name).strip(" .") or "file"
            if Path(name).suffix.lower() not in convert.INPUTS:
                abort(400, f"{name}: this file type can't be converted")
            f.save(in_dir / name)
            files.append(in_dir / name)

        def work(job: Job):
            out_dir = work_dir / "out"
            out_dir.mkdir()
            results = []
            if target == "merged-pdf":
                job.step(0, 1, f"Merging {len(files)} files")
                results.append(convert.merge_pdfs(files, out_dir / "merged.pdf", work_dir))
            else:
                for i, src in enumerate(files):
                    if job.cancelled():
                        raise Cancelled()
                    job.step(i, len(files), f"Converting {src.name}")
                    try:
                        if target == "searchable-pdf":
                            results.append(convert.searchable_pdf(
                                src, out_dir / f"{src.stem} (searchable).pdf",
                                should_stop=job.cancelled,
                                step=lambda n, total, name=src.name: job.note(
                                    f"{name}: OCR page {n} of {total}")))
                        else:
                            results.append(convert.convert(src, target, out_dir))
                    except convert.ConvertError as exc:
                        job.warn(str(exc))
            job.result = [converted_info(r) for r in results]
            shutil.rmtree(in_dir, ignore_errors=True)  # the uploaded originals aren't needed now
            job.step(1, 1, "Done")
            if not results:
                raise RuntimeError("Nothing could be converted. " + " ".join(
                    m[2:] for m in job.log if m.startswith("⚠")))

        return start_job(job, work)

    def converted_info(path: Path) -> dict:
        job_id = path.parent.parent.name
        return {"job": job_id, "name": path.name, "size": path.stat().st_size,
                "created": path.stat().st_mtime, "url": f"/api/converted/{job_id}/{quote(path.name)}"}

    def converted_path(job_id: str, name: str) -> Path:
        if not re.match(r"^[a-f0-9]{12}$", job_id):
            abort(404, "Not found")
        path = converted_dir / job_id / "out" / Path(name).name
        if not path.is_file():
            abort(404, "Not found")
        return path

    def busy_folders() -> set[str]:
        return {j.id for j in jobs.values() if j.kind == "convert" and j.state == "running"}

    @app.get("/api/converted")
    def list_converted():
        files = [p for p in converted_dir.glob("*/out/*") if p.is_file()]
        files.sort(key=lambda p: p.stat().st_mtime, reverse=True)
        return jsonify([converted_info(p) for p in files])

    @app.get("/api/converted/<job_id>/<path:name>")
    def converted_file(job_id, name):
        path = converted_path(job_id, name)
        return send_file(path, as_attachment=True, download_name=path.name)

    @app.delete("/api/converted/<job_id>/<path:name>")
    def delete_converted(job_id, name):
        path = converted_path(job_id, name)
        path.unlink()
        if not any(path.parent.iterdir()):
            shutil.rmtree(path.parent.parent, ignore_errors=True)
        return jsonify(ok=True)

    @app.delete("/api/converted")
    def delete_all_converted():
        busy = busy_folders()
        removed = 0
        for folder in converted_dir.glob("*"):
            if folder.is_dir() and folder.name not in busy:
                removed += sum(1 for p in folder.glob("out/*") if p.is_file())
                shutil.rmtree(folder, ignore_errors=True)
        return jsonify(ok=True, removed=removed)

    @app.post("/api/data/delete-all")
    def delete_all_data():
        """Delete every file SGPT made or was given: uploads, exams, study sets, converted
        files, question bank, analyses and caches. Optionally also settings and API keys."""
        s = request.get_json(force=True) or {}
        if s.get("confirm") != "DELETE":
            abort(400, 'Type DELETE to confirm')
        for job in jobs.values():
            if job.state == "running":
                job.cancel()
        deadline = time.time() + 10
        while any(j.state == "running" for j in jobs.values()) and time.time() < deadline:
            time.sleep(0.2)
        for folder in (library_dir, output_dir):
            for item in folder.iterdir():
                if item.name == ".gitkeep":
                    continue
                if item.is_dir():
                    shutil.rmtree(item, ignore_errors=True)
                else:
                    item.unlink(missing_ok=True)
        (output_dir / "study").mkdir(exist_ok=True)
        if s.get("settings"):
            config_path().unlink(missing_ok=True)
        jobs.clear()
        return jsonify(ok=True)

    # --- OCR only ------------------------------------------------------------------------
    @app.post("/api/ocr")
    def ocr_files():
        files = [(f.filename or "file", f.read()) for f in request.files.getlist("files")]
        if not files:
            abort(400, "Choose a PDF or image")
        force = request.form.get("force") == "true"

        def work(job: Job):
            results = []
            for index, (name, data) in enumerate(files):
                def step(i, n, name=name, index=index):
                    job.step(i - 1, n, f"{name}: page {i} of {n}"
                             + (f" (file {index + 1} of {len(files)})" if len(files) > 1 else ""))
                pages = ocr.ocr_document(name, data, force=force, step=step,
                                         should_stop=job.cancelled)
                results.append({"name": Path(name).name, "pages": pages})
                job.result = results
            job.step(1, 1, "Done")

        return start_job(Job("ocr"), work)

    @app.get("/api/jobs/<job_id>")
    def get_job(job_id):
        if job_id not in jobs:
            abort(404, "Job not found")
        return jsonify(jobs[job_id].as_dict())

    @app.post("/api/jobs/<job_id>/cancel")
    def cancel_job(job_id):
        if job_id not in jobs:
            abort(404, "Job not found")
        jobs[job_id].cancel()
        return jsonify(ok=True)

    @app.get("/api/exams")
    def list_exams():
        items = []
        for path in sorted(output_dir.glob("*.json"), key=lambda p: p.stat().st_mtime,
                           reverse=True):
            try:
                exam = json.loads(path.read_text(encoding="utf-8"))
                items.append({"id": exam["id"], "title": exam["title"], "created": exam["created"],
                              "questions": len(exam["questions"]),
                              "marks": sum(q["marks"] for q in exam["questions"])})
            except (OSError, ValueError, KeyError):
                continue
        return jsonify(items)

    @app.get("/api/exams/<exam_id>")
    def get_exam(exam_id):
        return jsonify(exam_payload(load_exam(exam_id)))

    @app.patch("/api/exams/<exam_id>")
    def update_exam(exam_id):
        exam = load_exam(exam_id)
        data = request.get_json(force=True) or {}
        if str(data.get("title") or "").strip():
            exam["title"] = str(data["title"]).strip()
        save_exam(exam)
        return jsonify(exam_payload(exam))

    @app.patch("/api/exams/<exam_id>/questions/<int:number>")
    def edit_question(exam_id, number):
        exam = load_exam(exam_id)
        q = next((q for q in exam["questions"] if q["number"] == number), None)
        if not q:
            abort(404, "Question not found")
        data = request.get_json(force=True) or {}
        for key in ("question", "answer", "final_answer", "accept"):
            if isinstance(data.get(key), str):
                q[key] = data[key].strip()
        if isinstance(data.get("options"), list) and q["type"] == "mcq":
            q["options"] = [str(o).strip() for o in data["options"] if str(o).strip()]
        if str(data.get("marks") or "").isdigit() and not q["parts"]:
            q["marks"] = max(int(data["marks"]), 1)
        save_exam(exam)
        return jsonify(exam_payload(exam))

    @app.delete("/api/exams/<exam_id>/questions/<int:number>")
    def delete_question(exam_id, number):
        exam = load_exam(exam_id)
        exam["questions"] = [q for q in exam["questions"] if q["number"] != number]
        if not exam["questions"]:
            abort(400, "An exam needs at least one question")
        renumber(exam)
        save_exam(exam)
        return jsonify(exam_payload(exam))

    @app.post("/api/exams/<exam_id>/questions/<int:number>/regenerate")
    def regenerate(exam_id, number):
        exam = load_exam(exam_id)
        if not any(q["number"] == number for q in exam["questions"]):
            abort(404, "Question not found")
        c, seed = client_from(request.get_json(force=True) or {})

        def work(job: Job):
            job.step(0, 1, f"Writing a new question {number}")
            regenerate_question(c, exam, number, progress=job, seed=seed)
            save_exam(exam)
            job.step(1, 1, "Done")

        return start_job(Job("regenerate", exam_id), work)

    @app.get("/api/exams/<exam_id>/export")
    def export_exam(exam_id):
        exam = load_exam(exam_id)
        part = request.args.get("part", "all")
        fmt = request.args.get("format", "md")
        if part not in ("all", "paper", "answers", "scheme"):
            abort(400, "Unknown part")
        suffix = {"all": "", "paper": "_paper", "answers": "_answers", "scheme": "_marking_scheme"}
        return download(render_markdown(exam, part), fmt, exam["title"], suffix[part])

    @app.delete("/api/exams/<exam_id>")
    def delete_exam(exam_id):
        path = exam_path(exam_id)
        if not path.exists():
            abort(404, "Exam not found")
        path.unlink()
        path.with_suffix(".md").unlink(missing_ok=True)
        return jsonify(ok=True)

    return app


def main(argv: list[str] | None = None) -> int:
    p = argparse.ArgumentParser(prog="sgpt.app", description="SGPT web app")
    p.add_argument("--port", type=int, default=8765)
    p.add_argument("--library", default="library", help="folder for your source files")
    p.add_argument("--output", default="output", help="folder for generated exams")
    p.add_argument("--host", help="Ollama URL (default: $OLLAMA_HOST or http://localhost:11434)")
    p.add_argument("--no-browser", action="store_true", help="don't open the browser")
    args = p.parse_args(argv)

    app = create_app(Path(args.library), Path(args.output), args.host)
    url = f"http://127.0.0.1:{args.port}"
    print(f"SGPT is running at {url}  (press Ctrl+C to quit)")
    if not args.no_browser:
        threading.Timer(1.0, webbrowser.open, [url]).start()
    app.run(host="127.0.0.1", port=args.port, threaded=True)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
