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
        self.provider = provider or "gemini"
        self.model = model or ""
        self.memory_text = ""
        self.history: list[dict] = []
        self._model_index = 0

    @property
    def available(self) -> bool:
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
        if not self.api_key:
            return None
        self.history.append({"role": "user", "text": text})
        self.history = self.history[-12:]
        try:
            return self._gemini() if self.provider == "gemini" else self._openai_like()
        except Exception:
            return None

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
        if not text or not self.api_key:
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
        base = self.model if self.model.startswith("http") else "https://api.groq.com/openai/v1"
        base = base.rstrip("/")
        model = "llama-3.3-70b-versatile" if "groq" in base else "gpt-4o-mini"
        try:
            response = requests.post(
                f"{base}/chat/completions",
                headers={"Authorization": f"Bearer {self.api_key}", "Content-Type": "application/json"},
                json={
                    "model": model,
                    "messages": [{"role": "system", "content": SUMMARY_PROMPT},
                                 {"role": "user", "content": prompt}],
                    "temperature": 0.3,
                    "max_tokens": 600,
                },
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

    def _openai_like(self) -> Optional[str]:
        base = self.model if self.model.startswith("http") else "https://api.groq.com/openai/v1"
        base = base.rstrip("/")
        model = "llama-3.3-70b-versatile" if "groq" in base else "gpt-4o-mini"
        messages = [{"role": "system", "content": self._system()}]
        messages += [{"role": "user" if m["role"] == "user" else "assistant", "content": m["text"]}
                     for m in self.history]
        try:
            response = requests.post(
                f"{base}/chat/completions",
                headers={"Authorization": f"Bearer {self.api_key}", "Content-Type": "application/json"},
                json={"model": model, "messages": messages, "temperature": 0.75, "max_tokens": 500},
                timeout=30,
            )
        except requests.RequestException:
            return None
        if response.status_code != 200:
            return None
        try:
            reply = response.json()["choices"][0]["message"]["content"].strip()
        except (KeyError, IndexError):
            return None
        if reply:
            self.history.append({"role": "model", "text": reply})
        return reply
