from __future__ import annotations
import re
from dataclasses import dataclass
from typing import List, Tuple


@dataclass
class DetectedCandidate:
    text: str
    span: Tuple[int, int]
    word_count: int
    char_count: int


def _normalizar_comillas(text: str) -> str:
    for ch in ('“', '‟', '«', '‹'):
        text = text.replace(ch, '"')
    for ch in ('”', '„', '»', '›'):
        text = text.replace(ch, '"')
    return text


class TextualDetector:
    """
    Detecta candidatos entre comillas con reglas anti-textuales largos.
    """

    QUOTE_PATTERNS = [r'"([^"]+)"']

    def detect(self, body: str, min_words: int = 4, max_words: int = 35, max_chars: int = 240) -> List[DetectedCandidate]:
        if not body:
            return []

        body = _normalizar_comillas(body)

        candidates: List[DetectedCandidate] = []
        for pat in self.QUOTE_PATTERNS:
            for m in re.finditer(pat, body, flags=re.DOTALL):
                raw = m.group(1).strip()
                if not raw:
                    continue
                if raw.count("\n") >= 2:
                    continue
                if "http://" in raw or "https://" in raw:
                    continue

                words = [w for w in re.split(r"\s+", raw) if w]
                wc = len(words)
                cc = len(raw)

                if wc < min_words:
                    continue
                if wc > max_words or cc > max_chars:
                    continue

                candidates.append(DetectedCandidate(
                    text=raw,
                    span=(m.start(1), m.end(1)),
                    word_count=wc,
                    char_count=cc
                ))

        # Deduplicar por texto exacto
        uniq = []
        seen = set()
        for c in candidates:
            if c.text in seen:
                continue
            seen.add(c.text)
            uniq.append(c)

        return uniq
