"""
Sentinel AI — local LLM client (Ollama).

No cloud, no API keys, no quotas. Talks to a locally running Ollama
server (http://localhost:11434 by default). Two models are used:
- a text model (llama3.2:3b by default) for chat, drafting, flagging
- a vision model (moondream by default) for describing evidence photos

Setup: install Ollama (ollama.com), then:
    ollama pull llama3.2:3b
    ollama pull moondream
Ollama must be running (`ollama serve`, or it runs automatically after
install on most systems) before this app can use it.
"""
import base64
import requests

import db
import config


class OllamaUnavailable(Exception):
    pass


class LLMResult:
    def __init__(self, text: str, provider: str, model: str):
        self.text = text
        self.provider = provider
        self.key_label = model  # kept for compatibility with older callers


SYSTEM_CONTEXT = """You are the AI component inside Sentinel AI, a local investigation-support tool \
used by an authorized child-protection unit. Your outputs are always leads, \
drafts, flags, or summaries for a human investigator to review — never a \
final decision, verdict, or action taken on your own. Stay factual and \
grounded only in the information given to you in each request; do not \
invent details, names, or events. Do not speculate about guilt, identity, \
or intent beyond what the provided text supports. When discussing minors, \
stay at a pattern/behavioral level rather than reproducing explicit or \
graphic content. If asked to do something outside a legitimate \
investigative-support role (e.g. explicit content, real-world harmful \
instructions), decline that part and explain why, while still helping \
with the legitimate parts of the request."""


def _base_url() -> str:
    return db.get_setting("ollama_base_url", default=config.OLLAMA_DEFAULT_BASE_URL)


def _text_model() -> str:
    return db.get_setting("ollama_text_model", default=config.OLLAMA_DEFAULT_TEXT_MODEL)


def _vision_model() -> str:
    return db.get_setting("ollama_vision_model", default=config.OLLAMA_DEFAULT_VISION_MODEL)


def set_text_model(name: str) -> None:
    db.set_setting("ollama_text_model", name)


def set_vision_model(name: str) -> None:
    db.set_setting("ollama_vision_model", name)


def set_base_url(url: str) -> None:
    db.set_setting("ollama_base_url", url)


def get_base_url() -> str:
    return _base_url()


def get_text_model() -> str:
    return _text_model()


def get_vision_model() -> str:
    return _vision_model()


def is_reachable() -> bool:
    try:
        r = requests.get(f"{_base_url()}/api/tags", timeout=3)
        return r.status_code == 200
    except requests.RequestException:
        return False


def list_local_models() -> list:
    try:
        r = requests.get(f"{_base_url()}/api/tags", timeout=3)
        r.raise_for_status()
        return [m["name"] for m in r.json().get("models", [])]
    except requests.RequestException:
        return []


def test_connection():
    """Returns (ok: bool, message: str) — used by the Settings page."""
    if not is_reachable():
        return False, (
            f"Cannot reach Ollama at {_base_url()}. Make sure it's "
            "installed and running (`ollama serve`)."
        )
    models = list_local_models()
    if not models:
        return False, "Ollama is running but no models are pulled yet. Run e.g. `ollama pull llama3.2:3b`."
    return True, f"Connected. Models available: {', '.join(models)}"


def call_llm(prompt: str, image_bytes: bytes = None, json_mode: bool = False) -> LLMResult:
    """
    Calls the local text model, or the local vision model if image_bytes is
    given. Raises OllamaUnavailable with a clear message if Ollama isn't
    reachable or the model isn't pulled — callers already handle this
    gracefully (falling back to a plain summary, etc.), same as before.
    """
    if not is_reachable():
        raise OllamaUnavailable(
            "Ollama isn't reachable. Make sure `ollama serve` is running "
            "and you've pulled a model (e.g. `ollama pull llama3.2:3b`)."
        )

    model = _vision_model() if image_bytes else _text_model()
    payload = {"model": model, "prompt": prompt, "stream": False}
    if image_bytes:
        payload["images"] = [base64.b64encode(image_bytes).decode()]
    else:
        payload["system"] = SYSTEM_CONTEXT

    try:
        resp = requests.post(f"{_base_url()}/api/generate", json=payload, timeout=180)
        resp.raise_for_status()
        text = resp.json().get("response", "")
    except requests.RequestException as e:
        raise OllamaUnavailable(f"Ollama call failed (model '{model}'): {e}")

    if json_mode:
        text = _strip_json_fences(text)
    return LLMResult(text=text, provider="ollama", model=model)


def _strip_json_fences(text: str) -> str:
    t = text.strip()
    if t.startswith("```"):
        t = t.split("\n", 1)[1] if "\n" in t else t
        if t.endswith("```"):
            t = t.rsplit("```", 1)[0]
        elif "```" in t:
            t = t.split("```")[0]
    return t.strip()
