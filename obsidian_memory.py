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
        self.feedback_dir = self.root / "HumanFeedback"
        self.state_file = self.root / ".learning_state.json"
        self._lock = threading.Lock()
        self._state = {"actions": {}, "procedures": {}, "concept_edges": {}, "updated": ""}
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
        self.feedback_dir.mkdir(parents=True, exist_ok=True)
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

    def _feedback_path(self) -> Path:
        month = datetime.now().strftime("%Y-%m")
        return self.feedback_dir / f"mc_feedback_{month}.md"

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
                if "procedures" not in self._state or not isinstance(self._state["procedures"], dict):
                    self._state["procedures"] = {}
                if "concept_edges" not in self._state or not isinstance(self._state["concept_edges"], dict):
                    self._state["concept_edges"] = {}
        except Exception:
            self._state = {"actions": {}, "procedures": {}, "concept_edges": {}, "updated": ""}

    def _save_state(self):
        if not self.enabled:
            return
        self._state["updated"] = datetime.now().isoformat(timespec="seconds")
        self.state_file.write_text(
            json.dumps(self._state, ensure_ascii=False, indent=2),
            encoding="utf-8",
        )

    @staticmethod
    def _normalize_proc_id(proc_id: str) -> str:
        return _slug(proc_id or "unknown")

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

    def _update_procedure_states(
        self,
        *,
        procedure_ids: list[str],
        concepts: list[str],
        status: str,
        action: str,
        command: str,
        summary: str,
    ):
        if not procedure_ids:
            return
        for raw_id in procedure_ids:
            pid = self._normalize_proc_id(raw_id)
            pdata = self._state["procedures"].setdefault(
                pid,
                {
                    "ok": 0,
                    "fail": 0,
                    "neutral": 0,
                    "fail_streak": 0,
                    "ok_streak": 0,
                    "last_status": "",
                    "last_action": "",
                    "last_command": "",
                    "last_summary": "",
                    "actions": {},
                    "concepts": {},
                },
            )

            if self._is_success(status):
                pdata["ok"] += 1
                pdata["ok_streak"] += 1
                pdata["fail_streak"] = 0
            elif self._is_failure(status):
                pdata["fail"] += 1
                pdata["fail_streak"] += 1
                pdata["ok_streak"] = 0
            else:
                pdata["neutral"] += 1
                pdata["ok_streak"] = 0

            pdata["last_status"] = status
            pdata["last_action"] = action
            pdata["last_command"] = command
            pdata["last_summary"] = summary

            act_key = _slug(action or "unknown")
            pdata["actions"][act_key] = int(pdata["actions"].get(act_key, 0)) + 1

            for concept in concepts or []:
                c = _slug(concept)
                pdata["concepts"][c] = int(pdata["concepts"].get(c, 0)) + 1
                edge_key = f"{c}::{pid}"
                self._state["concept_edges"][edge_key] = int(self._state["concept_edges"].get(edge_key, 0)) + 1

    def apply_human_feedback(
        self,
        *,
        user: str,
        raw_command: str,
        feedback: str,
        positive: bool,
    ) -> dict:
        if not self.enabled:
            return {"ok": False, "reason": "memory_disabled"}

        with self._lock:
            now = datetime.now()
            ts = now.strftime("%H:%M:%S")
            date = now.strftime("%Y-%m-%d")
            user = (user or "desconhecido").strip() or "desconhecido"
            raw_command = (raw_command or "").strip()
            feedback = (feedback or "").strip()
            signal = "positivo" if positive else "negativo"

            feedback_note = self._feedback_path()
            person_note = self._person_path(user)
            self._ensure_header(feedback_note, f"Feedback humano {now.strftime('%Y-%m')}", "feedback", "minecraft,feedback")
            self._ensure_header(person_note, f"Usuario Minecraft: {user}", "person", "minecraft,person")

            low = f"{raw_command} {feedback}".lower()
            tokens = set(re.findall(r"[a-z0-9_]{2,}", low))

            action_keys = list((self._state.get("actions") or {}).keys())
            matched_actions = [a for a in action_keys if a in low]
            alias_to_action = {
                "craft": "craft_tool",
                "craftar": "craft_tool",
                "crafting": "craft_tool",
                "mine": "mine",
                "minerar": "mine",
                "explorar": "explore",
                "explore": "explore",
                "seguir": "follow_player",
                "follow": "follow_player",
                "colocar": "place_block",
                "place": "place_block",
                "interagir": "interact_block",
                "interact": "interact_block",
                "coletar": "collect_for_item",
                "coleta": "collect_for_item",
            }
            for t in tokens:
                mapped = alias_to_action.get(t)
                if mapped and mapped not in matched_actions:
                    matched_actions.append(mapped)

            matched_actions = [a for a in matched_actions if a in (self._state.get("actions") or {})]

            procedure_keys = list((self._state.get("procedures") or {}).keys())
            matched_procedures = [p for p in procedure_keys if p in low]

            if not matched_actions and action_keys:
                # fallback: aplica no ultimo action mais recente conhecido
                latest = sorted(
                    action_keys,
                    key=lambda a: str((self._state.get("actions", {}).get(a, {}) or {}).get("last_summary", "")),
                    reverse=True,
                )
                if latest:
                    matched_actions = [latest[0]]

            for action in matched_actions:
                astate = self._state["actions"].setdefault(
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
                if positive:
                    astate["ok"] = int(astate.get("ok", 0)) + 1
                    astate["ok_streak"] = int(astate.get("ok_streak", 0)) + 1
                    astate["fail_streak"] = 0
                else:
                    astate["fail"] = int(astate.get("fail", 0)) + 1
                    astate["fail_streak"] = int(astate.get("fail_streak", 0)) + 1
                    astate["ok_streak"] = 0
                insight = f"feedback_humano_{signal}: {feedback}"
                astate["insights"] = list(astate.get("insights", [])) + [insight]
                if len(astate["insights"]) > 20:
                    astate["insights"] = astate["insights"][-20:]

                learning_note = self._learning_path(action)
                self._ensure_header(learning_note, f"Acao Minecraft: {action}", "learning", "minecraft,learning")
                self._append_line(learning_note, f"- {date} {ts} | reforco_{signal} | user=[[{person_note.stem}]] | {feedback}")

            for pid in matched_procedures:
                pdata = self._state["procedures"].setdefault(
                    pid,
                    {
                        "ok": 0,
                        "fail": 0,
                        "neutral": 0,
                        "fail_streak": 0,
                        "ok_streak": 0,
                        "last_status": "",
                        "last_action": "",
                        "last_command": "",
                        "last_summary": "",
                        "actions": {},
                        "concepts": {},
                    },
                )
                if positive:
                    pdata["ok"] = int(pdata.get("ok", 0)) + 1
                    pdata["ok_streak"] = int(pdata.get("ok_streak", 0)) + 1
                    pdata["fail_streak"] = 0
                else:
                    pdata["fail"] = int(pdata.get("fail", 0)) + 1
                    pdata["fail_streak"] = int(pdata.get("fail_streak", 0)) + 1
                    pdata["ok_streak"] = 0
                pdata["last_status"] = f"feedback_{signal}"
                pdata["last_summary"] = feedback

            self._append_line(
                feedback_note,
                f"- {date} {ts} | user=[[{person_note.stem}]] | sinal={signal} | cmd=`{raw_command}` | feedback={feedback} | actions={matched_actions or ['-']} | procedures={matched_procedures or ['-']}",
            )

            self._save_state()
            return {
                "ok": True,
                "matched_actions": matched_actions,
                "matched_procedures": matched_procedures,
                "signal": signal,
            }

    def _procedure_score(self, pid: str, query_text: str = "") -> float:
        data = self._state.get("procedures", {}).get(self._normalize_proc_id(pid), {})
        ok = float(data.get("ok", 0))
        fail = float(data.get("fail", 0))
        neutral = float(data.get("neutral", 0))
        total = ok + fail + neutral
        if total <= 0:
            return 0.0
        success_rate = ok / max(1.0, ok + fail)
        confidence = min(1.0, total / 8.0)
        streak_penalty = min(0.5, float(data.get("fail_streak", 0)) * 0.12)
        score = (success_rate * 2.0 + confidence) - streak_penalty
        q = (query_text or "").lower()
        if q and pid in q:
            score += 0.2
        return score

    def rank_procedure_ids(self, procedure_ids: list[str], query_text: str = "") -> list[str]:
        uniq = []
        seen = set()
        for p in procedure_ids or []:
            pid = self._normalize_proc_id(p)
            if pid in seen:
                continue
            seen.add(pid)
            uniq.append(pid)
        ranked = sorted(
            uniq,
            key=lambda pid: self._procedure_score(pid, query_text=query_text),
            reverse=True,
        )
        return ranked

    def get_procedure_learning_context(self, procedure_ids: list[str], top_k: int = 2) -> str:
        if not self.enabled or not procedure_ids:
            return ""
        ranked = self.rank_procedure_ids(procedure_ids)[: max(1, int(top_k or 1))]
        lines = []
        for pid in ranked:
            data = self._state.get("procedures", {}).get(pid, {})
            ok = int(data.get("ok", 0))
            fail = int(data.get("fail", 0))
            fs = int(data.get("fail_streak", 0))
            last_action = str(data.get("last_action", "")).strip()
            last_summary = str(data.get("last_summary", "")).strip()
            lines.append(
                f"- procedure={pid} | ok={ok} fail={fail} fail_streak={fs} | ultima_acao={last_action} | ultimo={last_summary}"
            )
        if not lines:
            return ""
        return "Historico de eficacia dos procedures:\n" + "\n".join(lines)

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
        procedure_ids: list[str] | None = None,
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
            procedure_ids = [self._normalize_proc_id(p) for p in (procedure_ids or []) if str(p or "").strip()]
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
            procedures_links = " ".join(f"[[{pid}]]" for pid in procedure_ids) if procedure_ids else "(sem procedures)"
            event_line = (
                f"- {ts} | [[{person_link}]] | acao=[[{learning_link}]] | review=[[{review_link}]] "
                f"| status={status} | cmd=`{command}` | {summary} | conceitos: {concepts_str} | procedures: {procedures_links}"
            )

            self._append_line(session_note, event_line)
            self._append_line(
                person_note,
                f"- {date} {ts} | acao=[[{learning_link}]] | review=[[{review_link}]] "
                f"| status={status} | cmd=`{command}` | {summary} | conceitos: {concepts_str} | procedures: {procedures_links}",
            )
            self._append_line(
                learning_note,
                f"- {date} {ts} | user=[[{person_link}]] | review=[[{review_link}]] "
                f"| status={status} | cmd=`{command}` | {summary} | conceitos: {concepts_str} | procedures: {procedures_links}",
            )
            self._append_line(
                review_note,
                f"- {date} {ts} | user=[[{person_link}]] | status={status} | cmd=`{command}` | {summary} | procedures: {procedures_links}",
            )
            for concept in concepts:
                cpath = self._concept_path(concept)
                self._append_line(
                    cpath,
                    f"- {date} {ts} | acao=[[{learning_link}]] | status={status} | cmd=`{command}` | {summary} | procedures: {procedures_links}",
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
            self._update_procedure_states(
                procedure_ids=procedure_ids,
                concepts=concepts,
                status=status,
                action=action,
                command=command,
                summary=summary,
            )

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
