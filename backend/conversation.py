"""Conversation manager with embedding-based retrieval and disk persistence.

Stores full conversation history — nothing is ever summarized or thrown away.
On each request, injects the N most recent turns plus K semantically relevant
older turns (retrieved via model2vec dot-product search).
"""
from __future__ import annotations

import json
import threading
from dataclasses import dataclass, field
from pathlib import Path

import numpy as np

_CONV_DIR    = Path.home() / ".tensor" / "conversations"
_KEEP_RECENT = 10   # always include last N turns verbatim
_RETRIEVE_K  = 5    # retrieve K additional turns via semantic search

# ── Embedder (lazy singleton) ─────────────────────────────────────

_embedder      = None
_embedder_lock = threading.Lock()


def _get_embedder():
    global _embedder
    if _embedder is None:
        with _embedder_lock:
            if _embedder is None:
                try:
                    from model2vec import StaticModel
                    _embedder = StaticModel.from_pretrained("minishlab/potion-base-8M")
                    print("[conversation] model2vec loaded (potion-base-8M)")
                except Exception as e:
                    print(f"[conversation] model2vec unavailable: {e}")
                    _embedder = False  # sentinel: don't retry
    return _embedder if _embedder is not False else None


def _embed(texts: list[str]) -> np.ndarray | None:
    m = _get_embedder()
    if m is None:
        return None
    try:
        vecs = m.encode(texts).astype(np.float32)
        norms = np.linalg.norm(vecs, axis=1, keepdims=True)
        norms = np.where(norms == 0, 1.0, norms)
        return vecs / norms   # L2-normalized → dot product = cosine sim
    except Exception as e:
        print(f"[conversation] embed error: {e}")
        return None


# ── Data classes ──────────────────────────────────────────────────

@dataclass
class Turn:
    role: str   # "user" or "assistant"
    text: str

    def to_dict(self) -> dict:
        return {"role": self.role, "text": self.text}

    @staticmethod
    def from_dict(d: dict) -> "Turn":
        return Turn(role=d["role"], text=d["text"])


@dataclass
class Conversation:
    id: str = ""
    turns: list[Turn] = field(default_factory=list)
    _lock: threading.Lock = field(default_factory=threading.Lock, repr=False)
    _embeddings: "np.ndarray | None" = field(default=None, repr=False)  # (N, D)

    def _emb_path(self) -> Path:
        return _CONV_DIR / f"{self.id}.npy"

    # ── Mutation ───────────────────────────────────────────────────

    def add_user(self, text: str):
        with self._lock:
            self.turns.append(Turn(role="user", text=text))
            self._append_embedding(text)
            self._save()

    def add_assistant(self, text: str):
        with self._lock:
            self.turns.append(Turn(role="assistant", text=text))
            self._append_embedding(text)
            self._save()

    def _append_embedding(self, text: str):
        vec = _embed([text])
        if vec is None:
            return
        self._embeddings = vec if self._embeddings is None else np.vstack([self._embeddings, vec])
        if self.id:
            _CONV_DIR.mkdir(parents=True, exist_ok=True)
            np.save(str(self._emb_path()), self._embeddings)

    # ── Retrieval ──────────────────────────────────────────────────

    def _retrieve(self, query: str, older: list[Turn], k: int) -> list[Turn]:
        """Return up to k older turns most semantically relevant to query."""
        if not older or not query or self._embeddings is None:
            return []
        q_vec = _embed([query])
        if q_vec is None:
            return []
        n = min(len(older), len(self._embeddings))
        if n == 0:
            return []
        scores = self._embeddings[:n] @ q_vec[0]          # (n,)
        top_k  = min(k, n)
        idxs   = sorted(np.argsort(scores)[-top_k:].tolist())   # chronological
        return [older[i] for i in idxs]

    # ── Prompt builders ────────────────────────────────────────────

    def build_messages(self, query: str = "") -> list[dict]:
        """Structured messages for providers with native multi-turn APIs."""
        with self._lock:
            if len(self.turns) <= _KEEP_RECENT:
                return [{"role": t.role, "content": t.text} for t in self.turns]

            recent = self.turns[-_KEEP_RECENT:]
            older  = self.turns[:-_KEEP_RECENT]
            retrieved = self._retrieve(query, older, _RETRIEVE_K)

            msgs: list[dict] = []
            if retrieved:
                ctx = "\n".join(
                    f"{'User' if t.role == 'user' else 'Tensor'}: {t.text[:600]}"
                    for t in retrieved
                )
                msgs.append({"role": "user", "content":
                    f"[Relevant context from earlier in this conversation]\n{ctx}\n"
                    f"[End context — conversation continues below]"})
                msgs.append({"role": "assistant", "content": "Understood."})

            for t in recent:
                msgs.append({"role": t.role, "content": t.text})
            return msgs

    def build_prompt(self, query: str = "") -> str:
        """Flat text prompt for providers without structured message APIs."""
        with self._lock:
            parts: list[str] = []

            if len(self.turns) > _KEEP_RECENT:
                older  = self.turns[:-_KEEP_RECENT]
                recent = self.turns[-_KEEP_RECENT:]
                retrieved = self._retrieve(query, older, _RETRIEVE_K)
                if retrieved:
                    ctx = "\n".join(
                        f"{'User' if t.role == 'user' else 'Tensor'}: {t.text[:600]}"
                        for t in retrieved
                    )
                    parts.append(f"[Relevant context from earlier]\n{ctx}\n[End context]")
                turns_to_show = recent
            else:
                turns_to_show = self.turns

            for t in turns_to_show:
                parts.append(f"{'User' if t.role == 'user' else 'Tensor'}: {t.text}")
            return "\n\n".join(parts)

    # ── Persistence ────────────────────────────────────────────────

    def _save(self):
        """Persist turns to disk. Called with lock held."""
        if not self.id:
            return
        _CONV_DIR.mkdir(parents=True, exist_ok=True)
        (_CONV_DIR / f"{self.id}.json").write_text(
            json.dumps({"id": self.id, "turns": [t.to_dict() for t in self.turns]}, indent=2),
            encoding="utf-8",
        )

    @staticmethod
    def load(conv_id: str) -> "Conversation":
        path = _CONV_DIR / f"{conv_id}.json"
        if not path.exists():
            return Conversation(id=conv_id)
        try:
            data  = json.loads(path.read_text(encoding="utf-8"))
            turns = [Turn.from_dict(t) for t in data.get("turns", [])]
            conv  = Conversation(id=data.get("id", conv_id), turns=turns)

            emb_path = _CONV_DIR / f"{conv_id}.npy"
            if emb_path.exists():
                conv._embeddings = np.load(str(emb_path))
            elif turns:
                # First load — embed all turns in one batch
                conv._embeddings = _embed([t.text for t in turns])
                if conv._embeddings is not None:
                    _CONV_DIR.mkdir(parents=True, exist_ok=True)
                    np.save(str(emb_path), conv._embeddings)

            return conv
        except Exception as e:
            print(f"[conversation] Error loading {conv_id}: {e}")
            return Conversation(id=conv_id)


# ── Manager ───────────────────────────────────────────────────────

class ConversationManager:
    """Thread-safe registry of conversations with disk persistence."""

    def __init__(self):
        self._convs: dict[str, Conversation] = {}
        self._lock  = threading.Lock()

    def get(self, conv_id: str) -> Conversation:
        with self._lock:
            if conv_id not in self._convs:
                self._convs[conv_id] = Conversation.load(conv_id)
            return self._convs[conv_id]

    def clear(self, conv_id: str):
        with self._lock:
            self._convs.pop(conv_id, None)
            for ext in (".json", ".npy"):
                (_CONV_DIR / f"{conv_id}{ext}").unlink(missing_ok=True)

    def list_all(self) -> list[str]:
        if not _CONV_DIR.exists():
            return []
        return sorted(p.stem for p in _CONV_DIR.glob("*.json"))
