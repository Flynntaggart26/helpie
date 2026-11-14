"""Read documents (PDF, Word, PowerPoint, plain text) and summarise them."""
from __future__ import annotations

import html
import re
import zipfile
from pathlib import Path
from typing import Optional

import actions

MAX_CHARS = 24000
DOC_SUFFIXES = {".pdf", ".docx", ".docm", ".pptx", ".pptm", ".txt", ".md",
                ".csv", ".json", ".rtf", ".log", ".py", ".html"}


def _pdf_text(path: Path) -> str:
    reader = None
    try:
        from pypdf import PdfReader

        reader = PdfReader(str(path))
    except Exception:
        try:
            from PyPDF2 import PdfReader  # type: ignore

            reader = PdfReader(str(path))
        except Exception:
            return ""
    pages: list[str] = []
    try:
        for page in reader.pages[:40]:
            pages.append(page.extract_text() or "")
    except Exception:
        pass
    return "\n".join(pages)


def _zip_xml_text(path: Path, folder: str, pattern: str) -> str:
    chunks: list[str] = []
    try:
        with zipfile.ZipFile(path) as archive:
            names = sorted(name for name in archive.namelist()
                           if name.startswith(folder) and re.search(pattern, name))
            for name in names[:60]:
                try:
                    xml = archive.read(name).decode("utf-8", "ignore")
                except Exception:
                    continue
                xml = re.sub(r"</w:p>|</a:p>|</w:tr>", "\n", xml)
                xml = re.sub(r"<[^>]+>", " ", xml)
                chunks.append(html.unescape(xml))
    except (zipfile.BadZipFile, OSError):
        return ""
    return "\n".join(chunks)


def extract_text(path: Path) -> str:
    suffix = path.suffix.lower()
    if suffix == ".pdf":
        text = _pdf_text(path)
    elif suffix in (".docx", ".docm"):
        text = _zip_xml_text(path, "word/", r"document\.xml$")
    elif suffix in (".pptx", ".pptm"):
        text = _zip_xml_text(path, "ppt/slides/", r"slide\d+\.xml$")
    else:
        try:
            raw = path.read_bytes()
        except OSError:
            return ""
        if b"\x00" in raw[:2048]:
            return ""
        text = raw.decode("utf-8", "ignore")
    text = text.replace("\r", "\n")
    text = re.sub(r"[ \t]+", " ", text)
    text = re.sub(r"\n\s*\n+", "\n", text)
    return text.strip()[:MAX_CHARS]


def _extractive(text: str, sentences: int = 4) -> str:
    flat = re.sub(r"\s+", " ", text).strip()
    parts = re.split(r"(?<=[.!?])\s+", flat)
    picked = [part.strip() for part in parts if len(part.strip()) > 20][:sentences]
    if not picked:
        picked = [flat[:400]]
    words = len(re.findall(r"\w+", flat))
    return " ".join(picked) + f" (about {words} words)"


def _resolve(query: str) -> Optional[Path]:
    candidate = Path(query).expanduser()
    if candidate.is_file():
        return candidate
    return actions.find_file(query, DOC_SUFFIXES)


def summarize(query: str, llm=None) -> str:
    query = (query or "").strip()
    if not query:
        return "Which document should I summarise?"
    path = _resolve(query)
    if not path:
        return f"I could not find a document called {query}."
    text = extract_text(path)
    if not text.strip():
        return f"I could not read any text from {path.name}."
    if llm is not None and getattr(llm, "available", False):
        answer = llm.summarize(text, path.name)
        if answer:
            return answer
    return f"Here is a quick summary of {path.name}: {_extractive(text)}"
