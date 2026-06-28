from __future__ import annotations
import re
import unicodedata
from pathlib import Path
from typing import List

from utils.app_logger import get_logger

_log = get_logger(__name__)

# Palabras "no significativas" — no se marcan como repetición por proximidad
_PROXIMITY_STOP: frozenset[str] = frozenset({
    "que", "del", "los", "las", "con", "por", "para", "una",
    "este", "esta", "como", "pero", "cuando", "donde", "desde",
    "hasta", "entre", "sobre", "bajo", "ante", "sin", "tras",
    "son", "fue", "han", "ser", "hay", "tiene", "muy", "bien",
    "solo", "sino", "aunque", "cuya", "cuyo", "cuyas", "cuyos",
    "esto", "ello", "esos", "esas", "esos", "estos",
    "puede", "hacer", "tener", "estar", "deben", "haber",
    "todo", "toda", "todos", "todas", "cada", "otro", "otra",
    "otros", "otras", "mismo", "misma",
})

# Filtra sugerencias con ü sin g precedente ("segün" etc.)
_INVALID_U_RE = re.compile(r"(?<!g)ü", re.IGNORECASE)

# Regex palabras para revisión de proximidad (≥ 5 chars)
_PROX_WORD_RE = re.compile(r"\b[a-záéíóúüñA-ZÁÉÍÓÚÜÑ]{5,}\b")


class SpellService:
    """
    Corrección ortográfica + palabras repetidas (adyacentes y por proximidad).
    - Rojo    (#ff4444): error ortográfico
    - Naranja (#ff8c00): palabra repetida adyacente
    - Violeta (#b388ff): palabra repetida en párrafos cercanos
    """

    _WORD_RE   = re.compile(r"\b[a-záéíóúüñA-ZÁÉÍÓÚÜÑ]{2,}\b")
    _REPEAT_RE = re.compile(r"\b(\w{2,})\s+\1\b", re.IGNORECASE)

    def __init__(self):
        self._checker = None
        self._custom_path: Path | None = None
        self._shared_path: Path | None = None   # base_root/diccionario.txt (compartido)
        try:
            from config.config import Config
            self._custom_path = Config.DATA_DIR / "diccionario.txt"
            # Migración del nombre viejo "custom_words.txt" → "diccionario.txt".
            old = Config.DATA_DIR / "custom_words.txt"
            if old.exists() and not self._custom_path.exists():
                try:
                    self._custom_path.write_text(old.read_text(encoding="utf-8"), encoding="utf-8")
                except Exception:
                    pass
        except Exception:
            pass
        try:
            from spellchecker import SpellChecker
            self._checker = SpellChecker(language="es")
            self._load_custom_words()
        except Exception:
            pass

    # ── Diccionario compartido en la raíz base ────────────────────────────
    def set_base_root(self, base_root) -> None:
        """Define la raíz base (donde se crean las ediciones) para sincronizar el
        diccionario de corrección entre estaciones."""
        try:
            self._shared_path = (Path(base_root) / "diccionario.txt") if base_root else None
        except Exception:
            self._shared_path = None

    @staticmethod
    def _read_words(path: "Path | None") -> set:
        try:
            if path and path.exists():
                return {w.strip().lower() for w in
                        path.read_text(encoding="utf-8").splitlines() if w.strip()}
        except Exception:
            pass
        return set()

    def _write_shared(self, words: set) -> None:
        """Une `words` al diccionario compartido (re-lee bajo lock + escritura atómica)."""
        if not self._shared_path:
            return
        try:
            from services.shared_config_service import _FileLock
        except Exception:
            _FileLock = None
        try:
            self._shared_path.parent.mkdir(parents=True, exist_ok=True)
            lock = _FileLock(self._shared_path) if _FileLock else None
            if lock is not None and not lock.acquire():
                return
            try:
                full = self._read_words(self._shared_path) | {w.strip().lower() for w in words if w.strip()}
                import os
                tmp = self._shared_path.with_suffix(f".{os.getpid()}.tmp")
                tmp.write_text("\n".join(sorted(full)) + "\n", encoding="utf-8")
                os.replace(tmp, self._shared_path)
            finally:
                if lock is not None:
                    lock.release()
        except Exception:
            pass

    def merge_shared(self) -> None:
        """Une el diccionario compartido (base_root) con el local: carga al checker las
        palabras nuevas y las persiste en ambos lados (unión, dedup)."""
        if not self._shared_path:
            return
        local = self._read_words(self._custom_path)
        shared = self._read_words(self._shared_path)
        union = local | shared
        if not union:
            return
        if self._checker is not None:
            try:
                self._checker.word_frequency.load_words(list(union))
            except Exception:
                pass
        # Faltantes en el local → reescribir local con la unión.
        if (union - local) and self._custom_path:
            try:
                self._custom_path.parent.mkdir(parents=True, exist_ok=True)
                self._custom_path.write_text("\n".join(sorted(union)) + "\n", encoding="utf-8")
            except Exception:
                pass
        # Faltantes en el compartido → publicarlas.
        if union - shared:
            self._write_shared(union)
        if (union - local) or (union - shared):
            _log.info("Diccionario sincronizado: %d palabras (local +%d, compartido +%d)",
                      len(union), len(union - local), len(union - shared))

    def _load_custom_words(self) -> None:
        if self._checker is None or not self._custom_path:
            return
        try:
            if self._custom_path.exists():
                words = [w.strip().lower() for w in
                         self._custom_path.read_text(encoding="utf-8").splitlines()
                         if w.strip()]
                if words:
                    self._checker.word_frequency.load_words(words)
        except Exception:
            pass

    def add_word(self, word: str) -> None:
        w = word.strip().lower()
        if not w:
            return
        if self._checker is not None:
            self._checker.word_frequency.load_words([w])
        if self._custom_path:
            try:
                self._custom_path.parent.mkdir(parents=True, exist_ok=True)
                with open(self._custom_path, "a", encoding="utf-8") as f:
                    f.write(w + "\n")
            except Exception:
                pass
        # Compartir en la raíz base (sincroniza entre estaciones).
        if self._shared_path:
            self._write_shared({w})
        _log.info("Diccionario: palabra agregada '%s'", w)

    def check(self, text: str) -> List[dict]:
        if not text:
            return []

        errors: List[dict] = []
        repeat_spans: set[tuple] = set()

        # Palabras adyacentes repetidas
        for m in self._REPEAT_RE.finditer(text):
            s1, e1 = m.start(1), m.end(1)
            word = m.group(1)
            errors.append({"start": s1, "end": e1, "word": word, "type": "repeat", "suggestions": []})
            s2 = text.index(word, e1)
            e2 = s2 + len(word)
            errors.append({"start": s2, "end": e2, "word": word, "type": "repeat", "suggestions": []})
            repeat_spans.add((s1, e1))
            repeat_spans.add((s2, e2))

        # Corrección ortográfica
        if self._checker is not None:
            matches = [(m.start(), m.end(), m.group()) for m in self._WORD_RE.finditer(text)]
            if matches:
                words_norm = [unicodedata.normalize("NFC", w.lower()) for _, _, w in matches]
                unknown_raw = self._checker.unknown(words_norm)
                unknown = unknown_raw
                for start, end, word in matches:
                    w_norm = unicodedata.normalize("NFC", word.lower())
                    if (start, end) in repeat_spans or w_norm not in unknown:
                        continue
                    errors.append({
                        "start": start, "end": end,
                        "word": word, "type": "spell",
                        "suggestions": None,
                    })

        # Repetición por proximidad entre párrafos
        existing_spans = {(e["start"], e["end"]) for e in errors}
        errors.extend(self._check_proximity(text, existing_spans))

        return errors

    def _check_proximity(self, text: str, existing_spans: set[tuple],
                          window: int = 3) -> List[dict]:
        """Detecta palabras significativas repetidas en párrafos cercanos."""
        errors: List[dict] = []
        lines = [(m.start(), m.group()) for m in re.finditer(r"[^\n]+", text)]
        if len(lines) < 2:
            return errors

        word_pos: dict[str, list] = {}
        for li, (line_start, line_text) in enumerate(lines):
            for m in _PROX_WORD_RE.finditer(line_text):
                raw = m.group()
                wn = unicodedata.normalize("NFC", raw.lower())
                if wn in _PROXIMITY_STOP:
                    continue
                abs_s = line_start + m.start()
                abs_e = line_start + m.end()
                if wn not in word_pos:
                    word_pos[wn] = []
                word_pos[wn].append((li, abs_s, abs_e))

        seen: set[tuple] = set()
        for wn, occ in word_pos.items():
            if len(occ) < 2:
                continue
            flagged: set[int] = set()
            for i in range(len(occ)):
                for j in range(i + 1, len(occ)):
                    if abs(occ[i][0] - occ[j][0]) <= window:
                        flagged.add(i)
                        flagged.add(j)
            for idx in flagged:
                _, si, ei = occ[idx]
                span = (si, ei)
                if span not in existing_spans and span not in seen:
                    seen.add(span)
                    errors.append({
                        "start": si, "end": ei,
                        "word": text[si:ei],
                        "type": "proximity",
                        "suggestions": [],
                    })
        return errors

    def get_suggestions(self, word: str) -> list[str]:
        if self._checker is None:
            return []
        try:
            cands = self._checker.candidates(word) or []
            filtered = [c for c in cands if not _INVALID_U_RE.search(c)]
            return filtered[:5]
        except Exception:
            return []

    def is_available(self) -> bool:
        return self._checker is not None
