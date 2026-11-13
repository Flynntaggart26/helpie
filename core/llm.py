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
- The action line is silent: never mention it in your spoken answer.
- Only add an action when the user actually asks for one."""


class Brain:
    def __init__(self, api_key: str = "", provider: str = "gemini", model: str = "") -> None:
        self.api_key = (api_key or "").strip()
        self.provider = provider or "gemini"
        self.model = model or ""
        self.history: list[dict] = []
        self._model_index = 0

    @property
    def available(self) -> bool:
        return bool(self.api_key)

    def reset(self) -> None:
        self.history.clear()

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
            "system_instruction": {"parts": [{"text": SYSTEM_PROMPT}]},
            "contents": contents,
            "generationConfig": {"temperature": 0.75, "maxOutputTokens": 500},
        }
        models = self._models()
        for index in range(len(models)):
            model = models[(self._model_index + index) % len(models)]
            try:
                response = requests.post(
                    GEMINI_URL.format(model=model),
                    headers={"x-goog-api-key": self.api_key, "Content-Type": "application/json"},
                    json=payload,
                    timeout=30,
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
                    self.history.append({"role": "model", "text": reply})
                    return reply
                return None
            if response.status_code not in (400, 403, 404, 429):
                return None
        return None

    def _openai_like(self) -> Optional[str]:
        base = self.model if self.model.startswith("http") else "https://api.groq.com/openai/v1"
        base = base.rstrip("/")
        model = "llama-3.3-70b-versatile" if "groq" in base else "gpt-4o-mini"
        messages = [{"role": "system", "content": SYSTEM_PROMPT}]
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
