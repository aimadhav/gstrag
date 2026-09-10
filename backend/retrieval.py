from collections.abc import Iterable
from .models import Chunk

def filtered_chunks(chunks: Iterable[Chunk], permitted: set[str] | frozenset[str], limit: int = 5) -> list[Chunk]:
    """Apply authorization before ranking/returning evidence."""
    return sorted((c for c in chunks if c.source_type in permitted), key=lambda c: c.similarity, reverse=True)[:limit]

def format_evidence(chunks: Iterable[Chunk]) -> str:
    return "\n\n".join(
        f"Source {i}: {c.document_title}, page {c.page_number or 'unknown'}, section {' > '.join(c.section_path) or 'unknown'}\n{c.content}"
        for i, c in enumerate(chunks, 1)
    )
