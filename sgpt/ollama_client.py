"""Minimal client for the local Ollama HTTP API (standard library only), plus shared helpers."""

from __future__ import annotations

import base64
import json
import re
import sys
import time
import urllib.error
import urllib.request
from typing import Callable

_THINK_BLOCK = re.compile(r"<think>.*?</think>", re.DOTALL)


class LLMError(RuntimeError):
    """A problem talking to the AI provider, with a message fit to show the user."""


OllamaError = LLMError


class Cancelled(Exception):
    """Raised when the user stops a generation part-way through."""


def strip_thinking(text: str) -> str:
    """Remove qwen3 <think>...</think> reasoning, including an unterminated block."""
    text = _THINK_BLOCK.sub("", text)
    if "<think>" in text:
        text = text.split("<think>", 1)[0]
    return text.strip()


# When a provider is busy or overloaded (e.g. Gemini "503: high demand") or rate-limited,
# wait this many seconds before each new try.
RETRY_WAITS = (5, 15, 30, 60)
BUSY_CODES = {429, 500, 502, 503, 504, 529}


def wait_to_retry(label: str, attempt: int, should_stop: Callable[[], bool] | None) -> bool:
    """Wait before retry number attempt+1; False once every retry is used up.

    Stop still works while waiting. When should_stop belongs to a running job (it is the
    job's bound cancelled() method), the wait is shown in its progress.
    """
    if attempt >= len(RETRY_WAITS):
        return False
    wait = RETRY_WAITS[attempt]
    job = getattr(should_stop, "__self__", None)
    if hasattr(job, "note"):
        job.note(f"{label} is busy right now. Trying again in {wait}s "
                 f"(try {attempt + 2} of {len(RETRY_WAITS) + 1})…")
    end = time.time() + wait
    while time.time() < end:
        if should_stop and should_stop():
            raise Cancelled()
        time.sleep(min(0.25, max(end - time.time(), 0)))
    return True


def busy_message(label: str, code: int, detail: str) -> str:
    if code == 429:
        return (f"{label} rate limit or quota reached, even after waiting and trying "
                f"{len(RETRY_WAITS) + 1} times: {detail} Wait a few minutes, check your plan's "
                "limits, or choose another model or provider in the settings.")
    return (f"{label} is busy or having problems (error {code}), even after trying "
            f"{len(RETRY_WAITS) + 1} times over about two minutes: {detail} Try again later, "
            "or choose another model or provider in the settings (for example a \"lite\" or "
            "older model, which is often less busy).")


def parse_json(text: str) -> dict:
    """Parse the first JSON object in a model reply."""
    text = strip_thinking(text)
    text = re.sub(r"^```(?:json)?\s*|\s*```$", "", text.strip())
    start, end = text.find("{"), text.rfind("}")
    if start == -1 or end <= start:
        raise ValueError("no JSON object in reply")
    return json.loads(text[start : end + 1])


class OllamaClient:
    def __init__(self, host: str, model: str, num_ctx: int = 16384, temperature: float = 0.7,
                 seed: int | None = None, verbose: bool = True, timeout: float = 1800):
        self.host = host.rstrip("/")
        if not self.host.startswith(("http://", "https://")):
            self.host = "http://" + self.host
        self.model = model
        self.num_ctx = num_ctx
        self.temperature = temperature
        self.seed = seed
        self.verbose = verbose
        self.timeout = timeout
        self._vision: bool | None = None

    @property
    def vision(self) -> bool:
        """Whether the model can read images (e.g. qwen2.5vl, gemma3, llava; not qwen3:4b)."""
        if self._vision is None:
            try:
                with self._request("/api/show", {"model": self.model}) as resp:
                    self._vision = "vision" in (json.load(resp).get("capabilities") or [])
            except (OllamaError, ValueError, OSError):
                self._vision = False
        return self._vision

    def _request(self, path: str, payload: dict | None = None):
        data = json.dumps(payload).encode() if payload is not None else None
        req = urllib.request.Request(self.host + path, data=data,
                                     headers={"Content-Type": "application/json"})
        try:
            return urllib.request.urlopen(req, timeout=self.timeout)
        except urllib.error.HTTPError as exc:
            detail = exc.read().decode(errors="replace")
            raise OllamaError(f"Ollama returned HTTP {exc.code}: {detail}") from exc
        except urllib.error.URLError as exc:
            raise OllamaError(
                f"Cannot reach Ollama at {self.host} ({exc.reason}). "
                "Is it running? Start it with `ollama serve` or open the Ollama app."
            ) from exc

    def list_models(self) -> list[str]:
        with self._request("/api/tags") as resp:
            return sorted(m.get("name") for m in json.load(resp).get("models", []))

    def check_model(self) -> None:
        names = set(self.list_models())
        wanted = self.model if ":" in self.model else self.model + ":latest"
        if wanted not in names:
            raise OllamaError(
                f"Model '{self.model}' is not installed. Run: ollama pull {self.model}"
            )

    def chat(self, system: str, prompt: str, json_mode: bool = False,
             max_tokens: int = 4096, label: str = "",
             should_stop: Callable[[], bool] | None = None, think: bool = False,
             images: list[bytes] | None = None) -> str:
        options = {"temperature": self.temperature, "num_ctx": self.num_ctx,
                   "num_predict": max_tokens * 3 if think else max_tokens}
        if self.seed is not None:
            options["seed"] = self.seed
        payload = {
            "model": self.model,
            "messages": [{"role": "system", "content": system},
                         {"role": "user", "content": prompt,
                          **({"images": [base64.b64encode(i).decode() for i in images]}
                             if images and self.vision else {})}],
            "stream": True,
            # qwen3: skip the hidden reasoning phase for speed, except when checking answers
            "think": think,
            "options": options,
        }
        if json_mode:
            payload["format"] = "json"

        if self.verbose and label:
            print(f"  -> {label} ", end="", flush=True)
        chunks: list[str] = []
        with self._request("/api/chat", payload) as resp:
            for raw in resp:
                if not raw.strip():
                    continue
                event = json.loads(raw)
                if "error" in event:
                    raise OllamaError(event["error"])
                chunks.append(event.get("message", {}).get("content", ""))
                if self.verbose and label and len(chunks) % 40 == 0:
                    print(".", end="", flush=True)
                if should_stop and should_stop():
                    raise Cancelled()
                if event.get("done"):
                    break
        if self.verbose and label:
            print(" done", file=sys.stdout, flush=True)
        return strip_thinking("".join(chunks))
