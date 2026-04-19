import os
import re
import threading
from datetime import datetime
from pathlib import Path


def _slug(text: str) -> str:
    t = (text or "").strip().lower()
    t = re.sub(r"[^a-z0-9_]+", "_", t)
    t = re.sub(r"_+", "_", t).strip("_")
    return t or "unknown"


class ObsidianMemory:
    def __init__(self):
        self.enabled = os.getenv("OBSIDIAN_AUTO_MEMORY", "1") == "1"
        base_dir = os.getenv("OBSIDIAN_MEMORY_BASE", "IARA").strip() or "IARA"
        vault_dir = os.getenv("OBSIDIAN_VAULT_DIR", ".").strip() or "."
        self.root = Path(vault_dir).expanduser().resolve() / base_dir
        self.sessions_dir = self.root / "Sessions"
        self.people_dir = self.root / "People"
        self.learnings_dir = self.root / "Learnings"
        self._lock = threading.Lock()
        self._ensure_dirs()

    def _ensure_dirs(self):
        if not self.enabled:
            return
        self.sessions_dir.mkdir(parents=True, exist_ok=True)
        self.people_dir.mkdir(parents=True, exist_ok=True)
        self.learnings_dir.mkdir(parents=True, exist_ok=True)

    def _append_line(self, path: Path, line: str):
        with path.open("a", encoding="utf-8") as f:
            f.write(line.rstrip() + "\n")

    def _ensure_header(self, path: Path, title: str, type_: str, tags: str):
        if path.exists():
            return
        header = (
            "---\n"
            f"type: {type_}\n"
            f"title: {title}\n"
            f"updated: {datetime.now().strftime('%Y-%m-%d')}\n"
            f"tags: [{tags}]\n"
            "---\n\n"
        )
        path.write_text(header, encoding="utf-8")

    def _session_path(self) -> Path:
        date_str = datetime.now().strftime("%Y-%m-%d")
        return self.sessions_dir / f"mc_session_{date_str}.md"

    def _person_path(self, user: str) -> Path:
        return self.people_dir / f"mc_user_{_slug(user)}.md"

    def _learning_path(self, action: str) -> Path:
        return self.learnings_dir / f"mc_action_{_slug(action)}.md"

    def record_minecraft_event(
        self,
        *,
        user: str,
        command: str,
        status: str,
        summary: str,
        action: str = "unknown",
    ):
        if not self.enabled:
            return
        with self._lock:
            now = datetime.now()
            ts = now.strftime("%H:%M:%S")
            date = now.strftime("%Y-%m-%d")
            user = (user or "desconhecido").strip() or "desconhecido"
            action = (action or "unknown").strip() or "unknown"
            status = (status or "info").strip() or "info"
            command = (command or "").strip()
            summary = (summary or "").strip()

            person_note = self._person_path(user)
            learning_note = self._learning_path(action)
            session_note = self._session_path()

            self._ensure_header(person_note, f"Usuario Minecraft: {user}", "person", "minecraft,person")
            self._ensure_header(learning_note, f"Acao Minecraft: {action}", "learning", "minecraft,learning")
            self._ensure_header(session_note, f"Sessao Minecraft {date}", "session", "minecraft,session")

            person_link = person_note.stem
            learning_link = learning_note.stem

            self._append_line(
                session_note,
                f"- {ts} | [[{person_link}]] | acao=[[{learning_link}]] | status={status} | cmd=`{command}` | {summary}",
            )
            self._append_line(
                person_note,
                f"- {date} {ts} | acao=[[{learning_link}]] | status={status} | cmd=`{command}` | {summary}",
            )
            self._append_line(
                learning_note,
                f"- {date} {ts} | user=[[{person_link}]] | status={status} | cmd=`{command}` | {summary}",
            )

            # heuristica simples de aprendizado
            low = summary.lower()
            if "sem receita" in low or "materiais" in low:
                self._append_line(
                    learning_note,
                    "- insight: faltou receita/material; verificar pre-requisitos e craft intermediario.",
                )
            if "nao consegui aproximar" in low or "bloco nao encontrado" in low:
                self._append_line(
                    learning_note,
                    "- insight: alvo distante/inexistente; considerar exploracao/posicionamento antes da acao.",
                )
