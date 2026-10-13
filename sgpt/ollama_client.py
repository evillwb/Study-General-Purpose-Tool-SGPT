"""Minimal client for the local Ollama HTTP API (standard library only), plus shared helpers."""

from __future__ import annotations

import base64
import json
import re
import sys
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
