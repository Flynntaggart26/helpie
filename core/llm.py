"""LLM brains: Gemini (free tier) or any OpenAI-compatible endpoint."""
from __future__ import annotations

from typing import Optional

import requests

GEMINI_URL = "https://generativelanguage.googleapis.com/v1beta/models/{model}:generateContent"
GEMINI_MODELS = ["gemini-flash-latest", "gemini-2.5-flash", "gemini-2.0-flash", "gemini-1.5-flash"]

SYSTEM_PROMPT = """You are Helpie, a desktop assistant living on the user's Windows computer.
Rules:
- Always answer in English. Keep it short and conversational, 1-3 sentences unless the user asks for detail.
- Your answers are read out loud. Avoid markdown, bullet lists, emoji and code blocks.
- Never invent facts. If you are unsure, say so.
- The user may speak Turkish. Understand it, but still answer in English.
- When the user asks you to do something on the computer, you may append ONE action line at the end:
  [[ACTION]] {"name": "action_name", "args": {...}}
- Available actions:
  open_app {"app": "chrome"}
  close_app {"app": "chrome"}
  web_search {"query": "...", "engine": "google"}   (engine may be "youtube")
  open_site {"name": "youtube"}
  open_url {"url": "https://..."}
  set_volume {"percent": 40}
  volume {"direction": "up"}                        (up, down, mute)
  set_brightness {"percent": 60}
  add_note {"text": "..."}
  type_text {"text": "..."}
  screenshot {}
  set_timer {"minutes": 5, "label": "..."}
  lock_screen {}
  calculate {"expression": "12*8"}
  weather {}
  battery {}
  system_info {}
  remember {"text": "..."}                          (save a lasting fact about the user)
  read_screen {}                                    (look at what is currently on screen)
  summarize_file {"query": "report"}                (summarise a document by name)
  briefing {}
  plan {"steps": ["open chrome", "search for cats"]} (up to 4 short commands, in order)
- The action line is silent: never mention it in your spoken answer.
- For multi-step requests use one plan action and do not add other actions.
- Only add an action when the user actually asks for one."""

VISION_PROMPT = """You look at a screenshot of the user's Windows desktop and describe it out loud.
- Answer in English, 2-4 short sentences, no markdown.
- Focus on the active window and anything the user asked about.
- If the user asks about an error, read the exact error text and explain it briefly.
- Never invent text that is not visible."""

SUMMARY_PROMPT = """You summarise documents for a desktop assistant whose answer is read out loud.
- Answer in English, 3-6 short sentences, plain prose, no markdown or lists.
- Start with the main point, then the most important details or numbers.
- Keep names, dates and figures accurate. Do not invent anything."""


class Brain:
    def __init__(self, api_key: str = "", provider: str = "gemini", model: str = "") -> None:
        self.api_key = (api_key or "").strip()
        self.provider = (provider or "gemini").strip().lower()
        self.model = model or ""
        self.ollama_url = "http://localhost:11434"
        self.ollama_model = "llama3.2"
        self.openai_url = ""
        self.openai_key = ""
        self.openai_model = ""
        self.last_error = ""
        self.memory_text = ""
        self.history: list[dict] = []
        self._model_index = 0

    def configure(self, cfg: dict) -> None:
        """Apply provider settings. The single source of truth for startup and refresh."""
        self.api_key = (cfg.get("api_key") or "").strip()
        self.provider = (cfg.get("provider") or "gemini").strip().lower()
        self.model = (cfg.get("model") or "").strip()
        self.ollama_url = (cfg.get("ollama_url") or "http://localhost:11434").strip()
        self.ollama_model = (cfg.get("ollama_model") or "llama3.2").strip()
        self.openai_url = (cfg.get("openai_url") or "").strip()
        self.openai_key = (cfg.get("openai_key") or "").strip()
        self.openai_model = (cfg.get("openai_model") or "").strip()

    @property
    def available(self) -> bool:
        if self.provider == "ollama":
            return bool(self.ollama_url and self.ollama_model)
        if self.provider == "openai":
            return bool(self.openai_url)
        return bool(self.api_key)

    def reset(self) -> None:
        self.history.clear()

    def _system(self) -> str:
        if self.memory_text:
            return f"{SYSTEM_PROMPT}\n\n{self.memory_text}"
        return SYSTEM_PROMPT

    def _models(self) -> list[str]:
        if self.provider == "gemini":
            return [m for m in ([self.model] if self.model else []) + GEMINI_MODELS if m]
        return [self.model or "llama-3.3-70b-versatile"]

    def chat(self, text: str) -> Optional[str]:
        self.last_error = ""
        if not self.available:
            self.last_error = self._not_ready_message()
            return None
        self.history.append({"role": "user", "text": text})
        self.history = self.history[-12:]
        try:
            if self.provider == "gemini":
                reply = self._gemini()
            elif self.provider == "ollama":
                reply = self._ollama()
            else:
                reply = self._openai_like()
        except Exception:
            reply = None
        if not reply:
            self.last_error = self._unreachable_message()
        return reply

    def _not_ready_message(self) -> str:
        if self.provider == "ollama":
            return ("Ollama is not configured. Add the server URL and model in "
                    "Settings -> AI Providers -> Ollama.")
        if self.provider == "openai":
            return ("The custom provider needs a base URL in "
                    "Settings -> AI Providers -> Custom OpenAI.")
        return ("Chat needs a Gemini API key. Add one in "
                "Settings -> AI Providers -> Gemini.")

    def _unreachable_message(self) -> str:
        if self.provider == "ollama":
            return (f"I could not reach Ollama at {self.ollama_url}. "
                    "Make sure the Ollama app is running.")
        if self.provider == "openai":
            return f"I could not reach the model endpoint at {self.openai_url}."
        return "I could not reach Gemini. Check your API key and your connection."

    def _gemini(self) -> Optional[str]:
        contents = [
            {"role": "user" if item["role"] == "user" else "model",
             "parts": [{"text": item["text"]}]}
            for item in self.history
        ]
        payload = {
            "system_instruction": {"parts": [{"text": self._system()}]},
            "contents": contents,
            "generationConfig": {"temperature": 0.75, "maxOutputTokens": 500},
        }
        reply = self._gemini_request(payload)
        if reply:
            self.history.append({"role": "model", "text": reply})
        return reply

    def _gemini_request(self, payload: dict) -> Optional[str]:
        """POST a payload to Gemini, trying the configured model and free fallbacks."""
        models = self._models()
        for index in range(len(models)):
            model = models[(self._model_index + index) % len(models)]
            try:
                response = requests.post(
                    GEMINI_URL.format(model=model),
                    headers={"x-goog-api-key": self.api_key, "Content-Type": "application/json"},
                    json=payload,
                    timeout=45,
                )
            except requests.RequestException:
                return None
            if response.status_code == 200:
                try:
                    parts = response.json()["candidates"][0]["content"]["parts"]
                except (KeyError, IndexError):
                    return None
                reply = "".join(part.get("text", "") for part in parts).strip()
                if reply:
                    self._model_index = (self._model_index + index) % len(models)
                    return reply
                return None
            if response.status_code not in (400, 403, 404, 429):
                return None
        return None

    def vision(self, prompt: str, image_bytes: bytes, mime: str = "image/png") -> Optional[str]:
        """Ask Gemini about a screenshot. Does not touch the chat history."""
        if not self.api_key or not image_bytes or self.provider != "gemini":
            return None
        import base64

        payload = {
            "system_instruction": {"parts": [{"text": VISION_PROMPT}]},
            "contents": [{
                "role": "user",
                "parts": [
                    {"text": prompt or "What is on my screen right now?"},
                    {"inline_data": {"mime_type": mime,
                                     "data": base64.b64encode(image_bytes).decode("ascii")}},
                ],
            }],
            "generationConfig": {"temperature": 0.4, "maxOutputTokens": 700},
        }
        return self._gemini_request(payload)

    def summarize(self, text: str, name: str = "") -> Optional[str]:
        """Summarise a document without polluting the conversation history."""
        text = (text or "").strip()
        if not text or not self.available:
            return None
        prompt = (f"Document name: {name or 'untitled'}\n"
                  f"Summarise it for the user.\n\n{text[:20000]}")
        if self.provider == "gemini":
            payload = {
                "system_instruction": {"parts": [{"text": SUMMARY_PROMPT}]},
                "contents": [{"role": "user", "parts": [{"text": prompt}]}],
                "generationConfig": {"temperature": 0.3, "maxOutputTokens": 600},
            }
            return self._gemini_request(payload)
        messages = [{"role": "system", "content": SUMMARY_PROMPT},
                    {"role": "user", "content": prompt}]
        if self.provider == "ollama":
            return self._ollama_post(messages, temperature=0.3)
        base = (self.openai_url or "").rstrip("/")
        if not base:
            return None
        return self._openai_post(base, messages, self._openai_model(base), temperature=0.3)

    def _openai_model(self, base: str) -> str:
        return self.openai_model or (
            "llama-3.3-70b-versatile" if "groq" in base else "gpt-4o-mini")

    def _openai_like(self) -> Optional[str]:
        base = (self.openai_url or "").rstrip("/")
        if not base:
            return None
        messages = [{"role": "system", "content": self._system()}]
        messages += [{"role": "user" if m["role"] == "user" else "assistant", "content": m["text"]}
                     for m in self.history]
        reply = self._openai_post(base, messages, self._openai_model(base))
        if reply:
            self.history.append({"role": "model", "text": reply})
        return reply

    def _openai_post(self, base: str, messages: list[dict], model: str,
                     temperature: float = 0.75) -> Optional[str]:
        headers = {"Content-Type": "application/json"}
        if self.openai_key:
            headers["Authorization"] = f"Bearer {self.openai_key}"
        try:
            response = requests.post(
                f"{base}/chat/completions",
                headers=headers,
                json={"model": model, "messages": messages,
                      "temperature": temperature, "max_tokens": 500},
                timeout=45,
            )
        except requests.RequestException:
            return None
        if response.status_code != 200:
            return None
        try:
            return response.json()["choices"][0]["message"]["content"].strip() or None
        except (KeyError, IndexError):
            return None

    def _ollama(self) -> Optional[str]:
        messages = [{"role": "system", "content": self._system()}]
        messages += [{"role": "user" if m["role"] == "user" else "assistant", "content": m["text"]}
                     for m in self.history]
        reply = self._ollama_post(messages)
        if reply:
            self.history.append({"role": "model", "text": reply})
        return reply

    def _ollama_post(self, messages: list[dict],
                     temperature: float = 0.75) -> Optional[str]:
        base = (self.ollama_url or "").rstrip("/")
        if not base:
            return None
        try:
            response = requests.post(
                f"{base}/api/chat",
                json={"model": self.ollama_model, "messages": messages,
                      "stream": False, "options": {"temperature": temperature}},
                timeout=90,
            )
        except requests.RequestException:
            return None
        if response.status_code != 200:
            return None
        try:
            return (response.json().get("message") or {}).get("content", "").strip() or None
        except (ValueError, AttributeError):
            return None
