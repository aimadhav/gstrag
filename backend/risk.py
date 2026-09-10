import re
from .models import Chunk

HIGH_RISK = re.compile(r"\b(penalty|late fee|deadline|due date|file|claim|compliance|interest)\b", re.I)

def review_reason(question: str, answer: str, evidence: list[Chunk], citations_ok: bool) -> str | None:
    if not evidence:
        return "No reliable supporting evidence was retrieved."
    if not citations_ok:
        return "Answer citations are missing or do not match retrieved evidence."
    if HIGH_RISK.search(question) or HIGH_RISK.search(answer):
        return "High-risk compliance answer requires admin verification."
    if any(c.similarity < 0.55 for c in evidence):
        return "Evidence similarity is below the confidence threshold."
    return None
