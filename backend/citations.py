import re
from .models import Chunk, Citation

_REF = re.compile(r"\[(?:source\s*)?(\d+)\]", re.I)

def validate_citations(answer: str, evidence: list[Chunk]) -> list[Citation]:
    refs = {int(x) for x in _REF.findall(answer)}
    if not refs or any(n < 1 or n > len(evidence) for n in refs):
        return []
    return [Citation(document_id=evidence[n-1].document_id, document_title=evidence[n-1].document_title, page_number=evidence[n-1].page_number) for n in sorted(refs)]
