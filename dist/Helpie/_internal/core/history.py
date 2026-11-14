"""Chat history saved to data/history.json.

A chat is {id, title, created, updated, messages:[{role, text, time}]}.
The newest chat is what the UI restores on launch.
"""
from __future__ import annotations

import datetime as dt
import json
import threading
import uuid
from typing import Optional

import config

PATH = config.DATA_DIR / "history.json"
MAX_CHATS = 60
MAX_MESSAGES = 400


def _now() -> str:
    return dt.datetime.now().strftime("%Y-%m-%d %H:%M")


class History:
    def __init__(self) -> None:
        self._lock = threading.RLock()
        self.chats: list[dict] = self._load()
        self.current: Optional[str] = self.chats[0]["id"] if self.chats else None

    # -- storage -------------------------------------------------------- #
    def _load(self) -> list[dict]:
        try:
            raw = json.loads(PATH.read_text(encoding="utf-8"))
        except (OSError, json.JSONDecodeError):
            return []
        chats = []
        for chat in raw if isinstance(raw, list) else []:
            if not isinstance(chat, dict):
                continue
            messages = [
                {"role": str(m.get("role", "assistant")), "text": str(m.get("text", "")),
                 "time": str(m.get("time", ""))}
                for m in chat.get("messages", []) if isinstance(m, dict) and m.get("text")
            ]
            if not messages:
                continue
            chats.append({
                "id": str(chat.get("id") or uuid.uuid4().hex[:10]),
                "title": str(chat.get("title") or "Chat"),
                "created": str(chat.get("created") or _now()),
                "updated": str(chat.get("updated") or _now()),
                "messages": messages,
            })
        return chats[:MAX_CHATS]

    def _save(self) -> None:
        try:
            config.DATA_DIR.mkdir(parents=True, exist_ok=True)
            PATH.write_text(json.dumps(self.chats, ensure_ascii=False, indent=2), encoding="utf-8")
        except OSError:
            pass

    # -- api ------------------------------------------------------------ #
    def new_chat(self) -> dict:
        with self._lock:
            chat = {
                "id": uuid.uuid4().hex[:10],
                "title": "New chat",
                "created": _now(),
                "updated": _now(),
                "messages": [],
            }
            self.chats.insert(0, chat)
            self.chats = self.chats[:MAX_CHATS]
            self.current = chat["id"]
            self._save()
            return dict(chat)

    def current_chat(self) -> dict:
        with self._lock:
            if not self.current:
                return self.new_chat_locked()
            for chat in self.chats:
                if chat["id"] == self.current:
                    return chat
            return self.new_chat_locked()

    def new_chat_locked(self) -> dict:
        chat = {
            "id": uuid.uuid4().hex[:10],
            "title": "New chat",
            "created": _now(),
            "updated": _now(),
            "messages": [],
        }
        self.chats.insert(0, chat)
        self.current = chat["id"]
        self._save()
        return chat

    def append(self, role: str, text: str) -> None:
        text = (text or "").strip()
        if not text:
            return
        with self._lock:
            chat = self.current_chat()
            chat["messages"].append({"role": role, "text": text, "time": _now()})
            chat["messages"] = chat["messages"][-MAX_MESSAGES:]
            chat["updated"] = _now()
            if chat["title"] in ("", "New chat") and role == "user":
                title = " ".join(text.split())
                chat["title"] = (title[:38] + "…") if len(title) > 38 else title
            self.chats.sort(key=lambda item: item.get("updated", ""), reverse=True)
            self._save()

    def list_chats(self) -> list[dict]:
        with self._lock:
            return [
                {"id": chat["id"], "title": chat["title"], "updated": chat["updated"],
                 "created": chat["created"], "count": len(chat["messages"]),
                 "current": chat["id"] == self.current}
                for chat in sorted(self.chats, key=lambda item: item.get("updated", ""), reverse=True)
            ]

    def get(self, chat_id: str) -> Optional[dict]:
        with self._lock:
            for chat in self.chats:
                if chat["id"] == chat_id:
                    return dict(chat)
        return None

    def select(self, chat_id: str) -> Optional[dict]:
        with self._lock:
            for chat in self.chats:
                if chat["id"] == chat_id:
                    self.current = chat_id
                    return dict(chat)
        return None

    def delete(self, chat_id: str) -> bool:
        with self._lock:
            before = len(self.chats)
            self.chats = [chat for chat in self.chats if chat["id"] != chat_id]
            if len(self.chats) == before:
                return False
            if self.current == chat_id:
                self.current = self.chats[0]["id"] if self.chats else None
            self._save()
            return True
