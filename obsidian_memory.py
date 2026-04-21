import os
import re
import json
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
        self.concepts_dir = self.root / "Concepts"
        self.reviews_dir = self.root / "ActionReviews"
        self.state_file = self.root / ".learning_state.json"
        self._lock = threading.Lock()
        self._state = {"actions": {}, "updated": ""}
        self._ensure_dirs()
        self._load_state()

    def _ensure_dirs(self):
        if not self.enabled:
            return
        self.sessions_dir.mkdir(parents=True, exist_ok=True)
        self.people_dir.mkdir(parents=True, exist_ok=True)
        self.learnings_dir.mkdir(parents=True, exist_ok=True)
        self.concepts_dir.mkdir(parents=True, exist_ok=True)
        self.reviews_dir.mkdir(parents=True, exist_ok=True)
        self._ensure_moc()

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

    def _ensure_moc(self):
        moc = self.root / "Minecraft_Learning_MOC.md"
        if moc.exists():
            return
        content = (
            "---\n"
            "type: moc\n"
            "title: Minecraft Learning MOC\n"
            f"updated: {datetime.now().strftime('%Y-%m-%d')}\n"
            "tags: [minecraft,moc]\n"
            "---\n\n"
            "# Minecraft Learning Hub\n\n"
            "- [[Sessions]]\n"
            "- [[People]]\n"
            "- [[Learnings]]\n"
            "- [[Concepts]]\n"
            "- [[ActionReviews]]\n"
        )
        moc.write_text(content, encoding="utf-8")

    def _session_path(self) -> Path:
        date_str = datetime.now().strftime("%Y-%m-%d")
        return self.sessions_dir / f"mc_session_{date_str}.md"

    def _person_path(self, user: str) -> Path:
        return self.people_dir / f"mc_user_{_slug(user)}.md"

    def _learning_path(self, action: str) -> Path:
        return self.learnings_dir / f"mc_action_{_slug(action)}.md"

    def _concept_path(self, concept: str) -> Path:
        return self.concepts_dir / f"mc_concept_{_slug(concept)}.md"

    def _review_path(self, action: str) -> Path:
        month = datetime.now().strftime("%Y-%m")
        return self.reviews_dir / f"mc_review_{_slug(action)}_{month}.md"

    def _load_state(self):
        if not self.enabled:
            return
        if not self.state_file.exists():
            return
        try:
            raw = json.loads(self.state_file.read_text(encoding="utf-8"))
            if isinstance(raw, dict):
                self._state = raw
                if "actions" not in self._state or not isinstance(self._state["actions"], dict):
                    self._state["actions"] = {}
        except Exception:
            self._state = {"actions": {}, "updated": ""}

    def _save_state(self):
        if not self.enabled:
            return
        self._state["updated"] = datetime.now().isoformat(timespec="seconds")
        self.state_file.write_text(
            json.dumps(self._state, ensure_ascii=False, indent=2),
            encoding="utf-8",
        )

    @staticmethod
    def _is_success(status: str) -> bool:
        return status in {"planner_ok", "command_ok"}

    @staticmethod
    def _is_failure(status: str) -> bool:
        return status in {"planner_error", "command_error", "planner_invalid"}

    def _extract_concepts(self, action: str, command: str, summary: str):
        text = f"{action} {command} {summary}".lower()
        tokens = re.findall(r"[a-z0-9_]{3,}", text)
        stop = {
            "para", "com", "sem", "que", "isso", "essa", "esse", "agora", "depois", "antes",
            "minecraft", "acao", "status", "user", "cmd", "vou", "fazer", "aqui", "quando",
            "planner", "command", "none", "true", "false",
        }

        concepts = []
        for t in tokens:
            if t in stop:
                continue
            if t.isdigit():
                continue
            concepts.append(t)

        hints = [
            "crafting_table",
            "craft",
            "planks",
            "wood",
            "mine",
            "ore",
            "coal",
            "iron",
            "diamond",
            "follow",
            "explore",
            "loot",
            "combat",
            "food",
            "flee",
            "stuck",
            "inventory",
            "drop",
            "place",
            "interact",
            "biome",
            "base",
        ]
        for h in hints:
            if h in text:
                concepts.append(h)

        seen = set()
        final = []
        for c in concepts:
            if c in seen:
                continue
            seen.add(c)
            final.append(c)
            if len(final) >= 8:
                break
        return final

    def _append_insight(self, learning_note: Path, review_note: Path, insight: str):
        if not insight:
            return
        line = f"- insight: {insight}"
        self._append_line(learning_note, line)
        self._append_line(review_note, line)

    def _update_action_state(self, action: str, status: str, command: str, summary: str):
        action = action or "unknown"
        action_state = self._state["actions"].setdefault(
            action,
            {
                "ok": 0,
                "fail": 0,
                "neutral": 0,
                "fail_streak": 0,
                "ok_streak": 0,
                "last_status": "",
                "last_command": "",
                "last_summary": "",
                "insights": [],
            },
        )

        if self._is_success(status):
            action_state["ok"] += 1
            action_state["ok_streak"] += 1
            prev_fail_streak = int(action_state.get("fail_streak", 0))
            action_state["fail_streak"] = 0
            if prev_fail_streak >= 2:
                action_state["insights"].append(
                    "recuperou apos falhas; manter estrategia que funcionou por ultimo"
                )
        elif self._is_failure(status):
            action_state["fail"] += 1
            action_state["fail_streak"] += 1
            action_state["ok_streak"] = 0
            fs = int(action_state["fail_streak"])
            if fs >= 2:
                action_state["insights"].append(
                    "falha recorrente detectada; tentar pre-requisitos/posicionamento alternativo"
                )
        else:
            action_state["neutral"] += 1
            action_state["ok_streak"] = 0

        action_state["last_status"] = status
        action_state["last_command"] = command
        action_state["last_summary"] = summary
        if len(action_state["insights"]) > 20:
            action_state["insights"] = action_state["insights"][-20:]
        return action_state

    def get_learning_context(self, user_text: str, top_k: int = 3) -> str:
        if not self.enabled:
            return ""
        query = (user_text or "").lower()
        if not query:
            return ""

        scored = []
        for action, data in self._state.get("actions", {}).items():
            score = 0
            if action in query:
                score += 3
            for token in re.findall(r"[a-z0-9_]{3,}", query):
                if token in action:
                    score += 1
                if token in str(data.get("last_command", "")).lower():
                    score += 1
            if score > 0:
                scored.append((score, action, data))

        scored.sort(key=lambda x: x[0], reverse=True)
        if not scored:
            return ""

        lines = []
        for _, action, data in scored[:max(1, top_k)]:
            ok = int(data.get("ok", 0))
            fail = int(data.get("fail", 0))
            fail_streak = int(data.get("fail_streak", 0))
            last_summary = str(data.get("last_summary", "")).strip()
            lines.append(
                f"- acao={action} | ok={ok} fail={fail} fail_streak={fail_streak} | ultimo={last_summary}"
            )
            insights = data.get("insights", [])
            if insights:
                lines.append(f"  insight_recente: {insights[-1]}")

        if not lines:
            return ""
        return "Aprendizados recentes de execucao no Minecraft:\n" + "\n".join(lines)

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
            concepts = self._extract_concepts(action, command, summary)
            concept_links = [f"[[{self._concept_path(c).stem}]]" for c in concepts]

            person_note = self._person_path(user)
            learning_note = self._learning_path(action)
            review_note = self._review_path(action)
            session_note = self._session_path()

            self._ensure_header(person_note, f"Usuario Minecraft: {user}", "person", "minecraft,person")
            self._ensure_header(learning_note, f"Acao Minecraft: {action}", "learning", "minecraft,learning")
            self._ensure_header(review_note, f"Review da acao {action}", "review", "minecraft,review")
            self._ensure_header(session_note, f"Sessao Minecraft {date}", "session", "minecraft,session")
            for concept in concepts:
                cpath = self._concept_path(concept)
                self._ensure_header(cpath, f"Conceito Minecraft: {concept}", "concept", "minecraft,concept")

            person_link = person_note.stem
            learning_link = learning_note.stem
            review_link = review_note.stem
            concepts_str = " ".join(concept_links) if concept_links else "(sem conceitos)"
            event_line = (
                f"- {ts} | [[{person_link}]] | acao=[[{learning_link}]] | review=[[{review_link}]] "
                f"| status={status} | cmd=`{command}` | {summary} | conceitos: {concepts_str}"
            )

            self._append_line(session_note, event_line)
            self._append_line(
                person_note,
                f"- {date} {ts} | acao=[[{learning_link}]] | review=[[{review_link}]] "
                f"| status={status} | cmd=`{command}` | {summary} | conceitos: {concepts_str}",
            )
            self._append_line(
                learning_note,
                f"- {date} {ts} | user=[[{person_link}]] | review=[[{review_link}]] "
                f"| status={status} | cmd=`{command}` | {summary} | conceitos: {concepts_str}",
            )
            self._append_line(
                review_note,
                f"- {date} {ts} | user=[[{person_link}]] | status={status} | cmd=`{command}` | {summary}",
            )
            for concept in concepts:
                cpath = self._concept_path(concept)
                self._append_line(
                    cpath,
                    f"- {date} {ts} | acao=[[{learning_link}]] | status={status} | cmd=`{command}` | {summary}",
                )

            # heuristica simples de aprendizado
            low = summary.lower()
            if "sem receita" in low or "materiais" in low:
                self._append_line(
                    learning_note,
                    "- insight: faltou receita/material; verificar pre-requisitos e craft intermediario.",
                )
                self._append_line(
                    review_note,
                    "- insight: faltou receita/material; verificar pre-requisitos e craft intermediario.",
                )
            if "nao consegui aproximar" in low or "bloco nao encontrado" in low:
                self._append_line(
                    learning_note,
                    "- insight: alvo distante/inexistente; considerar exploracao/posicionamento antes da acao.",
                )
                self._append_line(
                    review_note,
                    "- insight: alvo distante/inexistente; considerar exploracao/posicionamento antes da acao.",
                )

            action_state = self._update_action_state(action, status, command, summary)

            ok = int(action_state.get("ok", 0))
            fail = int(action_state.get("fail", 0))
            fail_streak = int(action_state.get("fail_streak", 0))
            self._append_line(
                review_note,
                f"- metricas: ok={ok} fail={fail} fail_streak={fail_streak}",
            )

            insights = action_state.get("insights", [])
            if insights:
                self._append_insight(learning_note, review_note, str(insights[-1]))

            self._save_state()
