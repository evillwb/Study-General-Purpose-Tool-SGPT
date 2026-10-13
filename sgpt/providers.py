"""AI providers: local Ollama, Anthropic Claude, and any OpenAI-compatible API.

Every client has the same small interface used by the generator:
    .model, .list_models(), .check_model(), .chat(system, prompt, json_mode, max_tokens, should_stop)
"""

from __future__ import annotations

import base64
import json
import os
import re
import urllib.error
import urllib.request
from dataclasses import dataclass
from pathlib import Path
from typing import Callable

from .ollama_client import Cancelled, LLMError, OllamaClient, strip_thinking


@dataclass(frozen=True)
class ProviderInfo:
    id: str
    label: str
    kind: str  # "ollama" | "openai" | "anthropic"
    base_url: str
    key_env: str | None
    default_model: str
    key_url: str = ""


PROVIDERS: dict[str, ProviderInfo] = {p.id: p for p in [
    ProviderInfo("ollama", "Ollama (local, private)", "ollama",
                 os.environ.get("OLLAMA_HOST", "http://localhost:11434"), None, "qwen3:4b"),
    ProviderInfo("openai", "OpenAI", "openai", "https://api.openai.com/v1",
                 "OPENAI_API_KEY", "gpt-5-mini", "https://platform.openai.com/api-keys"),
    ProviderInfo("anthropic", "Anthropic Claude", "anthropic", "https://api.anthropic.com",
                 "ANTHROPIC_API_KEY", "claude-opus-5-5", "https://platform.claude.com/settings/keys"),
    ProviderInfo("gemini", "Google Gemini", "openai",
                 "https://generativelanguage.googleapis.com/v1beta/openai",
                 "GEMINI_API_KEY", "gemini-2.5-flash", "https://aistudio.google.com/apikey"),
    ProviderInfo("groq", "Groq", "openai", "https://api.groq.com/openai/v1",
                 "GROQ_API_KEY", "llama-3.3-70b-versatile", "https://console.groq.com/keys"),
    ProviderInfo("openrouter", "OpenRouter", "openai", "https://openrouter.ai/api/v1",
                 "OPENROUTER_API_KEY", "openai/gpt-5-mini", "https://openrouter.ai/settings/keys"),
    ProviderInfo("deepseek", "DeepSeek", "openai", "https://api.deepseek.com/v1",
                 "DEEPSEEK_API_KEY", "deepseek-chat", "https://platform.deepseek.com/api_keys"),
    ProviderInfo("custom", "Custom (OpenAI-compatible)", "openai", "http://localhost:1234/v1",
                 "CUSTOM_API_KEY", ""),
]}


# --- Saved settings (API keys live only on this computer) ----------------------

def config_path() -> Path:
    return Path(os.environ.get("SGPT_CONFIG", Path.home() / ".sgpt" / "config.json"))


def load_config() -> dict:
    try:
        return json.loads(config_path().read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return {}


def save_provider_config(provider_id: str, api_key: str | None = None,
                         base_url: str | None = None) -> None:
    config = load_config()
    entry = config.setdefault("providers", {}).setdefault(provider_id, {})
    for key, value in (("api_key", api_key), ("base_url", base_url)):
        if value is None:
            continue
        if value.strip():
            entry[key] = value.strip()
        else:
            entry.pop(key, None)
    path = config_path()
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(config, indent=2), encoding="utf-8")
    try:
        path.chmod(0o600)  # readable only by you
    except OSError:
        pass


def resolve_key(provider_id: str, explicit: str | None = None) -> str:
    info = PROVIDERS[provider_id]
    saved = load_config().get("providers", {}).get(provider_id, {}).get("api_key")
    return explicit or saved or (os.environ.get(info.key_env, "") if info.key_env else "")


def resolve_base_url(provider_id: str, explicit: str | None = None) -> str:
    saved = load_config().get("providers", {}).get(provider_id, {}).get("base_url")
    return (explicit or saved or PROVIDERS[provider_id].base_url).rstrip("/")


def mask_key(key: str) -> str:
    return f"{key[:3]}…{key[-4:]}" if len(key) > 10 else ("set" if key else "")


def make_client(provider_id: str, model: str | None = None, *, api_key: str | None = None,
                base_url: str | None = None, temperature: float = 0.7, seed: int | None = None,
                num_ctx: int = 16384, verbose: bool = True):
    if provider_id not in PROVIDERS:
        raise LLMError(f"Unknown provider '{provider_id}'. Choose one of: {', '.join(PROVIDERS)}")
    info = PROVIDERS[provider_id]
    model = model or info.default_model
    url = resolve_base_url(provider_id, base_url)
    if info.kind == "ollama":
        return OllamaClient(url, model, num_ctx=num_ctx, temperature=temperature, seed=seed,
                            verbose=verbose)
    key = resolve_key(provider_id, api_key)
    if info.kind == "anthropic":
        return AnthropicClient(key, model, label=info.label)
    if not model:
        raise LLMError(f"Choose a model for {info.label}.")
    return OpenAICompatClient(url, key, model, label=info.label, key_env=info.key_env,
                              temperature=temperature, seed=seed,
                              key_optional=provider_id == "custom")


# --- OpenAI-compatible APIs (OpenAI, Gemini, Groq, OpenRouter, DeepSeek, LM Studio…) ---

_NON_CHAT = ("embed", "tts", "whisper", "dall-e", "moderation", "image", "audio", "realtime",
             "transcribe", "speech", "search", "davinci", "babbage", "aqa", "veo", "imagen")


def _error_message(body: str) -> str:
    try:
        data = json.loads(body)
    except ValueError:
        return body.strip()[:300]
    if isinstance(data, list) and data:
        data = data[0]
    err = data.get("error", data) if isinstance(data, dict) else data
    if isinstance(err, dict):
        return str(err.get("message") or err)[:300]
    return str(err)[:300]


# Model names that accept images on OpenAI-compatible APIs.
_VISION_MODELS = re.compile(
    r"gpt-4o|gpt-4\.1|gpt-5|\bo[34]\b|o[34]-|gemini|vision|llava|llama-4|claude|pixtral|"
    r"qwen[\d.]*-?vl|gemma-?3|grok-[\d]+v|mistral-(?:medium|small)-3", re.IGNORECASE)


class OpenAICompatClient:
    def __init__(self, base_url: str, api_key: str, model: str, *, label: str = "API",
                 key_env: str | None = None, temperature: float = 0.7, seed: int | None = None,
                 timeout: float = 600, key_optional: bool = False):
        self.base_url = base_url.rstrip("/")
        self.api_key = api_key
        self.model = model
        self.label = label
        self.key_env = key_env
        self.temperature = temperature
        self.seed = seed
        self.timeout = timeout
        self.key_optional = key_optional

    def _request(self, path: str, payload: dict | None = None):
        headers = {"Content-Type": "application/json"}
        if self.api_key:
            headers["Authorization"] = f"Bearer {self.api_key}"
        data = json.dumps(payload).encode() if payload is not None else None
        req = urllib.request.Request(self.base_url + path, data=data, headers=headers)
        try:
            return urllib.request.urlopen(req, timeout=self.timeout)
        except urllib.error.HTTPError as exc:
            message = _error_message(exc.read().decode(errors="replace"))
            if exc.code in (401, 403):
                raise LLMError(f"{self.label} rejected the API key: {message}") from exc
            if exc.code == 429:
                raise LLMError(f"{self.label} rate limit or quota reached: {message}") from exc
            raise _HTTPError(exc.code, f"{self.label} error {exc.code}: {message}") from exc
        except urllib.error.URLError as exc:
            raise LLMError(f"Cannot reach {self.label} at {self.base_url} ({exc.reason}).") from exc

    def _require_key(self) -> None:
        if not self.api_key and not self.key_optional:
            hint = f" or set {self.key_env}" if self.key_env else ""
            raise LLMError(f"No API key for {self.label}. Add one in the settings{hint}.")

    def list_models(self) -> list[str]:
        self._require_key()
        with self._request("/models") as resp:
            data = json.load(resp)
        ids = [str(m.get("id", "")).removeprefix("models/") for m in data.get("data", [])]
        return sorted(i for i in ids if i and not any(word in i.lower() for word in _NON_CHAT))

    def check_model(self) -> None:
        self._require_key()
        self.list_models()  # confirms the key and URL work; model errors surface on first call

    @property
    def vision(self) -> bool:
        """Whether the model can read images (judged from its name)."""
        return bool(_VISION_MODELS.search(self.model)) and "deepseek" not in self.base_url

    def chat(self, system: str, prompt: str, json_mode: bool = False, max_tokens: int = 4096,
             label: str = "", should_stop: Callable[[], bool] | None = None,
             think: bool = False, images: list[bytes] | None = None) -> str:
        self._require_key()
        content = prompt
        if images and self.vision:
            content = [{"type": "text", "text": prompt}] + [
                {"type": "image_url",
                 "image_url": {"url": "data:image/png;base64," + base64.b64encode(i).decode()}}
                for i in images]
        payload = {
            "model": self.model,
            "messages": [{"role": "system", "content": system},
                         {"role": "user", "content": content}],
            "stream": True,
            "temperature": self.temperature,
        }
        if "api.openai.com" in self.base_url:
            # Newer OpenAI models count hidden reasoning against this limit, so allow more.
            payload["max_completion_tokens"] = max(max_tokens * 4, 32000)
        else:
            payload["max_tokens"] = max_tokens
        if self.seed is not None:
            payload["seed"] = self.seed
        if json_mode:
            payload["response_format"] = {"type": "json_object"}

        # Models differ in which options they accept; drop any option they reject and retry.
        for _ in range(4):
            try:
                return self._stream(payload, should_stop)
            except _HTTPError as exc:
                text = str(exc).lower()
                if exc.code != 400:
                    raise LLMError(str(exc)) from None
                dropped = False
                for option in ("temperature", "response_format", "seed"):
                    if option in payload and option in text:
                        payload.pop(option)
                        dropped = True
                if "max_tokens" in payload and "max_tokens" in text:
                    payload["max_completion_tokens"] = payload.pop("max_tokens")
                    dropped = True
                if not dropped:
                    raise LLMError(str(exc)) from None
        raise LLMError(f"{self.label} rejected the request settings.")

    def _stream(self, payload: dict, should_stop) -> str:
        chunks: list[str] = []
        with self._request("/chat/completions", payload) as resp:
            for raw in resp:
                line = raw.decode("utf-8", errors="replace").strip()
                if not line.startswith("data:"):
                    continue
                data = line[5:].strip()
                if data == "[DONE]":
                    break
                event = json.loads(data)
                if event.get("error"):
                    raise LLMError(f"{self.label}: {_error_message(json.dumps(event))}")
                for choice in event.get("choices", []):
                    chunks.append((choice.get("delta") or {}).get("content") or "")
                if should_stop and should_stop():
                    raise Cancelled()
        return strip_thinking("".join(chunks))


class _HTTPError(LLMError):
    def __init__(self, code: int, message: str):
        super().__init__(message)
        self.code = code


# --- Anthropic Claude (official SDK) -------------------------------------------------

# Models that accept the server-side refusal fallback (`fallbacks: "default"`).
_FALLBACK_MODELS = {"claude-fable-5-1", "claude-opus-5-5", "claude-opus-5", "claude-sonnet-5-5"}


class AnthropicClient:
    def __init__(self, api_key: str, model: str, *, label: str = "Anthropic Claude",
                 effort: str = "high"):
        self.api_key = api_key
        self.model = model
        self.label = label
        self.effort = effort
        self._client = None

    def _sdk(self):
        if not self.api_key:
            raise LLMError("No API key for Anthropic Claude. Add one in the settings "
                           "or set ANTHROPIC_API_KEY.")
        if self._client is None:
            try:
                import anthropic
            except ImportError as exc:
                raise LLMError("The Claude provider needs the Anthropic SDK: "
                               "pip install anthropic") from exc
            self._client = anthropic.Anthropic(api_key=self.api_key)
        return self._client

    def _call(self, fn):
        import anthropic

        try:
            return fn()
        except anthropic.AuthenticationError as exc:
            raise LLMError("Anthropic rejected the API key.") from exc
        except anthropic.PermissionDeniedError as exc:
            raise LLMError(f"Anthropic: permission denied ({exc.message}).") from exc
        except anthropic.NotFoundError as exc:
            raise LLMError(f"Anthropic: model '{self.model}' not found.") from exc
        except anthropic.RateLimitError as exc:
            raise LLMError("Anthropic rate limit reached. Wait a minute and try again.") from exc
        except anthropic.APIStatusError as exc:
            raise LLMError(f"Anthropic error {exc.status_code}: {exc.message}") from exc
        except anthropic.APIConnectionError as exc:
            raise LLMError("Cannot reach the Anthropic API. Check your internet connection.") from exc

    def list_models(self) -> list[str]:
        client = self._sdk()
        return sorted((m.id for m in self._call(lambda: list(client.models.list(limit=100)))),
                      reverse=True)

    def check_model(self) -> None:
        self.list_models()

    vision = True  # every current Claude model reads images

    def chat(self, system: str, prompt: str, json_mode: bool = False, max_tokens: int = 4096,
             label: str = "", should_stop: Callable[[], bool] | None = None,
             think: bool = False, images: list[bytes] | None = None) -> str:
        client = self._sdk()
        content = prompt
        if images:
            content = [{"type": "image", "source": {"type": "base64", "media_type": "image/png",
                                                     "data": base64.b64encode(i).decode()}}
                       for i in images] + [{"type": "text", "text": prompt}]
        if json_mode:
            system += "\nRespond with a single JSON object and nothing else."
        params = {
            "model": self.model,
            # Thinking counts toward max_tokens on current models, so leave plenty of room.
            "max_tokens": 64000,
            "system": system,
            "messages": [{"role": "user", "content": content}],
            "output_config": {"effort": self.effort},
        }

        def run():
            if self.model in _FALLBACK_MODELS:
                stream = client.beta.messages.stream(
                    **params, betas=["server-side-fallback-2026-07-01"], fallbacks="default")
            else:
                stream = client.messages.stream(**params)
            with stream as s:
                for _ in s.text_stream:
                    if should_stop and should_stop():
                        raise Cancelled()
                return s.get_final_message()

        try:
            message = self._call(run)
        except LLMError as exc:
            if "effort" not in str(exc) and "output_config" not in str(exc):
                raise
            params.pop("output_config")  # older Claude models have no effort setting
            message = self._call(run)
        if message.stop_reason == "refusal":
            raise LLMError("Claude declined this request. Try different papers or instructions.")
        return "".join(block.text for block in message.content if block.type == "text").strip()


# --- Internet search settings ------------------------------------------------------

SEARCH_ENGINES = {
    "auto": ("DuckDuckGo + Wikipedia (free, no key)", None),
    "brave": ("Brave Search API", "BRAVE_API_KEY"),
    "tavily": ("Tavily", "TAVILY_API_KEY"),
}


def search_settings() -> tuple[str, str]:
    """Return (engine, api key) for internet search."""
    saved = load_config().get("search", {})
    engine = saved.get("engine", "auto")
    if engine not in SEARCH_ENGINES:
        engine = "auto"
    env = SEARCH_ENGINES[engine][1]
    key = saved.get("keys", {}).get(engine) or (os.environ.get(env, "") if env else "")
    return engine, key


def save_search_settings(engine: str, api_key: str | None = None) -> None:
    if engine not in SEARCH_ENGINES:
        raise LLMError(f"Unknown search engine '{engine}'")
    config = load_config()
    search = config.setdefault("search", {})
    search["engine"] = engine
    if api_key is not None:
        keys = search.setdefault("keys", {})
        if api_key.strip():
            keys[engine] = api_key.strip()
        else:
            keys.pop(engine, None)
    path = config_path()
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(config, indent=2), encoding="utf-8")
    try:
        path.chmod(0o600)
    except OSError:
        pass
