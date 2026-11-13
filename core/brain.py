"""The brain: fast rule engine first, then the LLM."""
from __future__ import annotations

import datetime as dt
import json
import random
import re
from typing import Callable, Optional

import actions
from llm import Brain as LlmBrain

GREETINGS = [
    "Hey! I'm here. What do you need?",
    "Hi there. Listening.",
    "Hello! What can I do for you?",
]

HELP_TEXT = (
    "I can open and close apps, set volume and brightness, search the web, take notes, "
    "set reminders, do math, take screenshots, open files and lock the computer. "
    "Ask me anything else too and I will answer."
)

INTRO = (
    "I'm Helpie, your desktop assistant. I listen for your voice, run tasks on this "
    "computer and answer your questions out loud."
)

OPEN_VERBS = ("open", "launch", "start", "run", "aç", "başlat", "çalıştır")
CLOSE_VERBS = ("close", "quit", "kill", "stop", "kapat", "sonlandır")

FILLERS = re.compile(
    r"\b(helpie|please|just|hey|now|for me|can you|could you|would you|"
    r"lütfen|hemen|şimdi|bana|benim için|bir|acaba)\b", re.I
)

CONFIRM_YES = ("yes", "yeah", "yep", "sure", "do it", "confirm", "ok", "okay",
               "evet", "onayla", "onaylıyorum", "tamam", "doğru")
CONFIRM_NO = ("no", "nope", "cancel", "stop", "never mind", "don't",
              "hayır", "vazgeç", "iptal", "dur", "yok")


def _norm(text: str) -> str:
    t = (text or "").lower().strip()
    t = t.replace("’", "'").replace("`", "'").replace("´", "'")
    return re.sub(r"\s+", " ", t)


def _clean_query(text: str) -> str:
    q = text
    q = re.sub(r"^(search|look up|find|google)\s+", "", q)
    q = re.sub(r"^(on |in )?(the )?(web|internet|google|youtube)\s+(for\s+)?", "", q)
    q = re.sub(r"\b(the web|the internet|internette|you ?tube'?da)\b", " ", q)
    q = re.sub(r"\b(com|net|org|from|please|for me|lütfen|bana|bir)\b", " ", q)
    q = re.sub(r"\b(search|look up|find|ara|araştır|bul|bak|bilgi ver|tell me)\b", " ", q)
    q = re.sub(r"\b(about|hakkında|ile ilgili)\b", " ", q)
    return re.sub(r"\s+", " ", q).strip(" ?!.,'\"")


class Brain:
    """Understands text, performs the action, returns something to say."""

    def __init__(
        self,
        cfg: dict,
        on_speak: Optional[Callable[[str], None]] = None,
        on_quit: Optional[Callable[[], None]] = None,
        on_event: Optional[Callable[[dict], None]] = None,
    ) -> None:
        self.cfg = cfg
        self.on_speak = on_speak or (lambda _text: None)
        self.on_quit = on_quit or (lambda: None)
        self.on_event = on_event or (lambda _event: None)
        self.llm = LlmBrain(cfg.get("api_key", ""), cfg.get("provider", "gemini"), cfg.get("model", ""))
        self.pending: Optional[tuple[str, dict]] = None

    def refresh(self, cfg: dict) -> None:
        self.cfg = cfg
        self.llm.api_key = (cfg.get("api_key") or "").strip()
        self.llm.provider = cfg.get("provider") or "gemini"
        self.llm.model = cfg.get("model") or ""

    # ------------------------------------------------------------------ #
    def handle(self, text: str) -> str:
        raw = (text or "").strip()
        if not raw:
            return "I didn't hear anything. Try again?"
        t = _norm(raw)
        alt = re.sub(r"\s+", " ", FILLERS.sub(" ", t)).strip()

        if self.pending:
            pending, self.pending = self.pending, None
            if any(word in t for word in CONFIRM_YES):
                return self._dispatch(*pending)
            if any(word in t for word in CONFIRM_NO):
                return "Okay, cancelled."
            self.pending = pending
            return "I need a yes or a no to continue."

        if re.search(r"\b(quit|exit|goodbye|good bye|see you|shut yourself down|"
                     r"kendini kapat|görüşürüz|helpie kapan)\b", t):
            self.on_quit()
            return "See you! Open Helpie again whenever you need me."

        if re.fullmatch(r"(hi|hello|hey|yo|good morning|good afternoon|good evening|"
                        r"merhaba|selam|selamlar|günaydın)[!. ]*", t):
            return random.choice(GREETINGS)
        if re.search(r"\b(who are you|your name|what are you|introduce yourself|"
                     r"sen kimsin|adın ne|kimsin)\b", t):
            return INTRO
        if re.search(r"\b(what can you do|help me|show commands|commands|abilities|"
                     r"ne yapabilirsin|yardım)\b", t):
            return HELP_TEXT

        if re.search(r"\b(what time|the time|time is it|saat kaç)\b", t):
            return actions.now_time()
        if re.search(r"\b(what day|the date|today's date|which day|tarih|hangi gün)\b", t):
            return actions.now_date()

        if re.search(r"\b(weather|temperature|forecast|hava durumu|hava nasıl)\b", t):
            return actions.weather(self.cfg.get("city", ""))

        if re.search(r"\bbattery\b|\bcharge level\b|\bpil\b", t) and \
                re.search(r"(status|level|percent|how much|durum|kaç)", t):
            return actions.battery()
        if re.search(r"\b(cpu|ram|memory|system)\b", t) and \
                re.search(r"(usage|load|status|how much|kullanım|durum)", t):
            return actions.system_info()

        # volume
        match = re.search(r"(?:volume|ses)\s*(?:to|at|seviyesini|seviyesi)?\s*(?:%|yüzde)?\s*(\d{1,3})", t)
        if match:
            return actions.set_volume(int(match.group(1)))
        if re.search(r"\b(mute|sessize al|sustur|sessiz)\b", t):
            return actions.volume("mute")
        if re.search(r"\b(unmute|turn (the )?volume up|volume up|louder|sesi aç|sesi artır)\b", t):
            return actions.volume("up")
        if re.search(r"\b(turn (the )?volume down|volume down|quieter|lower the volume|sesi kıs|sesi azalt)\b", t):
            return actions.volume("down")

        # brightness
        match = re.search(r"brightness\s*(?:to|at)?\s*(\d{1,3})", t)
        if match:
            return actions.set_brightness(int(match.group(1)))
        if re.search(r"(increase|raise|up)\s+(the\s+)?brightness|parlakl[ıi][ğg][ıi]\s*(artır|yükselt)", t):
            return actions.brightness("up")
        if re.search(r"(decrease|lower|reduce|dim)\s+(the\s+)?(brightness|screen)|parlakl[ıi][ğg][ıi]\s*(kıs|azalt)", t):
            return actions.brightness("down")

        # media
        if re.search(r"\b(pause|stop) (the )?(music|video|playback)\b|\bmüziği durdur\b", t):
            return actions.media("pause")
        if re.search(r"\b(play|resume) (the )?(music|video)\b|\bmüziği (çal|oynat)\b", t):
            return actions.media("play")
        if re.search(r"\b(next (track|song))|sonraki (şarkı|parça)\b", t):
            return actions.media("next")
        if re.search(r"\b(previous|last) (track|song)|önceki (şarkı|parça)\b", t):
            return actions.media("prev")

        if re.search(r"\b(screenshot|screen shot|screen capture|capture the screen|ekran görüntüsü)\b", t):
            return actions.screenshot()

        if re.search(r"\b(lock (the )?(screen|pc|computer)|kilitle)\b", t) and "shut" not in t:
            return actions.lock_screen()

        if re.search(r"\b(shut ?down|turn off (the )?(pc|computer)|power off|bilgisayarı kapat)\b", t):
            self.pending = ("power", {"mode": "shutdown"})
            return "I am about to shut the computer down. Are you sure?"
        if re.search(r"\b(restart|reboot|yeniden başlat)\b", t):
            self.pending = ("power", {"mode": "restart"})
            return "I am about to restart the computer. Are you sure?"
        if re.search(r"\b(sleep|suspend)\b", t) and re.search(r"(pc|computer|bilgisayar)", t):
            self.pending = ("power", {"mode": "sleep"})
            return "I am about to put the computer to sleep. Are you sure?"
        if re.search(r"\b(cancel (the )?(shutdown|restart)|kapanmayı iptal)\b", t):
            return actions.cancel_shutdown()

        if re.search(r"recycle bin|geri dönüşüm", t) and re.search(r"(empty|clear|boşalt|temizle)", t):
            return actions.empty_recycle_bin()

        # notes
        match = re.search(r"(?:take a note|make a note|note that|add a note|not al)[:\s]+(.+)$", t)
        if match:
            return actions.add_note(match.group(1).strip())
        if re.search(r"\b(read|show|list)\b.*\bnotes\b|\bnotlarımı (oku|göster)\b", t):
            return actions.read_notes()
        if re.search(r"\b(clear|delete|erase)\b.*\bnotes\b|\bnotlarımı sil\b", t):
            return actions.clear_notes()

        # timers
        match = re.search(
            r"(\d+(?:\.\d+)?)\s*(seconds?|secs?|minutes?|mins?|hours?|saniye|dakika|saat)\b(.*)", t)
        if match and re.search(r"(remind|reminder|timer|alarm|hatırlat|kur)", t):
            amount = float(match.group(1))
            unit = match.group(2)
            factor = 1 if unit.startswith(("sec", "saniye")) else 60 if unit.startswith(("min", "dakika")) else 3600
            label = match.group(3)
            label = re.sub(r"^(to|için|sonra)\s+", "", label.strip())
            label = re.sub(r"\b(remind|reminder|timer|alarm|hatırlat|kur|set|me)\b", " ", label)
            return actions.set_timer(amount * factor, re.sub(r"\s+", " ", label).strip(), self.on_speak)

        if re.search(r"\b(calculate|compute|how much is|what is|what's|hesapla|kaç eder)\b", t) and re.search(r"\d", t):
            return actions.calculate(t)
        if re.fullmatch(r"[\d\s+\-*/().,%]+", t):
            return actions.calculate(t)

        match = re.search(r"^(?:type|write|yaz)[:\s]+(.+)$", t)
        if match:
            return actions.type_text(match.group(1))

        # files
        match = re.search(r"(?:open|find|aç)\s+(?:the\s+)?(?:file\s+)?(.+?)\s*(?:file|dosyasını|dosyayı)?$", t)
        if match and re.search(r"(file|dosya)", t):
            return actions.open_file(re.sub(r"\bfile\b|\bdosya\b", "", match.group(1)).strip())
        match = re.search(r"open\s+(?:the\s+)?(desktop|downloads|documents|pictures|music|videos)"
                          r"|(masaüstü|indirilenler|belgeler|resimler|müzik|videolar)\s*(?:klasörünü|klasörü)?\s*aç", t)
        if match:
            return actions.open_folder(match.group(1) or match.group(2))

        site_key = next((s for s in actions.SITES if s in t), None)
        if site_key and re.search(r"\b(open|go to|launch|aç|git|gir)\b", t):
            return actions.open_site(site_key)

        app_key = actions.resolve_app(alt)
        if app_key and any(verb in t for verb in CLOSE_VERBS):
            return actions.close_app(app_key)
        if app_key and any(verb in t for verb in OPEN_VERBS):
            return actions.open_app(app_key)
        match = re.search(r"^(?:open|launch|start|run|aç|başlat|çalıştır)\s+(.+)$", alt)
        if match and not re.search(r"(file|dosya|folder|klasör|volume|ses|brightness|parlaklık)", match.group(1)):
            return actions.open_app(match.group(1))

        # search
        match = re.search(r"^(?:youtube|yt)\s+(.{2,})$", t)
        if match:
            return actions.web_search(match.group(1), "youtube")
        if re.search(r"\b(search|look up|google|ara|araştır)\b", t) or re.search(r"(hakkında|about)", t):
            engine = "youtube" if "youtube" in t else "google"
            query = _clean_query(t)
            if len(query) > 1:
                return actions.web_search(query, engine)

        match = re.search(r"(https?://\S+|www\.\S+)", t)
        if match:
            return actions.open_url(match.group(1))

        if self.llm.available:
            reply = self.llm.chat(raw)
            if reply:
                cleaned, action = self._extract_action(reply)
                if action:
                    spoken = self._dispatch(*action)
                    return f"{cleaned} {spoken}".strip() if cleaned else spoken
                return cleaned or reply

        if re.search(r"\b(open|close|set|start|stop|turn|delete|show)\b", t):
            return "Sorry, I did not understand that. Could you rephrase it?"
        if not self.llm.available:
            return ("I can't answer that yet. Add a free Gemini API key in Settings and "
                    "I will be able to chat about anything.")
        return "Sorry, something went wrong while answering."

    # ------------------------------------------------------------------ #
    @staticmethod
    def _extract_action(reply: str) -> tuple[str, Optional[tuple[str, dict]]]:
        match = re.search(r"\[\[ACTION\]\]\s*(\{.*?\})\s*$", reply, re.S)
        if not match:
            return reply.strip(), None
        try:
            payload = json.loads(match.group(1))
            name = str(payload.get("name", "")).strip()
            if name:
                return reply[: match.start()].strip(), (name, payload.get("args") or {})
        except (json.JSONDecodeError, AttributeError):
            pass
        return reply.strip(), None

    def _dispatch(self, name: str, args: dict) -> str:
        try:
            minutes = float(args.get("minutes", 0) or 0)
        except (TypeError, ValueError):
            minutes = 0.0

        handlers: dict[str, Callable[[dict], str]] = {
            "open_app": lambda a: actions.open_app(str(a.get("app", ""))),
            "close_app": lambda a: actions.close_app(str(a.get("app", ""))),
            "web_search": lambda a: actions.web_search(str(a.get("query", "")), str(a.get("engine", "google"))),
            "open_site": lambda a: actions.open_site(str(a.get("name", ""))),
            "open_url": lambda a: actions.open_url(str(a.get("url", ""))),
            "set_volume": lambda a: actions.set_volume(float(a.get("percent", 50))),
            "volume": lambda a: actions.volume(str(a.get("direction", "up"))),
            "set_brightness": lambda a: actions.set_brightness(int(a.get("percent", 50))),
            "add_note": lambda a: actions.add_note(str(a.get("text", ""))),
            "type_text": lambda a: actions.type_text(str(a.get("text", ""))),
            "screenshot": lambda a: actions.screenshot(),
            "set_timer": lambda a: actions.set_timer(minutes * 60, str(a.get("label", "")), self.on_speak),
            "lock_screen": lambda a: actions.lock_screen(),
            "calculate": lambda a: actions.calculate(str(a.get("expression", ""))),
            "weather": lambda a: actions.weather(self.cfg.get("city", "")),
            "battery": lambda a: actions.battery(),
            "system_info": lambda a: actions.system_info(),
            "power": lambda a: self._power(str(a.get("mode", "shutdown"))),
        }
        handler = handlers.get(name)
        if not handler:
            return ""
        try:
            return handler(args)
        except Exception:
            return "Something went wrong while doing that."

    @staticmethod
    def _power(mode: str) -> str:
        if mode == "restart":
            return actions.shutdown_pc(restart=True)
        if mode == "sleep":
            return actions.sleep_pc()
        return actions.shutdown_pc()

    def summary(self) -> str:
        now = dt.datetime.now()
        who = self.cfg.get("user_name") or "there"
        return (f"Hi {who}. It is {now.hour:02d}:{now.minute:02d}. "
                "Press Control H any time you want to talk, or type below.")
