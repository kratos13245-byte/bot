import os
import re
from dataclasses import dataclass
from pathlib import Path
from typing import List


@dataclass
class ProcedureNote:
    path: Path
    id_: str
    title: str
    tags: List[str]
    body: str


def _default_dir() -> Path:
    raw = os.getenv("MC_PROCEDURES_DIR", "").strip()
    if raw:
        return Path(raw).expanduser()
    return Path("IARA") / "Procedures"


def _extract_frontmatter(text: str):
    if not text.startswith("---"):
        return {}, text
    m = re.match(r"^---\n(.*?)\n---\n?(.*)$", text, flags=re.DOTALL)
    if not m:
        return {}, text
    raw_fm, body = m.group(1), m.group(2)
    data = {}
    for line in raw_fm.splitlines():
        if ":" not in line:
            continue
        k, v = line.split(":", 1)
        key = k.strip().lower()
        val = v.strip()
        if key == "tags":
            tags = re.findall(r"[\w\-]+", val.lower())
            data[key] = tags
        else:
            data[key] = val.strip('"').strip("'")
    return data, body


def _read_note(path: Path):
    try:
        text = path.read_text(encoding="utf-8")
    except Exception:
        return None
    fm, body = _extract_frontmatter(text)
    note = ProcedureNote(
        path=path,
        id_=str(fm.get("id", path.stem)).strip().lower(),
        title=str(fm.get("title", path.stem)).strip(),
        tags=[str(t).strip().lower() for t in fm.get("tags", []) if str(t).strip()],
        body=body.strip(),
    )
    return note


def _tokenize(text: str):
    t = (text or "").lower()
    return set(re.findall(r"[a-z0-9_]{2,}", t))


def _score(note: ProcedureNote, query_tokens: set[str]):
    note_tokens = _tokenize(f"{note.id_} {note.title} {' '.join(note.tags)} {note.body[:2000]}")
    overlap = query_tokens.intersection(note_tokens)
    score = len(overlap)
    if query_tokens and note.id_ in query_tokens:
        score += 2
    if query_tokens and any(t in note.title.lower() for t in query_tokens):
        score += 1
    return score


def _load_notes() -> List[ProcedureNote]:
    base = _default_dir()
    if not base.exists() or not base.is_dir():
        return []
    notes = []
    for p in sorted(base.glob("*.md")):
        note = _read_note(p)
        if note:
            notes.append(note)
    return notes


def buscar_procedures(query: str, top_k: int = 2) -> List[ProcedureNote]:
    notes = _load_notes()
    if not notes:
        return []
    q = _tokenize(query)
    ranked = sorted(
        notes,
        key=lambda n: _score(n, q),
        reverse=True,
    )
    ranked = [n for n in ranked if _score(n, q) > 0]
    return ranked[:top_k]


def montar_contexto_procedural(query: str, top_k: int = 2) -> str:
    notas = buscar_procedures(query, top_k=top_k)
    return montar_contexto_procedural_de_notas(notas, top_k=top_k)


def montar_contexto_procedural_de_notas(notas: List[ProcedureNote], top_k: int = 2) -> str:
    notas = (notas or [])[: max(1, int(top_k or 1))]
    if not notas:
        return ""
    chunks = []
    for i, n in enumerate(notas, start=1):
        resumo = n.body[:1400].strip()
        chunks.append(
            f"[Procedimento {i}] id={n.id_} | titulo={n.title}\n"
            f"tags={', '.join(n.tags) if n.tags else '-'}\n"
            f"{resumo}"
        )
    return "\n\n".join(chunks)
