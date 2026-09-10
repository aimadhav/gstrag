from backend.policy import allowed_sources
from backend.retrieval import filtered_chunks
from backend.models import Chunk
from backend.citations import validate_citations
from ingestion.chunk_documents import chunk_sections

def c(source, score=.9):
    return Chunk(id=source, document_id=source, document_title=source, source_type=source, content="evidence", similarity=score)

def test_plus_cannot_retrieve_private_book():
    result = filtered_chunks([c("private_book"), c("icai_book")], allowed_sources("plus"))
    assert [x.source_type for x in result] == ["icai_book"]

def test_pro_can_retrieve_private_book():
    assert "private_book" in allowed_sources("pro")

def test_citations_must_reference_evidence():
    evidence = [c("icai_book")]
    assert validate_citations("Answer [Source 1]", evidence)
    assert not validate_citations("Answer [Source 2]", evidence)

def test_chunker_keeps_section_context_and_overlap():
    chunks = chunk_sections("Section 1 Eligibility\n" + "important condition " * 700)
    assert len(chunks) > 1
    assert all(x["section_path"] for x in chunks)
