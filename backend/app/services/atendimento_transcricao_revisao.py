"""Bounded, advisory comparison of two audio readings; never edits the first."""
from __future__ import annotations

from collections import Counter
from dataclasses import dataclass
from difflib import SequenceMatcher
import re
import time
import unicodedata
from typing import Callable


MAX_TOKENS = 6000
MAX_MATCH_PAIRS = 2_000_000
# Keep the review bounded without hiding ordinary disagreements in a long
# segment. The clinical recording evaluation had 29 short differences in one.
MAX_DIVERGENCIAS = 40
MAX_FRAGMENT_CHARS = 600
CONTEXT_TOKENS = 4
MIN_REVIEW_SECONDS = 1.0
TOKEN = re.compile(r"\d+(?:[.,]\d+)*|[.,]\d+|(?<=\d)[:^](?=\d)|[^\W\d_]+(?:[-’'][^\W\d_]+)*|[/+%°µμ−±×<>≤≥-]", re.UNICODE)
UNCERTAIN = re.compile(r"\[(?:inaud[ií]vel|incert[oa]|inintelig[ií]vel)[^\]\r\n]{0,120}\]", re.IGNORECASE)


@dataclass(frozen=True)
class TrechoTranscricao:
    indice: int
    inicio_frame: int
    fim_frame: int
    texto: str


def _tokens(text: str):
    return list(TOKEN.finditer(text))


def _key(token) -> str:
    # Only the comparison ignores letter case/canonical Unicode composition.
    # Returned excerpts are slices of the unchanged source strings.
    return unicodedata.normalize("NFC", token.group()).casefold()


def _excerpt(text: str, tokens, start: int, end: int) -> tuple[str, bool]:
    if not tokens:
        return "", False
    low, high = max(0, start - CONTEXT_TOKENS), min(len(tokens), end + CONTEXT_TOKENS)
    excerpt = text[tokens[low].start():tokens[high - 1].end()]
    if len(excerpt) > MAX_FRAGMENT_CHARS:
        return excerpt[:MAX_FRAGMENT_CHARS] + "…", True
    return excerpt, False


def comparar_leituras(original: str, alternativa: str) -> tuple[list[dict], bool]:
    """Return contextual disagreements, without choosing a preferred reading.

    Limits bound the diff's work and response size. A capped comparison is never
    represented as agreement. Numbers, decimal separators, units and negations
    participate in comparison; ordinary punctuation/case do not.
    """
    first, second = _tokens(original), _tokens(alternativa)
    if max(len(first), len(second)) > MAX_TOKENS:
        return [], True
    first_keys, second_keys = [_key(t) for t in first], [_key(t) for t in second]
    first_counts, second_counts = Counter(first_keys), Counter(second_keys)
    # Popular clinical words must remain alignment anchors: autojunk can merge
    # two distant name/dose changes into a long excerpt that gets clipped. Bound
    # the potential matching pairs explicitly instead of discarding anchors.
    if sum(count * second_counts.get(key, 0) for key, count in first_counts.items()) > MAX_MATCH_PAIRS:
        return [], True
    matcher = SequenceMatcher(None, first_keys, second_keys, autojunk=False)
    differences = []
    for tag, a, b, c, d in matcher.get_opcodes():
        if tag == "equal":
            continue
        # Merge nearby disagreements so the same sentence is not shown as many
        # disconnected word replacements. No mutation of either string occurs.
        if differences and a - differences[-1][1] <= 2 and c - differences[-1][3] <= 2:
            previous = differences[-1]
            differences[-1] = (previous[0], b, previous[2], d)
        else:
            differences.append((a, b, c, d))
    limited = len(differences) > MAX_DIVERGENCIAS
    result = []
    for a, b, c, d in differences[:MAX_DIVERGENCIAS]:
        text, clipped_first = _excerpt(original, first, a, b)
        other, clipped_second = _excerpt(alternativa, second, c, d)
        limited = limited or clipped_first or clipped_second
        result.append({"texto_original": text, "leitura_alternativa": other})
    return result, limited


def revisar_trechos(*, provider, trechos: list[TrechoTranscricao],
                    carregar_audio: Callable[[TrechoTranscricao], bytes],
                    sample_rate: int, deadline: float) -> dict:
    """Review only after the complete primary transcript has been obtained.

    One blind second reading per chunk, at most, sharing the caller's deadline.
    Failure is advisory: preserve the primary text and explicitly report which
    chunks could not be checked. No patient name or previous text is supplied.
    """
    results = []
    review = getattr(provider, "transcrever_revisao", None)
    for chunk in trechos:
        markers = list(dict.fromkeys(match.group() for match in UNCERTAIN.finditer(chunk.texto)))
        result = {
            "indice": chunk.indice,
            "inicio_segundos": chunk.inicio_frame / sample_rate,
            "fim_segundos": chunk.fim_frame / sample_rate,
            "estado": "indisponivel",
            "limitado": len(markers) > MAX_DIVERGENCIAS,
            "divergencias": [],
            "marcacoes_incerteza": markers[:MAX_DIVERGENCIAS],
        }
        results.append(result)
        remaining = deadline - time.monotonic()
        if not callable(review) or remaining < MIN_REVIEW_SECONDS:
            continue
        try:
            content = carregar_audio(chunk)
            remaining = deadline - time.monotonic()
            if remaining < MIN_REVIEW_SECONDS:
                continue
            reading = review(nome=f"conferencia-{chunk.indice:02d}.wav", mime="audio/wav",
                             content=content, timeout=remaining)
            if not isinstance(reading, dict) or not isinstance(reading.get("texto"), str) or not reading["texto"].strip():
                continue
            differences, limited = comparar_leituras(chunk.texto, reading["texto"])
            result.update(estado="concluido", divergencias=differences,
                          limitado=result["limitado"] or limited)
        except Exception:
            # Secondary review must not discard a successful full transcript.
            # Provider messages can contain identifiers: expose no exception text.
            continue
    completed = sum(item["estado"] == "concluido" for item in results)
    limited = any(item["limitado"] for item in results)
    state = "concluida" if completed == len(trechos) and completed and not limited else "parcial" if completed else "indisponivel"
    notices = ["A comparação entre duas leituras pode deixar erros em comum sem sinalização. Confira o áudio, principalmente nomes, medicamentos, doses e negações."]
    if completed != len(trechos):
        notices.append(f"A segunda leitura foi concluída em {completed} de {len(trechos)} trechos. A transcrição principal está completa; a conferência das dúvidas ficou pendente nos demais trechos.")
    if any(item["divergencias"] or item["marcacoes_incerteza"] for item in results):
        notices.append("Há palavras incertas ou divergências entre leituras. As alternativas não corrigem a transcrição e não confirmam qual leitura está certa.")
    if limited:
        notices.append("A comparação atingiu um limite de tamanho. Há divergências ou marcações que podem não estar exibidas; confira os trechos completos no áudio.")
    return {"estado": state, "trechos_total": len(trechos), "trechos_revisados": completed,
            "avisos": notices, "trechos": results}
